from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# 进程内登录失败限流：抵御暴力破解/撞库（OWASP A07）。
# 适用范围：单实例 beta。多实例部署需换成共享存储（如 Redis），否则各实例计数独立、可被绕过。
# 计数按"账号（邮箱）"而非来源 IP（OWASP 建议）：IP 易被代理池绕过，且锁 IP 会误伤同网用户。
# 失败达阈值后锁定一个窗口；窗口内再试直接拒（不消耗 PBKDF2，也不泄露账号是否存在）。


@dataclass
class _Entry:
    failures: int = 0
    locked_until: float = 0.0
    window_start: float = 0.0


class LoginThrottle:
    def __init__(self, *, max_failures: int, lockout_seconds: int, window_seconds: int = 900) -> None:
        self._max_failures = max(1, max_failures)
        self._lockout_seconds = max(1, lockout_seconds)
        self._window_seconds = max(1, window_seconds)
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _key(self, email: str) -> str:
        return email.strip().lower()

    def retry_after(self, email: str) -> int:
        """当前是否处于锁定中。返回剩余锁定秒数（>0 表示锁定），0 表示放行。"""
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(self._key(email))
            if entry is None or entry.locked_until <= now:
                return 0
            return int(entry.locked_until - now) + 1

    def record_failure(self, email: str) -> None:
        """记一次登录失败。超过观察窗口则重新计数；达阈值则按失败次数指数退避锁定。"""
        now = time.monotonic()
        with self._lock:
            key = self._key(email)
            entry = self._entries.get(key)
            if entry is None or (now - entry.window_start) > self._window_seconds:
                entry = _Entry(window_start=now)
                self._entries[key] = entry
            entry.failures += 1
            if entry.failures >= self._max_failures:
                # 指数退避：基础锁定 × 2^(超出阈值的次数)，上限 1 小时，避免无限增长。
                over = entry.failures - self._max_failures
                backoff = self._lockout_seconds * (2 ** min(over, 6))
                entry.locked_until = now + min(backoff, 3600)

    def reset(self, email: str) -> None:
        """登录成功后清除该账号的失败记录。"""
        with self._lock:
            self._entries.pop(self._key(email), None)

    def clear(self) -> None:
        """清空全部（测试用）。"""
        with self._lock:
            self._entries.clear()


_throttle: LoginThrottle | None = None


def get_login_throttle() -> LoginThrottle:
    """惰性单例。首次构造时读 settings 的阈值/锁定时长。"""
    global _throttle
    if _throttle is None:
        from app.core.settings import get_settings

        settings = get_settings()
        _throttle = LoginThrottle(
            max_failures=settings.auth_login_max_failures,
            lockout_seconds=settings.auth_login_lockout_seconds,
        )
    return _throttle


def reset_login_throttle() -> None:
    """重置单例（测试用，配合 conftest 的全局缓存重置）。"""
    global _throttle
    _throttle = None
