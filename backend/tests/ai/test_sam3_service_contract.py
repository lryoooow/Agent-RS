"""CPU service-contract checks; actual official GPU engine is verified on deployment."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
from types import ModuleType
import numpy as np
import pytest
from fastapi import HTTPException, Response
from PIL import Image

@pytest.fixture
def service(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root))
    fake = ModuleType("ops.sam3_runtime.runtime")
    fake.Engine = object
    monkeypatch.setitem(sys.modules, "ops.sam3_runtime.runtime", fake)
    spec = importlib.util.spec_from_file_location("sam3_service_under_test", root / "ops/sam3_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ALLOWED_ROOT", tmp_path)
    return module

@pytest.mark.asyncio
async def test_official_provenance_and_configuration_reach_engine(service, monkeypatch):
    thresholds = []
    monkeypatch.setattr(service, "Engine", lambda value: thresholds.append(value) or object())
    await service.load_model()
    result = await service.health()
    assert thresholds == [service.CONFIDENCE_THRESHOLD]
    assert result["provider"] == "meta_official_sam3"
    assert len(result["source_commit"]) == 40
    assert len(result["checkpoint_sha256"]) == 64
    assert result["tile_overlap"] == service.TILE_OVERLAP

@pytest.mark.asyncio
async def test_success_artifacts_and_settled_header(service, tmp_path):
    class Engine:
        def infer(self, image, concepts):
            mask = np.zeros((1, image.height, image.width), dtype=bool)
            mask[0, 2:6, 3:8] = True
            return {concepts[0]: {"masks": mask, "scores": np.array([.9])}}, .01
    service.engine = Engine()
    path = tmp_path / "input.png"
    Image.new("RGB", (16, 16)).save(path)
    response = Response()
    result = await service.infer(service.InferRequest(input_path=str(path), output_dir=str(tmp_path), concepts=["building"]), response)
    assert response.headers["X-SAM3-Settled"] == "1"
    assert result["provider"] == "meta_official_sam3"
    assert result["counts"] == {"building": 1}
    assert np.load(tmp_path / result["labels_npy"], allow_pickle=False).shape == (16, 16)

@pytest.mark.asyncio
async def test_pixel_limit_checked_before_rgb_allocation(service, tmp_path, monkeypatch):
    service.engine = object()
    service.MAX_PIXELS = 16
    path = tmp_path / "input.png"
    Image.new("RGB", (8, 8)).save(path)
    monkeypatch.setattr(Image.Image, "convert", lambda *a, **kw: pytest.fail("oversize input was decoded"))
    with pytest.raises(HTTPException) as caught:
        await service.infer(service.InferRequest(input_path=str(path), output_dir=str(tmp_path), concepts=["building"]), Response())
    assert caught.value.status_code == 500
    assert caught.value.headers["X-SAM3-Settled"] == "1"

@pytest.mark.asyncio
async def test_cancelled_caller_keeps_gpu_slot_until_native_worker_finishes(service, tmp_path, monkeypatch):
    service.engine = object()
    path = tmp_path / "input.png"
    Image.new("RGB", (8, 8)).save(path)
    request = service.InferRequest(input_path=str(path), output_dir=str(tmp_path), concepts=["building"])
    started, release = threading.Event(), threading.Event()
    calls = []
    def work(*args):
        calls.append(len(calls))
        started.set()
        assert release.wait(5)
        return {"status": "ok"}
    monkeypatch.setattr(service, "_infer", work)
    first = asyncio.create_task(service.infer(request, Response()))
    await asyncio.to_thread(started.wait, 5)
    first.cancel()
    second = asyncio.create_task(service.infer(request, Response()))
    try:
        await asyncio.sleep(.02)
        assert calls == [0] and not first.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError): await first
    await second
    assert calls == [0, 1]
