from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import require_authenticated_user
from app.agent.ontology.catalog import build_catalog, make_overlay, merge_custom, to_playground
from app.agent.ontology.models import OntologySchema
from app.agent.ontology.storage import OntologyConflict, OntologyStorageUnavailable, read_overlay, save_overlay

router = APIRouter(prefix="/ontology", tags=["ontology"])


class SaveDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: OntologySchema = Field(alias="schema")
    version: int = Field(ge=0)
    catalog_revision: str = Field(min_length=1, max_length=64)


async def _document(user_id: str):
    base, tools, revision = await asyncio.to_thread(build_catalog)
    try:
        overlay, version, writable = await read_overlay(user_id)
    except OntologyStorageUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    try:
        schema = merge_custom(base, overlay)
    except ValueError as exc:
        raise HTTPException(409, "个人定义与当前代码存在引用冲突，请检查保存的定义。") from exc
    return {"schema": schema.model_dump(), "version": version, "catalog_revision": revision,
        "tools": tools, "writable": writable}


@router.get("")
async def get_definition(user_id: str = Depends(require_authenticated_user)):
    return await _document(user_id)


@router.post("")
async def save_definition(body: SaveDefinition, user_id: str = Depends(require_authenticated_user)):
    if len(body.model_dump_json()) > 500_000:
        raise HTTPException(413, "图谱定义不能超过 500 KB。")
    base, _, revision = await asyncio.to_thread(build_catalog)
    if revision != body.catalog_revision:
        raise HTTPException(409, "代码定义已变化，请先同步代码，再保存编辑。")
    try:
        overlay = make_overlay(base, body.definition)
        version = await save_overlay(user_id, overlay, body.version)
    except OntologyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except OntologyStorageUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version": version, "catalog_revision": revision}


@router.get("/export")
async def export_definition(user_id: str = Depends(require_authenticated_user)):
    data = await _document(user_id)
    return to_playground(OntologySchema.model_validate(data["schema"]))
