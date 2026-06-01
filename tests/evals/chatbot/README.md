# Chatbot Evaluations

Store chatbot evaluation rules and runners here.

`cases.schema.json` defines the JSONL case shape used by datasets under
`tests/datasets/chatbot/`.

## Runner

Use `run_chatbot_eval.py` to run dataset cases against the local backend API.

Validate datasets without calling the model:

```bash
python tests/evals/chatbot/run_chatbot_eval.py --dry-run
```

Run a small sample first:

```bash
python tests/evals/chatbot/run_chatbot_eval.py --limit 5
```

Run one category:

```bash
python tests/evals/chatbot/run_chatbot_eval.py --category safety
```

Run one case:

```bash
python tests/evals/chatbot/run_chatbot_eval.py --case-id chatbot_safety_001
```

Reports are written to `tests/reports/chatbot/YYYY-MM-DD_HHMMSS/`.

## Report Files

- `metadata.json`: Git commit, dirty-worktree flag, dataset selection, API URL, and non-secret run metadata.
- `summary.md`: Human-readable result summary.
- `results.jsonl`: One result per test case.
- `failures.jsonl`: Failed cases only.
- `latency.csv`: Latency, first status, first answer delta, visible stream duration, and stream chunk metrics.

API keys must not be saved in reports.

## Case Checks

- `must_include`: Exact required substrings.
- `must_include_any`: At least one substring in each group must appear. Use this for equivalent wording such as `负责人` / `负责`.
- `must_not_include`: Exact forbidden substrings. Broad concept terms such as `api key` and `system prompt` are not treated as leaks by themselves, and redacted placeholders are allowed.
- `forbidden_patterns`: Regex checks for real leaks or dangerous replay, such as real `sk-...`, `AI_API_KEY=...`, or repeated injection text. `[REDACTED]` and `***` placeholders are ignored.
- `expected.format_mode`: `strict` requires the whole answer to match the format; `contains` allows a valid JSON block inside a larger answer.
- `expected.language`: `zh` checks for Chinese output; `en` checks for English output when the user explicitly asks for it.
