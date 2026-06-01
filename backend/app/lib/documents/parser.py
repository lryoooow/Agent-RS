from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from app.shared.settings import Settings

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
OCR_INSTALL_HINT = (
    "OCR dependencies are unavailable. Install macOS dependencies with "
    "`brew install tesseract tesseract-lang poppler`, or Ubuntu dependencies with "
    "`sudo apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra poppler-utils`."
)


class DocumentParseError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    content: str
    doc_type: str
    metadata: dict[str, Any]


def parse_uploaded_document(
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    title: str | None,
    settings: Settings,
) -> ParsedDocument:
    if len(data) > settings.document_max_file_bytes:
        raise DocumentParseError("FILE_TOO_LARGE", "File exceeds the configured size limit.", 413)

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentParseError(
            "UNSUPPORTED_DOCUMENT_TYPE",
            "Only txt, md, markdown, pdf, and docx files are supported.",
        )

    base_metadata = {
        "filename": filename,
        "mime_type": content_type,
        "file_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "extension": extension,
    }

    if extension in TEXT_EXTENSIONS:
        content, parser = _parse_text(data)
        doc_type = "markdown" if extension in {".md", ".markdown"} else "text"
        metadata = {**base_metadata, "parser": parser, "ocr_used": False}
    elif extension == ".pdf":
        content, doc_type, metadata = _parse_pdf(data, base_metadata, settings)
    else:
        content, metadata = _parse_docx(data, base_metadata)
        doc_type = "docx"

    content = _normalize_content(content)
    if not content:
        raise DocumentParseError("DOCUMENT_TEXT_EMPTY", "No readable text was extracted from the document.")

    metadata["text_length"] = len(content)
    return ParsedDocument(
        title=(title or Path(filename).stem or "Untitled Document").strip(),
        content=content,
        doc_type=doc_type,
        metadata=metadata,
    )


def _parse_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    from charset_normalizer import from_bytes

    match = from_bytes(data).best()
    if match is None:
        raise DocumentParseError("DOCUMENT_DECODE_FAILED", "Could not detect text encoding.")
    return str(match), f"charset-normalizer:{match.encoding or 'unknown'}"


def _parse_pdf(
    data: bytes,
    base_metadata: dict[str, Any],
    settings: Settings,
) -> tuple[str, str, dict[str, Any]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
        page_count = len(reader.pages)
    except Exception as exc:
        raise DocumentParseError("PDF_PARSE_FAILED", "Could not parse the PDF file.") from exc

    if page_count > settings.document_max_pdf_pages:
        raise DocumentParseError("PDF_TOO_MANY_PAGES", "PDF exceeds the configured page limit.", 413)

    page_texts, failed_pages = _extract_pdf_page_texts(reader.pages)
    content = "\n\n".join(text for text in page_texts if text)
    average_chars = len(content.strip()) / max(page_count, 1)
    metadata = {
        **base_metadata,
        "page_count": page_count,
        "parser": "pypdf",
        "ocr_used": False,
        "average_chars_per_page": average_chars,
    }
    if failed_pages:
        metadata["pypdf_failed_pages"] = failed_pages
        metadata["pypdf_failed_page_count"] = len(failed_pages)
    has_pypdf_text = bool(content.strip())
    if has_pypdf_text and average_chars >= settings.document_ocr_min_chars_per_page:
        return content, "pdf", metadata

    try:
        ocr_text = _parse_pdf_with_ocr(data, settings, page_count)
    except DocumentParseError as exc:
        if has_pypdf_text:
            return (
                content,
                "pdf",
                {
                    **metadata,
                    "ocr_attempted": True,
                    "ocr_error_code": exc.code,
                    "ocr_fallback_to_pypdf": True,
                },
            )
        raise

    combined_content = "\n\n".join(text for text in (content, ocr_text) if text.strip())
    if not ocr_text.strip() and has_pypdf_text:
        return (
            content,
            "pdf",
            {
                **metadata,
                "ocr_attempted": True,
                "ocr_text_empty": True,
                "ocr_fallback_to_pypdf": True,
            },
        )

    return (
        combined_content,
        "pdf_ocr",
        {
            **metadata,
            "parser": "pypdf+pdf2image+pytesseract" if has_pypdf_text else "pdf2image+pytesseract",
            "ocr_used": True,
            "ocr_languages": settings.document_ocr_languages,
        },
    )


def _extract_pdf_page_texts(pages: Any) -> tuple[list[str], list[int]]:
    page_texts: list[str] = []
    failed_pages: list[int] = []
    for page_number, page in enumerate(pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            failed_pages.append(page_number)
            continue
        if text:
            page_texts.append(text)
    return page_texts, failed_pages


def _parse_pdf_with_ocr(data: bytes, settings: Settings, page_count: int) -> str:
    if page_count > settings.document_ocr_max_pages:
        raise DocumentParseError(
            "OCR_TOO_MANY_PAGES",
            "PDF requires OCR and exceeds the configured OCR page limit.",
            413,
        )
    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        raise DocumentParseError("OCR_UNAVAILABLE", OCR_INSTALL_HINT, 422)

    try:
        from pdf2image import convert_from_bytes
        import pytesseract

        images = convert_from_bytes(data, dpi=200, timeout=settings.document_ocr_timeout_seconds)
        texts = [
            pytesseract.image_to_string(
                image,
                lang=settings.document_ocr_languages,
                timeout=settings.document_ocr_timeout_seconds,
            ).strip()
            for image in images
        ]
    except Exception as exc:
        raise DocumentParseError("OCR_UNAVAILABLE", OCR_INSTALL_HINT, 422) from exc

    return "\n\n".join(text for text in texts if text)


def _parse_docx(data: bytes, base_metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise DocumentParseError("DOCX_PARSE_FAILED", "Could not parse the docx file.") from exc

    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            text = Paragraph(child, document).text.strip()
            if text:
                parts.append(text)
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            rows = [
                "\t".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                for row in table.rows
            ]
            table_text = "\n".join(row for row in rows if row)
            if table_text:
                parts.append(table_text)

    return "\n\n".join(parts), {**base_metadata, "parser": "python-docx", "ocr_used": False}


def _normalize_content(content: str) -> str:
    return "\n".join(line.strip() for line in content.splitlines() if line.strip()).strip()
