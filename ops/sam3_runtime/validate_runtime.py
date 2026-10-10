from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path('/home/LRY/sam3-runtime-releases/20260922-meta-2345a4ad').resolve()
MANIFEST_PATH = ROOT / 'runtime-manifest.json'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f'SAM3 runtime validation failed: {message}')


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    commit = subprocess.run(
        ['git', '-C', str(ROOT / 'source'), 'rev-parse', 'HEAD'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != manifest['source']['commit']:
        fail('official source commit mismatch')

    patch_path = ROOT / 'patch_official_sam3.py'
    spec = importlib.util.spec_from_file_location('sam3_runtime_patch', patch_path)
    if spec is None or spec.loader is None:
        fail('patch verifier cannot be loaded')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_digest = module._source_sha256(ROOT / 'source' / 'sam3')
    if source_digest != manifest['source']['patched_sha256']:
        fail('patched official source digest mismatch')

    for key in ('original', 'tensor'):
        item = manifest['checkpoints'][key]
        path = (ROOT / item['path']).resolve()
        if path.stat().st_size != item['size_bytes'] or sha256(path) != item['sha256']:
            fail(f'{key} checkpoint mismatch')

    for relative, expected in manifest['code_sha256'].items():
        if sha256(ROOT / relative) != expected:
            fail(f'code digest mismatch: {relative}')

    application = manifest.get('agent_rs')
    if application:
        release_root = Path(application['release_root']).resolve()
        release_manifest = json.loads((release_root / 'runtime-manifest.json').read_text(encoding='utf-8'))
        if release_manifest['release'] != application['release']:
            fail('application release mismatch')
        for relative in application['code_paths']:
            expected = release_manifest['files'].get(relative)
            path = (release_root / relative).resolve()
            if not path.is_relative_to(release_root) or not expected or sha256(path) != expected:
                fail(f'application adapter digest mismatch: {relative}')

    print(json.dumps({
        'status': 'ok',
        'provider': manifest['provider'],
        'source_commit': commit,
        'source_sha256': source_digest,
        'checkpoint_sha256': manifest['checkpoints']['original']['sha256'],
    }, separators=(',', ':')))


if __name__ == '__main__':
    main()
