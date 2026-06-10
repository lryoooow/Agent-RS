from pathlib import Path

from docx import Document


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "tests" / "reports" / "agent_rs_strict_smoke_test_report_2026-06-09.docx"


def test_strict_smoke_report_keeps_readable_chinese_text() -> None:
    assert REPORT_PATH.exists()

    document = Document(REPORT_PATH)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "Agent-RS" in text
    assert "冒烟" in text
    assert "测试" in text
    assert "工具" in text
    assert "？？" not in text
    assert text.count("?") < 20


def test_python_sources_are_utf8_without_replacement_characters() -> None:
    scanned = 0

    for base in (REPO_ROOT / "backend" / "app", REPO_ROOT / "backend" / "tests"):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            scanned += 1
            assert "\ufffd" not in text, path.relative_to(REPO_ROOT).as_posix()

    assert scanned > 0
