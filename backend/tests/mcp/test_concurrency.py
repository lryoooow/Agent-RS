from __future__ import annotations

import asyncio

import pytest

import app.mcp.concurrency as concurrency
from app.mcp.concurrency import reset_tool_semaphore, tool_semaphore


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """每个用例前后重置模块级信号量，避免跨 event loop 复用导致的误绑。"""
    reset_tool_semaphore()
    yield
    reset_tool_semaphore()


def _set_limit(monkeypatch, value: int) -> None:
    """改 settings.rs_tools_max_concurrent。tool_semaphore 懒读 settings，
    故 patch 后首次调用即生效。"""
    settings = concurrency.get_settings()
    monkeypatch.setattr(settings, "rs_tools_max_concurrent", value, raising=False)
    reset_tool_semaphore()  # 清掉可能已按旧值建好的实例


# ── 常规：上限内全部直接放行 ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_within_limit_all_acquire_without_blocking(monkeypatch) -> None:
    _set_limit(monkeypatch, 3)
    sem = tool_semaphore()
    # 连续 acquire 3 次不阻塞（locked() 在第 3 次后才为 True）
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    assert sem.locked() is True
    sem.release()
    sem.release()
    sem.release()


# ── 边界：第 N+1 个被挡，前 N 个未释放前拿不到槽 ──────────────────────────
@pytest.mark.asyncio
async def test_n_plus_one_blocks_until_release(monkeypatch) -> None:
    _set_limit(monkeypatch, 2)
    sem = tool_semaphore()

    entered = []  # 真正进入临界区的任务序号
    release_gate = asyncio.Event()

    async def worker(idx: int) -> None:
        async with sem:
            entered.append(idx)
            await release_gate.wait()  # 卡住，模拟 docker 跑着不退出

    t1 = asyncio.create_task(worker(1))
    t2 = asyncio.create_task(worker(2))
    t3 = asyncio.create_task(worker(3))  # 第 3 个应被挡在闸外

    await asyncio.sleep(0.05)  # 让前两个进入
    assert sorted(entered) == [1, 2]  # 第 3 个未进入

    release_gate.set()  # 放行
    await asyncio.gather(t1, t2, t3)
    assert sorted(entered) == [1, 2, 3]  # 第 3 个最终也跑了


# ── 异常分支：临界区抛异常仍释放槽位（防"异常吞槽"永久饿死）──────────────
@pytest.mark.asyncio
async def test_exception_in_critical_section_releases_slot(monkeypatch) -> None:
    _set_limit(monkeypatch, 1)
    sem = tool_semaphore()

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        async with sem:
            raise Boom()

    # 异常退出后槽位必须已释放：后续任务能立即拿到
    assert sem.locked() is False
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    sem.release()


# ── 非法输入：0 / 负数配置被兜底为至少 1，不死锁 ─────────────────────────
@pytest.mark.asyncio
async def test_zero_or_negative_limit_clamped_to_one(monkeypatch) -> None:
    for bad in (0, -5):
        _set_limit(monkeypatch, bad)
        sem = tool_semaphore()
        # max(1, bad) → 至少能 acquire 一次而不永久阻塞
        await asyncio.wait_for(sem.acquire(), timeout=0.5)
        assert sem.locked() is True  # 容量确为 1
        sem.release()


# ── 单例：同一 loop 内多次调用返回同一实例 ──────────────────────────────
@pytest.mark.asyncio
async def test_returns_same_instance_within_loop(monkeypatch) -> None:
    _set_limit(monkeypatch, 3)
    assert tool_semaphore() is tool_semaphore()


# ── loop 一致性：reset 后在新 loop 重建不报 "different event loop" ────────
def test_reset_allows_rebind_in_new_loop(monkeypatch) -> None:
    _set_limit(monkeypatch, 2)

    async def grab() -> bool:
        sem = tool_semaphore()
        await asyncio.wait_for(sem.acquire(), timeout=0.5)
        sem.release()
        return True

    # 两个独立 loop 各跑一次；reset 保证第二个 loop 不会复用第一个 loop 绑定的信号量
    assert asyncio.run(grab()) is True
    reset_tool_semaphore()
    assert asyncio.run(grab()) is True


# ── 历史重复点：工具闸与 embedding 闸互不干扰（两个独立信号量）────────────
@pytest.mark.asyncio
async def test_tool_semaphore_independent_from_embedding(monkeypatch) -> None:
    from app.agent.embedding.service import EmbeddingService

    _set_limit(monkeypatch, 1)
    tool_sem = tool_semaphore()
    await tool_sem.acquire()  # 占满工具闸

    # embedding 服务的信号量是另一把锁，不应受工具闸影响
    emb = EmbeddingService()
    assert emb._semaphore is not tool_sem
    await asyncio.wait_for(emb._semaphore.acquire(), timeout=0.5)
    emb._semaphore.release()
    tool_sem.release()


# ── 集成：闸确实接在 RSToolsMCPClient.call_tool 上（防"信号量写对但没接线"）─
@pytest.mark.asyncio
async def test_semaphore_wired_into_rs_tools_client(monkeypatch, tmp_path) -> None:
    import app.mcp.rs_tools_client as rs_mod
    from app.mcp.rs_tools_client import RSToolsMCPClient

    _set_limit(monkeypatch, 2)

    concurrent = 0
    peak = 0
    gate = asyncio.Event()

    class FakeStdio:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def call_tool(self, _name, _payload):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)  # 记录同时在跑的峰值
            try:
                await gate.wait()
                return {"mean": 0.5}
            finally:
                concurrent -= 1

    # 替换真实 docker 执行，避免起容器；闸在 RSToolsMCPClient.call_tool 内，仍生效
    monkeypatch.setattr(rs_mod, "StdioMCPClient", FakeStdio)

    src = tmp_path / "source.tif"
    src.write_bytes(b"x")
    out = tmp_path / "results"
    out.mkdir()

    def run_one():
        client = RSToolsMCPClient(image="fake:0.1.0", timeout_seconds=5)
        return asyncio.create_task(
            client.call_tool("calculate_ndvi", source_path=src, output_dir=out)
        )

    tasks = [run_one() for _ in range(4)]  # 4 个并发，闸=2
    await asyncio.sleep(0.05)
    assert peak <= 2  # 峰值绝不超过闸上限——证明闸真接在 client 上

    gate.set()
    results = await asyncio.gather(*tasks)
    assert all(r == {"mean": 0.5} for r in results)  # 4 个最终都完成
    assert peak == 2  # 闸=2 时峰值恰为 2（既不超也确实并发）
