from app.lib.ai.rag.mmr import mmr_select


def test_mmr_select_removes_near_duplicate_vectors() -> None:
    candidates = [
        {"id": "a", "rerank_score": 0.9, "embedding": [1.0, 0.0]},
        {"id": "b", "rerank_score": 0.89, "embedding": [0.99, 0.01]},
        {"id": "c", "rerank_score": 0.65, "embedding": [0.0, 1.0]},
    ]

    selected = mmr_select(
        candidates=candidates,
        query_embedding=[1.0, 0.0],
        top_n=2,
        lambda_mult=0.7,
    )

    assert [item["id"] for item in selected] == ["a", "c"]


def test_mmr_select_without_embeddings_falls_back_to_score_order() -> None:
    candidates = [
        {"id": "a", "rerank_score": 0.3, "embedding": None},
        {"id": "b", "rerank_score": 0.9, "embedding": None},
        {"id": "c", "rerank_score": 0.6, "embedding": None},
    ]

    selected = mmr_select(candidates=candidates, query_embedding=[], top_n=2)

    assert [item["id"] for item in selected] == ["b", "c"]


def test_mmr_select_returns_all_when_top_n_exceeds_candidates() -> None:
    candidates = [
        {"id": "a", "rerank_score": 0.3, "embedding": [1.0]},
        {"id": "b", "rerank_score": 0.9, "embedding": [0.0]},
    ]

    selected = mmr_select(candidates=candidates, query_embedding=[1.0], top_n=5)

    assert [item["id"] for item in selected] == ["b", "a"]
