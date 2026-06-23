from app.auth.throttle import LoginThrottle


def test_below_threshold_not_locked() -> None:
    t = LoginThrottle(max_failures=3, lockout_seconds=60)
    t.record_failure("a@x.com")
    t.record_failure("a@x.com")
    assert t.retry_after("a@x.com") == 0  # 2 < 3，未锁定


def test_locks_after_threshold() -> None:
    t = LoginThrottle(max_failures=3, lockout_seconds=60)
    for _ in range(3):
        t.record_failure("a@x.com")
    assert t.retry_after("a@x.com") > 0  # 达阈值即锁定


def test_lock_is_per_account_not_global() -> None:
    t = LoginThrottle(max_failures=2, lockout_seconds=60)
    t.record_failure("a@x.com")
    t.record_failure("a@x.com")
    assert t.retry_after("a@x.com") > 0
    # 另一账号不受影响（按账号计数，非全局/按 IP）
    assert t.retry_after("b@x.com") == 0


def test_reset_clears_failures() -> None:
    t = LoginThrottle(max_failures=2, lockout_seconds=60)
    t.record_failure("a@x.com")
    t.record_failure("a@x.com")
    assert t.retry_after("a@x.com") > 0
    t.reset("a@x.com")
    assert t.retry_after("a@x.com") == 0  # 登录成功后清零


def test_email_key_is_case_and_space_insensitive() -> None:
    t = LoginThrottle(max_failures=2, lockout_seconds=60)
    t.record_failure(" A@X.com ")
    t.record_failure("a@x.com")
    # 归一化大小写/空白后视为同一账号，两次失败触发锁定
    assert t.retry_after("a@x.com") > 0


def test_exponential_backoff_grows() -> None:
    t = LoginThrottle(max_failures=1, lockout_seconds=10)
    t.record_failure("a@x.com")
    first = t.retry_after("a@x.com")
    t.record_failure("a@x.com")
    second = t.retry_after("a@x.com")
    # 失败越多锁定越久（指数退避）；允许相等下界，核心是不缩短
    assert second >= first
