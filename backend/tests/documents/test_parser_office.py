from __future__ import annotations

from io import BytesIO

import pytest

from app.core.settings import Settings
from app.documents.parser import (
    DocumentParseError,
    SUPPORTED_EXTENSIONS,
    parse_uploaded_document,
)


@pytest.fixture
def settings():
    return Settings(_env_file=None)


def _make_pptx(slides: list[list[str]]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    blank = prs.slide_layouts[6]
    for texts in slides:
        slide = prs.slides.add_slide(blank)
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(4))
        tf = box.text_frame
        for i, line in enumerate(texts):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = line
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extensions_registered():
    assert ".pptx" in SUPPORTED_EXTENSIONS
    assert ".xlsx" in SUPPORTED_EXTENSIONS


# ---- PPTX ----

def test_parse_pptx_extracts_text(settings):
    data = _make_pptx([["遥感影像分析", "NDVI 植被指数"], ["第二页内容"]])
    parsed = parse_uploaded_document(
        filename="deck.pptx", content_type=None, data=data, title=None, settings=settings
    )
    assert parsed.doc_type == "pptx"
    assert "遥感影像分析" in parsed.content
    assert "NDVI 植被指数" in parsed.content
    assert "第二页内容" in parsed.content
    assert parsed.metadata["slide_count"] == 2
    assert parsed.metadata["parser"] == "python-pptx"


def test_parse_pptx_empty_raises(settings):
    data = _make_pptx([[]])  # one blank slide, no text
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="empty.pptx", content_type=None, data=data, title=None, settings=settings
        )
    assert exc.value.code == "DOCUMENT_TEXT_EMPTY"


def test_parse_pptx_corrupted_raises(settings):
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bad.pptx", content_type=None, data=b"not a real pptx", title=None, settings=settings
        )
    assert exc.value.code == "PPTX_PARSE_FAILED"


# ---- XLSX ----

def test_parse_xlsx_multi_sheet(settings):
    data = _make_xlsx({
        "Sheet1": [["name", "value"], ["alpha", 10], ["beta", 20]],
        "数据": [["城市", "温度"], ["北京", 25]],
    })
    parsed = parse_uploaded_document(
        filename="book.xlsx", content_type=None, data=data, title=None, settings=settings
    )
    assert parsed.doc_type == "xlsx"
    assert "# Sheet1" in parsed.content
    assert "# 数据" in parsed.content
    assert "alpha\t10" in parsed.content
    assert "北京\t25" in parsed.content
    assert parsed.metadata["sheet_count"] == 2
    assert parsed.metadata["parser"] == "openpyxl"


def test_parse_xlsx_empty_raises(settings):
    data = _make_xlsx({"Empty": []})
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="empty.xlsx", content_type=None, data=data, title=None, settings=settings
        )
    assert exc.value.code == "DOCUMENT_TEXT_EMPTY"


def test_parse_xlsx_corrupted_raises(settings):
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bad.xlsx", content_type=None, data=b"garbage bytes", title=None, settings=settings
        )
    assert exc.value.code == "XLSX_PARSE_FAILED"


def test_unsupported_type_message_mentions_new_formats(settings):
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="image.png", content_type=None, data=b"x" * 10, title=None, settings=settings
        )
    assert exc.value.code == "UNSUPPORTED_DOCUMENT_TYPE"
    assert "pptx" in exc.value.message and "xlsx" in exc.value.message


# ---- Office zip 炸弹预检（G1，2026-10-09）----
# 历史 bug：docx/pptx/xlsx 解析前无任何解压检查，70.9KB 上传（压缩比 880:1）迫使
# 进程分配 187MB（tracemalloc 实测，复现脚本见 bugfix-plan-G 工作单汇报）；
# 攻击者用 20MB 上传额度可迫使 ~12GB 分配，拖垮整个后端。
# 修复：_check_office_zip 只读 zip 中央目录预检（条目数/单条目压缩比/解压总量），
# 超限 DocumentParseError(413)，在任何解压发生之前拦截。

import tracemalloc
import zipfile
from io import BytesIO as _BytesIO


def _split_into(total: int, parts: int) -> list[int]:
    """把 total 字节尽量均分进 parts 份（整数，余数给前几份）。"""
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def _make_zip_docx(entries: dict[str, str], compression=zipfile.ZIP_DEFLATED) -> bytes:
    """构造最小可解析 docx（zip 包）；entries 允许注入任意大小/压缩比的条目。"""
    base = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
    }
    document = entries.pop(
        "word/document.xml",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>正常内容</w:t></w:r></w:p></w:body></w:document>",
    )
    buf = _BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, payload in {**base, "word/document.xml": document, **entries}.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def test_office_normal_zip_passes_precheck(settings):
    """正常：自制小体积、低压缩比 docx 通过预检并解析出文本。"""
    data = _make_zip_docx({})
    parsed = parse_uploaded_document(
        filename="normal.docx", content_type=None, data=data, title=None, settings=settings
    )
    assert parsed.doc_type == "docx"
    assert "正常内容" in parsed.content


def test_office_zip_bomb_high_ratio_rejected_413(settings):
    """非法：高压缩比条目（~71KB 压缩 → 61MB 解压，比 ~880:1）→ 413，进程内存不暴涨。"""
    huge = "<w:p><w:r><w:t>" + "A" * 100_000 + "</w:t></w:r></w:p>"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + huge * 640 + "</w:body></w:document>"
    )
    data = _make_zip_docx({"word/document.xml": document})
    assert len(data) < 200 * 1024  # 上传体积确实很小（<200KB）

    tracemalloc.start()
    tracemalloc.reset_peak()
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bomb.docx", content_type=None, data=data, title=None, settings=settings
        )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert exc.value.code == "OFFICE_ARCHIVE_COMPRESSION_RATIO"
    assert exc.value.status_code == 413
    # 回归：61MB 解压体不得进入内存（预检只读中央目录，峰值须远小于解压体积）
    assert peak < 4 * 1024 * 1024, f"pre-check allocated {peak} bytes; decompression happened?"


def test_office_zip_bomb_total_uncompressed_rejected_413(settings):
    """非法：总解压体积超限（默认 100MB）→ 413。用小上限 settings 精确构造。"""
    # 每条目 50KB×3 = 150KB 解压，压缩比 ~500:1 会先撞比值上限——改为 stored（不压缩）条目，
    # 比值 1:1 不触发，只触发总量上限。
    small = Settings(
        _env_file=None,
        document_office_max_total_uncompressed_bytes=100 * 1024,
        document_office_max_entry_compression_ratio=10_000,
    )
    data = _make_zip_docx(
        {
            "word/media/blob1.bin": "B" * 50_000,
            "word/media/blob2.bin": "B" * 50_000,
            "word/media/blob3.bin": "B" * 50_000,
        },
        compression=zipfile.ZIP_STORED,
    )
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="big.docx", content_type=None, data=data, title=None, settings=small
        )
    assert exc.value.code == "OFFICE_ARCHIVE_TOO_LARGE"
    assert exc.value.status_code == 413


def test_office_zip_bomb_too_many_entries_rejected_413(settings):
    """非法：条目数超限（默认 10000）→ 413。"""
    data = _make_zip_docx({f"word/media/f{i}.bin".format(i=i): "x" for i in range(10_001)})
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="many.docx", content_type=None, data=data, title=None, settings=settings
        )
    assert exc.value.code == "OFFICE_ARCHIVE_TOO_MANY_ENTRIES"
    assert exc.value.status_code == 413


def test_office_precheck_boundaries_pass(settings):
    """边界：恰好等于各上限（10000 条目 / 比值=上限 / 总量=上限）不拒——上限含边界值。"""
    # 条目数恰好 10000（3 个基础条目 + 9997 个附加）；python-docx 忽略未知条目，能正常解析
    exact_entries = {f"word/media/f{i}.bin": "x" for i in range(9_997)}
    data = _make_zip_docx(exact_entries)
    roomy = Settings(
        _env_file=None,
        document_office_max_total_uncompressed_bytes=200 * 1024,  # 实际总量（约 100KB 附件+小基础条目）< 上限
    )
    parsed = parse_uploaded_document(
        filename="edge.docx", content_type=None, data=data, title=None, settings=roomy
    )
    assert "正常内容" in parsed.content  # 预检三项全部放行（任一超限会是 OFFICE_ARCHIVE_*）

    # 总解压体积恰好等于上限：基础条目总量 + stored 附件补齐到恰等 100KB 上限
    # 基础 zip（Content_Types/rels/document.xml）体量小且不定，先量出实际值再补差值。
    base_data = _make_zip_docx({})
    with zipfile.ZipFile(_BytesIO(base_data)) as zf:
        base_total = sum(i.file_size for i in zf.infolist() if not i.is_dir())
    remain = 100 * 1024 - base_total
    assert remain > 0
    payload = {f"pad{i}.bin": "P" * split for i, split in enumerate(_split_into(remain, 2))}
    exact_total = _make_zip_docx(payload, compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(_BytesIO(exact_total)) as zf:
        assert sum(i.file_size for i in zf.infolist() if not i.is_dir()) == 100 * 1024
    exact_settings = Settings(_env_file=None, document_office_max_total_uncompressed_bytes=100 * 1024)
    parsed = parse_uploaded_document(
        filename="exact.docx", content_type=None, data=exact_total, title=None, settings=exact_settings
    )
    assert "正常内容" in parsed.content

    # 压缩比恰好等于上限：stored 条目 file_size==compress_size（比=1）+ 上限 1 → 不 > 1，放行
    ratio_edge = Settings(
        _env_file=None,
        document_office_max_entry_compression_ratio=1,
    )
    stored = _make_zip_docx({}, compression=zipfile.ZIP_STORED)
    parsed = parse_uploaded_document(
        filename="ratio1.docx", content_type=None, data=stored, title=None, settings=ratio_edge
    )
    assert "正常内容" in parsed.content


def test_office_precheck_skips_dir_and_empty_entries(settings):
    """异常分支：目录条目不计总量；压缩体积为 0 的空文件条目不做除零。"""
    buf = _BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "x")
        zf.writestr("empty.bin", "")
        zf.writestr("dir/", "")
    data = buf.getvalue()
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="dirs.docx", content_type=None, data=data, title=None, settings=settings
        )
    # 预检通过（未抛 OFFICE_ARCHIVE_*），到达解析器本体报 DOCX_PARSE_FAILED
    assert exc.value.code == "DOCX_PARSE_FAILED"


def test_office_fake_nonzip_docx_rejected_400(settings):
    """异常：非 zip 的伪 docx → DOCX_PARSE_FAILED(400)，与修复前行为一致。"""
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bad.docx", content_type=None, data=b"plain text pretending", title=None, settings=settings
        )
    assert exc.value.code == "DOCX_PARSE_FAILED"
    assert exc.value.status_code == 400


def test_office_precheck_covers_pptx_and_xlsx(settings):
    """回归：pptx/xlsx 同样过预检——正常文件放行、高压缩比炸弹 413。"""
    # 正常 pptx（真实 python-pptx 构造，低压缩比）不受影响
    normal = _make_pptx([["正常页"]])
    parsed = parse_uploaded_document(
        filename="ok.pptx", content_type=None, data=normal, title=None, settings=settings
    )
    assert "正常页" in parsed.content

    # pptx 炸弹：把高压缩比条目塞进真实 pptx 包
    src = _BytesIO(normal)
    out = _BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            zout.writestr(name, zin.read(name))
        zout.writestr("ppt/media/bomb.bin", "C" * 8_000_000)  # 8MB→~8KB，比~1000:1
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bomb.pptx", content_type=None, data=out.getvalue(), title=None, settings=settings
        )
    assert exc.value.code == "OFFICE_ARCHIVE_COMPRESSION_RATIO"
    assert exc.value.status_code == 413

    # xlsx 炸弹（同样机制）
    normal_x = _make_xlsx({"S": [["a"]]})
    src = _BytesIO(normal_x)
    out = _BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            zout.writestr(name, zin.read(name))
        zout.writestr("xl/media/bomb.bin", "D" * 8_000_000)
    with pytest.raises(DocumentParseError) as exc:
        parse_uploaded_document(
            filename="bomb.xlsx", content_type=None, data=out.getvalue(), title=None, settings=settings
        )
    assert exc.value.code == "OFFICE_ARCHIVE_COMPRESSION_RATIO"
