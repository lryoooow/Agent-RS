"""注册门控 / 登录硬化 / 管理 API 的端到端集成测试（真库 pg_pool）。

覆盖：邀请码注册全流程、各类无效码拒绝、事务回滚不消费、登录枚举防护与限流、
管理员鉴权、停用用户即会话失效。库不可达整组 skip。

为何用 httpx.AsyncClient + ASGITransport 而非 TestClient：
pg_pool 夹具的 asyncpg 连接绑定 session 级 event loop（见全局 conftest），
TestClient 自带独立 loop 会触发 asyncpg "attached to a different loop"。
AsyncClient 直接在 session loop 上跑 ASGI 应用，与夹具池同 loop，安全共享。
"""
from __future__ import annotations

import contextlib

import pytest
from httpx import ASGITransport, AsyncClient

import app.db.pool as pool_module
from app.auth.invites import generate_invite_code, hash_invite_code
from app.auth.throttle import reset_login_throttle
from app.db.repositories.identity import ensure_default_identity
from app.db.repositories.invite import create_invite
from app.core.settings import get_settings

pytestmark = pytest.mark.asyncio(loop_scope="session")

_SECRET = "test-secret-key-please-change"


@contextlib.contextmanager
def _auth_env(monkeypatch, *, invite_required=True, admin_emails="", max_failures=5):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("INVITE_REQUIRED", "true" if invite_required else "false")
    monkeypatch.setenv("ADMIN_EMAILS", admin_emails)
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES", str(max_failures))
    get_settings.cache_clear()
    reset_login_throttle()
    yield


def _client(pg_pool, monkeypatch) -> AsyncClient:
    # 把全局池指向夹具池：所有 by-name importers 经 fetch_optional_pool→get_db_pool 读到它。
    monkeypatch.setattr(pool_module, "_pool", pg_pool, raising=False)
    monkeypatch.setattr(pool_module, "_pool_initialized", True, raising=False)
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    return AsyncClient(transport=transport, base_url="http://test")


async def _mint(pg_pool, code: str) -> None:
    settings = get_settings()
    async with pg_pool.acquire() as conn:
        await ensure_default_identity(conn, settings)
        await create_invite(
            conn,
            code_hash=hash_invite_code(code, _SECRET),
            created_by_user_id=settings.default_user_id,
        )


async def test_register_requires_invite_when_enabled(pg_pool, monkeypatch):
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            resp = await client.post(
                "/api/auth/register",
                json={"email": "u1@x.com", "password": "averylongpassword"},
            )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INVITE_REQUIRED"


async def test_valid_invite_registers_and_is_single_use(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            ok = await client.post(
                "/api/auth/register",
                json={"email": "u2@x.com", "password": "averylongpassword", "invite_code": code},
            )
            assert ok.status_code == 200
            assert ok.json()["user"]["authenticated"] is True
            # 单次码二次使用被拒
            again = await client.post(
                "/api/auth/register",
                json={"email": "u3@x.com", "password": "averylongpassword", "invite_code": code},
            )
    assert again.status_code == 403
    assert again.json()["detail"]["code"] == "INVITE_INVALID"


async def test_unknown_invite_rejected(pg_pool, monkeypatch):
    async with pg_pool.acquire() as conn:
        await ensure_default_identity(conn, get_settings())
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            resp = await client.post(
                "/api/auth/register",
                json={
                    "email": "u4@x.com",
                    "password": "averylongpassword",
                    "invite_code": "RS-ZZZZ-ZZZZ-ZZZZ",
                },
            )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "INVITE_INVALID"


async def test_duplicate_email_409_and_invite_not_consumed(pg_pool, monkeypatch):
    # 事务回滚：注册重复邮箱失败时，邀请码不被消费，仍可给新邮箱用。
    used_code = generate_invite_code()
    spare_code = generate_invite_code()
    await _mint(pg_pool, used_code)
    await _mint(pg_pool, spare_code)
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            first = await client.post(
                "/api/auth/register",
                json={"email": "dup@x.com", "password": "averylongpassword", "invite_code": used_code},
            )
            assert first.status_code == 200
            # 用 spare_code 注册重复邮箱 → 409
            dup = await client.post(
                "/api/auth/register",
                json={"email": "dup@x.com", "password": "averylongpassword", "invite_code": spare_code},
            )
            assert dup.status_code == 409
            # spare_code 未被消费：换新邮箱仍能注册成功
            fresh = await client.post(
                "/api/auth/register",
                json={"email": "fresh@x.com", "password": "averylongpassword", "invite_code": spare_code},
            )
    assert fresh.status_code == 200


async def test_password_too_short_rejected(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            resp = await client.post(
                "/api/auth/register",
                json={"email": "pw@x.com", "password": "short", "invite_code": code},
            )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PASSWORD_TOO_SHORT"


async def test_login_enumeration_protection(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            await client.post(
                "/api/auth/register",
                json={"email": "known@x.com", "password": "averylongpassword", "invite_code": code},
            )
            unknown = await client.post(
                "/api/auth/login", json={"email": "ghost@x.com", "password": "whatever12345"}
            )
            wrong = await client.post(
                "/api/auth/login", json={"email": "known@x.com", "password": "wrongpassword1"}
            )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"]["code"] == wrong.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_login_lockout(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch, max_failures=3):
        async with _client(pg_pool, monkeypatch) as client:
            await client.post(
                "/api/auth/register",
                json={"email": "lock@x.com", "password": "averylongpassword", "invite_code": code},
            )
            for _ in range(3):
                await client.post(
                    "/api/auth/login", json={"email": "lock@x.com", "password": "badpassword12"}
                )
            locked = await client.post(
                "/api/auth/login", json={"email": "lock@x.com", "password": "badpassword12"}
            )
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"


async def test_login_succeeds_with_correct_password(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch):
        async with _client(pg_pool, monkeypatch) as client:
            await client.post(
                "/api/auth/register",
                json={"email": "good@x.com", "password": "averylongpassword", "invite_code": code},
            )
            # 退出当前会话 cookie，重新登录
            client.cookies.clear()
            resp = await client.post(
                "/api/auth/login", json={"email": "good@x.com", "password": "averylongpassword"}
            )
    assert resp.status_code == 200
    assert resp.json()["user"]["authenticated"] is True


async def test_admin_required_for_admin_endpoints(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch, admin_emails="boss@x.com"):
        async with _client(pg_pool, monkeypatch) as client:
            # 普通用户
            await client.post(
                "/api/auth/register",
                json={"email": "peon@x.com", "password": "averylongpassword", "invite_code": code},
            )
            forbidden = await client.post("/api/admin/invites", json={})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_admin_mints_invite_code_returned_once(pg_pool, monkeypatch):
    code = generate_invite_code()
    await _mint(pg_pool, code)
    with _auth_env(monkeypatch, admin_emails="boss@x.com"):
        async with _client(pg_pool, monkeypatch) as client:
            await client.post(
                "/api/auth/register",
                json={"email": "boss@x.com", "password": "averylongpassword", "invite_code": code},
            )
            created = await client.post("/api/admin/invites", json={"label": "for-tester"})
            assert created.status_code == 200
            body = created.json()
            assert body["code"].startswith("RS-")
            listed = (await client.get("/api/admin/invites")).json()
    assert all("code" not in inv for inv in listed["invites"])


async def test_deactivated_user_session_invalidated(pg_pool, monkeypatch):
    admin_code = generate_invite_code()
    victim_code = generate_invite_code()
    await _mint(pg_pool, admin_code)
    await _mint(pg_pool, victim_code)
    with _auth_env(monkeypatch, admin_emails="boss@x.com"):
        app_transport = None
        async with _client(pg_pool, monkeypatch) as admin_client:
            await admin_client.post(
                "/api/auth/register",
                json={"email": "boss@x.com", "password": "averylongpassword", "invite_code": admin_code},
            )
            # 受害者用独立 client（独立 cookie）
            from app.main import create_app

            victim_transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=victim_transport, base_url="http://test") as victim:
                reg = await victim.post(
                    "/api/auth/register",
                    json={"email": "victim@x.com", "password": "averylongpassword", "invite_code": victim_code},
                )
                assert reg.status_code == 200
                user_id = reg.json()["user"]["id"]
                assert (await victim.get("/api/auth/me")).json()["user"]["authenticated"] is True
                # 管理员停用
                deact = await admin_client.post(f"/api/admin/users/{user_id}/deactivate")
                assert deact.status_code == 200
                # 停用后会话失效
                me = await victim.get("/api/auth/me")
    assert me.json()["user"]["authenticated"] is False
