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
    geocode._FORWARD_CACHE.clear()
    geocode._PREFETCH_TASKS.clear()
    monkeypatch.setattr(geocode, "_client", None)
    yield
    geocode._GEOCODE_CACHE.clear()
    geocode._FORWARD_CACHE.clear()
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


@pytest.mark.asyncio
async def test_prefetch_location_caps_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    # O5：去重外的并发 prefetch 有上限，避免突发请求把 Nominatim 打到限流/封禁。
    release = asyncio.Event()

    async def slow_reverse_geocode(*_args, **_kwargs):
        await release.wait()

    monkeypatch.setattr(geocode, "reverse_geocode", slow_reverse_geocode)
    monkeypatch.setattr(geocode, "PREFETCH_MAX_CONCURRENT", 2)

    for i in range(5):  # 5 个不同坐标单元，都未命中缓存
        geocode.prefetch_location(22.0 + i, 114.0)
    await asyncio.sleep(0)

    assert len(geocode._PREFETCH_TASKS) <= 2  # 受并发上限约束（5 里只起 2 个）

    release.set()
    await asyncio.gather(*tuple(geocode._PREFETCH_TASKS.values()), return_exceptions=True)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_aclose_geocode_client_closes_and_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    # O5：aclose 关闭模块全局 httpx 客户端并置 None（lifespan 收尾释放连接池）。
    closed = {"flag": False}

    class ClosableClient:
        async def aclose(self) -> None:
            closed["flag"] = True

    monkeypatch.setattr(geocode, "_client", ClosableClient())
    await geocode.aclose_geocode_client()
    assert closed["flag"] is True
    assert geocode._client is None


@pytest.mark.asyncio
async def test_forward_geocode_returns_center_and_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    # 对话控图：forward_geocode 把地名解析成 center[bbox?] 供地图跳转。
    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "lat": "39.9042",
                    "lon": "116.4074",
                    "display_name": "北京, 中国",
                    "boundingbox": ["39.4", "41.1", "115.4", "117.5"],
                }
            ]

    class FakeClient:
        async def get(self, *_args, **_kwargs) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(geocode, "_client", FakeClient())
    geocode._FORWARD_CACHE.clear()

    res = await geocode.forward_geocode("北京")
    assert res is not None
    assert res["center"] == [116.4074, 39.9042]  # [lng, lat]
    assert res["bbox"] == [[115.4, 39.4], [117.5, 41.1]]  # [[west,south],[east,north]]
    assert res["display_name"]

    assert await geocode.forward_geocode("") is None  # 空查询安全回落


@pytest.mark.asyncio
async def test_forward_geocode_prefers_photon_and_parses_chinese_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PhotonResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {
                        "type": "city",
                        "name": "杭州市",
                        "state": "浙江省",
                        "country": "中国",
                        "extent": [118.3397, 30.5649, 120.7255, 29.1888],
                    },
                    "geometry": {"type": "Point", "coordinates": [120.2052342, 30.2489634]},
                }],
            }

    class PhotonClient:
        calls: list[str] = []

        async def get(self, url: str, **_kwargs) -> PhotonResp:
            self.calls.append(url)
            return PhotonResp()

    client = PhotonClient()
    monkeypatch.setattr(geocode, "_client", client)

    result = await geocode.forward_geocode("杭州市")

    assert result is not None
    assert result["center"] == [120.2052342, 30.2489634]
    assert result["zoom"] == 11
    assert result["provider"] == "photon"
    assert "bbox" not in result
    assert client.calls == [f"{geocode.PHOTON_BASE_URL}/api/"]


def test_photon_query_variants_normalize_chinese_admin_names() -> None:
    assert geocode._photon_query_variants("浙江省杭州市")[0] == "杭州市"
    assert "南山区 深圳市" in geocode._photon_query_variants("深圳南山")


def _fake_nominatim(monkeypatch: pytest.MonkeyPatch, item: dict) -> None:
    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [item]

    class FakeClient:
        async def get(self, *_args, **_kwargs) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(geocode, "_client", FakeClient())
    geocode._FORWARD_CACHE.clear()


@pytest.mark.asyncio
async def test_city_geocodes_to_center_without_admin_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """点状地名（城市）定心 + 城市级缩放，不框行政区划。

    Nominatim 把「北京市」标成 addresstype=city 但 bbox 是整个市域（含远郊
    山区）；下发 bbox 会让前端 fitBounds 把市域框进视野，用户只看到"缩小"。
    """
    _fake_nominatim(
        monkeypatch,
        {
            "lat": "39.9057",
            "lon": "116.3913",
            "display_name": "北京市, 中国",
            "addresstype": "city",
            "boundingbox": ["39.17", "41.06", "115.42", "117.51"],
        },
    )
    res = await geocode.forward_geocode("北京")
    assert res is not None
    assert res["center"] == [116.3913, 39.9057]
    assert res["zoom"] == 11
    assert "bbox" not in res, "点状地名不应下发行政边界 bbox"


@pytest.mark.asyncio
async def test_area_geocodes_to_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """面状地名（省/流域/国家）保留 bbox 框选视角。"""
    _fake_nominatim(
        monkeypatch,
        {
            "lat": "30.5",
            "lon": "114.3",
            "display_name": "长江流域",
            "addresstype": "river",
            "boundingbox": ["24.0", "35.0", "90.0", "122.0"],
        },
    )
    res = await geocode.forward_geocode("长江流域")
    assert res is not None
    assert res["bbox"] == [[90.0, 24.0], [122.0, 35.0]]
    assert res["zoom"] == 4  # 跨度 >10° 的全国级视角
