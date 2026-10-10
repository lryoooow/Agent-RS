"""P2-10 回归：auth_login 的 rehash + create_session + prune 必须在同一事务内。

修复前三条写各自 autocommit，create_session 中途失败会残留已落库的 rehash（与 register
的事务语义不一致）。这里用 fake pool/conn 验证：成功时三写落在同一事务并提交；
create_session 失败时事务回滚（rehash 不残留）。
"""
from __future__ import annotations

import asyncio
import pytest
from starlette.responses import Response

import app.api.routes.auth as auth_route
from app.api.routes.auth import AuthCredentials, _validate_password, auth_login
from app.core.settings import Settings


def _ret(value):
    async def _f(*_, **__):
        return value
    return _f


@pytest.mark.parametrize(
    "password",
    ["password123", "Password-123", "1111111111", "qwerty12345"],
)
def test_registration_rejects_common_or_trivially_repeated_passwords(password: str) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        _validate_password(password, Settings(_env_file=None), email="alice@example.com")
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "PASSWORD_TOO_COMMON"


def test_registration_accepts_long_passphrase_without_forcing_character_classes() -> None:
    _validate_password(
        "correct horse battery staple",
        Settings(_env_file=None),
        email="alice@example.com",
    )


class _FakeTxn:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        self.conn.depth += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.conn.depth -= 1
        if exc is None:
            self.conn.committed = True
        else:
            self.conn.rolled_back = True
        return False  # 不吞异常，交回上层


class _FakeConn:
    def __init__(self) -> None:
        self.depth = 0
        self.committed = False
        self.rolled_back = False
        self.held = 0

    def transaction(self):
        return _FakeTxn(self)


class _FakeAcquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        self.conn.held += 1
        return self.conn

    async def __aexit__(self, *exc):
        self.conn.held -= 1
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


def _wire_login_doubles(monkeypatch, *, conn, create_session, needs_rehash_=True) -> None:
    """把 login 路由依赖的 DB/密码函数替换为 fake，复用同一 fake 连接。"""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-not-default-value-32")
    from app.core.settings import get_settings
    get_settings.cache_clear()

    pool = _FakePool(conn)
    monkeypatch.setattr(auth_route, "fetch_optional_pool", _ret(pool))
    monkeypatch.setattr(
        auth_route, "find_user_by_email",
        _ret({"id": "u1", "email": "a@b.com", "password_hash": "pbkdf2_sha256$1$x==",
              "is_active": True, "name": "A"}),
    )
    monkeypatch.setattr(auth_route, "verify_password", _ret(True))
    monkeypatch.setattr(auth_route, "lock_user_for_login", _ret({"id": "u1", "email": "a@b.com", "password_hash": "pbkdf2_sha256$1$x==", "is_active": True, "name": "A"}))
    monkeypatch.setattr(auth_route, "needs_rehash", lambda _h: needs_rehash_)
    monkeypatch.setattr(auth_route, "hash_password", _ret("NEWHASH"))
    monkeypatch.setattr(auth_route, "update_user_password_hash", _ret(None))
    monkeypatch.setattr(auth_route, "create_session", create_session)
    monkeypatch.setattr(auth_route, "prune_expired_sessions", _ret(None))
    monkeypatch.setattr(auth_route, "limit_user_sessions", _ret(0))


@pytest.mark.asyncio
async def test_login_commits_rehash_session_prune_in_one_transaction(monkeypatch) -> None:
    # 成功路径：三条写落在同一事务、提交。
    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None))
    await auth_login(
        AuthCredentials(email="a@b.com", password="validpass1"),
        Response(),
        client_key="test-client-success",
    )
    assert conn.depth == 0        # 事务正常退出
    assert conn.committed is True
    assert conn.rolled_back is False


@pytest.mark.asyncio
async def test_login_rolls_back_when_create_session_fails(monkeypatch) -> None:
    # P2-10 核心断言：create_session 失败 → 事务回滚（rehash 不残留半套）。
    conn = _FakeConn()

    async def _fail(*_, **__):
        raise RuntimeError("simulated DB error during create_session")

    _wire_login_doubles(monkeypatch, conn=conn, create_session=_fail)
    with pytest.raises(RuntimeError, match="create_session"):
        await auth_login(
            AuthCredentials(email="a@b.com", password="validpass1"),
            Response(),
            client_key="test-client-rollback",
        )
    assert conn.rolled_back is True
    assert conn.committed is False


@pytest.mark.asyncio
async def test_login_lockout_returns_retry_after_before_repeating_password_work(monkeypatch) -> None:
    from fastapi import HTTPException
    from app.auth.rate_limit import reset_auth_rate_limiters
    from app.core.settings import get_settings

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-not-default-value-32")
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES", "1")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_SECONDS", "30")
    get_settings.cache_clear()
    reset_auth_rate_limiters()

    conn = _FakeConn()
    monkeypatch.setattr(auth_route, "fetch_optional_pool", _ret(_FakePool(conn)))
    monkeypatch.setattr(auth_route, "find_user_by_email", _ret(None))
    password_checks: list[str] = []

    async def verify(password, _password_hash):
        password_checks.append(password)
        return False

    monkeypatch.setattr(auth_route, "verify_password", verify)
    credentials = AuthCredentials(email="missing@example.com", password="invalid-password")

    with pytest.raises(HTTPException) as first:
        await auth_login(credentials, Response(), client_key="lockout-test-ip")
    assert first.value.status_code == 401
    assert len(password_checks) == 1

    with pytest.raises(HTTPException) as blocked:
        await auth_login(credentials, Response(), client_key="lockout-test-ip")
    assert blocked.value.status_code == 429
    assert blocked.value.headers == {"Retry-After": "30"}
    assert len(password_checks) == 1


@pytest.mark.asyncio
async def test_password_verification_and_rehash_hold_no_database_connection(monkeypatch):
    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None))

    async def verify(*args):
        assert conn.held == 0 and conn.depth == 0
        return True

    async def hash_(*args):
        assert conn.held == 0 and conn.depth == 0
        return "new-hash"

    monkeypatch.setattr(auth_route, "verify_password", verify)
    monkeypatch.setattr(auth_route, "hash_password", hash_)
    await auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response(), client_key="hash-outside-connection")
    assert conn.held == conn.depth == 0


@pytest.mark.asyncio
async def test_login_with_single_connection_allows_health_query_during_password_work(monkeypatch):
    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None), needs_rehash_=False)
    entered, release = asyncio.Event(), asyncio.Event()
    semaphore = asyncio.Semaphore(1)

    class Acquire(_FakeAcquire):
        async def __aenter__(self):
            await semaphore.acquire()
            return await super().__aenter__()

        async def __aexit__(self, *args):
            await super().__aexit__(*args)
            semaphore.release()

    class Pool:
        def acquire(self):
            return Acquire(conn)

    async def verify(*args):
        entered.set()
        await release.wait()
        return True

    pool = Pool()
    monkeypatch.setattr(auth_route, "fetch_optional_pool", _ret(pool))
    monkeypatch.setattr(auth_route, "verify_password", verify)
    task = asyncio.create_task(auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response(), client_key="single-pool-login"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        async def health():
            async with pool.acquire():
                return "ok"
        assert await asyncio.wait_for(health(), 1) == "ok"
        release.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["disabled", "password"])
async def test_user_changed_during_verification_cannot_get_stale_session(monkeypatch, changed):
    from fastapi import HTTPException
    from unittest.mock import AsyncMock

    conn = _FakeConn()
    session = AsyncMock()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=session, needs_rehash_=False)
    if changed == "disabled":
        monkeypatch.setattr(auth_route, "lock_user_for_login", _ret(None))
    else:
        monkeypatch.setattr(auth_route, "lock_user_for_login", _ret({"id": "u1", "email": "a@b.com", "password_hash": "changed-hash", "is_active": True, "name": "A"}))
        monkeypatch.setattr(auth_route, "verify_password", AsyncMock(side_effect=[True, False]))
    with pytest.raises(HTTPException) as error:
        await auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response(), client_key=f"changed-{changed}")
    assert error.value.status_code == 401
    session.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_transparent_rehash_can_revalidate_same_password(monkeypatch):
    from unittest.mock import AsyncMock

    conn = _FakeConn()
    session = AsyncMock()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=session, needs_rehash_=False)
    current = {"id": "u1", "email": "a@b.com", "password_hash": "new-parallel-hash", "is_active": True, "name": "A"}
    monkeypatch.setattr(auth_route, "lock_user_for_login", AsyncMock(return_value=current))
    verify = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_route, "verify_password", verify)
    await auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response(), client_key="parallel-rehash")
    assert verify.await_count == 2
    session.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_registration_hash_is_outside_connection_and_unique_race_is_conflict(monkeypatch, duplicate):
    from asyncpg import UniqueViolationError
    from fastapi import HTTPException
    from unittest.mock import AsyncMock

    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None))
    monkeypatch.setattr(auth_route, "ensure_default_identity", _ret(None))
    monkeypatch.setattr(auth_route, "find_user_by_email", _ret(None))
    monkeypatch.setattr(auth_route, "ensure_workspace_membership", _ret(None))

    async def hash_(*args):
        assert conn.held == conn.depth == 0
        return "new-register-hash"

    user = {"id": "u1", "email": "new@example.com", "name": "New", "is_active": True}
    create = AsyncMock(return_value=user)
    if duplicate:
        error = UniqueViolationError("synthetic duplicate")
        error.constraint_name = "idx_users_email_unique"
        create.side_effect = error
    monkeypatch.setattr(auth_route, "hash_password", hash_)
    monkeypatch.setattr(auth_route, "create_user", create)
    payload = auth_route.RegisterRequest(email="new@example.com", password="correct horse battery staple", name="New")
    if duplicate:
        with pytest.raises(HTTPException) as caught:
            await auth_route.auth_register(payload, Response(), client_key="unique-race")
        assert caught.value.status_code == 409
        assert conn.rolled_back
    else:
        await auth_route.auth_register(payload, Response(), client_key="hash-free-registration")
        assert conn.committed


@pytest.mark.parametrize("identifier", ["admin", " ADMIN ", "admin@local.agent-rs"])
@pytest.mark.asyncio
async def test_reserved_admin_login_uses_same_form_and_server_id(monkeypatch, identifier):
    from app.core.settings import get_settings
    from unittest.mock import AsyncMock
    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None), needs_rehash_=False)
    monkeypatch.setenv("AUTH_ADMIN_USER_IDS", "u1")
    get_settings.cache_clear()
    lookup = AsyncMock(return_value={"id":"u1", "email":auth_route.ADMIN_LOGIN_EMAIL, "password_hash":"hash", "is_active":True})
    monkeypatch.setattr(auth_route, "find_user_by_email", lookup)
    monkeypatch.setattr(auth_route, "lock_user_for_login", _ret(lookup.return_value))
    result = await auth_login(AuthCredentials(email=identifier, password="test-admin-password！"), Response(), client_key="reserved-"+identifier)
    assert result.user.id == "u1"
    lookup.assert_awaited_once_with(conn, email=auth_route.ADMIN_LOGIN_EMAIL)


@pytest.mark.asyncio
async def test_reserved_login_does_not_grant_unconfigured_user_privilege(monkeypatch):
    from fastapi import HTTPException
    from app.core.settings import get_settings
    from unittest.mock import AsyncMock
    conn = _FakeConn()
    created = AsyncMock()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=created, needs_rehash_=False)
    monkeypatch.setenv("AUTH_ADMIN_USER_IDS", "other")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as caught:
        await auth_login(AuthCredentials(email="admin", password="test-admin-password！"), Response(), client_key="no-admin-id")
    assert caught.value.status_code == 401
    created.assert_not_awaited()


def test_reserved_administrator_cannot_be_registered_publicly():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        auth_route._normalize_registration_email(" ADMIN@LOCAL.AGENT-RS ")
    assert caught.value.detail["code"] == "RESERVED_ACCOUNT"
    with pytest.raises(HTTPException):
        auth_route._normalize_registration_email("admin")
    assert auth_route._normalize_registration_email("alice@example.com") == "alice@example.com"


@pytest.mark.asyncio
async def test_fullwidth_password_character_is_not_normalized():
    from app.auth.security import hash_password, verify_password
    encoded = await hash_password("test-passphrase！")
    assert await verify_password("test-passphrase！", encoded)
    assert not await verify_password("test-passphrase!", encoded)
    assert not await verify_password("test-passphrase", encoded)
