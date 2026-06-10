from __future__ import annotations

import contextlib

import pytest
from pydantic import ValidationError

from app.agent.tools.parse_document.runner import run_parse_document
from app.agent.tools.parse_document.schema import ParseDocumentArguments
from app.core.settings import get_settings

VALID_DOC_ID = "3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071"


# ---------- schema ----------

def test_parse_document_schema_accepts_uuid() -> None:
    args = ParseDocumentArguments(document_id=VALID_DOC_ID)
    assert args.document_id == VALID_DOC_ID
    assert args.max_chars == 0
    assert args.reason


def test_parse_document_schema_rejects_non_uuid() -> None:
    with pytest.raises(ValidationError):
        ParseDocumentArguments(document_id="94e758f38ede")  # 影像式 12-hex 不是 UUID


def test_parse_document_schema_rejects_negative_max_chars() -> None:
    with pytest.raises(ValidationError):
        ParseDocumentArguments(document_id=VALID_DOC_ID, max_chars=-1)


# ---------- 测试用的 pool stub ----------

class _FakeConn:
    def __init__(self, row) -> None:
        self._row = row
        self.called_with: dict | None = None

    async def fetchrow(self, *a, **k):  # 兼容 get_document 内部用法
        return self._row


class _FakePool:
    def __init__(self, row=None, *, raise_on_acquire: Exception | None = None) -> None:
        self._row = row
        self._raise = raise_on_acquire
        self.conn = _FakeConn(row)

    @contextlib.asynccontextmanager
    async def acquire(self):
        if self._raise is not None:
            raise self._raise
        yield self.conn


def _patch_db(monkeypatch, *, document_row, enabled=True, pool=...):
    monkeypatch.setenv("DATABASE_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()

    async def _fake_get_document(conn, *, document_id, user_id):
        return document_row

    actual_pool = _FakePool(document_row) if pool is ... else pool

    async def _fake_fetch_pool():
        return actual_pool

    monkeypatch.setattr("app.agent.tools.parse_document.runner.fetch_optional_pool", _fake_fetch_pool)
    monkeypatch.setattr("app.agent.tools.parse_document.runner.get_document", _fake_get_document)
    return actual_pool


# ---------- runner 边界/错误路径 ----------

@pytest.mark.asyncio
async def test_parse_document_runner_invalid_id() -> None:
    result = await run_parse_document(
        ParseDocumentArguments.model_construct(document_id="not-a-uuid", max_chars=0)
    )
    assert result.error == "invalid_document_id"


@pytest.mark.asyncio
async def test_parse_document_runner_database_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))
    assert result.error == "database_disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parse_document_runner_db_unavailable(monkeypatch) -> None:
    _patch_db(monkeypatch, document_row=None, pool=None)
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))
    assert result.error == "database_unavailable"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parse_document_runner_not_found(monkeypatch) -> None:
    _patch_db(monkeypatch, document_row=None)
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))
    assert result.error == "document_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parse_document_runner_empty_content(monkeypatch) -> None:
    _patch_db(
        monkeypatch,
        document_row={"id": VALID_DOC_ID, "title": "空文档", "content": "   ", "doc_type": "text", "metadata": {}},
    )
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))
    assert result.error == "document_empty"
    get_settings.cache_clear()


# ---------- runner 成功路径 ----------

@pytest.mark.asyncio
async def test_parse_document_runner_success_full(monkeypatch) -> None:
    _patch_db(
        monkeypatch,
        document_row={
            "id": VALID_DOC_ID,
            "title": "年度报告",
            "content": "第一段内容。\n第二段内容。",
            "doc_type": "pdf",
            "metadata": {"page_count": 12, "ocr_used": False},
        },
    )
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))

    assert result.error is None
    assert result.result_count == 1
    assert "年度报告" in result.tool_context
    assert "第一段内容" in result.tool_context
    assert result.metadata["execution_mode"] == "process"
    assert result.metadata["truncated"] is False
    assert result.metadata["full_length"] == len("第一段内容。\n第二段内容。")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parse_document_runner_truncates_long_content(monkeypatch) -> None:
    long_text = "字" * 500
    _patch_db(
        monkeypatch,
        document_row={
            "id": VALID_DOC_ID,
            "title": "长文档",
            "content": long_text,
            "doc_type": "text",
            "metadata": {},
        },
    )
    result = await run_parse_document(
        ParseDocumentArguments(document_id=VALID_DOC_ID, max_chars=100)
    )

    assert result.error is None
    assert result.metadata["truncated"] is True
    assert result.metadata["full_length"] == 500
    assert result.metadata["returned_chars"] == 100
    assert "已截断" in result.tool_context
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parse_document_runner_db_error(monkeypatch) -> None:
    _patch_db(monkeypatch, document_row=None, pool=_FakePool(raise_on_acquire=RuntimeError("boom")))
    result = await run_parse_document(ParseDocumentArguments(document_id=VALID_DOC_ID))
    assert result.error == "db_error"
    get_settings.cache_clear()
