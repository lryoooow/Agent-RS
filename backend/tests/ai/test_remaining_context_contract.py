from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from app.agent.context.assembler import assemble_context
from app.agent.context.budget import estimate_tokens
from app.agent.errors import ContextBudgetError
from app.agent.persistence import PersistenceContext, schedule_after_response, drain_persistence_tasks
from app.core.settings import Settings, get_settings
from app.schemas.chat import ChatMessage


@pytest.mark.parametrize("budget",[250,500,950,1500])
def test_final_history_partition_has_no_unrecorded_gap(budget):
    messages=[ChatMessage(role="user" if i%2==0 else "assistant",content=f"HISTORY_STEP_{i:02d} "+"x"*60) for i in range(8)]
    result=assemble_context(system_prompt="base",messages=messages,tool_context="tool "*40,
        max_total_chars=budget,max_recent_chars=200,max_recent_messages=6,max_summary_chars=200,auto_history_summary=True)
    coverage=result.history_coverage
    covered=set(coverage["summary_indices"])
    omitted=set(coverage["omitted_indices"])
    recent=set(range(coverage["recent_start"],coverage["loaded_count"]))
    assert covered|omitted|recent==set(range(8))
    assert not covered&omitted and not covered&recent and not omitted&recent
    assert result.messages[-1]["content"]==messages[-1].content
    assert result.used_chars<=budget
    text="\n".join(row["content"] for row in result.messages)
    for i in covered|recent: assert f"HISTORY_STEP_{i:02d}" in text


def test_latest_request_is_never_silently_shortened_by_optional_evidence():
    question="最新问题"*200
    result=assemble_context(system_prompt="base",messages=[ChatMessage(role="user",content=question)],
        tool_context="tool "*1000,max_total_chars=3000,max_recent_chars=10,max_summary_chars=100,auto_history_summary=True)
    assert result.messages[-1]["content"]==question
    with pytest.raises(ContextBudgetError):
        assemble_context(system_prompt="base",messages=[ChatMessage(role="user",content=question)],
            max_total_chars=20,auto_history_summary=True)


@pytest.mark.parametrize("value",["2026-02-30","20260101","bad","2026-1-01"])
def test_invalid_date_rejected_in_settings_before_provider_calls(value):
    with pytest.raises(ValidationError): Settings(_env_file=None,agent_as_of_date=value)


def test_date_override_uses_validated_process_snapshot(monkeypatch):
    from app.agent.prompting.renderer import _as_of_date
    monkeypatch.setenv("AGENT_AS_OF_DATE","2024-02-29"); get_settings.cache_clear()
    assert _as_of_date().isoformat()=="2024-02-29"
    monkeypatch.setenv("AGENT_AS_OF_DATE","bad")
    assert _as_of_date().isoformat()=="2024-02-29"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_memory_off_skips_judging_without_losing_normal_message_embedding(monkeypatch):
    import app.agent.persistence as module
    embed=AsyncMock(); store=AsyncMock()
    monkeypatch.setattr(module,"_embed_messages",embed)
    monkeypatch.setattr(module,"maybe_store_memory",store)
    context=PersistenceContext(user_id="a",conversation_id="c",user_message_id="u",assistant_message_id="s",user_content="hello",use_memory=False)
    schedule_after_response(context,assistant_content="answer")
    await drain_persistence_tasks()
    embed.assert_awaited_once(); store.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_background_keeps_original_owner_and_switch(monkeypatch):
    import app.agent.persistence as module
    store=AsyncMock(); monkeypatch.setattr(module,"maybe_store_memory",store)
    monkeypatch.setattr(module,"_embed_messages",AsyncMock())
    schedule_after_response(PersistenceContext(user_id="a",conversation_id="ca",assistant_message_id="sa",use_memory=True),assistant_content="a")
    schedule_after_response(PersistenceContext(user_id="b",conversation_id="cb",assistant_message_id="sb",use_memory=False),assistant_content="b")
    await drain_persistence_tasks()
    store.assert_awaited_once(); assert store.await_args.kwargs["user_id"]=="a"


@pytest.mark.parametrize("value",["producton","other",""])
def test_invalid_deployment_environment_cannot_bypass_production_checks(value):
    with pytest.raises(ValidationError): Settings(_env_file=None,deployment_environment=value)
    assert Settings(_env_file=None,deployment_environment=" Production ").deployment_environment=="production"


def test_client_system_boundary_is_counted_once_in_final_partition():
    from app.agent.context.history import CLIENT_SYSTEM_PREFIX
    messages=[ChatMessage(role="system",content="HISTORY "+"x"*100),ChatMessage(role="system",content="CURRENT "+"x"*150)]
    result=assemble_context(system_prompt="base",messages=messages,max_total_chars=300,
        max_recent_chars=300,max_recent_messages=4,max_summary_chars=30,auto_history_summary=True)
    assert result.used_chars<=300
    assert result.messages[-1]["content"]==CLIENT_SYSTEM_PREFIX+"\n\n"+messages[-1].content
    assert result.messages[-1]["content"].count(CLIENT_SYSTEM_PREFIX)==1
