"""按内容特征从 git 历史定位"修复前"的旧版源码，供回归对比使用。

为什么不能用 ``git show HEAD:<path>``：
HEAD 会随着任何一次提交前移。旧版基线一旦锚在 HEAD 上，修复代码一入库，
守卫就会拿"修复后"的版本冒充旧版——要么直接加载失败，要么静默失去对比意义
（2026-10-08 提交阶段 A 修复后，两个守卫就是这样同时变红的）。

定位规则改为按文件的提交历史回溯，用内容特征判断：
``absent`` 中出现的标记在旧版必须不存在，``present`` 中出现的标记必须存在。
找不到符合条件的版本时抛错，绝不退回新版冒充。

另外，git 输出统一按 UTF-8 解码。本机 locale 为 cp950 时，
``subprocess.run(text=True)`` 会因源码里的中文/特殊字符直接抛
UnicodeDecodeError（读线程里抛出后 stdout 退化成 None）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def resolve_old_version_source(
    repo_root: Path,
    path: str,
    *,
    absent: tuple[str, ...] = (),
    present: tuple[str, ...] = (),
) -> tuple[str, str]:
    """沿 ``path`` 的提交历史回溯，返回最近一个符合特征版本的 (commit, 源码)。

    特征由 ``absent``（不得出现的标记）与 ``present``（必须出现的标记）给出。
    """
    if not absent and not present:
        raise ValueError("至少需要一个内容特征，否则无法区分修复前后")

    commits = _run_git(repo_root, "log", "--format=%H", "--", path).split()
    for commit in commits:
        source = _run_git(repo_root, "show", f"{commit}:{path}")
        if all(marker not in source for marker in absent) and all(
            marker in source for marker in present
        ):
            return commit, source
    raise RuntimeError(
        f"git 历史中未找到符合条件的旧版 {path}"
        f"（absent={absent}, present={present}）"
    )
