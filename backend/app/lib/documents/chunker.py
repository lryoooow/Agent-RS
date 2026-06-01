from __future__ import annotations

import re

TITLE_BOUNDARY_RE = re.compile(r"(?m)(?=^#{1,6}\s+)")
SENTENCE_RE = re.compile(r"[^。！？!?。\n]+[。！？!?。]?")


def chunk_text(
    text: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    min_chunk_size: int = 200,
) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    parts = _split_by_markdown_titles(normalized)
    atoms: list[str] = []
    for part in parts:
        atoms.extend(_split_to_atoms(part, chunk_size=chunk_size, chunk_overlap=chunk_overlap))

    chunks = _pack_atoms(atoms, chunk_size=chunk_size)
    chunks = _merge_small_tail(chunks, min_chunk_size=min_chunk_size, chunk_size=chunk_size)
    return _apply_overlap(chunks, chunk_overlap=chunk_overlap, chunk_size=chunk_size)


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()


def _split_by_markdown_titles(text: str) -> list[str]:
    sections = [section.strip() for section in TITLE_BOUNDARY_RE.split(text) if section.strip()]
    return sections or [text]


def _split_to_atoms(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    heading = ""
    if re.match(r"^#{1,6}\s+", text):
        first_line, _, rest = text.partition("\n")
        heading = first_line.strip()
        text = rest.strip()

    atoms: list[str] = []
    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            atoms.append(paragraph)
            continue

        sentence_atoms = _split_sentences(paragraph)
        for sentence in sentence_atoms:
            if len(sentence) <= chunk_size:
                atoms.append(sentence)
            else:
                atoms.extend(_char_window(sentence, chunk_size=chunk_size))
    if heading:
        if atoms:
            atoms[0] = f"{heading}\n\n{atoms[0]}".strip()
        else:
            atoms.append(heading)
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
        prefix = previous[-chunk_overlap:].strip()
        if not prefix or current.startswith(prefix):
            overlapped.append(current)
            continue
        candidate = f"{prefix}\n\n{current}".strip()
        overlapped.append(candidate if len(candidate) <= chunk_size + chunk_overlap else current)
    return overlapped
