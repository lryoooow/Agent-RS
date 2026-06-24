from app.documents.chunker import ChunkPiece, chunk_document, chunk_text


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


# ---- 语义连贯优化：章节边界 / 面包屑 / 句子正则 / 重叠对齐（新增）----


def test_no_chunk_spans_two_sections() -> None:
    # 历史问题回归：旧实现全局打包会把 A 节尾与 B 节头塞进同一块。
    # 锁死"章节不跨界"：每个章节的特征词不得同时出现在同一块。
    text = "# 甲章\n\n" + "甲内容句子。" * 30 + "\n\n# 乙章\n\n" + "乙内容句子。" * 30

    pieces = chunk_document(text, chunk_size=200, chunk_overlap=40, min_chunk_size=50)

    assert all(not ("甲内容句子" in p.text and "乙内容句子" in p.text) for p in pieces)


def test_every_chunk_in_long_section_carries_breadcrumb() -> None:
    # 长章节切成多块时，每一块都必须带章节面包屑（而非仅首块）。
    text = "# 第3章 数据来源\n\n" + "卫星影像通过开放中心下载。" * 40

    pieces = chunk_document(text, chunk_size=200, chunk_overlap=40, min_chunk_size=50)

    assert len(pieces) > 1
    assert all(p.section == "第3章 数据来源" for p in pieces)
    assert all(p.text.startswith("第3章 数据来源") for p in pieces)


def test_breadcrumb_includes_nested_heading_path() -> None:
    text = "# 第3章 数据来源\n\n" + "概述内容。" * 30 + "\n\n## 3.1 卫星影像\n\n" + "细节内容。" * 30

    pieces = chunk_document(text, chunk_size=200, chunk_overlap=40, min_chunk_size=50)

    assert any(p.section == "第3章 数据来源 › 3.1 卫星影像" for p in pieces)
    # 嵌套块的面包屑必须含父级路径
    nested = [p for p in pieces if "卫星影像" in p.section]
    assert nested and all("第3章 数据来源" in p.section for p in nested)


def test_plain_text_without_headings_has_no_breadcrumb() -> None:
    # 无 Markdown 标题的纯文本：行为兼容，块不带面包屑前缀。
    text = "这是一段没有任何标题的纯文本内容。" * 40

    pieces = chunk_document(text, chunk_size=200, chunk_overlap=40, min_chunk_size=50)

    assert len(pieces) > 1
    assert all(p.section == "" for p in pieces)


def test_chunk_document_short_text_single_piece() -> None:
    pieces = chunk_document("# 标题\n\n很短的正文。", chunk_size=800)

    assert len(pieces) == 1
    assert pieces[0].index == 0
    assert pieces[0].section == "标题"


def test_sentence_split_handles_english_and_decimals() -> None:
    # 英文句号断句 + 中文混排；小数点/版本号不得被误切。
    text = "First sentence. Second sentence. 版本 v1.5 数据已就绪。最后一句。"

    pieces = chunk_document(text, chunk_size=20, chunk_overlap=0, min_chunk_size=5)
    joined = " ".join(p.text for p in pieces)

    # 小数完整保留
    assert "v1.5" in joined
    # 英文两句可分（chunk_size 远小于全文，必然多块且各含独立英文句）
    assert any("First sentence." in p.text for p in pieces)
    assert any("Second sentence." in p.text for p in pieces)


def test_overlap_prefix_is_whole_sentence_not_mid_sentence() -> None:
    # 重叠 bug 回归：旧实现按字符硬截会粘半句。新实现重叠前缀须是完整句子。
    text = "".join(f"第{i}句完整内容。" for i in range(1, 21))

    chunks = chunk_text(text, chunk_size=60, chunk_overlap=24, min_chunk_size=10)

    assert len(chunks) > 1
    # 第二块开头的重叠部分应以"第N句"起头（完整句），不以句子中段起头
    second = chunks[1]
    assert second.startswith("第")
    # 重叠段每个句子完整结尾（不出现裸截断的残句：以"内容"结尾却无"。"）
    assert "内容\n" not in second and not second.startswith("内容")


def test_chunk_text_still_returns_list_of_str() -> None:
    text = "# 标题\n\n" + "内容句子。" * 50

    chunks = chunk_text(text, chunk_size=200)

    assert all(isinstance(c, str) for c in chunks)


def test_chunk_document_returns_pieces_with_index() -> None:
    text = "# 标题\n\n" + "内容句子。" * 50

    pieces = chunk_document(text, chunk_size=200)

    assert all(isinstance(p, ChunkPiece) for p in pieces)
    assert [p.index for p in pieces] == list(range(len(pieces)))
