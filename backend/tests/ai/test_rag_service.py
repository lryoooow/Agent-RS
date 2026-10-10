"""RAG service 上下文扩展（Context Expansion）单测。

_expand_context 是纯编排逻辑：给检索命中的锚点块补回同文档相邻块。用假 pool/conn 隔离
真实数据库（真实 SQL 由 tests/db/test_pg_backend.py::test_fetch_adjacent_chunks_* 覆盖），
专注校验分组/去重/跨文档隔离/边界/开关这些编排正确性。

五维覆盖：常规（相邻拼接）/ 边界（首末块、radius=0、空输入）/ 非法输入（缺 index/metadata）/
历史问题点（跨文档不串、重叠窗口去重）/ 降级（无 index 的块原样保留）。
"""
from __future__ import annotations

import pytest

from app.agent.rag import service


class _FakeConn:
    """模拟 fetch_adjacent_chunks 的 SQL：从内存 store 按 (doc_id, indices) 取块。"""

    def __init__(self, store: dict[str, dict[int, str]]):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def fetch(self, _sql, doc_id, _user_id, indices):
        rows = []
        for i in sorted(indices):
            if i in self.store.get(doc_id, {}):
                rows.append(
                    {
                        "id": f"{doc_id}-{i}",
                        "document_id": doc_id,
                        "chunk_index": i,
                        "content": self.store[doc_id][i],
                        "metadata": {},
                    }
                )
        return rows


class _FakePool:
    def __init__(self, store):
        self._conn = _FakeConn(store)

    def acquire(self):
        return self._conn


_STORE = {"doc-a": {0: "A0", 1: "A1", 2: "A2"}, "doc-b": {0: "B0", 1: "B1"}}


def _anchor(doc_id, idx, **extra):
    return {"document_id": doc_id, "chunk_index": idx, "content": _STORE[doc_id][idx],
            "metadata": {}, **extra}


# ---- _chunk_index_of / _dedupe_join 纯函数 ----


def test_chunk_index_of_prefers_top_level_then_metadata() -> None:
    assert service._chunk_index_of({"chunk_index": 3}) == 3
    assert service._chunk_index_of({"metadata": {"chunk_index": 5}}) == 5
    assert service._chunk_index_of({"metadata": '{"chunk_index": 7}'}) == 7  # jsonb→str
    assert service._chunk_index_of({"metadata": "not json"}) is None
    assert service._chunk_index_of({}) is None


def test_dedupe_join_skips_empty_and_duplicates() -> None:
    assert service._dedupe_join(["a", "b", "a", ""]) == "a\nb"
    assert service._dedupe_join([None, "  x  ", "x"]) == "x"
    assert service._dedupe_join([]) == ""


# ---- 空检索告警（阈值全滤空 → logger.warning 一次；正常检索不打） ----


class _FakeSearch:
    """返回固定候选（vector_score 直接驱动 semantic_similarity 的阈值判定）。"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __call__(self, _conn, *, embedding, query, limit, k, user_id):
        return self._chunks


class _FakeRerank:
    """rerank 直通（保序返回 top_n），隔离真实 API。"""

    async def rerank(self, *, query, items, top_n):
        return items[:top_n]


@pytest.mark.asyncio
async def test_empty_retrieval_all_filtered_logs_warning(monkeypatch, caplog) -> None:
    """历史问题（E4 实测 126/126）：候选全被阈值滤空曾完全静默。现在必须打一次
    warning，且只含查询哈希与候选数——不得把用户原文写进日志。"""
    from app.core.settings import get_settings

    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.55")
    get_settings.cache_clear()
    try:
        import hashlib
        import logging

        query = "user secret question about Arminius"
        candidates = [
            {"document_id": "d1", "chunk_index": 0, "content": "c" * 40, "vector_score": 0.10},
            {"document_id": "d1", "chunk_index": 1, "content": "c" * 30, "vector_score": 0.42},
        ]
        with caplog.at_level(logging.WARNING, logger="app.agent.rag.service"):
            result = await service.retrieve_rag_context(
                _FakePool(_STORE),
                query=query,
                embedding=[0.1, 0.2],
                user_id="u1",
                trace={},
                search_fn=_FakeSearch(candidates),
            )
        assert result.retrieved_chunks == 0
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, "阈值全滤空必须恰好打一条 warning"
        message = warnings[0].getMessage()
        expected_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        assert expected_hash in message, "warning 必须含查询哈希"
        assert "all 2 candidates" in message, "warning 必须含候选数（2 个候选全被滤掉）"
        assert query not in message, "不得把用户原文写进日志"
        assert result.trace["relevance_rejected"] == 2
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_no_candidates_no_warning(monkeypatch, caplog) -> None:
    """检索侧本身无候选（非阈值过滤）：不打告警（归因不同，避免噪声）。"""
    from app.core.settings import get_settings

    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.55")
    get_settings.cache_clear()
    try:
        import logging

        with caplog.at_level(logging.WARNING, logger="app.agent.rag.service"):
            result = await service.retrieve_rag_context(
                _FakePool(_STORE),
                query="anything",
                embedding=[0.1, 0.2],
                user_id="u1",
                trace={},
                search_fn=_FakeSearch([]),
            )
        assert result.retrieved_chunks == 0
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_normal_retrieval_no_warning(monkeypatch, caplog) -> None:
    """正常检索（有过阈值候选）：不打空检索告警，行为不变。"""
    from app.core.settings import get_settings

    # 关闭 MMR/扩展/知识图谱：隔离数据库与额外分支，只验证告警逻辑本身
    monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.55")
    monkeypatch.setenv("RAG_MMR_ENABLED", "false")
    monkeypatch.setenv("RAG_CONTEXT_EXPANSION_ENABLED", "false")
    monkeypatch.setattr(service, "get_rerank_service", lambda: _FakeRerank())
    get_settings.cache_clear()
    try:
        import logging

        candidates = [
            {"document_id": "d1", "chunk_index": 0, "content": "relevant text", "vector_score": 0.90},
        ]
        with caplog.at_level(logging.WARNING, logger="app.agent.rag.service"):
            result = await service.retrieve_rag_context(
                _FakePool(_STORE),
                query="normal question",
                embedding=[0.1, 0.2],
                user_id="u1",
                trace={},
                search_fn=_FakeSearch(candidates),
            )
        assert result.retrieved_chunks == 1
        assert result.context is not None and "relevant text" in result.context
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    finally:
        get_settings.cache_clear()


# ---- _expand_context 编排 ----


@pytest.mark.asyncio
async def test_expand_adjacent_concatenation() -> None:
    # 命中中间块 idx1 → 补回 0,1,2 按序拼接。
    out = await service._expand_context(
        _FakePool(_STORE), chunks=[_anchor("doc-a", 1, rerank_score=0.9)],
        user_id="u1", radius=1, trace={},
    )
    assert len(out) == 1
    assert out[0]["content"] == "A0\nA1\nA2"


@pytest.mark.asyncio
async def test_expand_groups_per_document_no_cross_bleed() -> None:
    # 跨文档：各自扩展，绝不串内容。
    out = await service._expand_context(
        _FakePool(_STORE),
        chunks=[_anchor("doc-a", 0), _anchor("doc-b", 1)],
        user_id="u1", radius=1, trace={},
    )
    assert len(out) == 2
    assert out[0]["content"] == "A0\nA1"  # 首块只补右侧
    assert out[1]["content"] == "B0\nB1"  # 末块只补左侧


@pytest.mark.asyncio
async def test_expand_merges_overlapping_anchors_and_dedupes() -> None:
    # 同文档两锚点(idx1,idx2)窗口重叠 → 合并为一个块去重，不重复正文。
    out = await service._expand_context(
        _FakePool(_STORE),
        chunks=[_anchor("doc-a", 1, rerank_score=0.9), _anchor("doc-a", 2, rerank_score=0.8)],
        user_id="u1", radius=1, trace={},
    )
    assert len(out) == 1  # 合并为一个扩展块
    assert out[0]["content"] == "A0\nA1\nA2"


@pytest.mark.asyncio
async def test_expand_boundary_first_and_last_chunk() -> None:
    # 边界：首块(idx0)只补右、末块只补左，不越界（缺失序号被 SQL 忽略）。
    out_first = await service._expand_context(
        _FakePool(_STORE), chunks=[_anchor("doc-a", 0)], user_id="u1", radius=1, trace={},
    )
    assert out_first[0]["content"] == "A0\nA1"
    out_last = await service._expand_context(
        _FakePool(_STORE), chunks=[_anchor("doc-a", 2)], user_id="u1", radius=1, trace={},
    )
    assert out_last[0]["content"] == "A1\nA2"


@pytest.mark.asyncio
async def test_expand_radius_zero_returns_unchanged() -> None:
    chunks = [_anchor("doc-a", 1)]
    out = await service._expand_context(
        _FakePool(_STORE), chunks=chunks, user_id="u1", radius=0, trace={},
    )
    assert out is chunks  # radius<=0 直接原样返回


@pytest.mark.asyncio
async def test_expand_chunk_without_index_is_preserved() -> None:
    # 降级：无 chunk_index、无 metadata 的块无法定位邻居 → 原样保留，不丢块。
    weird = {"document_id": "doc-a", "content": "orphan", "metadata": {}}
    out = await service._expand_context(
        _FakePool(_STORE), chunks=[weird], user_id="u1", radius=1, trace={},
    )
    assert len(out) == 1
    assert out[0]["content"] == "orphan"


@pytest.mark.asyncio
async def test_expand_radius_two_widens_window() -> None:
    # radius=2：命中 idx2 → 补 0,1,2（左侧 0 起，右侧到末）。
    out = await service._expand_context(
        _FakePool(_STORE), chunks=[_anchor("doc-a", 2)], user_id="u1", radius=2, trace={},
    )
    assert out[0]["content"] == "A0\nA1\nA2"


# ---- E7 §1.5 可观测性：merged_chunk_indices 只进 trace，不进注入正文 ----


@pytest.mark.asyncio
async def test_merged_chunk_indices_observable_context_unchanged(monkeypatch) -> None:
    """零行为变更守卫（E7 §1.5.3）：新增 merged_chunk_indices 后，开/关扩展两种
    模式下注入给模型的正文必须与修复前逐字节一致；字段只出现在 trace 里。

    手算期望（formatter：块头 `[document {i} score={rerank_score:.3f}]` + 块正文）：
    - 锚点 doc-a idx1、radius=1、开扩展：拼接正文 "A0\\nA1\\nA2"（8 字符），
      注入正文 = "[document 1 score=0.900]\\nA0\\nA1\\nA2"；
      trace.retrieved[0] = {document_id, chunk_index=1, chars=8,
      merged_chunk_indices=[0,1,2]}。
    - 关扩展：注入正文 = "[document 1 score=0.900]\\nA1"；trace 条目无
      merged_chunk_indices、chars=2。
    """
    from app.core.settings import get_settings

    candidates = [
        {"document_id": "doc-a", "chunk_index": 1, "content": "A1",
         "rerank_score": 0.9, "vector_score": 0.90},
    ]

    async def _run(expansion_enabled: str):
        monkeypatch.setenv("RAG_MIN_SIMILARITY", "0.55")
        monkeypatch.setenv("RAG_MMR_ENABLED", "false")
        monkeypatch.setenv("RAG_CONTEXT_EXPANSION_ENABLED", expansion_enabled)
        monkeypatch.setenv("RAG_CONTEXT_EXPANSION_RADIUS", "1")
        monkeypatch.setattr(service, "get_rerank_service", lambda: _FakeRerank())
        get_settings.cache_clear()
        try:
            trace = {}
            result = await service.retrieve_rag_context(
                _FakePool(_STORE),
                query="documents chapter question",
                embedding=[0.1, 0.2],
                user_id="u1",
                trace=trace,
                search_fn=_FakeSearch([dict(c) for c in candidates]),
            )
            return result, trace
        finally:
            get_settings.cache_clear()

    result_on, trace_on = await _run("true")
    # 开扩展：注入正文与修复前逐字节一致（拼接语义由上方 _expand_context 用例锁定）
    assert result_on.context == "[document 1 score=0.900]\nA0\nA1\nA2"
    assert trace_on["retrieved"] == [
        {
            "document_id": "doc-a",
            "chunk_index": 1,
            "chars": 8,  # len("A0\nA1\nA2") = 3*2 + 2 = 8
            "merged_chunk_indices": [0, 1, 2],
            # 登记 §13.1 可观测性透传：扩展块携带最靠前锚点的 rerank 分数
            "rerank_score": 0.9,
        }
    ]
    assert trace_on.get("expanded_blocks") == 1

    result_off, trace_off = await _run("false")
    # 关扩展：锚点块原样注入，trace 条目不带 merged_chunk_indices（分数仍透传）
    assert result_off.context == "[document 1 score=0.900]\nA1"
    assert trace_off["retrieved"] == [
        {"document_id": "doc-a", "chunk_index": 1, "chars": 2, "rerank_score": 0.9}
    ]
    assert "merged_chunk_indices" not in trace_off["retrieved"][0]
