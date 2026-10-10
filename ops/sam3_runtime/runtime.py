"""Meta SAM3 image-only production runtime adapted for the Hygon DCU host."""
# ruff: noqa

import faulthandler,json,os,pathlib,time,threading
faulthandler.enable()
import numpy as np
import torch
from safetensors import safe_open
from . import hygon_compat

ROOT=pathlib.Path(os.environ.get("SAM3_LAB_ROOT", "/home/LRY/sam3-runtime-releases/20260922-meta-2345a4ad")).resolve()

def validate_raw_outputs(outputs):
    # Check before confidence filtering: NaN logits compare false and otherwise
    # could be silently presented as a valid empty detection result.
    for name in ['pred_logits','pred_boxes','pred_masks','presence_logit_dec']:
        value=outputs[name]
        if not bool(torch.isfinite(value).all()):
            raise FloatingPointError(f'SAM3 non-finite raw output: {name}')
    return outputs

class Engine:
    def __init__(self,threshold=.5):
        self.lock=threading.Lock()
        self.compat=hygon_compat.install()
        torch.set_num_threads(8)
        torch.set_num_interop_threads(1)
        torch.manual_seed(20260916)
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
        torch.cuda.set_per_process_memory_fraction(.7)
        # Initialize and exercise the device on the main thread before building.
        torch.zeros(1,device='cuda').add_(1)
        torch.cuda.synchronize()
        from sam3.model_builder import build_sam3_image_model
        from sam3.model import vitdet
        from sam3.model.sam3_image_processor import Sam3Processor
        from torchvision.transforms import v2
        start=time.perf_counter()
        print('PHASE2 constructing model',flush=True)
        # MKL's CPU erfinv in timm's truncated-normal initializer reproducibly
        # segfaults on this host. These trainable parameters are all immediately
        # replaced by the complete pretrained checkpoint. Defer ONLY those
        # initializers, restore the module symbol even on failure, and verify
        # every deferred Parameter is present and exactly loaded before use.
        deferred=[];original_init=vitdet.trunc_normal_
        def defer_trunc_normal(tensor,*args,**kwargs):
            if not isinstance(tensor,torch.nn.Parameter):
                raise RuntimeError('Refusing to defer initialization of a non-Parameter')
            deferred.append(tensor)
            with torch.no_grad():return tensor.zero_()
        try:
            vitdet.trunc_normal_=defer_trunc_normal
            model=build_sam3_image_model(device='cpu',load_from_HF=False,compile=False,enable_inst_interactivity=False)
        finally:
            vitdet.trunc_normal_=original_init
        required=set(model.state_dict());weights={}
        with safe_open(str(ROOT/'models/sam3.safetensors'),framework='pt',device='cpu') as f:
            complex_keys=set(json.loads(f.metadata()['complex_keys']))
            for key in f.keys():
                if not key.startswith('detector.'):continue
                name=key[len('detector.'):]
                if name not in required:
                    assert name.startswith('backbone.vision_backbone.sam2_convs.'),name
                    continue
                tensor=f.get_tensor(key)
                weights[name]=torch.view_as_complex(tensor) if key in complex_keys else tensor
            assert set(weights)==required
            model.load_state_dict(weights,strict=True)
            parameter_names={id(value):name for name,value in model.named_parameters()}
            self.deferred_parameter_names=[]
            for parameter in deferred:
                assert id(parameter) in parameter_names,'Deferred tensor is not a registered Parameter'
                name=parameter_names[id(parameter)]
                assert name in weights,'Deferred Parameter lacks pretrained weight'
                assert torch.equal(parameter.detach(),weights[name]),'Deferred Parameter was not exactly restored'
                self.deferred_parameter_names.append(name)
        del deferred
        del weights,tensor
        self.model=model.to('cuda').eval()
        self.conv_layout_patches=hygon_compat.patch_model(self.model)
        original_grounding=self.model.forward_grounding
        def checked_grounding(*args,**kwargs):
            return validate_raw_outputs(original_grounding(*args,**kwargs))
        self.model.forward_grounding=checked_grounding
        self.processor=Sam3Processor(self.model,device='cuda',confidence_threshold=threshold)
        assert isinstance(self.processor.transform.transforms[1],v2.Resize)
        self.processor.transform.transforms[1].antialias=True
        torch.cuda.synchronize()
        self.load_seconds=time.perf_counter()-start
        print(f'PHASE2 loaded {len(required)} entries in {self.load_seconds:.3f}s',flush=True)
        print(f'PHASE2 verified {len(self.deferred_parameter_names)} deferred Parameters exactly match checkpoint',flush=True)

    def infer(self,image,prompts):
        """Return CPU arrays only; serialize processor access to avoid shared state."""
        with self.lock,torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            start=time.perf_counter()
            state=self.processor.set_image(image.convert('RGB'))
            torch.cuda.synchronize()
            embedding=time.perf_counter()-start
            results={}
            for concept in prompts:
                self.processor.reset_all_prompts(state)
                start=time.perf_counter()
                state=self.processor.set_text_prompt(concept,state)
                torch.cuda.synchronize()
                seconds=time.perf_counter()-start
                scores=state['scores'].float().cpu().numpy()
                boxes=state['boxes'].float().cpu().numpy()
                masks=state['masks'].squeeze(1).cpu().numpy()
                assert np.isfinite(scores).all() and np.isfinite(boxes).all()
                assert masks.shape==(len(scores),image.height,image.width)
                assert len(scores)==len(boxes)
                results[concept]={'scores':scores,'boxes':boxes,'masks':masks,'seconds':seconds}
            self.processor.reset_all_prompts(state)
            del state
        torch.cuda.synchronize()
        return results,embedding
