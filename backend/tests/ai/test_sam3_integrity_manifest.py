"""The startup gate rejects changed application adapters as well as model assets."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

@pytest.mark.parametrize("tamper", [False, True])
def test_startup_verifier_checks_release_adapter_contents(tmp_path, monkeypatch, tamper):
    project = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("sam3_integrity_under_test", project / "ops/sam3_runtime/validate_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    (sdk / "patch_official_sam3.py").write_text("def _source_sha256(path): return 'source-digest'\n")
    checks = {}
    for name in ("original", "tensor"):
        path = sdk / (name + ".bin")
        path.write_bytes(name.encode())
        checks[name] = {"path": path.name, "size_bytes": path.stat().st_size,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    release = tmp_path / "release"
    release.mkdir()
    adapter = release / "adapter.py"
    adapter.write_text("verified = True\n")
    (release / "runtime-manifest.json").write_text(json.dumps({"release": "candidate",
        "files": {"adapter.py": hashlib.sha256(adapter.read_bytes()).hexdigest()}}))
    manifest = {"source": {"commit": "official-commit", "patched_sha256": "source-digest"},
        "checkpoints": checks, "code_sha256": {}, "provider": "meta_official_sam3",
        "agent_rs": {"release_root": str(release), "release": "candidate", "code_paths": ["adapter.py"]}}
    path = sdk / "runtime-manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(module, "ROOT", sdk)
    monkeypatch.setattr(module, "MANIFEST_PATH", path)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="official-commit"))
    if tamper:
        adapter.write_text("changed = True\n")
        with pytest.raises(SystemExit, match="application adapter digest mismatch"):
            module.main()
    else:
        module.main()
