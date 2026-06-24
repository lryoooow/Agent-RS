from __future__ import annotations

import re
from dataclasses import dataclass

# 标题边界：在每个 Markdown 标题行（# ~ ######）前切分，标题归属其后的章节内容。
TITLE_BOUNDARY_RE = re.compile(r"(?m)(?=^#{1,6}\s+)")
# 标题行解析：捕获 # 级别与标题文本，用于构建层级面包屑。
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 句子切分：CJK 句末标点与英文 ! ? ; 一律断句；英文句点「.」仅当其后为空白/行尾才断句
# （避免切断小数 v1.5、缩写如 etc.）；段内换行处断句，避免不同物理行黏连成一句。
SENTENCE_RE = re.compile(r".+?(?:[。！？!?；;]|\.(?=\s|$)|(?=\n)|$)")


@dataclass(frozen=True)
class ChunkPiece:
    """切块结果（供入库链路使用）：块正文 + 所属章节面包屑 + 全局序号。"""

    text: str
    section: str
    index: int


@dataclass(frozen=True)
class _Section:
    """文档按标题切出的章节单元（内部用）。"""

    heading_line: str  # 原始标题行（如 "## 3.1 卫星影像"）；前导段无标题时为 ""
    breadcrumb: str  # 层级面包屑（如 "第3章 数据来源 › 3.1 卫星影像"）；无标题时为 ""
    body: str  # 去掉标题行后的章节正文


def chunk_text(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    min_chunk_size: int = 200,
) -> list[str]:
    """按结构切块，返回纯文本块列表。

    向后兼容旧接口：不附加章节面包屑，标题行仅保留在所属章节首块（与历史行为一致）。
    新入库链路请用 `chunk_document`（带章节面包屑，保证语义连贯）。
    """
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]
    pieces = _chunk_normalized(
        normalized,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
        with_breadcrumb=False,
    )
    return [chunk for _, chunk in pieces]


def chunk_document(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    min_chunk_size: int = 200,
) -> list[ChunkPiece]:
    """按结构切块，返回带章节面包屑与全局序号的块（供入库）。

    语义连贯保证：(1) 章节内独立打包，不把相邻章节内容混进同一块；
    (2) 同一章节切出的**每一块**开头都带章节面包屑，块脱离原文后仍知归属，
    且面包屑随正文一起进入向量嵌入与全文索引，参与召回。
    """
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [ChunkPiece(text=normalized, section=_leading_breadcrumb(normalized), index=0)]
    pieces = _chunk_normalized(
        normalized,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
        with_breadcrumb=True,
    )
    return [
        ChunkPiece(text=chunk, section=breadcrumb, index=index)
        for index, (breadcrumb, chunk) in enumerate(pieces)
    ]


def _chunk_normalized(
    normalized: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    min_chunk_size: int,
    with_breadcrumb: bool,
) -> list[tuple[str, str]]:
    """核心切块：按章节分组、组内独立打包（不跨章节），返回 (面包屑, 块文本) 列表。"""
    results: list[tuple[str, str]] = []
    for section in _split_into_sections(normalized):
        prefix = section.breadcrumb if with_breadcrumb else section.heading_line
        # 预留前缀长度，使「前缀 + 正文」总长尽量不超过 chunk_size；下限不低于 min_chunk_size。
        body_budget = max(chunk_size - (len(prefix) + 2 if prefix else 0), min_chunk_size)

        atoms = _split_to_atoms(section.body, chunk_size=body_budget)
        packed = _pack_atoms(atoms, chunk_size=body_budget)
        packed = _merge_small_tail(packed, min_chunk_size=min_chunk_size, chunk_size=body_budget)
        packed = _apply_overlap(packed, chunk_overlap=chunk_overlap, chunk_size=body_budget)

        if not packed:
            # 仅有标题、无正文的章节：保留标题/面包屑，避免结构信息丢失。
            if with_breadcrumb and section.breadcrumb:
                results.append((section.breadcrumb, section.breadcrumb))
            elif not with_breadcrumb and section.heading_line:
                results.append((section.breadcrumb, section.heading_line))
            continue

        for position, chunk in enumerate(packed):
            if with_breadcrumb:
                rendered = f"{section.breadcrumb}\n\n{chunk}" if section.breadcrumb else chunk
            elif position == 0 and section.heading_line:
                rendered = f"{section.heading_line}\n\n{chunk}"
            else:
                rendered = chunk
            results.append((section.breadcrumb, rendered))
    return results


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()


def _split_into_sections(text: str) -> list[_Section]:
    """按 Markdown 标题切分为章节，维护标题层级栈生成面包屑路径。

    `TITLE_BOUNDARY_RE` 在每个标题前切分，故除首个「前导段」外每段都以标题行开头。
    层级栈：遇到级别 L 的标题时，弹出栈中所有级别 >= L 的节点再压入，路径即为面包屑。
    """
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []  # (标题级别, 标题文本)
    for part in TITLE_BOUNDARY_RE.split(text):
        part = part.strip()
        if not part:
            continue
        first_line, _, rest = part.partition("\n")
        match = HEADING_RE.match(first_line.strip())
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            breadcrumb = " › ".join(node_title for _, node_title in stack if node_title)
            sections.append(
                _Section(heading_line=first_line.strip(), breadcrumb=breadcrumb, body=rest.strip())
            )
        else:
            # 前导段（首个标题之前的内容）：无标题、无面包屑。
            sections.append(_Section(heading_line="", breadcrumb="", body=part))
    return sections or [_Section(heading_line="", breadcrumb="", body=text)]


def _leading_breadcrumb(text: str) -> str:
    """提取文档起始处的标题文本（供短文档单块的章节标注）；起始为正文则返回空串。"""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = HEADING_RE.match(stripped)
        return match.group(2).strip() if match else ""
    return ""


def _split_to_atoms(text: str, *, chunk_size: int) -> list[str]:
    """把章节正文拆成原子片段：先按空行分段，超长段按句切分，超长句按字符窗兜底。"""
    atoms: list[str] = []
    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            atoms.append(paragraph)
            continue
        for sentence in _split_sentences(paragraph):
            if len(sentence) <= chunk_size:
                atoms.append(sentence)
            else:
                atoms.extend(_char_window(sentence, chunk_size=chunk_size))
    return atoms


def _split_sentences(text: str) -> list[str]:
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(text)]
    return [sentence for sentence in sentences if sentence] or [text]


def _char_window(text: str, *, chunk_size: int) -> list[str]:
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + chunk_size, len(text))
        chunk = text[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        cursor = end
    return chunks


def _pack_atoms(atoms: list[str], *, chunk_size: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for atom in atoms:
        if not current:
            current = atom
            continue
        separator = "\n\n" if "\n" in current or "\n" in atom else " "
        candidate = f"{current}{separator}{atom}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current)
            current = atom
    if current:
        chunks.append(current)
    return chunks


def _merge_small_tail(chunks: list[str], *, min_chunk_size: int, chunk_size: int) -> list[str]:
    if len(chunks) < 2 or len(chunks[-1]) >= min_chunk_size:
        return chunks
    previous = chunks[-2]
    tail = chunks[-1]
    separator = "\n\n" if "\n" in previous or "\n" in tail else " "
    merged = f"{previous}{separator}{tail}".strip()
    if len(merged) <= chunk_size + min_chunk_size:
        return [*chunks[:-2], merged]
    return chunks


def _apply_overlap(chunks: list[str], *, chunk_overlap: int, chunk_size: int) -> list[str]:
    if chunk_overlap <= 0 or len(chunks) < 2:
        return chunks

    overlapped = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:], strict=False):
        if current.lstrip().startswith("#"):
            overlapped.append(current)
            continue
        prefix = _overlap_prefix(previous, chunk_overlap=chunk_overlap)
        if not prefix or current.startswith(prefix):
            overlapped.append(current)
            continue
        candidate = f"{prefix}\n\n{current}".strip()
        overlapped.append(candidate if len(candidate) <= chunk_size + chunk_overlap else current)
    return overlapped


def _overlap_prefix(previous: str, *, chunk_overlap: int) -> str:
    """取 previous 末尾的完整句子作为重叠前缀（≤ ~chunk_overlap 预算）。

    旧实现按 `previous[-overlap:]` 裸字符截取，会粘半句话并污染块正文。改为按句子边界
    截取完整尾句；无内部句界（如无标点长串）时退回字符窗口，保持旧兜底行为。
    """
    sentences = _split_sentences(previous)
    if len(sentences) <= 1:
        return previous[-chunk_overlap:].strip()
    selected: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        if selected and total + len(sentence) > chunk_overlap:
            break
        selected.insert(0, sentence)
        total += len(sentence)
    return " ".join(selected).strip()
