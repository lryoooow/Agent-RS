from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.db.sqlite_pool import create_sqlite_pool


@pytest.fixture
async def pool(tmp_path):
    return await create_sqlite_pool(str(tmp_path / "it.db"))


@pytest.fixture
def settings():
    return Settings(_env_file=None, storage_backend="sqlite")


# ---- import the _sqlite repos directly (facade picks backend at import time) ----
from app.db.repositories._sqlite import auth as auth_repo
from app.db.repositories._sqlite import conversation as conv_repo
from app.db.repositories._sqlite import document as doc_repo
from app.db.repositories._sqlite import document_job as job_repo
from app.db.repositories._sqlite import identity as identity_repo
from app.db.repositories._sqlite import memory as mem_repo
from app.db.repositories._sqlite import message as msg_repo
from app.db.repositories._sqlite import vector_search as vs_repo


# ============ login + history group ============

async def test_auth_register_login_session_flow(pool):
    async with pool.acquire() as conn:
        user = await auth_repo.create_user(conn, email="A@B.com", password_hash="ph", name="Al")
        assert user["email"] == "a@b.com"  # lower() applied

        # email lookup case-insensitive
        found = await auth_repo.find_user_by_email(conn, email="a@b.COM")
        assert found and found["id"] == user["id"]

        sess = await auth_repo.create_session(conn, user_id=user["id"], token_hash="tok", days=14)
        assert sess["user_id"] == user["id"]

        # active session resolves; last_seen updated
        resolved = await auth_repo.find_user_by_session(conn, token_hash="tok")
        assert resolved and resolved["id"] == user["id"]

        # delete works
        assert await auth_repo.delete_session(conn, token_hash="tok") is True
        assert await auth_repo.find_user_by_session(conn, token_hash="tok") is None


async def test_expired_session_not_resolved(pool):
    async with pool.acquire() as conn:
        user = await auth_repo.create_user(conn, email="exp@b.c", password_hash="ph", name="E")
        # negative days => already expired
        await auth_repo.create_session(conn, user_id=user["id"], token_hash="old", days=-1)
        assert await auth_repo.find_user_by_session(conn, token_hash="old") is None
        pruned = await auth_repo.prune_expired_sessions(conn)
        assert pruned >= 1


async def test_identity_seed_idempotent(pool, settings):
    async with pool.acquire() as conn:
        uid, wid = await identity_repo.ensure_default_identity(conn, settings)
        assert uid == settings.default_user_id
        # second call must not raise (ON CONFLICT) nor duplicate
        uid2, wid2 = await identity_repo.ensure_default_identity(conn, settings)
        assert (uid2, wid2) == (uid, wid)
        n = await conn.fetchval("SELECT count(*) FROM users WHERE id = ?", uid)
        assert n == 1


async def test_conversation_message_history(pool, settings):
    async with pool.acquire() as conn:
        await identity_repo.ensure_default_identity(conn, settings)
        uid = settings.default_user_id
        cid = await conv_repo.create_conversation(conn, user_id=uid, settings=settings, title="T")

        await msg_repo.append_message(conn, conversation_id=cid, role="user", content="hello")
        await msg_repo.append_message(conn, conversation_id=cid, role="assistant", content="hi there")

        recent = await msg_repo.list_recent_messages(conn, conversation_id=cid, limit=10)
        assert [m.role for m in recent] == ["user", "assistant"]

        convs = await conv_repo.list_conversations(conn, user_id=uid)
        assert convs[0]["message_count"] == 2

        assert await conv_repo.update_conversation_title(conn, conversation_id=cid, user_id=uid, title="New") is True
        assert await conv_repo.delete_conversation(conn, conversation_id=cid, user_id=uid) is True


async def test_update_message_complete_json_patch(pool, settings):
    async with pool.acquire() as conn:
        await identity_repo.ensure_default_identity(conn, settings)
        cid = await conv_repo.create_conversation(conn, user_id=settings.default_user_id, settings=settings)
        mid = await msg_repo.append_message(
            conn, conversation_id=cid, role="assistant", content="", metadata={"a": 1}
        )
        await msg_repo.update_message_complete(
            conn, message_id=mid, content="done", metadata={"b": 2}, tokens_in=5, tokens_out=7
        )
        rows = await msg_repo.list_conversation_messages(conn, conversation_id=cid)
        msg = rows[0]
        assert msg["content"] == "done"
        assert msg["metadata_json"] == {"a": 1, "b": 2}  # json_patch merged
        assert msg["tokens_in"] == 5 and msg["tokens_out"] == 7


# ============ document + RAG group ============

async def test_document_crud_and_chunks(pool):
    async with pool.acquire() as conn:
        did = await doc_repo.insert_document(
            conn, title="Doc", content="full text", doc_type="text",
            metadata={"k": "v"}, user_id="u1",
        )
        await doc_repo.insert_chunks(
            conn, document_id=did,
            chunks=[(0, "chunk zero", [0.1, 0.2, 0.3], None, {"i": 0}),
                    (1, "chunk one", [0.4, 0.5, 0.6], None, {"i": 1})],
        )
        docs = await doc_repo.list_documents(conn, user_id="u1")
        assert docs[0]["chunk_count"] == 2

        detail = await doc_repo.get_document(conn, document_id=did, user_id="u1")
        assert detail["content"] == "full text"

        # wrong owner -> None
        assert await doc_repo.get_document(conn, document_id=did, user_id="other") is None

        chunks = await doc_repo.list_document_chunks(conn, document_id=did, user_id="u1")
        assert [c["chunk_index"] for c in chunks] == [0, 1]

        assert await doc_repo.delete_document(conn, document_id=did, user_id="u1") is True
        # cascade: chunks gone
        assert await conn.fetchval("SELECT count(*) FROM document_chunks WHERE document_id = ?", did) == 0


async def test_vector_search_cosine_ordering(pool):
    async with pool.acquire() as conn:
        did = await doc_repo.insert_document(conn, title="D", content="c", user_id="u1")
        # near = aligned with query [1,0,0]; far = orthogonal
        await doc_repo.insert_chunks(conn, document_id=did, chunks=[
            (0, "near vector", [1.0, 0.0, 0.0], None, {}),
            (1, "far vector", [0.0, 1.0, 0.0], None, {}),
        ])
        results = await vs_repo.search_vector_only(conn, embedding=[1.0, 0.0, 0.0], limit=5, user_id="u1")
        assert results[0]["content"] == "near vector"
        assert results[0]["vector_score"] > results[1]["vector_score"]
        assert "embedding" in results[0]  # MMR needs it


async def test_fts_and_hybrid_search(pool):
    async with pool.acquire() as conn:
        did = await doc_repo.insert_document(conn, title="D", content="c", user_id="u1")
        await doc_repo.insert_chunks(conn, document_id=did, chunks=[
            (0, "the quick brown fox jumps", [1.0, 0.0, 0.0], None, {}),
            (1, "lazy dog sleeps", [0.0, 1.0, 0.0], None, {}),
        ])
        # FTS path (>=3 chars)
        tsv = await vs_repo.search_tsv_only(conn, query="quick", limit=5, user_id="u1")
        assert any("quick" in r["content"] for r in tsv)

        # hybrid returns fused rows with id/content
        hybrid = await vs_repo.search_hybrid_rrf(
            conn, embedding=[1.0, 0.0, 0.0], query="quick fox", limit=5, user_id="u1"
        )
        assert hybrid and "id" in hybrid[0] and "content" in hybrid[0]


async def test_tsv_short_query_like_fallback(pool):
    async with pool.acquire() as conn:
        did = await doc_repo.insert_document(conn, title="D", content="c", user_id="u1")
        await doc_repo.insert_chunks(conn, document_id=did, chunks=[
            (0, "AI 遥感", [1.0, 0.0, 0.0], None, {}),
        ])
        # 2-char query: below trigram threshold -> LIKE fallback
        rows = await vs_repo.search_tsv_only(conn, query="遥感", limit=5, user_id="u1")
        assert any("遥感" in r["content"] for r in rows)


async def test_document_ingest_job_lifecycle(pool):
    async with pool.acquire() as conn:
        jid = await job_repo.create_ingest_job(
            conn, filename="f.pdf", file_size=100, temp_path="/tmp/x",
            metadata={"title": "t"}, user_id="u1",
        )
        await job_repo.update_ingest_job(
            conn, job_id=jid, status="chunking", progress=35, stage_timings={"parsing_ms": 10}
        )
        await job_repo.update_ingest_job(
            conn, job_id=jid, status="complete", progress=100, stage_timings={"inserting_ms": 5}
        )
        job = await job_repo.get_ingest_job(conn, job_id=jid, user_id="u1")
        assert job["status"] == "complete" and job["progress"] == 100
        # wrong owner
        assert await job_repo.get_ingest_job(conn, job_id=jid, user_id="other") is None


# ============ memory group ============

async def test_memory_insert_and_cosine_recall(pool):
    async with pool.acquire() as conn:
        await mem_repo.insert_memory(conn, user_id="u1", content="likes coffee", embedding=[1.0, 0.0, 0.0])
        await mem_repo.insert_memory(conn, user_id="u1", content="lives in NY", embedding=[0.0, 1.0, 0.0])
        relevant = await mem_repo.list_relevant_memories(conn, user_id="u1", embedding=[1.0, 0.0, 0.0], limit=5)
        assert relevant[0]["content"] == "likes coffee"
        assert relevant[0]["score"] > relevant[1]["score"]

        listed = await mem_repo.list_memories(conn, user_id="u1")
        assert len(listed) == 2 and isinstance(listed[0]["metadata"], dict)

        assert await mem_repo.delete_memory(conn, user_id="u1", memory_id=relevant[0]["id"]) is True


async def test_empty_db_searches_return_empty(pool):
    async with pool.acquire() as conn:
        assert await vs_repo.search_vector_only(conn, embedding=[1.0, 0.0], limit=5, user_id="u1") == []
        assert await vs_repo.search_tsv_only(conn, query="anything", limit=5, user_id="u1") == []
        assert await mem_repo.list_relevant_memories(conn, user_id="u1", embedding=[1.0, 0.0], limit=5) == []
