"""P2-10 回归：auth_login 的 rehash + create_session + prune 必须在同一事务内。

修复前三条写各自 autocommit，create_session 中途失败会残留已落库的 rehash（与 register
的事务语义不一致）。这里用 fake pool/conn 验证：成功时三写落在同一事务并提交；
create_session 失败时事务回滚（rehash 不残留）。
"""
from __future__ import annotations

import pytest
from starlette.responses import Response

import app.api.routes.auth as auth_route
from app.api.routes.auth import AuthCredentials, auth_login


def _ret(value):
    async def _f(*_, **__):
        return value
    return _f


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

    def transaction(self):
        return _FakeTxn(self)


class _FakeAcquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


def _wire_login_doubles(monkeypatch, *, conn, create_session, needs_rehash_=True) -> None:
    """把 login 路由依赖的 DB/密码函数替换为 fake，复用同一 fake 连接。"""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-not-default")
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
    monkeypatch.setattr(auth_route, "needs_rehash", lambda _h: needs_rehash_)
    monkeypatch.setattr(auth_route, "hash_password", _ret("NEWHASH"))
    monkeypatch.setattr(auth_route, "update_user_password_hash", _ret(None))
    monkeypatch.setattr(auth_route, "create_session", create_session)
    monkeypatch.setattr(auth_route, "prune_expired_sessions", _ret(None))


@pytest.mark.asyncio
async def test_login_commits_rehash_session_prune_in_one_transaction(monkeypatch) -> None:
    # 成功路径：三条写落在同一事务、提交。
    conn = _FakeConn()
    _wire_login_doubles(monkeypatch, conn=conn, create_session=_ret(None))
    await auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response())
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
        await auth_login(AuthCredentials(email="a@b.com", password="validpass1"), Response())
    assert conn.rolled_back is True
    assert conn.committed is False
