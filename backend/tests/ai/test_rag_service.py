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
