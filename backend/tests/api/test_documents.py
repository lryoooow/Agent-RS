from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.api.routes.documents import split_text
from app.main import create_app
from app.core.settings import get_settings


def make_client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


class FakeAcquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return None


class FakePool:
    def acquire(self):
        return FakeAcquire()


async def fake_fetch_optional_pool():
    return FakePool()


async def fake_create_ingest_job(*_, **__):
    return "00000000-0000-4000-8000-000000000999"


def fake_schedule_task(coro):
    coro.close()


def test_documents_route_reports_database_disabled(monkeypatch) -> None:
    # DATABASE_DISABLED now requires the postgres backend explicitly disabled;
    # the default (sqlite) backend keeps documents enabled locally.
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    client = make_client()

    response = client.post(
        "/api/documents",
        json={"title": "Doc", "content": "content"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_DISABLED"


def test_documents_list_reports_database_disabled(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    client = make_client()

    response = client.get("/api/documents")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_DISABLED"


async def _empty_list_documents(*_, **__):
    return []


@pytest.mark.skip(reason="SQLite 后端已于 2026-06-18 退役，统一使用 PostgreSQL")
def test_documents_enabled_on_sqlite_backend(monkeypatch) -> None:
    # The feature's core promise: with no cloud Postgres, the default sqlite
    # backend keeps the knowledge base usable (no DATABASE_DISABLED).
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.list_documents", _empty_list_documents)
    client = make_client()

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_documents_list_returns_documents(monkeypatch) -> None:
    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_fetch_optional_pool():
        return FakePool()

    async def fake_list_documents(_, *, user_id: str, limit: int = 100):
        assert user_id == get_settings().default_user_id
        assert limit == 100
        return [
            {
                "id": "00000000-0000-4000-8000-000000000901",
                "title": "Doc",
                "source_url": None,
                "doc_type": "text",
                "metadata": {"source": "test"},
                "chunk_count": 2,
                "created_at": FakeDate(),
                "updated_at": FakeDate(),
            }
        ]

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.list_documents", fake_list_documents)
    client = make_client()

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json()["documents"][0]["title"] == "Doc"
    assert response.json()["documents"][0]["chunk_count"] == 2


def test_documents_delete_returns_not_found(monkeypatch) -> None:
    class FakeTransaction:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *_):
            return None

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_fetch_optional_pool():
        return FakePool()

    async def fake_delete_document(*_, **__):
        return False

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.delete_document", fake_delete_document)
    client = make_client()

    response = client.delete("/api/documents/00000000-0000-4000-8000-000000000902")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"


def test_documents_upload_accepts_text_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("STORAGE_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.create_ingest_job", fake_create_ingest_job)
    monkeypatch.setattr("app.api.routes.documents.schedule_task", fake_schedule_task)
    client = make_client()

    response = client.post(
        "/api/documents/upload",
        data={"title": "upload-title"},
        files={"file": ("sample.txt", b"hello upload", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "00000000-0000-4000-8000-000000000999",
        "status": "pending",
    }


def test_documents_upload_accepts_docx_file(monkeypatch, tmp_path) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph("docx upload body")
    buffer = BytesIO()
    document.save(buffer)

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("STORAGE_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.create_ingest_job", fake_create_ingest_job)
    monkeypatch.setattr("app.api.routes.documents.schedule_task", fake_schedule_task)
    client = make_client()

    response = client.post(
        "/api/documents/upload",
        data={"title": "docx-title"},
        files={
            "file": (
                "sample.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "00000000-0000-4000-8000-000000000999"


def test_documents_upload_accepts_text_pdf_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("STORAGE_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.api.routes.documents.create_ingest_job", fake_create_ingest_job)
    monkeypatch.setattr("app.api.routes.documents.schedule_task", fake_schedule_task)
    client = make_client()

    response = client.post(
        "/api/documents/upload",
        data={"title": "pdf-title"},
        files={"file": ("sample.pdf", b"%PDF fake", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "00000000-0000-4000-8000-000000000999"


def test_documents_upload_rejects_empty_text_file() -> None:
    client = make_client()

    response = client.post(
        "/api/documents/upload",
        files={"file": ("empty.txt", b" \n\t ", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "DOCUMENT_TEXT_EMPTY"


def test_documents_upload_rejects_unsupported_file() -> None:
    client = make_client()

    response = client.post(
        "/api/documents/upload",
        files={"file": ("bad.doc", b"nope", "application/msword")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNSUPPORTED_DOCUMENT_TYPE"


def test_documents_create_rejects_too_many_chunks(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_MAX_CHUNKS", "1")
    client = make_client()

    response = client.post(
        "/api/documents",
        json={"title": "Long Doc", "content": "a" * 1700},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "DOCUMENT_TOO_MANY_CHUNKS"


def test_split_text_uses_overlap() -> None:
    chunks = split_text("a" * 1000, chunk_size=400, overlap=50)

    assert len(chunks) == 3
    assert chunks[0] == "a" * 400
    assert chunks[1] == "a" * 400
    assert chunks[1].startswith(chunks[0][-50:])
    assert chunks[2].startswith(chunks[1][-50:])


# ---- 入库语义元信息：每块 section / token_count（新增）----


class _FakeEmbeddingService:
    """桩 embedding 服务：按输入块数返回等量的固定向量，绕过真实 API。"""

    available = True

    async def embed_batch(self, texts):
        return [[0.0] * 8 for _ in texts]


class _CaptureInsertConn:
    def transaction(self):
        return FakeTransaction()


class FakeTransaction:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return None


def _store_capture_env(monkeypatch):
    """装配同步入库链路的桩：固定 embedding + 捕获 insert_chunks 入参。"""
    captured: dict = {}

    class CaptureAcquire:
        async def __aenter__(self):
            return _CaptureInsertConn()

        async def __aexit__(self, *_):
            return None

    class CapturePool:
        def acquire(self):
            return CaptureAcquire()

    async def fake_pool():
        return CapturePool()

    async def fake_insert_document(*_, **__):
        return "00000000-0000-4000-8000-0000000009aa"

    async def fake_insert_chunks(_, *, document_id, chunks):
        captured["chunks"] = chunks

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setattr("app.api.routes.documents.fetch_optional_pool", fake_pool)
    monkeypatch.setattr("app.api.routes.documents.insert_document", fake_insert_document)
    monkeypatch.setattr("app.api.routes.documents.insert_chunks", fake_insert_chunks)
    monkeypatch.setattr(
        "app.api.routes.documents.get_embedding_service", lambda: _FakeEmbeddingService()
    )
    return captured


def test_create_document_persists_section_and_token_count(monkeypatch) -> None:
    # 锁定上限隔离本地 .env 覆盖（见记忆 settings-default-test）。
    monkeypatch.setenv("DOCUMENT_MAX_CHUNKS", "240")
    captured = _store_capture_env(monkeypatch)
    client = make_client()

    # 内容足够长（远超 chunk_size=800）以保证切成多块，验证"每块都带 section"。
    content = "# 第3章 数据来源\n\n" + "卫星影像通过开放中心下载并完成预处理。" * 120
    response = client.post("/api/documents", json={"title": "Doc", "content": content})

    assert response.status_code == 200
    chunks = captured["chunks"]
    assert len(chunks) > 1
    # 元组结构 (index, text, embedding, token_count, metadata)
    for index, text, _embedding, token_count, metadata in chunks:
        assert metadata["section"] == "第3章 数据来源"
        assert metadata["chunk_index"] == index
        assert token_count is not None and token_count > 0
        assert text.startswith("第3章 数据来源")


def test_create_document_allows_more_than_old_limit(monkeypatch) -> None:
    # max_chunks 50→240 放宽：旧上限 50 会 413 的规模，现在应正常入库。
    # 显式锁定上限为 240，隔离本地 .env 的 DOCUMENT_MAX_CHUNKS 覆盖（见记忆 settings-default-test）。
    # 每段约 600 字符无句末标点：既不被 _pack_atoms 合并、也不被句切，段≈块 → 60 块。
    monkeypatch.setenv("DOCUMENT_MAX_CHUNKS", "240")
    _store_capture_env(monkeypatch)
    client = make_client()

    content = "\n\n".join(f"第{i}段编号标识" + "内容字" * 200 for i in range(60))
    response = client.post("/api/documents", json={"title": "Many", "content": content})

    assert response.status_code == 200
    assert response.json()["chunk_count"] > 50


def test_create_document_still_rejects_beyond_new_limit(monkeypatch) -> None:
    # 超过配置上限仍拦截（保护未失效）。上限设 5，20 段 → 20 块 > 5。
    monkeypatch.setenv("DOCUMENT_MAX_CHUNKS", "5")
    _store_capture_env(monkeypatch)
    client = make_client()

    content = "\n\n".join(f"第{i}段编号标识" + "内容字" * 200 for i in range(20))
    response = client.post("/api/documents", json={"title": "TooMany", "content": content})

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "DOCUMENT_TOO_MANY_CHUNKS"


class FakeDate:
    def isoformat(self):
        return "2026-05-27T00:00:00+00:00"
