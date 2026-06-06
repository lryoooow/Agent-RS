from __future__ import annotations

from pydantic import BaseModel

from app.agent.tool_registry import RegisteredTool, get_tool, list_tool_definitions
from app.agent.types import ToolRunResult
from app.core.settings import get_settings


async def _fake_runner(_args: BaseModel) -> ToolRunResult:
    return ToolRunResult(tool_context="ok")


def reset_settings() -> None:
    get_settings.cache_clear()


def _required_fields(model: type[BaseModel]) -> set[str]:
    return {name for name, field in model.model_fields.items() if field.is_required()}


def test_unknown_tool_returns_none() -> None:
    assert get_tool("missing") is None


def test_web_search_is_not_in_tool_registry() -> None:
    definitions = list_tool_definitions(available_only=False)
    names = {item["function"]["name"] for item in definitions}

    assert "web_search" not in names
    assert "calculate_ndvi" in names
    assert "raster_inspect" in names
    assert "calculate_spectral_index" in names
    assert "render_band_composite" in names


def test_registered_tool_enabled_defaults_to_true() -> None:
    class Args(BaseModel):
        value: str

    tool = RegisteredTool(
        name="fake",
        definition={"type": "function"},
        argument_model=Args,
        runner=_fake_runner,
    )

    assert tool.is_enabled() is True


def test_tool_schema_required_fields_match_pydantic_models() -> None:
    for definition in list_tool_definitions(available_only=False):
        tool = get_tool(definition["function"]["name"])
        assert tool is not None
        schema = definition["function"]["parameters"]
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == _required_fields(tool.argument_model)
