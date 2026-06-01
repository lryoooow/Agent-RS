from app.lib.documents.chunker import chunk_text


def test_chunk_text_keeps_short_text_as_one_chunk() -> None:
    assert chunk_text("短文本", chunk_size=800) == ["短文本"]


def test_chunk_text_keeps_paragraph_boundaries() -> None:
    text = "第一段内容。" + "\n\n" + "第二段内容。"

    chunks = chunk_text(text, chunk_size=80, chunk_overlap=0)

    assert chunks == ["第一段内容。\n\n第二段内容。"]


def test_chunk_text_splits_long_paragraph_by_sentence() -> None:
    text = "第一句内容很长。" * 12 + "第二句内容很长。" * 12

    chunks = chunk_text(text, chunk_size=80, chunk_overlap=0, min_chunk_size=10)

    assert len(chunks) > 1
    assert all(chunk.endswith("。") for chunk in chunks)


def test_chunk_text_falls_back_to_character_window_with_overlap() -> None:
    text = "a" * 120

    chunks = chunk_text(text, chunk_size=50, chunk_overlap=10, min_chunk_size=10)

    assert len(chunks) == 3
    assert chunks[0] == "a" * 50
    assert chunks[1].startswith("a" * 10)


def test_chunk_text_uses_markdown_titles_as_boundaries() -> None:
    text = "# A\n\n" + "alpha " * 40 + "\n\n# B\n\n" + "beta " * 40

    chunks = chunk_text(text, chunk_size=160, chunk_overlap=20, min_chunk_size=20)

    assert len(chunks) >= 2
    assert any(chunk.startswith("# A") for chunk in chunks)
    assert any(chunk.startswith("# B") for chunk in chunks)


def test_chunk_text_merges_small_tail() -> None:
    text = "a" * 700 + "\n\n" + "b" * 120

    chunks = chunk_text(text, chunk_size=800, chunk_overlap=0, min_chunk_size=200)

    assert len(chunks) == 1
    assert "b" * 120 in chunks[0]
