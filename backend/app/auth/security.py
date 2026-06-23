from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import secrets

# PBKDF2-HMAC-SHA256 工作因子。对齐 OWASP 2025 Password Storage 基线（600k）。
# 旧库可能存在 210k 的哈希：verify 读哈希内嵌的迭代数，旧哈希照常验证通过；
# 登录成功时若 needs_rehash 为真，调用方用本常量重哈希落库，实现透明升级（见 routes/auth.py）。
PASSWORD_ITERATIONS = 600_000


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(_verify_password_sync, password, password_hash)


def needs_rehash(password_hash: str) -> bool:
    """哈希是否低于当前工作因子，需要在下次登录成功时用新参数重哈希。

    只认 pbkdf2_sha256 且迭代数 >= 目标为"无需升级"；格式异常/算法不符/迭代数偏低
    一律判定需要重哈希（保守升级，不会误判把强哈希降级）。
    """
    try:
        algorithm, iterations, _salt, _digest = password_hash.split("$", 3)
    except ValueError:
        return True
    if algorithm != "pbkdf2_sha256":
        return True
    try:
        return int(iterations) < PASSWORD_ITERATIONS
    except (ValueError, TypeError):
        return True


def issue_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_password_sync(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PASSWORD_ITERATIONS,
        salt=base64.b64encode(salt).decode("ascii"),
        digest=base64.b64encode(digest).decode("ascii"),
    )


def _verify_password_sync(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        salt_bytes = base64.b64decode(salt.encode("ascii"))
        expected_bytes = base64.b64decode(expected.encode("ascii"))
        iteration_count = int(iterations)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iteration_count,
    )
    return hmac.compare_digest(actual, expected_bytes)
