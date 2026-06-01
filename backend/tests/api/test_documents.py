from io import BytesIO

from fastapi.testclient import TestClient

from app.api.routes.documents import split_text
from app.main import create_app
from app.shared.settings import get_settings


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
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    client = make_client()

    response = client.post(
        "/api/documents",
        json={"title": "Doc", "content": "content"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_DISABLED"


def test_documents_list_reports_database_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    client = make_client()

    response = client.get("/api/documents")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_DISABLED"


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

    async def fake_list_documents(_):
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


def test_documents_upload_accepts_text_file(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
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


def test_documents_upload_accepts_docx_file(monkeypatch) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph("docx upload body")
    buffer = BytesIO()
    document.save(buffer)

    monkeypatch.setenv("DATABASE_ENABLED", "true")
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


def test_documents_upload_accepts_text_pdf_file(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
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


class FakeDate:
    def isoformat(self):
        return "2026-05-27T00:00:00+00:00"
