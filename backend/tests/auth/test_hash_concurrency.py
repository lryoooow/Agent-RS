import asyncio
import threading

import pytest

import app.auth.security as security
from app.core.settings import get_settings


@pytest.mark.asyncio
async def test_cancelled_hash_retains_slot_until_cpu_thread_finishes(monkeypatch):
    monkeypatch.setenv("AUTH_HASH_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()
    started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def work(password):
        if password == "first":
            started.set()
            assert release.wait(2)
        else:
            second_started.set()
        return "test-hash"

    monkeypatch.setattr(security, "_hash_password_sync", work)
    first = asyncio.create_task(security.hash_password("first"))
    second = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(security.hash_password("second"))
        await asyncio.sleep(0.01)
        assert not second_started.is_set()
        release.set()
        assert await asyncio.wait_for(second, 1) == "test-hash"
        assert second_started.is_set()
    finally:
        release.set()
        first.cancel()
        if second:
            second.cancel()
        await asyncio.gather(*[task for task in (first, second) if task], return_exceptions=True)


@pytest.mark.asyncio
async def test_hash_and_verify_share_the_same_resource_limit(monkeypatch):
    monkeypatch.setenv("AUTH_HASH_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()
    active, peak = 0, 0
    lock = threading.Lock()

    def work(*args):
        import time
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(security, "_hash_password_sync", work)
    monkeypatch.setattr(security, "_verify_password_sync", work)
    await asyncio.gather(security.hash_password("test"), security.verify_password("test", "test-hash"), security.hash_password("test"))
    assert peak == 1
