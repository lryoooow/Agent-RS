"""长期记忆的结构化取值域。

单独成文件（而不是放在 engine/memory/pg_memory.py）是因为：`memory_judge` 是业务代码，
若从 engine/ 里取常量，会让纯数据库和 schema 模块传递性加载框架依赖。
这里不 import 任何 autogen。

改这里的取值域必须同步改两处：
- `sql/migrations/0011_memory_structured.sql` 的 CHECK 约束
- 本文件的 MEMORY_TYPES

否则模型给出新类型时会撞约束、记忆写入静默失败。
"""

from __future__ import annotations

# fact       客观事实（"这个项目用 GF-2 影像"）
# preference 用户偏好（"回复用中文"）
# constraint 硬性约束（"结论必须标注数据来源与时间"）
# project    项目上下文（"当前在做洪涝灾害评估"）
MEMORY_TYPES: tuple[str, ...] = ("fact", "preference", "constraint", "project")

DEFAULT_MEMORY_TYPE = "fact"
DEFAULT_IMPORTANCE = 0.7
