from __future__ import annotations

import hashlib
import hmac
import secrets

# 邀请码字符集：去掉易混字符（0/O、1/I/L），便于用户口头/手抄转录。
# 32 个字符 ≈ 每字符 5 bit；12 个字符 ≈ 60 bit 熵，足以抵御码空间枚举（配合管理签发为有限张）。
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 31 个，剔除 0O1IL
_GROUPS = 3
_GROUP_LEN = 4
_PREFIX = "RS"


def generate_invite_code() -> str:
    """生成高熵邀请码，形如 RS-XXXX-XXXX-XXXX（分组便于阅读/转录）。

    secrets.choice 为密码学安全随机；前缀 RS 仅作品牌标识，不参与校验/哈希
    （canonicalize 会连前缀一起规范化，所以哈希对前缀大小写不敏感）。
    """
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN))
        for _ in range(_GROUPS)
    ]
    return f"{_PREFIX}-" + "-".join(groups)


def canonicalize_invite_code(code: str) -> str:
    """规范化用户输入的邀请码，消除转录差异后再哈希/比对。

    - 去首尾空白、转大写：用户可能小写或带空格输入。
    - 去除连字符与内部空格：用户可能漏写/多写分隔符。
    这样 'rs7k2m9xqpab'、'RS-7K2M-9XQP-AB' 归一到同一规范形，哈希一致。
    """
    return code.strip().upper().replace("-", "").replace(" ", "")


def hash_invite_code(code: str, secret_key: str) -> str:
    """对规范化后的邀请码做 HMAC-SHA256（复用 auth_secret_key），与会话令牌同范式。

    存哈希而非明文：DB 泄露也无法反推可用码；明文仅在管理员创建时返回一次。
    """
    canonical = canonicalize_invite_code(code)
    return hmac.new(
        secret_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
