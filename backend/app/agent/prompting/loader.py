import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from app.agent.errors import ConfigError

TEMPLATES_DIR = Path(__file__).with_name("templates")
TEMPLATE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@lru_cache
def get_prompt_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


def render_template(template_name: str, variables: dict[str, str]) -> str:
    template_id = template_name.strip()
    if not TEMPLATE_NAME_PATTERN.fullmatch(template_id):
        raise ConfigError("AI prompt template name is invalid.")

    try:
        template = get_prompt_environment().get_template(f"{template_id}.jinja")
    except TemplateNotFound as exc:
        raise ConfigError(f"AI prompt template not found: {template_id}") from exc

    return template.render(**variables).strip()

