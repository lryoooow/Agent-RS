# Project Test Assets

This directory stores product-level test assets for the chatbot project.

Keep code-level backend tests in `backend/tests/`. Use this directory for reusable
datasets, fixtures, evaluation definitions, end-to-end scenarios, performance
checks, and generated reports.

## Directory Boundaries

- `datasets/`: Versioned JSONL test data. Do not place runners or scripts here.
- `fixtures/`: Reusable documents, conversations, and provider mock payloads.
- `evals/`: Evaluation schemas, rules, and future evaluation runners.
- `e2e/`: Browser or full-stack workflow scenarios.
- `performance/`: Load, latency, concurrency, and streaming performance checks.
- `reports/`: Generated test reports. Keep this directory clean and avoid mixing
  report output with source-controlled datasets.

## Current Rule

This initial structure only defines boundaries. Real test data should be added in
small, reviewed batches after the case schema is stable.
