# Prompt Templates

System prompts live in versioned Jinja templates so prompt changes are separate
from Python code and can be traced in tests.

## Versioning

- Template IDs map directly to file names, for example
  `system_chatbot_v1` -> `system_chatbot_v1.jinja`.
- Keep old templates when making large behavior changes. Add a new version such
  as `system_chatbot_v2.jinja`.
- Small wording fixes can stay in the current version when tests continue to
  cover the required boundaries.

## Variables

- `template_version`: active template ID.
- `language`: default response language.
- `current_date`: server-side current date in `YYYY-MM-DD` format.
- `assistant_name`: assistant display name.
- `user_extra_instructions`: optional per-chat instructions from the frontend.

