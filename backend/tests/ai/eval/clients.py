from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.agent.llm_planner import _extract_text


class RecordingError(RuntimeError):
    pass


class MissingRecordingError(RecordingError):
    pass


class StaleRecordingError(RecordingError):
    pass


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordingContext:
    case_id: str
    key: str
    scope: str
    query_hash: str
    context_hash: str
    prompt_hash: str
    model: str


def recording_path(recordings_dir: Path, context: RecordingContext) -> Path:
    return recordings_dir / f"{context.case_id}.json"


def load_recording(recordings_dir: Path, context: RecordingContext) -> dict[str, Any]:
    path = recording_path(recordings_dir, context)
    if not path.exists():
        raise MissingRecordingError(f"Missing planner recording for {context.case_id}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _assert_recording_fresh(payload, context, path)
    return payload


def write_recording(
    recordings_dir: Path,
    context: RecordingContext,
    *,
    raw_texts: list[str],
    source: str,
) -> Path:
    recordings_dir.mkdir(parents=True, exist_ok=True)
    path = recording_path(recordings_dir, context)
    payload = {
        "case_id": context.case_id,
        "key": context.key,
        "scope": context.scope,
        "query_hash": context.query_hash,
        "context_hash": context.context_hash,
        "prompt_hash": context.prompt_hash,
        "model": context.model,
        "recorded_at": datetime.now(UTC).isoformat(),
        "source": source,
        "raw_texts": raw_texts,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _assert_recording_fresh(payload: dict[str, Any], context: RecordingContext, path: Path) -> None:
    expected = {
        "key": context.key,
        "context_hash": context.context_hash,
        "prompt_hash": context.prompt_hash,
        "model": context.model,
    }
    mismatches = {
        name: {"expected": expected_value, "actual": payload.get(name)}
        for name, expected_value in expected.items()
        if payload.get(name) != expected_value
    }
    if mismatches:
        raise StaleRecordingError(f"Stale planner recording for {context.case_id}: {path}; {mismatches}")
    raw_texts = payload.get("raw_texts")
    if not isinstance(raw_texts, list) or not all(isinstance(item, str) for item in raw_texts):
        raise StaleRecordingError(f"Planner recording has no raw_texts list: {path}")


def _response_from_text(text: str) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ReplayClient:
    def __init__(self, recordings_dir: Path, context: RecordingContext) -> None:
        payload = load_recording(recordings_dir, context)
        self._raw_texts = list(payload["raw_texts"])
        self._context = context
        self._calls = 0
        self.chat = SimpleNamespace(completions=_ReplayCompletions(self))

    @property
    def calls(self) -> int:
        return self._calls

    def _next_response(self, kwargs: dict[str, Any]) -> Any:
        if self._calls == 0:
            self._assert_first_call_matches_context(kwargs)
        if self._calls >= len(self._raw_texts):
            raise MissingRecordingError(
                f"Recording for {self._context.case_id} has no response #{self._calls + 1}"
            )
        text = self._raw_texts[self._calls]
        self._calls += 1
        return _response_from_text(text)

    def _assert_first_call_matches_context(self, kwargs: dict[str, Any]) -> None:
        model = kwargs.get("model")
        if model != self._context.model:
            raise StaleRecordingError(
                f"Recording model mismatch for {self._context.case_id}: "
                f"expected {self._context.model}, got {model}"
            )
        messages = kwargs.get("messages") or []
        prompt = messages[0].get("content") if messages and isinstance(messages[0], dict) else ""
        prompt_hash = stable_hash(prompt)
        if prompt_hash != self._context.prompt_hash:
            raise StaleRecordingError(
                f"Recording prompt mismatch for {self._context.case_id}: "
                f"expected {self._context.prompt_hash}, got {prompt_hash}"
            )


class _ReplayCompletions:
    def __init__(self, owner: ReplayClient) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        return self._owner._next_response(kwargs)


class LiveRecordingClient:
    def __init__(self, base_client: Any, recordings_dir: Path, context: RecordingContext) -> None:
        self._base_client = base_client
        self._recordings_dir = recordings_dir
        self._context = context
        self._raw_texts: list[str] = []
        self.chat = SimpleNamespace(completions=_LiveRecordingCompletions(self))

    async def _create(self, **kwargs):
        response = await self._base_client.chat.completions.create(**kwargs)
        self._raw_texts.append(_extract_text(response))
        write_recording(
            self._recordings_dir,
            self._context,
            raw_texts=self._raw_texts,
            source="live",
        )
        return response


class _LiveRecordingCompletions:
    def __init__(self, owner: LiveRecordingClient) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        return await self._owner._create(**kwargs)
