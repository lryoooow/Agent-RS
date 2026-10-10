"""F16: no public half-files, no overwrite, per-call workspace cleanup."""
import asyncio
from pathlib import Path
import pytest
import app.mcp.rs_tools_client as module
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.mcp.client import MCPCallError
from app.mcp.concurrency import reset_tool_semaphore


@pytest.fixture(autouse=True)
def isolated_semaphore():
    reset_tool_semaphore()
    yield
    reset_tool_semaphore()


def paths(tmp_path):
    source = tmp_path / "source.tif"
    source.write_bytes(b"source")
    output = tmp_path / "results"
    output.mkdir()
    return source, output


def host_dir(source, payload):
    return source.parent / payload["output_dir"].removeprefix("/data/")


@pytest.mark.asyncio
async def test_outputs_stay_private_until_tool_finishes(tmp_path, monkeypatch):
    source, output = paths(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    class Client:
        def __init__(self, **kwargs):
            pass
        async def call_tool(self, name, payload):
            work = host_dir(source, payload)
            (work / "mask_run1.tif").write_bytes(b"partial")
            started.set()
            await release.wait()
            (work / "mask_run1.tif").write_bytes(b"complete")
            return {"output_tif": "mask_run1.tif"}
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    task = asyncio.create_task(RSToolsMCPClient("test").call_tool("compute", source_path=source, output_dir=output))
    await started.wait()
    assert list(output.iterdir()) == []
    release.set()
    result = await task
    assert (output / result["output_tif"]).read_bytes() == b"complete"
    assert list(source.parent.glob(".tool-output-*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_or_cancel_never_publishes_partial_file(tmp_path, monkeypatch, cancel):
    source, output = paths(tmp_path)
    started = asyncio.Event()
    class Client:
        def __init__(self, **kwargs):
            pass
        async def call_tool(self, name, payload):
            (host_dir(source, payload) / "partial.tif").write_bytes(b"partial")
            started.set()
            if cancel:
                await asyncio.Event().wait()
            raise MCPCallError("test inference failure")
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    task = asyncio.create_task(RSToolsMCPClient("test").call_tool("compute", source_path=source, output_dir=output))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else MCPCallError):
        await task
    assert list(output.iterdir()) == []
    assert list(source.parent.glob(".tool-output-*")) == []


@pytest.mark.asyncio
async def test_existing_artifact_never_overwritten(tmp_path, monkeypatch):
    source, output = paths(tmp_path)
    (output / "old.tif").write_bytes(b"old")
    class Client:
        def __init__(self, **kwargs):
            pass
        async def call_tool(self, name, payload):
            (host_dir(source, payload) / "old.tif").write_bytes(b"new")
            return {"output_tif": "old.tif"}
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    with pytest.raises(MCPCallError, match="artifact_publication_failed"):
        await RSToolsMCPClient("test").call_tool("compute", source_path=source, output_dir=output)
    assert (output / "old.tif").read_bytes() == b"old"


@pytest.mark.asyncio
async def test_publish_failure_rolls_back_only_new_files(tmp_path, monkeypatch):
    source, output = paths(tmp_path)
    (output / "historical.tif").write_bytes(b"history")
    class Client:
        def __init__(self, **kwargs):
            pass
        async def call_tool(self, name, payload):
            work = host_dir(source, payload)
            (work / "a.tif").write_bytes(b"a")
            (work / "b.png").write_bytes(b"b")
            return {"output_tif": "a.tif", "output_png": "b.png"}
    original = Path.replace
    def replace(path, target):
        if path.name == "b.png":
            raise OSError("test disk full")
        return original(path, target)
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(MCPCallError, match="artifact_publication_failed"):
        await RSToolsMCPClient("test").call_tool("compute", source_path=source, output_dir=output)
    assert [p.name for p in output.iterdir()] == ["historical.tif"]
    assert (output / "historical.tif").read_bytes() == b"history"


@pytest.mark.asyncio
async def test_concurrent_calls_have_independent_output_workspaces(tmp_path, monkeypatch):
    source, output = paths(tmp_path)
    workspaces = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def call_tool(self, name, payload):
            work = host_dir(source, payload)
            workspaces.append(work)
            (work / (name + ".tif")).write_bytes(name.encode())
            await asyncio.sleep(0)
            return {"output_tif": name + ".tif"}
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    client = RSToolsMCPClient("test")
    await asyncio.gather(*(client.call_tool(name, source_path=source, output_dir=output) for name in ("one", "two")))
    assert len(set(workspaces)) == 2
    assert sorted(p.name for p in output.iterdir()) == ["one.tif", "two.tif"]



def test_independent_publishers_do_not_delete_each_others_lock_directory(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    first_ready, second_done = Event(), Event()
    output = tmp_path / "results"
    output.mkdir()
    work_a, work_b = tmp_path / "a", tmp_path / "b"
    work_a.mkdir()
    work_b.mkdir()
    (work_a / "a_uuid.tif").write_bytes(b"a")
    (work_b / "b_uuid.tif").write_bytes(b"b")
    original = Path.mkdir
    def mkdir(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.name == ".artifact-locks" and current_thread().name == "publisher_0":
            first_ready.set()
            assert second_done.wait(3)
        return result
    monkeypatch.setattr(Path, "mkdir", mkdir)
    def publish_b():
        assert first_ready.wait(3)
        try:
            module._publish_outputs(work_b, output, {"output_tif": "b_uuid.tif"})
        finally:
            second_done.set()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="publisher") as pool:
        first = pool.submit(module._publish_outputs, work_a, output, {"output_tif": "a_uuid.tif"})
        second = pool.submit(publish_b)
        first.result(timeout=5)
        second.result(timeout=5)
    assert (output / "a_uuid.tif").read_bytes() == b"a"
    assert (output / "b_uuid.tif").read_bytes() == b"b"
    assert list((tmp_path / ".artifact-locks").iterdir()) == []


@pytest.mark.parametrize("value", [None, 123, [], "missing.png", "../escape.png"])
def test_declared_file_metadata_must_point_to_a_completed_file(tmp_path, value):
    work, out = tmp_path / "work", tmp_path / "results"
    work.mkdir()
    out.mkdir()
    with pytest.raises(MCPCallError, match="artifact_publication_failed"):
        module._publish_outputs(work, out, {"output_png": value})
    assert not list(out.iterdir())


def test_nonfile_output_metadata_is_preserved(tmp_path):
    work, out = tmp_path / "work", tmp_path / "results"
    work.mkdir()
    out.mkdir()
    result = {"output_crs": "EPSG:4326", "output_dtype": "float32", "output_geojson": None}
    module._publish_outputs(work, out, result)
    assert result["output_crs"] == "EPSG:4326"


@pytest.mark.asyncio
async def test_linux_container_uses_service_identity_without_relaxing_private_directories(tmp_path, monkeypatch):
    source, output = paths(tmp_path)
    commands = []
    monkeypatch.setattr(module.os, "getuid", lambda: 1002, raising=False)
    monkeypatch.setattr(module.os, "getgid", lambda: 1000, raising=False)
    class Client:
        def __init__(self, **kwargs):
            commands.append(kwargs["command"])
        async def call_tool(self, name, payload):
            work = host_dir(source, payload)
            if module.os.name == "posix":
                assert work.stat().st_mode & 0o077 == 0
            (work / "identity_run.tif").write_bytes(b"complete")
            return {"output_tif": "identity_run.tif"}
    monkeypatch.setattr(module, "StdioMCPClient", Client)
    await RSToolsMCPClient("test").call_tool("compute", source_path=source, output_dir=output)
    assert commands[0][commands[0].index("--user") + 1] == "1002:1000"
    assert (output / "identity_run.tif").read_bytes() == b"complete"
