"""heldout 冻结 manifest 与 live run 状态机。

纪律落点：
- freeze_dataset: 冻结一次，重复冻结只允许 hash 完全一致（防改题重冻结）。
- assert_dataset_frozen: 评分前重算 hash 对照 manifest（防冻结后改题/改生成器）。
- prepare_live_run / seal_run: 同 (dataset_hash, prompt_hash, model) 只允许一个 live run；
  in_progress 可断点续录缺失 case；sealed 后再次 live 直接抛 SealedRunError（防重采挑分）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path


DATASET_MANIFEST_NAME = "dataset_manifest.json"
RUN_MANIFEST_NAME = "run_manifest.json"


class HeldoutDisciplineError(RuntimeError):
    """违反 heldout 纪律（改题、重冻结、重采）。"""


class SealedRunError(HeldoutDisciplineError):
    """sealed run 禁止再次 live 录制。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# dataset 冻结


def freeze_dataset(
    cases,
    *,
    dataset_id: str,
    seed: int,
    out_dir: Path,
    label_policy: str,
) -> Path:
    """写 dataset manifest。已存在时只接受完全相同的 hash（幂等），否则拒绝。"""

    from tests.ai.eval.heldout_generator import dataset_hash, heldout_summary, validate_heldout_cases

    validate_heldout_cases(cases)
    current_hash = dataset_hash(cases)
    path = out_dir / DATASET_MANIFEST_NAME
    if path.exists():
        existing = _read_json(path)
        if existing.get("dataset_hash") != current_hash:
            raise HeldoutDisciplineError(
                f"dataset {dataset_id} already frozen with different hash; "
                "refusing to re-freeze (改题重冻结被拦截)"
            )
        return path
    summary = heldout_summary(cases)
    _write_json(
        path,
        {
            "dataset_id": dataset_id,
            "seed": seed,
            "case_count": len(cases),
            "dataset_hash": current_hash,
            "created_at": _now(),
            "label_policy": label_policy,
            "kinds": summary["kinds"],
            "expected_none": summary["expected_none"],
            "expected_call": summary["expected_call"],
            "diagnostic_unsupported": summary["diagnostic_unsupported"],
            "prompt_near": summary["prompt_near"],
        },
    )
    return path


def load_dataset_manifest(out_dir: Path) -> dict:
    path = out_dir / DATASET_MANIFEST_NAME
    if not path.exists():
        raise HeldoutDisciplineError(f"dataset manifest missing: {path}（必须先冻结再跑）")
    return _read_json(path)


def assert_dataset_frozen(cases, out_dir: Path) -> dict:
    """评分入口的硬门：重算 hash 必须与冻结 manifest 一致。"""

    from tests.ai.eval.heldout_generator import dataset_hash

    manifest = load_dataset_manifest(out_dir)
    current = dataset_hash(cases)
    if current != manifest["dataset_hash"]:
        raise HeldoutDisciplineError(
            "heldout dataset hash mismatch vs frozen manifest "
            f"(frozen={manifest['dataset_hash'][:12]}…, current={current[:12]}…)；"
            "冻结后改题/改生成器被拦截"
        )
    if len(cases) != manifest["case_count"]:
        raise HeldoutDisciplineError("heldout case count mismatch vs frozen manifest")
    return manifest


# ---------------------------------------------------------------------------
# live run 状态机


def prepare_live_run(
    run_dir: Path,
    *,
    dataset_id: str,
    dataset_hash: str,
    prompt_hash: str,
    model: str,
) -> dict:
    """开始/恢复 live 录制前的门。sealed → 拒绝；in_progress 且 pin 一致 → 续录。"""

    path = run_dir / RUN_MANIFEST_NAME
    if path.exists():
        manifest = _read_json(path)
        if manifest.get("status") == "sealed":
            raise SealedRunError(
                f"run {manifest.get('run_id')} is sealed; re-live recording is forbidden（重采被拦截）"
            )
        if manifest.get("status") == "aborted":
            raise HeldoutDisciplineError(
                "aborted run cannot be resumed as official score; create heldout-v2"
            )
        pins = {"dataset_id": dataset_id, "dataset_hash": dataset_hash, "prompt_hash": prompt_hash, "model": model}
        mismatched = {k: v for k, v in pins.items() if manifest.get(k) != v}
        if mismatched:
            raise HeldoutDisciplineError(
                f"in-progress run pins mismatch {sorted(mismatched)}; "
                "不允许换 prompt/model/数据集续录"
            )
        return manifest
    manifest = {
        "run_id": f"{dataset_id}__{prompt_hash[:12]}__{model}",
        "dataset_id": dataset_id,
        "dataset_hash": dataset_hash,
        "prompt_hash": prompt_hash,
        "model": model,
        "status": "in_progress",
        "created_at": _now(),
    }
    _write_json(path, manifest)
    return manifest


def recordings_digest(run_dir: Path) -> str:
    entries = []
    for file in sorted(run_dir.glob("*.json")):
        if file.name == RUN_MANIFEST_NAME:
            continue
        entries.append((file.name, sha256(file.read_bytes()).hexdigest()))
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def seal_run(run_dir: Path, *, expected_case_ids) -> dict:
    """全部 case 录制齐才允许封存；封存后写 recordings_hash，状态不可逆。"""

    path = run_dir / RUN_MANIFEST_NAME
    if not path.exists():
        raise HeldoutDisciplineError("cannot seal: run manifest missing (run never prepared)")
    manifest = _read_json(path)
    if manifest.get("status") == "sealed":
        return manifest
    recorded = {file.stem for file in run_dir.glob("*.json") if file.name != RUN_MANIFEST_NAME}
    missing = sorted(set(expected_case_ids) - recorded)
    if missing:
        raise HeldoutDisciplineError(
            f"cannot seal: {len(missing)} recordings missing (first: {missing[:5]})"
        )
    manifest["status"] = "sealed"
    manifest["sealed_at"] = _now()
    manifest["recordings_hash"] = recordings_digest(run_dir)
    manifest["recorded_count"] = len(recorded)
    _write_json(path, manifest)
    return manifest


def abort_run(run_dir: Path, *, reason: str) -> dict:
    path = run_dir / RUN_MANIFEST_NAME
    manifest = _read_json(path) if path.exists() else {"status": "in_progress"}
    if manifest.get("status") == "sealed":
        raise HeldoutDisciplineError("sealed run cannot be aborted")
    manifest["status"] = "aborted"
    manifest["aborted_at"] = _now()
    manifest["abort_reason"] = reason
    _write_json(path, manifest)
    return manifest


def assert_run_sealed(run_dir: Path) -> dict:
    """正式成绩只能来自 sealed run 的 replay。"""

    path = run_dir / RUN_MANIFEST_NAME
    if not path.exists():
        raise HeldoutDisciplineError(f"run manifest missing: {path}")
    manifest = _read_json(path)
    if manifest.get("status") != "sealed":
        raise HeldoutDisciplineError(
            f"official score requires a sealed run, got status={manifest.get('status')}"
        )
    current = recordings_digest(run_dir)
    if current != manifest.get("recordings_hash"):
        raise HeldoutDisciplineError(
            "recordings tampered after seal (digest mismatch)；封存后改录制被拦截"
        )
    return manifest
