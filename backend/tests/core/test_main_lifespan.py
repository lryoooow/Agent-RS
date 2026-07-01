from types import SimpleNamespace

import pytest

import app.main as main_module


class FakeConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commands: list[str] = []

    async def execute(self, command: str) -> None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *_args) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


@pytest.mark.asyncio
async def test_verify_database_connection_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(database_enabled=False),
    )

    async def fail_fetch():
        raise AssertionError("数据库关闭时不应读取连接池")

    monkeypatch.setattr(main_module, "fetch_optional_pool", fail_fetch)

    await main_module._verify_database_connection()


@pytest.mark.asyncio
async def test_verify_database_connection_rejects_missing_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(database_enabled=True),
    )

    async def fetch_none():
        return None

    monkeypatch.setattr(main_module, "fetch_optional_pool", fetch_none)

    with pytest.raises(RuntimeError, match="连接池未就绪"):
        await main_module._verify_database_connection()


@pytest.mark.asyncio
async def test_verify_database_connection_executes_select_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(database_enabled=True),
    )

    async def fetch_pool():
        return FakePool(connection)

    monkeypatch.setattr(main_module, "fetch_optional_pool", fetch_pool)

    await main_module._verify_database_connection()

    assert connection.commands == ["SELECT 1"]


@pytest.mark.asyncio
async def test_verify_database_connection_propagates_ping_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(ConnectionError("connection lost"))
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(database_enabled=True),
    )

    async def fetch_pool():
        return FakePool(connection)

    monkeypatch.setattr(main_module, "fetch_optional_pool", fetch_pool)

    with pytest.raises(ConnectionError, match="connection lost"):
        await main_module._verify_database_connection()
