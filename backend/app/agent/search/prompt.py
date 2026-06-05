from pathlib import Path


def load_web_search_prompt() -> str:
    return Path(__file__).with_name("prompt.jinja").read_text(encoding="utf-8").strip()
