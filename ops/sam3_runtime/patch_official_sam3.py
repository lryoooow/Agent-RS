"""Apply the audited Windows image-only import patch to pinned Meta SAM3.

Meta's model builder imports video tracking modules (and therefore Triton) at
module import time even when ``enable_inst_interactivity=False``. Triton is not
available in the supported Windows runtime. This patch only defers those video
and interactive imports until their corresponding builders are called; image
model construction and ``Sam3Processor`` are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

UPSTREAM_COMMIT = "2345a4ad109ac29c569da749c91d84f10dc08c40"
UPSTREAM_SOURCE_SHA256 = "3d81b2ad5a5e201ec280b1e0f0c43b2f531f5ecf54f0c112dfa8ce195e15a372"
UPSTREAM_MODEL_BUILDER_SHA256 = "c78af29c3db0f0ef3c9ec66dcfe32d6a9fd70b82f660142e97908a5ce61c469f"
UPSTREAM_IMAGE_MODEL_SHA256 = "baf67f45a914d9c377c850d52ed083db8924943775f5884b9fd7a5d65b8637d1"
PATCH_ID = "windows_image_only_lazy_video_imports_v1"
PATCHED_MODEL_BUILDER_SHA256 = "530bf7e7e0f4db1d6d28e2526902887ad8c872aa935736d7c9abacbf871cc0dd"
PATCHED_IMAGE_MODEL_SHA256 = "f5c9229edddd4189891510e4d998b9c6db0b41e8e9a14520044a942a031695cf"
PATCHED_SOURCE_SHA256 = "26a4f92919756ad412e111b20868f4bc1f2b2d7170214ab5cdae1669d6051f1a"

_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "# pyre-unsafe\n\nimport os",
        "# pyre-unsafe\n\nfrom __future__ import annotations\n\nimport os",
    ),
    (
        "from sam3.model.sam1_task_predictor import SAM3InteractiveImagePredictor\n",
        "",
    ),
    (
        "from sam3.model.sam3_image import Sam3Image, Sam3ImageOnVideoMultiGPU\n",
        "from sam3.model.sam3_image import Sam3Image\n",
    ),
    (
        "from sam3.model.sam3_tracking_predictor import Sam3TrackerPredictor\n",
        "",
    ),
    (
        "from sam3.model.sam3_video_inference import Sam3VideoInferenceWithInstanceInteractivity\n",
        "",
    ),
    (
        "from sam3.model.sam3_video_predictor import Sam3VideoPredictorMultiGPU\n",
        "",
    ),
    (
        "from sam3.model.video_tracking_multiplex import VideoTrackingDynamicMultiplex\n",
        "",
    ),
    (
        "        Sam3TrackerPredictor: Wrapped SAM3 Tracker module\n    \"\"\"\n\n    # Create model components",
        "        Sam3TrackerPredictor: Wrapped SAM3 Tracker module\n    \"\"\"\n    from sam3.model.sam3_tracking_predictor import Sam3TrackerPredictor\n\n    # Create model components",
    ),
    (
        "    if enable_inst_interactivity:\n        sam3_pvs_base = build_tracker",
        "    if enable_inst_interactivity:\n        from sam3.model.sam1_task_predictor import SAM3InteractiveImagePredictor\n\n        sam3_pvs_base = build_tracker",
    ),
    (
        "    # Build Tracker module\n    tracker = build_tracker",
        "    from sam3.model.sam3_image import Sam3ImageOnVideoMultiGPU\n    from sam3.model.sam3_video_inference import Sam3VideoInferenceWithInstanceInteractivity\n\n    # Build Tracker module\n    tracker = build_tracker",
    ),
    (
        "def build_sam3_video_predictor(*model_args, gpus_to_use=None, **model_kwargs):\n    return Sam3VideoPredictorMultiGPU(",
        "def build_sam3_video_predictor(*model_args, gpus_to_use=None, **model_kwargs):\n    from sam3.model.sam3_video_predictor import Sam3VideoPredictorMultiGPU\n\n    return Sam3VideoPredictorMultiGPU(",
    ),
)

_IMAGE_MODEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "# pyre-unsafe\n\nimport os",
        "# pyre-unsafe\n\nfrom __future__ import annotations\n\nimport os",
    ),
    (
        "from sam3.model.sam1_task_predictor import SAM3InteractiveImagePredictor\n",
        "",
    ),
    (
        "from sam3.train.data.collator import BatchedDatapoint\n",
        "",
    ),
    (
        "from .data_misc import FindStage\n",
        "from .data_misc import BatchedDatapoint, FindStage\n",
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_sha256(package_root: Path) -> str:
    rows: list[tuple[str, str]] = []
    for path in sorted(package_root.rglob("*"), key=lambda item: item.relative_to(package_root).as_posix()):
        if path.is_file() and (path.suffix == ".py" or path.name.endswith(".txt.gz")):
            rows.append((path.relative_to(package_root).as_posix(), _sha256(path)))
    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def patch_package(
    package_root: Path,
    *,
    expected_upstream_source: str = UPSTREAM_SOURCE_SHA256,
    expected_upstream_builder: str = UPSTREAM_MODEL_BUILDER_SHA256,
    expected_upstream_image: str = UPSTREAM_IMAGE_MODEL_SHA256,
    expected_patched_source: str = PATCHED_SOURCE_SHA256,
    expected_patched_builder: str = PATCHED_MODEL_BUILDER_SHA256,
    expected_patched_image: str = PATCHED_IMAGE_MODEL_SHA256,
) -> None:
    """Patch one verified package tree or accept the exact patched result."""
    builder = package_root / "model_builder.py"
    image_model = package_root / "model" / "sam3_image.py"
    current_builder = _sha256(builder)
    current_image = _sha256(image_model)
    current_source = _source_sha256(package_root)
    if (
        current_builder == expected_patched_builder
        and current_image == expected_patched_image
        and current_source == expected_patched_source
    ):
        return
    if (
        current_builder != expected_upstream_builder
        or current_image != expected_upstream_image
        or current_source != expected_upstream_source
    ):
        raise RuntimeError("Refusing to patch an unexpected Meta SAM3 source tree.")

    for path, replacements in (
        (builder, _REPLACEMENTS),
        (image_model, _IMAGE_MODEL_REPLACEMENTS),
    ):
        content = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if content.count(old) != 1:
                raise RuntimeError("Meta SAM3 Windows patch no longer matches its pinned source.")
            content = content.replace(old, new, 1)
        path.write_text(content, encoding="utf-8", newline="\n")
    if (
        _sha256(builder) != expected_patched_builder
        or _sha256(image_model) != expected_patched_image
        or _source_sha256(package_root) != expected_patched_source
    ):
        raise RuntimeError("Patched Meta SAM3 source digest does not match the frozen runtime.")


def _installed_package_root() -> Path:
    distribution = importlib.metadata.distribution("sam3")
    direct_url_text = distribution.read_text("direct_url.json")
    if not direct_url_text:
        raise RuntimeError("Meta SAM3 Git provenance is unavailable.")
    direct_url = json.loads(direct_url_text)
    commit = str(direct_url.get("vcs_info", {}).get("commit_id", "")).lower()
    if commit != UPSTREAM_COMMIT:
        raise RuntimeError("Meta SAM3 Git commit does not match the frozen runtime.")
    return Path(distribution.locate_file("sam3")).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path)
    args = parser.parse_args()
    patch_package((args.package_root or _installed_package_root()).resolve())
    print(f"RS_SAM3_PATCH={PATCH_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
