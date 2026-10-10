"""Process-local eager inference compatibility; does not modify installed torch.

The original SAM3 weights and layer topology are retained. Accelerated CUDA-only
attention uses PyTorch's mathematical SDPA backend on DTK 24.04 / torch 2.1.
Video and interactive-only kernels fail explicitly if requested by this image test.
"""
# ruff: noqa

import contextlib,enum,sys,types,importlib,functools
import torch

def install():
    changes=[]
    # SAM3 model_misc explicitly re-enables global fast SDPA flags during each
    # grounding pass. A one-time flag or outer context therefore does not protect
    # the next image encoder on DTK 24.04. Enforce math at the actual call site.
    # This wrapper is process-local, eager-only, and idempotent.
    functional=torch.nn.functional
    if not getattr(functional.scaled_dot_product_attention,'_sam3_hygon_math_only',False):
        original_sdpa=functional.scaled_dot_product_attention
        @functools.wraps(original_sdpa)
        def math_sdpa(*args,**kwargs):
            with torch.backends.cuda.sdp_kernel(enable_flash=False,enable_math=True,enable_mem_efficient=False):
                return original_sdpa(*args,**kwargs)
        math_sdpa._sam3_hygon_math_only=True
        functional.scaled_dot_product_attention=math_sdpa
    changes.append('every eager SDPA invocation forced to mathematical backend (including after SAM3 flag resets)')
    from torch.utils import _pytree
    if not hasattr(_pytree,'register_pytree_node'):
        _pytree.register_pytree_node=_pytree._register_pytree_node
        changes.append('pytree public registration -> equivalent torch 2.1 registration')
    if not hasattr(torch.compiler,'is_dynamo_compiling'):
        torch.compiler.is_dynamo_compiling=torch._dynamo.is_compiling
        changes.append('compiler query -> torch._dynamo.is_compiling')
    try:
        importlib.import_module('torch.nn.attention')
    except ImportError:
        class SDPBackend(enum.Enum):
            MATH=0
            FLASH_ATTENTION=1
            EFFICIENT_ATTENTION=2
        @contextlib.contextmanager
        def sdpa_kernel(backends,**kwargs):
            with torch.backends.cuda.sdp_kernel(enable_flash=False,enable_math=True,enable_mem_efficient=False):
                yield
        module=types.ModuleType('torch.nn.attention')
        module.SDPBackend=SDPBackend;module.sdpa_kernel=sdpa_kernel
        sys.modules[module.__name__]=module
        changes.append('SDPA backend selection -> torch 2.1 mathematical attention')
    # Importing the image builder also imports tracker utilities. Their Triton
    # distance-transform is irrelevant to text-only image inference.
    module=types.ModuleType('sam3.model.edt')
    def unsupported(*args,**kwargs):
        raise RuntimeError('Interactive/video distance transform is outside this SAM3-only image validation')
    module.edt_triton=unsupported
    sys.modules[module.__name__]=module
    changes.append('unused tracker distance-transform import isolated (explicit failure if called)')
    return changes

def patch_model(model):
    """DTK 24.04 MIOpen rejects BF16 channels-last Conv2d/ConvTranspose2d.

    Normalize the input's memory layout to NCHW-contiguous. This copies values
    without any numeric conversion and preserves the original layers/weights.
    The exact failure and passing contiguous case are reproduced in probe_deconv.
    """
    patched=[]
    def contiguous_input(module,args):
        return (args[0].contiguous(),*args[1:])
    for name,module in model.named_modules():
        if isinstance(module,(torch.nn.Conv2d,torch.nn.ConvTranspose2d)):
            module.register_forward_pre_hook(contiguous_input)
            patched.append(name)
    return patched
