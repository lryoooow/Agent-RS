"""核心配置默认值守门（settings.py）。

只断言 model_fields 上的代码默认值，不调用 get_settings()——后者会被本地 .env 覆盖，
测的就不是"代码默认值"了（见记忆 settings-default-test-via-model-fields）。
"""
from __future__ import annotations

from app.core.settings import Settings


def test_thinking_budget_default_is_low() -> None:
    # 本轮性能修复：思考预算 512→128。512 会让"组织回复"阶段先吐一大段被丢弃的思考
    # token 再出正文，造成可见的空转死区。锁死默认值，防止无意中回弹。
    assert Settings.model_fields["ai_thinking_budget"].default == 128


def test_output_format_module_is_required_in_default_profile() -> None:
    # 决策："提示词一个都不能漏"——output_format 改为常驻，必须在默认 profile 元组里。
    from app.agent.prompting.selector import DEFAULT_PROMPT_PROFILE, PROMPT_PROFILES

    assert "output_format_v1" in PROMPT_PROFILES[DEFAULT_PROMPT_PROFILE]
