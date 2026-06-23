"""tests/api 局部夹具：把 TestClient 路由单测与开发者本地 .env 的部署开关隔离。

根因：app.core.settings 会读 backend/.env。开发者本机 .env 常设 DATABASE_ENABLED=true、
AUTH_ENABLED=true，使 settings.auth_required 为真；而这些路由单测多用 fake pool/service 验证
路由逻辑本身，并不登录。强制登录门（require_authenticated_user）于是把它们挡成 401。
CI 无 .env 时 database_enabled 默认 false、auth_required 为假，故仅在有 .env 的本机暴露。

做法：autouse 在每个 api 用例前先把 AUTH_ENABLED 置 false（关掉强制登录门），
需要验证鉴权/强制登录的新用例在自身内 monkeypatch.setenv 覆盖回 true（用例内的 setenv 在夹具之后执行，优先级更高）。
真实 PG 集成用例走 pg_pool（另在全局 conftest），不经过本夹具的 create_app 路径，互不影响。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_auth_env_for_api_unit_tests(monkeypatch):
    # 默认关闭强制登录门，消除本地 .env 的 AUTH_ENABLED/DATABASE_ENABLED 泄漏；
    # 需要鉴权的用例在自身 setenv("AUTH_ENABLED","true") 覆盖。
    monkeypatch.setenv("AUTH_ENABLED", "false")
    yield
