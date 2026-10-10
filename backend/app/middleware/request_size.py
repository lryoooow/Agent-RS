from __future__ import annotations

import json
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.settings import Settings

_DOCUMENT_UPLOAD_PATH = "/api/documents/upload"
_IMAGERY_UPLOAD_PATH = "/api/imagery/upload"


class RequestBodyTooLarge(Exception):
    """Raised internally when streamed request bytes exceed the selected limit."""


def request_body_limit(scope: Scope, settings: Settings) -> int:
    """Return the raw HTTP body limit for the current route.

    Multipart framing is counted by the transport middleware. The upload route
    still enforces the exact file-byte limit while streaming the individual file.
    """

    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    content_type = headers.get("content-type", "").lower()
    if "multipart/form-data" not in content_type:
        return settings.max_json_body_bytes

    path = str(scope.get("path") or "")
    if path == _DOCUMENT_UPLOAD_PATH:
        file_limit = settings.document_max_file_bytes
    elif path == _IMAGERY_UPLOAD_PATH:
        file_limit = settings.imagery_max_file_bytes
    else:
        file_limit = settings.max_json_body_bytes
    return file_limit + settings.max_multipart_overhead_bytes


class RequestBodyLimitMiddleware:
    """Enforce actual received bytes, including chunked or undeclared bodies."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = request_body_limit(scope, self.settings)
        content_length = _content_length(scope)
        if content_length is not None and content_length > limit:
            await _send_too_large(send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await _send_too_large(send)


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() != b"content-length":
            continue
        try:
            parsed = int(value.decode("latin-1"))
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


async def _send_too_large(send: Send) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "REQUEST_TOO_LARGE",
                "message": "Request body is too large.",
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": body})
