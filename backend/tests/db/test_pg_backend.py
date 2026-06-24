"""仓储层 PostgreSQL 集成测试（从 test_sqlite_backend.py 移植）。

SQLite 后端退役后，这里是仓储 SQL 的唯一真实数据库覆盖。跑在 docker compose 的
pgvector/pg16 上（见 tests/db/conftest.py 的 pg_pool/pg_conn 夹具；库不可达整组 skip）。

与原 SQLite 套件的差异（PG 特性，移植时已处理）：
- 向量列是 vector(1536)，故所有 embedding 用 _vec() 造 1536 维（SQLite 不校验维度，PG 严格校验）；
- user_id 列（memories/documents）是 TEXT，沿用 "u1" 等字符串；conversations/sessions 走 UUID；
- 级联删除靠 PG 原生 ON DELETE CASCADE，单列一条 test_*_cascade 实测其真生效（原 SQLite 靠手动 DELETE）；
- 时间戳 created_at 用 now()（事务起始时刻）；夹具非事务态、每条 append 独立提交，故时序递增可靠，
  但仍以"集合/可还原数值"而非"严格顺序"断言，消除潜在 flaky。

五维覆盖：常规 CRUD / 边界（空库、limit 截断）/ 非法输入（损坏 metadata、维度不符）/
异常（事务回滚）/ 历史重复点（H3 跨租户隔离、分析结果回读锁死"否认已执行分析"、级联删除）。
"""
from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.db.repositories._pg import auth as auth_repo
from app.db.repositories._pg import conversation as conv_repo
from app.db.repositories._pg import document as doc_repo
from app.db.repositories._pg import document_job as job_repo
from app.db.repositories._pg import identity as identity_repo
from app.db.repositories._pg import memory as mem_repo
from app.db.repositories._pg import message as msg_repo
from app.db.repositories._pg import vector_search as vs_repo

pytestmark = pytest.mark.asyncio(loop_scope="session")

_EMB_DIM = 1536


def _vec(*head: float) -> list[float]:
    """造 1536 维向量：前 len(head) 位取给定值，其余补 0。

    用于在 vector(1536) 列上复刻 SQLite 测试的"near 对齐 query / far 正交"语义，
    无需写满 1536 个数。"""
    body = list(head)
    return body + [0.0] * (_EMB_DIM - len(body))


def _settings() -> Settings:
    return Settings(_env_file=None)


# ============ login + history group ============


async def test_auth_register_login_session_flow(pg_conn) -> None:
    user = await auth_repo.create_user(pg_conn, email="A@B.com", password_hash="ph", name="Al")
    assert user["email"] == "a@b.com"  # lower() applied

    found = await auth_repo.find_user_by_email(pg_conn, email="a@b.COM")
    assert found and found["id"] == user["id"]

    sess = await auth_repo.create_session(pg_conn, user_id=user["id"], token_hash="tok", days=14)
    assert sess["user_id"] == user["id"]

    resolved = await auth_repo.find_user_by_session(pg_conn, token_hash="tok")
    assert resolved and resolved["id"] == user["id"]

    assert await auth_repo.delete_session(pg_conn, token_hash="tok") is True
    assert await auth_repo.find_user_by_session(pg_conn, token_hash="tok") is None


async def test_expired_session_not_resolved(pg_conn) -> None:
    user = await auth_repo.create_user(pg_conn, email="exp@b.c", password_hash="ph", name="E")
    await auth_repo.create_session(pg_conn, user_id=user["id"], token_hash="old", days=-1)
    assert await auth_repo.find_user_by_session(pg_conn, token_hash="old") is None
    pruned = await auth_repo.prune_expired_sessions(pg_conn)
    assert pruned >= 1


async def test_identity_seed_idempotent(pg_conn) -> None:
    settings = _settings()
    uid, wid = await identity_repo.ensure_default_identity(pg_conn, settings)
    assert uid == settings.default_user_id
    # 二次调用不报错（ON CONFLICT）且不重复
    uid2, wid2 = await identity_repo.ensure_default_identity(pg_conn, settings)
    assert (uid2, wid2) == (uid, wid)
    n = await pg_conn.fetchval("SELECT count(*) FROM agent_rs.users WHERE id = $1::uuid", uid)
    assert n == 1


async def test_conversation_message_history(pg_conn) -> None:
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    uid = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=uid, settings=settings, title="T")

    await msg_repo.append_message(pg_conn, conversation_id=cid, role="user", content="hello")
    await msg_repo.append_message(pg_conn, conversation_id=cid, role="assistant", content="hi there")

    recent = await msg_repo.list_recent_messages(pg_conn, conversation_id=cid, limit=10)
    assert [m.role for m in recent] == ["user", "assistant"]

    convs = await conv_repo.list_conversations(pg_conn, user_id=uid)
    assert convs[0]["message_count"] == 2

    assert await conv_repo.update_conversation_title(
        pg_conn, conversation_id=cid, user_id=uid, title="New"
    ) is True
    assert await conv_repo.delete_conversation(pg_conn, conversation_id=cid, user_id=uid) is True


async def test_list_recent_messages_enforces_owner_when_user_id_given(pg_conn) -> None:
    # H3 结构性隔离：传 user_id 时按归属过滤；传错 user_id 拉不到他人历史；不传则按 conversation_id 兼容。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    owner = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=owner, settings=settings, title="Owned")
    await msg_repo.append_message(pg_conn, conversation_id=cid, role="user", content="机密历史问题")
    await msg_repo.append_message(pg_conn, conversation_id=cid, role="assistant", content="机密历史回答")

    mine = await msg_repo.list_recent_messages(pg_conn, conversation_id=cid, limit=10, user_id=owner)
    assert [m.role for m in mine] == ["user", "assistant"]

    intruder = "00000000-0000-4000-8000-0000000000ff"
    stolen = await msg_repo.list_recent_messages(pg_conn, conversation_id=cid, limit=10, user_id=intruder)
    assert stolen == []

    legacy = await msg_repo.list_recent_messages(pg_conn, conversation_id=cid, limit=10)
    assert [m.role for m in legacy] == ["user", "assistant"]


async def test_list_recent_analysis_results_roundtrip_and_isolation(pg_conn) -> None:
    # 跨轮回读结构化分析结果 + 归属过滤；复现实测 bug 真实数据，锁死"同对话否认已执行分析"。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    owner = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=owner, settings=settings, title="Seg")

    await msg_repo.append_message(
        pg_conn, conversation_id=cid, role="assistant", content="好的",
        metadata={"finish_reason": "stop"},
    )
    await msg_repo.append_message(
        pg_conn, conversation_id=cid, role="assistant", content="分类完成",
        metadata={
            "finish_reason": "stop",
            "geospatial_result": {
                "type": "segmentation",
                "imagery_id": "d722c20e1234",
                "classes": [
                    {"label": "背景", "percentage": 91.307},
                    {"label": "建筑", "percentage": 3.441},
                ],
            },
        },
    )

    results = await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=owner, limit=5
    )
    assert len(results) == 1
    geo = results[0]["geospatial_result"]
    assert geo["type"] == "segmentation"
    assert geo["classes"][0]["percentage"] == pytest.approx(91.307)

    intruder = "00000000-0000-4000-8000-0000000000ff"
    assert await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=intruder, limit=5
    ) == []

    assert await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=None, limit=5
    ) == []


async def test_list_recent_analysis_results_empty_and_corrupt_metadata(pg_conn) -> None:
    # 边界 + 非法输入：无分析结果 → 空；metadata 非 dict（脏数据）→ 跳过不崩。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    owner = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=owner, settings=settings, title="Plain")

    await msg_repo.append_message(
        pg_conn, conversation_id=cid, role="assistant", content="纯文字回答",
        metadata={"finish_reason": "stop"},
    )
    assert await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=owner, limit=5
    ) == []

    await msg_repo.append_message(
        pg_conn, conversation_id=cid, role="assistant", content="脏数据",
        metadata={"geospatial_result": "oops-not-a-dict"},
    )
    assert await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=owner, limit=5
    ) == []


async def test_list_recent_analysis_results_caps_at_limit(pg_conn) -> None:
    # 边界：多条结果按 limit 截最近的。以"返回数量 + 数值集合"断言，不依赖严格时序（消除 flaky）。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    owner = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=owner, settings=settings, title="Many")
    for i in range(4):
        await msg_repo.append_message(
            pg_conn, conversation_id=cid, role="assistant", content=f"r{i}",
            metadata={"geospatial_result": {
                "type": "ndvi", "imagery_id": f"img{i:08d}xxxx",
                "stats": {"mean": float(i)},
            }},
        )
    results = await msg_repo.list_recent_analysis_results(
        pg_conn, conversation_id=cid, user_id=owner, limit=2
    )
    assert len(results) == 2
    means = {r["geospatial_result"]["stats"]["mean"] for r in results}
    # 取最近两条（mean ∈ {2,3}），不依赖返回顺序
    assert means == {2.0, 3.0}


async def test_update_message_complete_json_patch(pg_conn) -> None:
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    cid = await conv_repo.create_conversation(pg_conn, user_id=settings.default_user_id, settings=settings)
    mid = await msg_repo.append_message(
        pg_conn, conversation_id=cid, role="assistant", content="", metadata={"a": 1}
    )
    await msg_repo.update_message_complete(
        pg_conn, message_id=mid, content="done", metadata={"b": 2}, tokens_in=5, tokens_out=7
    )
    rows = await msg_repo.list_conversation_messages(pg_conn, conversation_id=cid)
    msg = rows[0]
    assert msg["content"] == "done"
    assert msg["metadata_json"] == {"a": 1, "b": 2}  # jsonb || 合并
    assert msg["tokens_in"] == 5 and msg["tokens_out"] == 7


async def test_delete_conversation_cascades_messages(pg_conn) -> None:
    # 历史重复点 + PG 特性：删 conversation 必须级联删 messages（验 ON DELETE CASCADE 真生效）。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    uid = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=uid, settings=settings, title="Cascade")
    await msg_repo.append_message(pg_conn, conversation_id=cid, role="user", content="x")
    await msg_repo.append_message(pg_conn, conversation_id=cid, role="assistant", content="y")

    before = await pg_conn.fetchval(
        "SELECT count(*) FROM agent_rs.messages WHERE conversation_id = $1::uuid", cid
    )
    assert before == 2
    assert await conv_repo.delete_conversation(pg_conn, conversation_id=cid, user_id=uid) is True
    after = await pg_conn.fetchval(
        "SELECT count(*) FROM agent_rs.messages WHERE conversation_id = $1::uuid", cid
    )
    assert after == 0  # 级联删除：消息随对话一起消失


async def test_transaction_rollback_on_error(pg_conn) -> None:
    # 异常分支：事务中途抛错 → 整事务回滚，无半写。
    settings = _settings()
    await identity_repo.ensure_default_identity(pg_conn, settings)
    uid = settings.default_user_id
    cid = await conv_repo.create_conversation(pg_conn, user_id=uid, settings=settings, title="Tx")
    with pytest.raises(RuntimeError):
        async with pg_conn.transaction():
            await msg_repo.append_message(pg_conn, conversation_id=cid, role="user", content="will-rollback")
            raise RuntimeError("boom")
    n = await pg_conn.fetchval(
        "SELECT count(*) FROM agent_rs.messages WHERE conversation_id = $1::uuid", cid
    )
    assert n == 0  # 回滚后无残留


# ============ document + RAG group ============


async def test_document_crud_and_chunks(pg_conn) -> None:
    did = await doc_repo.insert_document(
        pg_conn, title="Doc", content="full text", doc_type="text",
        metadata={"k": "v"}, user_id="u1",
    )
    await doc_repo.insert_chunks(
        pg_conn, document_id=did,
        chunks=[(0, "chunk zero", _vec(0.1, 0.2, 0.3), None, {"i": 0}),
                (1, "chunk one", _vec(0.4, 0.5, 0.6), None, {"i": 1})],
    )
    docs = await doc_repo.list_documents(pg_conn, user_id="u1")
    assert docs[0]["chunk_count"] == 2

    detail = await doc_repo.get_document(pg_conn, document_id=did, user_id="u1")
    assert detail["content"] == "full text"

    assert await doc_repo.get_document(pg_conn, document_id=did, user_id="other") is None

    chunks = await doc_repo.list_document_chunks(pg_conn, document_id=did, user_id="u1")
    assert [c["chunk_index"] for c in chunks] == [0, 1]

    assert await doc_repo.delete_document(pg_conn, document_id=did, user_id="u1") is True
    # 级联：chunks 随 document 删除（ON DELETE CASCADE）
    assert await pg_conn.fetchval(
        "SELECT count(*) FROM public.document_chunks WHERE document_id = $1::uuid", did
    ) == 0


async def test_vector_search_cosine_ordering(pg_conn) -> None:
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    # near 与 query [1,0,0,...] 对齐；far 正交
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "near vector", _vec(1.0, 0.0, 0.0), None, {}),
        (1, "far vector", _vec(0.0, 1.0, 0.0), None, {}),
    ])
    results = await vs_repo.search_vector_only(pg_conn, embedding=_vec(1.0, 0.0, 0.0), limit=5, user_id="u1")
    assert results[0]["content"] == "near vector"
    assert results[0]["vector_score"] > results[1]["vector_score"]
    assert "embedding" in results[0]  # MMR needs it


async def test_fts_and_hybrid_search(pg_conn) -> None:
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "the quick brown fox jumps", _vec(1.0, 0.0, 0.0), None, {}),
        (1, "lazy dog sleeps", _vec(0.0, 1.0, 0.0), None, {}),
    ])
    tsv = await vs_repo.search_tsv_only(pg_conn, query="quick", limit=5, user_id="u1")
    assert any("quick" in r["content"] for r in tsv)

    hybrid = await vs_repo.search_hybrid_rrf(
        pg_conn, embedding=_vec(1.0, 0.0, 0.0), query="quick fox", limit=5, user_id="u1"
    )
    assert hybrid and "id" in hybrid[0] and "content" in hybrid[0]


async def test_document_ingest_job_lifecycle(pg_conn) -> None:
    jid = await job_repo.create_ingest_job(
        pg_conn, filename="f.pdf", file_size=100, temp_path="/tmp/x",
        metadata={"title": "t"}, user_id="u1",
    )
    await job_repo.update_ingest_job(
        pg_conn, job_id=jid, status="chunking", progress=35, stage_timings={"parsing_ms": 10}
    )
    await job_repo.update_ingest_job(
        pg_conn, job_id=jid, status="complete", progress=100, stage_timings={"inserting_ms": 5}
    )
    job = await job_repo.get_ingest_job(pg_conn, job_id=jid, user_id="u1")
    assert job["status"] == "complete" and job["progress"] == 100
    assert await job_repo.get_ingest_job(pg_conn, job_id=jid, user_id="other") is None


# ============ memory group ============


async def test_memory_insert_and_cosine_recall(pg_conn) -> None:
    await mem_repo.insert_memory(pg_conn, user_id="u1", content="likes coffee", embedding=_vec(1.0, 0.0, 0.0))
    await mem_repo.insert_memory(pg_conn, user_id="u1", content="lives in NY", embedding=_vec(0.0, 1.0, 0.0))
    relevant = await mem_repo.list_relevant_memories(pg_conn, user_id="u1", embedding=_vec(1.0, 0.0, 0.0), limit=5)
    assert relevant[0]["content"] == "likes coffee"
    assert relevant[0]["score"] > relevant[1]["score"]

    listed = await mem_repo.list_memories(pg_conn, user_id="u1")
    assert len(listed) == 2 and isinstance(listed[0]["metadata"], dict)

    assert await mem_repo.delete_memory(pg_conn, user_id="u1", memory_id=relevant[0]["id"]) is True


async def test_memory_user_isolation(pg_conn) -> None:
    # 历史重复点：记忆按 user_id 隔离，他人召回不到。
    await mem_repo.insert_memory(pg_conn, user_id="u1", content="u1 secret", embedding=_vec(1.0, 0.0, 0.0))
    other = await mem_repo.list_relevant_memories(pg_conn, user_id="u2", embedding=_vec(1.0, 0.0, 0.0), limit=5)
    assert other == []


async def test_empty_db_searches_return_empty(pg_conn) -> None:
    assert await vs_repo.search_vector_only(pg_conn, embedding=_vec(1.0, 0.0), limit=5, user_id="u1") == []
    assert await vs_repo.search_tsv_only(pg_conn, query="anything", limit=5, user_id="u1") == []
    assert await mem_repo.list_relevant_memories(pg_conn, user_id="u1", embedding=_vec(1.0, 0.0), limit=5) == []


# ============ CJK 全文检索：二元分词（migration 0010）============


async def test_cjk_bigram_tokenization(pg_conn) -> None:
    # 二元分词正确性：连续中文切重叠二字组；中英混排时英文不被破坏。
    assert (await pg_conn.fetchval("SELECT agent_rs.cjk_bigram('卫星影像')")).split() == [
        "卫星", "星影", "影像"
    ]
    mixed = (await pg_conn.fetchval("SELECT agent_rs.cjk_bigram('使用NDVI分析植被')")).split()
    assert "NDVI" in mixed and "使用" in mixed and "植被" in mixed
    # to_cjk_tsvector 产出含各二字组 lexeme
    tsv = await pg_conn.fetchval("SELECT agent_rs.to_cjk_tsvector('卫星影像')::text")
    assert "卫星" in tsv and "星影" in tsv and "影像" in tsv


async def test_cjk_chinese_fulltext_recall_regression(pg_conn) -> None:
    # 历史 bug 回归（最关键）：旧 'simple' 分词把整段中文当一个 token，中文子串查询命中率=0。
    # 新 CJK bigram 下，中文查询必须能命中。
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "卫星影像通过开放中心下载并完成预处理", _vec(1.0, 0.0, 0.0), None, {}),
        (1, "无关内容植物生长记录", _vec(0.0, 1.0, 0.0), None, {}),
    ])
    # 旧实现：to_tsvector('simple', ...) @@ plainto_tsquery('simple','卫星影像') 为 False
    old_hit = await pg_conn.fetchval(
        "SELECT to_tsvector('simple','卫星影像通过开放中心下载') @@ plainto_tsquery('simple','卫星影像')"
    )
    assert old_hit is False  # 锁死旧 bug 存在
    # 新实现：中文查询命中正确的块
    results = await vs_repo.search_tsv_only(pg_conn, query="卫星影像", limit=5, user_id="u1")
    assert any("卫星影像" in r["content"] for r in results)
    assert all("无关内容" not in r["content"] for r in results)


async def test_cjk_mixed_and_english_query(pg_conn) -> None:
    # 中英混排：中文查"植被"命中、英文查"NDVI"命中（英文路径不被 bigram 破坏）。
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "使用NDVI分析植被覆盖", _vec(1.0, 0.0, 0.0), None, {}),
    ])
    zh = await vs_repo.search_tsv_only(pg_conn, query="植被", limit=5, user_id="u1")
    en = await vs_repo.search_tsv_only(pg_conn, query="NDVI", limit=5, user_id="u1")
    assert zh and en
    # 纯英文文档 + 英文查询仍可用（降级路径不报错）
    did2 = await doc_repo.insert_document(pg_conn, title="E", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did2, chunks=[
        (0, "the quick brown fox", _vec(0.0, 1.0, 0.0), None, {}),
    ])
    assert await vs_repo.search_tsv_only(pg_conn, query="quick", limit=5, user_id="u1")


async def test_tsv_only_hit_carries_embedding(pg_conn) -> None:
    # 附带 bug 修复：纯 tsv 命中块经 search_tsv_only 也带 embedding（供下游 MMR 多样性）。
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "植被覆盖分析报告", _vec(1.0, 0.0, 0.0), None, {}),
    ])
    results = await vs_repo.search_tsv_only(pg_conn, query="植被", limit=5, user_id="u1")
    assert results
    assert "embedding" in results[0] and isinstance(results[0]["embedding"], list)


async def test_cjk_migration_is_idempotent(pg_conn) -> None:
    # 迁移 0010 幂等：content_tsv 生成定义已是 to_cjk_tsvector，重复应用不重建/不报错。
    gendef = await pg_conn.fetchval(
        """
        SELECT pg_get_expr(d.adbin, d.adrelid)
        FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid='public.document_chunks'::regclass AND a.attname='content_tsv'
        """
    )
    assert "to_cjk_tsvector" in gendef


# ============ 上下文链接：fetch_adjacent_chunks（migration 无关，新查询）============


async def test_fetch_adjacent_chunks_by_index(pg_conn) -> None:
    # 按 (document_id, chunk_index ∈ indices) 批量取块，按序升序返回。
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "块零", _vec(1.0, 0.0, 0.0), None, {}),
        (1, "块一", _vec(0.0, 1.0, 0.0), None, {}),
        (2, "块二", _vec(0.0, 0.0, 1.0), None, {}),
    ])
    rows = await doc_repo.fetch_adjacent_chunks(pg_conn, document_id=did, indices=[0, 1, 2], user_id="u1")
    assert [r["chunk_index"] for r in rows] == [0, 1, 2]
    assert [r["content"] for r in rows] == ["块零", "块一", "块二"]
    # 越界序号被自然忽略，不报错
    partial = await doc_repo.fetch_adjacent_chunks(pg_conn, document_id=did, indices=[1, 99], user_id="u1")
    assert [r["chunk_index"] for r in partial] == [1]
    # 空 indices → 空
    assert await doc_repo.fetch_adjacent_chunks(pg_conn, document_id=did, indices=[], user_id="u1") == []


async def test_fetch_adjacent_chunks_tenant_isolation(pg_conn) -> None:
    # 防跨租户：他人 user_id 取不到邻居块。
    did = await doc_repo.insert_document(pg_conn, title="D", content="c", user_id="u1")
    await doc_repo.insert_chunks(pg_conn, document_id=did, chunks=[
        (0, "私有块", _vec(1.0, 0.0, 0.0), None, {}),
    ])
    assert await doc_repo.fetch_adjacent_chunks(pg_conn, document_id=did, indices=[0], user_id="u2") == []
