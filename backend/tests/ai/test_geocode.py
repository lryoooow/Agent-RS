import asyncio

import httpx
import pytest

from app.agent import geocode


class FakeResponse:
    def __init__(self, display_name: str = "深圳市南山区") -> None:
        self._display_name = display_name

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"display_name": self._display_name}


class FakeClient:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse()
        self.calls = 0

    async def get(self, *_args, **_kwargs) -> FakeResponse:
        self.calls += 1
        return self.response


@pytest.fixture(autouse=True)
def reset_geocode_state(monkeypatch: pytest.MonkeyPatch):
    geocode._GEOCODE_CACHE.clear()
    geocode._PREFETCH_TASKS.clear()
    monkeypatch.setattr(geocode, "_client", None)
    yield
    geocode._GEOCODE_CACHE.clear()
    geocode._PREFETCH_TASKS.clear()


@pytest.mark.asyncio
async def test_reverse_geocode_caches_result_and_reuses_current_zoom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr(geocode, "_client", client)

    first = await geocode.reverse_geocode(22.5431, 114.0579, zoom=10)
    second = await geocode.reverse_geocode(22.544, 114.058, zoom=13)

    assert first is not None
    assert second is not None
    assert client.calls == 1
    assert second.display_name == "深圳市南山区"
    assert second.zoom == 13


@pytest.mark.asyncio
async def test_reverse_geocode_does_not_cache_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(FakeResponse(display_name=""))
    monkeypatch.setattr(geocode, "_client", client)

    assert await geocode.reverse_geocode(22.54, 114.05) is None
    assert await geocode.reverse_geocode(22.54, 114.05) is None
    assert client.calls == 2


@pytest.mark.asyncio
async def test_reverse_geocode_degrades_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimeoutClient:
        async def get(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(geocode, "_client", TimeoutClient())

    assert await geocode.reverse_geocode(22.54, 114.05) is None
    assert geocode.cached_location(22.54, 114.05) is None


@pytest.mark.asyncio
async def test_prefetch_location_deduplicates_pending_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_reverse_geocode(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(geocode, "reverse_geocode", slow_reverse_geocode)

    geocode.prefetch_location(22.54, 114.05)
    geocode.prefetch_location(22.54, 114.05)
    await started.wait()

    assert calls == 1
    assert len(geocode._PREFETCH_TASKS) == 1

    release.set()
    await asyncio.gather(*tuple(geocode._PREFETCH_TASKS.values()))
    await asyncio.sleep(0)
    assert geocode._PREFETCH_TASKS == {}


@pytest.mark.asyncio
async def test_geocode_cache_evicts_oldest_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(geocode, "_client", client)
    monkeypatch.setattr(geocode, "GEOCODE_CACHE_MAX_SIZE", 2)

    await geocode.reverse_geocode(10, 10)
    await geocode.reverse_geocode(20, 20)
    await geocode.reverse_geocode(30, 30)

    assert list(geocode._GEOCODE_CACHE) == ["20.00,20.00", "30.00,30.00"]
