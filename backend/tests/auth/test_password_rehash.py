import pytest

from app.auth.security import (
    PASSWORD_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)


@pytest.mark.asyncio
async def test_new_hash_uses_current_iterations() -> None:
    digest = await hash_password("a-strong-passphrase")
    algorithm, iterations, _salt, _h = digest.split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == PASSWORD_ITERATIONS == 600_000
    assert not needs_rehash(digest)


@pytest.mark.asyncio
async def test_legacy_210k_hash_still_verifies_but_needs_rehash() -> None:
    # 旧库可能存 210k 哈希：verify 读内嵌迭代数，仍须验证通过（向后兼容，不能把老用户锁在门外）。
    import base64
    import hashlib

    password = "legacy-user-password"
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    legacy = "pbkdf2_sha256$210000${salt}${digest}".format(
        salt=base64.b64encode(salt).decode(),
        digest=base64.b64encode(digest).decode(),
    )
    assert await verify_password(password, legacy) is True
    assert await verify_password("wrong", legacy) is False
    # 但工作因子偏低，应被标记为需要在下次登录成功时重哈希升级。
    assert needs_rehash(legacy) is True


def test_needs_rehash_edge_cases() -> None:
    assert needs_rehash("pbkdf2_sha256$600000$abc$def") is False
    assert needs_rehash("pbkdf2_sha256$210000$abc$def") is True
    assert needs_rehash("pbkdf2_sha256$notanint$abc$def") is True
    assert needs_rehash("bcrypt$12$abc$def") is True  # 非 pbkdf2 一律重哈希
    assert needs_rehash("garbage") is True  # 格式异常保守判定需重哈希
