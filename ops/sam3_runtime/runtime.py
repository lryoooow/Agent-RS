"""Image inference with Meta's SAM 3 SDK and NVIDIA CUDA PyTorch."""
from __future__ import annotations

import hashlib
import os
import time
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from . import CHECKPOINT_SHA256, SOURCE_SHA256


def _verify_sdk() -> None:
    spec = find_spec("sam3")
    if spec is None or not spec.origin:
        raise RuntimeError("Install the Meta SAM 3 SDK from ops/sam3_runtime/requirements.txt")
    root = Path(spec.origin).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf8")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(name + b"\0" + hashlib.sha256(content).digest())
    if digest.hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Installed SAM 3 SDK differs from the pinned Meta source revision")


class Engine:
    def __init__(self, confidence_threshold: float) -> None:
        if not torch.version.cuda or not torch.cuda.is_available():
            raise RuntimeError("SAM 3 requires an NVIDIA GPU and a CUDA-enabled PyTorch installation")
        path = Path(os.environ["SAM3_CHECKPOINT_PATH"]).expanduser().resolve(strict=True)
        with path.open("rb") as source:
            self.checkpoint_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        if self.checkpoint_sha256 != CHECKPOINT_SHA256:
            raise ValueError("SAM3_CHECKPOINT_PATH must point to the official facebook/sam3 sam3.pt")

        _verify_sdk()
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model

        # Map the official detector weights so startup never needs a second fully
        # materialized CPU copy of the checkpoint. The tracker is a separate model.
        model = build_sam3_image_model(device="cuda", load_from_HF=False, compile=False)
        checkpoint = torch.load(str(path), mmap=True, map_location="cpu", weights_only=True)
        tensors = checkpoint.get("model", checkpoint)
        image_weights = {key: tensors["detector." + key] for key in model.state_dict()}
        model.load_state_dict(image_weights, strict=True)
        self.processor = Sam3Processor(model.eval(), device="cuda", confidence_threshold=confidence_threshold)
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        self.device = str(next(model.parameters()).device)
        self.gpu = torch.cuda.get_device_name()

    def infer(self, image: Image.Image, concepts: list[str]) -> tuple[dict, float]:
        predictions = {}
        with torch.inference_mode(), torch.autocast("cuda", dtype=self.dtype):
            start = time.perf_counter()
            state = self.processor.set_image(image.convert("RGB"))
            torch.cuda.synchronize()
            embedding_seconds = time.perf_counter() - start
            for concept in concepts:
                self.processor.reset_all_prompts(state)
                output = self.processor.set_text_prompt(prompt=concept, state=state)
                scores = output["scores"].detach().float().cpu().numpy()
                boxes = output["boxes"].detach().float().cpu().numpy()
                masks = output["masks"].squeeze(1).detach().bool().cpu().numpy()
                if masks.shape != (len(scores), image.height, image.width) or boxes.shape != (len(scores), 4):
                    raise RuntimeError("SAM 3 returned inconsistent prediction shapes")
                if not np.isfinite(scores).all() or not np.isfinite(boxes).all():
                    raise RuntimeError("SAM 3 returned non-finite predictions")
                predictions[concept] = {"scores": scores, "boxes": boxes, "masks": masks}
        return predictions, embedding_seconds
