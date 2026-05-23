import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from app.lib.ai.errors import ConfigError
from app.schemas.chat import ChatMessage

DEFAULT_SYSTEM_PROMPT_TEMPLATE = "system_chatbot_v1"
DEFAULT_SYSTEM_PROMPT_LANGUAGE = "zh-CN"
DEFAULT_ASSISTANT_NAME = "Chatbot AI Assistant"
TEMPLATES_DIR = Path(__file__).with_name("templates")
TEMPLATE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@lru_cache
def get_template_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


def render_system_prompt(
    *,
    template_name: str = DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    language: str = DEFAULT_SYSTEM_PROMPT_LANGUAGE,
    assistant_name: str = DEFAULT_ASSISTANT_NAME,
    user_extra_instructions: str | None = None,
    current_date: date | None = None,
) -> str:
    template_id = template_name.strip()
    if not TEMPLATE_NAME_PATTERN.fullmatch(template_id):
        raise ConfigError("AI system prompt template name is invalid.")

    try:
        template = get_template_environment().get_template(f"{template_id}.jinja")
    except TemplateNotFound as exc:
        raise ConfigError(f"AI system prompt template not found: {template_id}") from exc

    return template.render(
        template_version=template_id,
        language=language,
        current_date=(current_date or date.today()).isoformat(),
        assistant_name=assistant_name,
        user_extra_instructions=(user_extra_instructions or "").strip(),
    ).strip()


def build_messages(
    messages: list[ChatMessage],
    system_prompt: str | None = None,
    *,
    max_history_messages: int | None = None,
    max_context_chars: int | None = None,
    system_prompt_template: str = DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    system_prompt_language: str = DEFAULT_SYSTEM_PROMPT_LANGUAGE,
    assistant_name: str = DEFAULT_ASSISTANT_NAME,
    allow_user_extra_instructions: bool = True,
    current_date: date | None = None,
) -> list[dict[str, str]]:
    user_extra_instructions = system_prompt if allow_user_extra_instructions else None
    prompt = render_system_prompt(
        template_name=system_prompt_template,
        language=system_prompt_language,
        assistant_name=assistant_name,
        user_extra_instructions=user_extra_instructions,
        current_date=current_date,
    )
    payload: list[dict[str, str]] = [{"role": "system", "content": prompt}]

    trimmed_messages = trim_messages(
        messages,
        max_history_messages=max_history_messages,
        max_context_chars=max_context_chars,
    )
    payload.extend(
        {"role": message.role, "content": message.content}
        for message in trimmed_messages
    )
    return payload


def trim_messages(
    messages: list[ChatMessage],
    *,
    max_history_messages: int | None = None,
    max_context_chars: int | None = None,
) -> list[ChatMessage]:
    selected = list(messages)

    if max_history_messages and max_history_messages > 0:
        selected = selected[-max_history_messages:]

    if not max_context_chars or max_context_chars <= 0:
        return selected

    budgeted: list[ChatMessage] = []
    used_chars = 0

    for message in reversed(selected):
        content_length = len(message.content)
        if budgeted and used_chars + content_length > max_context_chars:
            break
        budgeted.append(message)
        used_chars += content_length

    budgeted.reverse()
    return budgeted
