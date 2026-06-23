from app.auth.invites import (
    canonicalize_invite_code,
    generate_invite_code,
    hash_invite_code,
)


def test_generated_code_has_expected_shape() -> None:
    code = generate_invite_code()
    assert code.startswith("RS-")
    parts = code.split("-")
    assert len(parts) == 4  # RS + 3 组
    assert all(len(group) == 4 for group in parts[1:])
    # 字符集剔除了易混字符 0/O/1/I/L
    body = "".join(parts[1:])
    assert not (set(body) & set("01OIL"))


def test_generated_codes_are_unique() -> None:
    codes = {generate_invite_code() for _ in range(200)}
    # 60bit 熵，200 个几乎不可能撞；撞了说明随机性出问题。
    assert len(codes) == 200


def test_canonicalize_is_transcription_insensitive() -> None:
    code = "RS-7K2M-9XQP-ABCD"
    assert canonicalize_invite_code(code) == "RS7K2M9XQPABCD"
    # 小写、空格替连字符、首尾空白都归一到同一规范形
    assert canonicalize_invite_code("  rs 7k2m 9xqp abcd ") == canonicalize_invite_code(code)


def test_hash_is_canonical_insensitive_and_secret_dependent() -> None:
    code = generate_invite_code()
    variant = code.lower().replace("-", " ")
    assert hash_invite_code(code, "secret") == hash_invite_code(variant, "secret")
    # 不同密钥 → 不同哈希（HMAC 依赖密钥）
    assert hash_invite_code(code, "secret-a") != hash_invite_code(code, "secret-b")
    # 不同码 → 不同哈希
    assert hash_invite_code(code, "secret") != hash_invite_code(generate_invite_code(), "secret")
