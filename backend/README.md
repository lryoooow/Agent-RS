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

Prompt templates live under `app/lib/ai/prompting/templates/`. Set
`AI_PROMPT_PROFILE` to choose the active prompt profile. The renderer injects
only the selected prompt modules for the current request; task-specific prompt
modules are not part of every provider request.

Set `stream: true` to receive Server-Sent Events from the same endpoint:

```txt
event: meta
data: {"model":"deepseek-chat","provider":"openai-compatible"}

event: analysis_status
data: {"status":"analyzing","label":"正在分析问题…"}

event: analysis_status
data: {"status":"preparing","label":"正在整理内容…"}

event: analysis_status
data: {"status":"answering","label":"正在组织回复…"}

event: analysis_status
data: {"status":"complete","label":"思考完成"}

event: delta
data: {"content":"你好"}

event: done
data: {"finish_reason":"stop"}
```

The frontend sends `stream: true` by default and reads the response with
`fetch()` + `ReadableStream`, because the chat request is a `POST` body and
cannot use browser `EventSource`.

When a provider returns `reasoning_content`, `reasoning`, `thinking`, `thought`,
or explicit `<think>...</think>` text, the backend strips that raw reasoning
from user-visible responses. Streaming clients receive only safe
`analysis_status` progress events plus final answer deltas.

Before sending provider requests, the backend assembles context through
`app/lib/ai/context/`. The base system prompt, per-chat extra instructions,
recent dialogue, and future summary/memory/RAG/tool blocks are separate context
sections with their own budgets. Empty optional blocks are not injected.

Current context limits:

- `AI_CONTEXT_MAX_TOTAL_CHARS`: total context budget.
- `AI_CONTEXT_MAX_RECENT_MESSAGES`: latest dialogue message count.
- `AI_CONTEXT_MAX_RECENT_CHARS`: latest dialogue character budget.
- `AI_CONTEXT_MAX_USER_EXTRA_CHARS`: per-chat extra instruction budget.
- `AI_CONTEXT_MAX_SUMMARY_CHARS`: future compressed conversation summary budget.
- `AI_CONTEXT_MAX_MEMORY_CHARS`: future long-term memory summary budget.
- `AI_CONTEXT_MAX_RAG_CHARS`: future retrieved context budget.
- `AI_CONTEXT_MAX_TOOL_CHARS`: future tool result summary budget.

`AI_MAX_HISTORY_MESSAGES` and `AI_MAX_CONTEXT_CHARS` remain as compatibility
fallbacks for recent messages and total context if the newer context settings
are not provided.

If your shell has `http_proxy` or `https_proxy` pointing to a local proxy that is
not running, provider requests can fail with a network error. The backend ignores
environment proxy variables by default. Set `AI_TRUST_ENV_PROXY=true` only when
you intentionally want the OpenAI-compatible client to use those proxy variables.
