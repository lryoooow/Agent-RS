# Chatbot

This project contains a React frontend and a Python FastAPI backend.

## Structure

```txt
frontend/   Vite React chat interface
backend/    FastAPI chatbot backend
```

## Development

Install dependencies once:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cd ..
npm --prefix frontend install
```

Backend:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

Frontend:

```bash
npm --prefix frontend run dev
```

The frontend defaults to `POST /api/chat` and proxies `/api` to the backend.

Chat supports both modes on the same endpoint:

- `stream: false` returns the existing JSON response.
- `stream: true` returns SSE events: `meta`, `reasoning_delta`, `delta`, `done`, and `error`.

The backend is the final boundary for model context. It keeps only recent
messages and applies a character budget before calling the provider; tune this
with `AI_MAX_HISTORY_MESSAGES` and `AI_MAX_CONTEXT_CHARS` in `backend/.env`.

The backend ignores `http_proxy` and `https_proxy` by default because broken
local proxy variables commonly cause provider network failures. Set
`AI_TRUST_ENV_PROXY=true` in `backend/.env` only when that proxy is running and
you intentionally want to use it.

Optional web search is handled directly by the backend Tavily tool:

```env
TAVILY_API_KEY=your_key
```

If `TAVILY_API_KEY` is set, the LLM receives the `web_search` tool and decides
whether to call it. If the key is empty, search is unavailable and normal chat
still works.
