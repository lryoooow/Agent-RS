"""管理 bootstrap CLI：直连 DB 铸第一张邀请码，解决"首个管理员"鸡生蛋问题。

背景：注册需邀请码、签发邀请码需管理员、管理员需先注册——闭环死锁。
本脚本绕过 HTTP 层直接写库铸码：管理员用它拿到首张码 → 用 admin_emails 内的邮箱注册
（注册接口自动识别其为管理员）→ 之后都用管理界面签发。也作为 UI 失效时的兜底。

用法（在 backend/ 下）：
  python -m scripts.admin_bootstrap mint-invite [--label 备注] [--expires-days N] [--max-uses N]
  python -m scripts.admin_bootstrap list-invites

需 DATABASE_ENABLED=true 且 DATABASE_URL/AUTH_SECRET_KEY 已配置（读 backend/.env）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.auth.invites import generate_invite_code, hash_invite_code  # noqa: E402
from app.db.pool import close_db_pool, get_db_pool, init_db_pool  # noqa: E402
from app.db.repositories.identity import ensure_default_identity  # noqa: E402
from app.db.repositories.invite import create_invite, list_invites  # noqa: E402
from app.core.settings import get_settings  # noqa: E402


async def _get_pool():
    await init_db_pool()
    pool = await get_db_pool()
    if pool is None:
        raise SystemExit(
            "数据库未启用或 DATABASE_URL 未配置。请在 backend/.env 设 DATABASE_ENABLED=true 与 DATABASE_URL。"
        )
    return pool


async def mint_invite(*, label: str, expires_days: int | None, max_uses: int) -> None:
    settings = get_settings()
    if not settings.auth_secret_key or settings.auth_secret_key == "dev-change-me":
        raise SystemExit("AUTH_SECRET_KEY 未配置或仍是默认值；铸码前请先设置一个强密钥。")
    from datetime import datetime, timedelta, timezone

    pool = await _get_pool()
    try:
        code = generate_invite_code()
        code_hash = hash_invite_code(code, settings.auth_secret_key)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=expires_days) if expires_days else None
        )
        async with pool.acquire() as conn:
            # 确保默认身份存在：created_by 引用 users(id)，用默认用户作为 bootstrap 签发者。
            await ensure_default_identity(conn, settings)
            await create_invite(
                conn,
                code_hash=code_hash,
                created_by_user_id=settings.default_user_id,
                label=label or "bootstrap",
                expires_at=expires_at,
                max_uses=max_uses,
            )
        print("邀请码已生成（仅显示这一次，请立即保存）：")
        print(f"  {code}")
        print(f"  备注: {label or 'bootstrap'} | 可用次数: {max_uses} | 过期: {expires_at or '永不'}")
        print("\n下一步：用 ADMIN_EMAILS 中的邮箱 + 此邀请码注册，即成为管理员。")
    finally:
        await close_db_pool()


async def show_invites() -> None:
    pool = await _get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await list_invites(conn, limit=100)
        if not rows:
            print("（暂无邀请）")
            return
        for row in rows:
            print(
                f"{row['id']} | 备注={row['label'] or '-'} | "
                f"用量={row['used_count']}/{row['max_uses']} | "
                f"撤销={row['revoked']} | 过期={row['expires_at'] or '永不'}"
            )
    finally:
        await close_db_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent-RS 管理 bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint-invite", help="铸一张邀请码")
    mint.add_argument("--label", default="", help="备注（发给谁/用途）")
    mint.add_argument("--expires-days", type=int, default=None, help="多少天后过期（默认永不）")
    mint.add_argument("--max-uses", type=int, default=1, help="可用次数（默认 1）")

    sub.add_parser("list-invites", help="列出邀请")

    args = parser.parse_args()
    if args.command == "mint-invite":
        asyncio.run(
            mint_invite(label=args.label, expires_days=args.expires_days, max_uses=args.max_uses)
        )
    elif args.command == "list-invites":
        asyncio.run(show_invites())


if __name__ == "__main__":
    main()
