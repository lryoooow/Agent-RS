# Chatbot Datasets

Store versioned chatbot evaluation datasets here. Each dataset should be JSONL:
one complete test case per line.

Planned files:

- `basic_v1.jsonl`: Basic Chinese chat, markdown/table/json formatting, and simple document-style tasks.
- `streaming_v1.jsonl`: Streaming response behavior and event-order expectations.
- `context_v1.jsonl`: Short-term dialogue, summarized history, and memory boundary checks.
- `safety_v1.jsonl`: Prompt boundary, system prompt leakage, API key leakage, and reasoning leakage checks.
- `errors_v1.jsonl`: Invalid input, provider failure, timeout, and recovery cases.

Do not place execution scripts here.
