from app.agent.rag.formatter import format_retrieved_blocks


def test_document_block_shows_section_breadcrumb() -> None:
    # document 块带 metadata.section → 块头注明章节归属，让模型知道来源位置。
    items = [
        {"content": "卫星影像通过开放中心下载。", "metadata": {"section": "第3章 数据来源 › 3.1"}, "rerank_score": 0.82},
    ]

    rendered = format_retrieved_blocks(items, title="document")

    assert "第3章 数据来源 › 3.1" in rendered
    assert "卫星影像通过开放中心下载。" in rendered


def test_memory_block_without_section_falls_back() -> None:
    # memory 调用点无 section → 优雅降级，块头仍为 [memory N]，行为不变。
    items = [{"content": "用户偏好简洁回答。", "metadata": {}}]

    rendered = format_retrieved_blocks(items, title="memory")

    assert rendered.startswith("[memory 1]")
    assert "·" not in rendered.split("\n")[0]


def test_block_handles_metadata_as_json_string() -> None:
    # jsonb 反序列化可能给出 str 形态的 metadata → 解析后仍能取出 section，不抛异常。
    items = [{"content": "正文。", "metadata": '{"section": "甲章"}'}]

    rendered = format_retrieved_blocks(items, title="document")

    assert "甲章" in rendered


def test_block_handles_malformed_metadata_string() -> None:
    # 非法 JSON 字符串不得让格式化崩溃，退化为无章节标注。
    items = [{"content": "正文。", "metadata": "not-json"}]

    rendered = format_retrieved_blocks(items, title="document")

    assert "正文。" in rendered
    assert rendered.startswith("[document 1]")


def test_block_without_metadata_key() -> None:
    # 完全没有 metadata 字段（如旧数据/其它来源）→ 不报错，块头无章节。
    items = [{"content": "正文。"}]

    rendered = format_retrieved_blocks(items, title="document")

    assert rendered.startswith("[document 1]")


def test_empty_content_skipped() -> None:
    items = [{"content": "  ", "metadata": {"section": "甲"}}, {"content": "有效", "metadata": {}}]

    rendered = format_retrieved_blocks(items, title="document")

    # 空白内容不渲染（既有行为：编号沿用 enumerate 序号，不重排）
    assert "有效" in rendered
    assert "甲" not in rendered
    assert rendered.count("[document") == 1
