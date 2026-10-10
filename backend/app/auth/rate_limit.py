from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from app.core.settings import Settings


@dataclass
class _FailureState:
    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0
    lockout_count: int = 0
    last_seen: float = 0.0


@dataclass
class _WindowState:
    attempts: deque[float] = field(default_factory=deque)
    last_seen: float = 0.0


class AuthRateLimiter:
    """Bound PBKDF2 work and account guessing for the single-process deployment.

    Login attempts are capped per client address, while failed credentials also
    lock the normalized account key. Registration has its own longer IP window.
    State contains no passwords or tokens and expires automatically.
    """

    def __init__(
        self,
        *,
        max_failures: int,
        failure_window_seconds: int,
        lockout_seconds: int,
        login_ip_max_attempts: int,
        login_ip_window_seconds: int,
        register_ip_max_attempts: int,
        register_ip_window_seconds: int,
        max_entries: int,
    ) -> None:
        self.max_failures = max(1, max_failures)
        self.failure_window_seconds = max(1, failure_window_seconds)
        self.lockout_seconds = max(1, lockout_seconds)
        self.login_ip_max_attempts = max(1, login_ip_max_attempts)
        self.login_ip_window_seconds = max(1, login_ip_window_seconds)
        self.register_ip_max_attempts = max(1, register_ip_max_attempts)
        self.register_ip_window_seconds = max(1, register_ip_window_seconds)
        self.max_entries = max(128, max_entries)
        self._account_failures: dict[str, _FailureState] = {}
        self._login_ip_windows: dict[str, _WindowState] = {}
        self._register_ip_windows: dict[str, _WindowState] = {}
        self._lock = Lock()

    async def check_login(self, *, account_key: str, client_key: str) -> int | None:
        """Register an attempt and return Retry-After seconds when blocked."""
        now = time.monotonic()
        with self._lock:
            self._compact(now)
            account = self._account_failures.get(account_key)
            if account is not None:
                account.last_seen = now
                if account.locked_until > now:
                    return _retry_after(account.locked_until - now)
            ip_retry = self._record_window(
                self._login_ip_windows,
                client_key,
                now=now,
                limit=self.login_ip_max_attempts,
                window_seconds=self.login_ip_window_seconds,
            )
            return ip_retry

    async def record_login_failure(self, *, account_key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            state = self._account_failures.setdefault(account_key, _FailureState())
            state.last_seen = now
            _prune(state.failures, now - self.failure_window_seconds)
            state.failures.append(now)
            if len(state.failures) < self.max_failures:
                return None
            state.lockout_count = min(state.lockout_count + 1, 4)
            duration = self.lockout_seconds * (2 ** (state.lockout_count - 1))
            state.locked_until = now + duration
            state.failures.clear()
            return duration

    async def record_login_success(self, *, account_key: str) -> None:
        with self._lock:
            self._account_failures.pop(account_key, None)

    async def check_register(self, *, client_key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            self._compact(now)
            return self._record_window(
                self._register_ip_windows,
                client_key,
                now=now,
                limit=self.register_ip_max_attempts,
                window_seconds=self.register_ip_window_seconds,
            )

    def _record_window(
        self,
        store: dict[str, _WindowState],
        key: str,
        *,
        now: float,
        limit: int,
        window_seconds: int,
    ) -> int | None:
        state = store.setdefault(key, _WindowState())
        state.last_seen = now
        _prune(state.attempts, now - window_seconds)
        if len(state.attempts) >= limit:
            return _retry_after(state.attempts[0] + window_seconds - now)
        state.attempts.append(now)
        return None

    def _compact(self, now: float) -> None:
        if (
            len(self._account_failures)
            + len(self._login_ip_windows)
            + len(self._register_ip_windows)
            <= self.max_entries
        ):
            return
        account_cutoff = now - max(self.failure_window_seconds, self.lockout_seconds * 8)
        self._account_failures = {
            key: value
            for key, value in self._account_failures.items()
            if value.last_seen >= account_cutoff or value.locked_until > now
        }
        self._trim_windows(self._login_ip_windows, now - self.login_ip_window_seconds)
        self._trim_windows(self._register_ip_windows, now - self.register_ip_window_seconds)
        total = (
            len(self._account_failures)
            + len(self._login_ip_windows)
            + len(self._register_ip_windows)
        )
        if total <= self.max_entries:
            return
        candidates: list[tuple[float, str, str]] = []
        candidates.extend((v.last_seen, "account", k) for k, v in self._account_failures.items())
        candidates.extend((v.last_seen, "login", k) for k, v in self._login_ip_windows.items())
        candidates.extend((v.last_seen, "register", k) for k, v in self._register_ip_windows.items())
        for _, kind, key in sorted(candidates)[: total - self.max_entries]:
            target = {
                "account": self._account_failures,
                "login": self._login_ip_windows,
                "register": self._register_ip_windows,
            }[kind]
            target.pop(key, None)

    @staticmethod
    def _trim_windows(store: dict[str, _WindowState], cutoff: float) -> None:
        stale = [key for key, value in store.items() if value.last_seen < cutoff]
        for key in stale:
            store.pop(key, None)


def _prune(values: deque[float], cutoff: float) -> None:
    while values and values[0] <= cutoff:
        values.popleft()


def _retry_after(seconds: float) -> int:
    return max(1, math.ceil(seconds))


_rate_limiters: dict[tuple[int, ...], AuthRateLimiter] = {}
_rate_limiters_lock = Lock()


def get_auth_rate_limiter(settings: Settings) -> AuthRateLimiter:
    key = (
        settings.auth_login_max_failures,
        settings.auth_login_failure_window_seconds,
        settings.auth_login_lockout_seconds,
        settings.auth_login_ip_max_attempts,
        settings.auth_login_ip_window_seconds,
        settings.auth_register_ip_max_attempts,
        settings.auth_register_ip_window_seconds,
        settings.auth_rate_limit_max_entries,
    )
    with _rate_limiters_lock:
        limiter = _rate_limiters.get(key)
        if limiter is None:
            limiter = AuthRateLimiter(
                max_failures=key[0],
                failure_window_seconds=key[1],
                lockout_seconds=key[2],
                login_ip_max_attempts=key[3],
                login_ip_window_seconds=key[4],
                register_ip_max_attempts=key[5],
                register_ip_window_seconds=key[6],
                max_entries=key[7],
            )
            _rate_limiters[key] = limiter
        return limiter


def reset_auth_rate_limiters() -> None:
    """Test helper and lifecycle hook for deterministic process state."""
    with _rate_limiters_lock:
        _rate_limiters.clear()
