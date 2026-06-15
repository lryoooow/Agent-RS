# Agent-RS Promptfoo Red Team

This folder is a red-team track for the Agent-RS planner. It does not replace the
heldout/stress evaluation harness. Heldout measures route quality; this track
tries to break safety boundaries.

## Discipline

- Do not aim for all green on the first run.
- Do not change prompts or assertions to hide red-team failures.
- Raw model output stays out of git.
- Hard failures are structural: hallucinated IDs, non-owner bypass, and excessive agency.
- LLM judges may be used for review only, never as the main safety score.

## Local smoke

```powershell
D:\miniconda3\envs\chatbot\python.exe -m pytest tests\redteam -q --basetemp=.tmp_pytest_run_redteam
```

## Static promptfoo run

This path does not depend on promptfoo remote red-team generation. It uses
hand-written adversarial prompts and the same provider/security flags.

```powershell
$env:AGENT_RS_REDTEAM_OBSERVATIONS="backend/tests/redteam/runs/static_observations.jsonl"
npx promptfoo@latest eval -c backend/tests/redteam/redteam_static.yaml
D:\miniconda3\envs\chatbot\python.exe -m tests.redteam.score_redteam_observations backend/tests/redteam/runs/static_observations.jsonl
```

## Generated promptfoo red-team run

Run this only when API cost is acceptable. Source config and generated cases are
kept separate: `-c` reads the hand-written source, `-o` writes generated attack
cases to `runs/` (gitignored) instead of overwriting the source.

```powershell
$env:AGENT_RS_REDTEAM_OBSERVATIONS="backend/tests/redteam/runs/redteam_observations.jsonl"
npx promptfoo@latest redteam run -c backend/tests/redteam/promptfooconfig.yaml -o backend/tests/redteam/runs/redteam_generated.yaml
D:\miniconda3\envs\chatbot\python.exe -m tests.redteam.score_redteam_observations backend/tests/redteam/runs/redteam_observations.jsonl
```

Never pass the source config as `-o`, and never use `generate -w`: that writes
generated cases back into the source and clobbers it.
