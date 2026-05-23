# Chatbot Backend

Python FastAPI backend for the chatbot UI. The AI layer uses an OpenAI-compatible
provider interface, so OpenAI, DeepSeek, Moonshot/Kimi, and similar services can
be switched by changing configuration.

## Run

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

## API

- `GET /api/health`
- `GET /api/config`
- `POST /api/chat`

`POST /api/chat` accepts `messages`, optional `model`, optional `system_prompt`,
and optional per-request `provider_config`. The backend owns the base system
prompt through a versioned Jinja template. Request-level `system_prompt` is
treated only as extra instructions for that chat and cannot replace the base
rules.

Prompt templates live under `app/lib/ai/templates/`. Set
`AI_SYSTEM_PROMPT_TEMPLATE` to choose the active template version and
`AI_SYSTEM_PROMPT_LANGUAGE` to set the default prompt language metadata.

Set `stream: true` to receive Server-Sent Events from the same endpoint:

```txt
event: meta
data: {"model":"deepseek-chat","provider":"openai-compatible"}

event: delta
data: {"content":"你好"}

event: reasoning_delta
data: {"content":"先判断用户的问题..."}

event: done
data: {"finish_reason":"stop"}
```

The frontend sends `stream: true` by default and reads the response with
`fetch()` + `ReadableStream`, because the chat request is a `POST` body and
cannot use browser `EventSource`.

When a provider returns `reasoning_content`, `reasoning`, `thinking`, `thought`,
or explicit `<think>...</think>` text, the backend normalizes it into
`reasoning_delta` SSE events or the non-streaming `reasoning` response field.

Before sending chat history to the provider, the backend applies a simple
context boundary. `AI_MAX_HISTORY_MESSAGES` keeps only the latest messages and
`AI_MAX_CONTEXT_CHARS` applies a character budget from newest to oldest. This
keeps long conversations from growing provider requests without changing the
frontend-visible chat history.

If your shell has `http_proxy` or `https_proxy` pointing to a local proxy that is
not running, provider requests can fail with a network error. The backend ignores
environment proxy variables by default. Set `AI_TRUST_ENV_PROXY=true` only when
you intentionally want the OpenAI-compatible client to use those proxy variables.
