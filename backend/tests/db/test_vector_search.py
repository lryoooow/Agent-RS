import pytest

from app.lib.db.repositories.vector_search import search_hybrid_rrf


class FakeConn:
    def __init__(self, *, vector_rows, tsv_rows):
        self.vector_rows = vector_rows
        self.tsv_rows = tsv_rows
        self.calls: list[str] = []

    async def fetch(self, sql, *_):
        self.calls.append(sql)
        if "ts_rank_cd" in sql and "WHERE content_tsv" in sql:
            return self.tsv_rows
        return self.vector_rows


@pytest.mark.asyncio
async def test_search_hybrid_rrf_fuses_and_deduplicates_results() -> None:
    conn = FakeConn(
        vector_rows=[
            {
                "id": "a",
                "document_id": "doc-a",
                "content": "alpha vector",
                "metadata": {},
                "embedding": "[1,0]",
                "vector_score": 0.9,
            },
            {
                "id": "b",
                "document_id": "doc-b",
                "content": "beta vector",
                "metadata": {},
                "embedding": "[0.8,0.2]",
                "vector_score": 0.8,
            },
        ],
        tsv_rows=[
            {
                "id": "b",
                "document_id": "doc-b",
                "content": "beta text",
                "metadata": {},
                "text_score": 0.7,
            },
            {
                "id": "c",
                "document_id": "doc-c",
                "content": "gamma text",
                "metadata": {},
                "text_score": 0.6,
            },
        ],
    )

    rows = await search_hybrid_rrf(conn, embedding=[1, 0], query="beta", limit=3, k=60)

    assert [row["id"] for row in rows] == ["b", "a", "c"]
    assert rows[0]["vector_score"] == 0.8
    assert rows[0]["text_score"] == 0.7
    assert rows[0]["embedding"] == [0.8, 0.2]
    assert rows[0]["rrf_score"] > rows[1]["rrf_score"]


@pytest.mark.asyncio
async def test_search_hybrid_rrf_uses_vector_only_for_empty_query() -> None:
    conn = FakeConn(
        vector_rows=[
            {
                "id": "a",
                "document_id": "doc-a",
                "content": "alpha vector",
                "metadata": {},
                "embedding": "[1,0]",
                "vector_score": 0.9,
            }
        ],
        tsv_rows=[],
    )

    rows = await search_hybrid_rrf(conn, embedding=[1, 0], query=" ", limit=3, k=60)

    assert [row["id"] for row in rows] == ["a"]
    assert len(conn.calls) == 1


@pytest.mark.asyncio
async def test_search_hybrid_rrf_keeps_tsv_only_results() -> None:
    conn = FakeConn(
        vector_rows=[],
        tsv_rows=[
            {
                "id": "c",
                "document_id": "doc-c",
                "content": "gamma text",
                "metadata": {},
                "text_score": 0.6,
            }
        ],
    )

    rows = await search_hybrid_rrf(conn, embedding=[1, 0], query="gamma", limit=3, k=60)

    assert [row["id"] for row in rows] == ["c"]
    assert rows[0]["embedding"] is None if "embedding" in rows[0] else True
