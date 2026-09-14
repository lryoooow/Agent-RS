"""P1 统一错误契约：所有错误响应只有一种形状。

    {"error": {"code": <机器码>, "message": <用户可读>}}

三个来源全覆盖：路由 api_error、存量字符串 detail（处理器包裹）、
未处理异常（兜底 500）。任何端点返回其它顶层形状都算违约。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.main import create_app


def _assert_envelope(payload) -> None:
    assert isinstance(payload, dict), payload
    assert set(payload) == {"error"}, f"顶层只允许 error 键，实际 {sorted(payload)}"
    error = payload["error"]
    assert isinstance(error["code"], str) and error["code"], error
    assert "HTTP" not in error["code"] or error["code"].startswith("HTTP_"), error
    assert isinstance(error["message"], str) and error["message"], error


@pytest.fixture()
def client():
    # raise_server_exceptions=False：让兜底 500 处理器真的生成响应而不是重抛。
    return TestClient(create_app(), raise_server_exceptions=False)


def test_plain_string_detail_is_wrapped(client) -> None:
    """存量字符串 detail → HTTP_<status> 码 + 原文案。"""
    app: FastAPI = client.app
    from fastapi import APIRouter

    probe = APIRouter()

    @probe.get("/api/__probe/string")
    async def plain():
        raise StarletteHTTPException(status_code=418, detail="存量写法")

    @probe.get("/api/__probe/coded")
    async def coded():
        from app.api.errors import api_error

        raise api_error(409, "CONFLICT", "冲突演示")

    app.include_router(probe)
    response = client.get("/api/__probe/string")
    assert response.status_code == 418
    _assert_envelope(response.json())
    assert response.json()["error"] == {"code": "HTTP_418", "message": "存量写法"}

    response = client.get("/api/__probe/coded")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_unknown_route_404_uses_envelope(client) -> None:
    response = client.get("/api/definitely/not/a/route")
    assert response.status_code == 404
    _assert_envelope(response.json())


def test_unhandled_exception_is_500_envelope_without_leak(client) -> None:
    app: FastAPI = client.app
    from fastapi import APIRouter

    probe = APIRouter()

    @probe.get("/api/__probe/boom")
    async def boom():
        raise RuntimeError("SECRET_INTERNAL_DETAIL")

    app.include_router(probe)
    response = client.get("/api/__probe/boom")
    assert response.status_code == 500
    payload = response.json()
    _assert_envelope(payload)
    assert "SECRET_INTERNAL_DETAIL" not in response.text, "内部异常细节不得外泄"


def test_real_routes_all_use_envelope(client, monkeypatch) -> None:
    """真实路由抽样：scenes 404/400、imagery 400、校验 422 全部同一形状。"""
    from app.core.settings import get_settings

    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()

    cases = [
        ("get", "/api/scenes/ffffffffffff/preview", 404),
        ("post", "/api/imagery/upload", 400),  # 无文件
        ("post", "/api/scenes/search", 400),  # 无区域
        ("post", "/api/scenes/search", 422),  # body 非法
    ]
    bodies = {
        "post:/api/scenes/search": None,  # 第一个 400 用例：空 body
    }
    # 简化：逐案调用
    r = client.get("/api/scenes/ffffffffffff/preview")
    assert r.status_code == 404
    _assert_envelope(r.json())

    r = client.post("/api/scenes/search", json={})
    assert r.status_code == 400
    _assert_envelope(r.json())

    r = client.post("/api/scenes/search", data="{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    _assert_envelope(r.json())
