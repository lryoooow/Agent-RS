"""Trusted, request-scoped facts. No entity facts are parsed from model prose."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .catalog import build_catalog, load_schema, merge_custom
from .router import OntologyRouter
from .storage import read_overlay, OntologyStorageUnavailable

logger = logging.getLogger(__name__)
_current: ContextVar[OntologySession | None] = ContextVar("ontology_session", default=None)
RESULT_TYPES = {"raster_inspect": "raster_profile", "instance_segmentation": "land_cover_result",
    "detection": "object_detection_result", "clip_reproject": "derived_raster"}
REPORTABLE = {"raster_inspect", "instance_segmentation", "segmentation", "detection", "ndvi", "spectral_index", "water_mask", "cloud_mask", "composite", "ocr", "clip_reproject"}


def image_fact(identifier: str, metadata: dict) -> dict:
    roles = metadata.get("band_roles") or {}
    alpha = metadata.get("alpha_bands") or []
    count = metadata.get("band_count")
    # Only complete explicit role coverage establishes missing spectral capabilities.
    complete = isinstance(count, int) and count > 0 and len(set(roles.values()) | set(alpha)) == count
    fact = {**metadata, "id": identifier, "imagery_id": identifier, "entity_type": "imagery", "roles_complete": complete}
    if "quality_mask" in metadata:
        fact["quality_available"] = bool(metadata.get("quality_mask"))
    return fact


@dataclass
class OntologySession:
    router: OntologyRouter
    request: dict = field(default_factory=dict)
    entities: list[dict] = field(default_factory=list)
    user_id: str | None = None
    notify_observers: Callable[[], Awaitable[None]] | None = field(default=None, repr=False, compare=False)

    def refresh_scenes(self):
        from app.agent.stac_search.cache import get_scene
        for entity in self.entities:
            if entity["entity_type"] == "satellite_scene":
                entity["cached"] = get_scene(self.user_id, entity.get("key", "")) is not None

    def add(self, fact: dict):
        key = (fact["entity_type"], fact["id"])
        self.entities = [e for e in self.entities if (e["entity_type"], e["id"]) != key] + [fact]

    def observe(self, name: str, result):
        if result.error:
            return
        for value in (result.geospatial_result, result.tool_result):
            payload = value.model_dump(exclude_none=True) if hasattr(value, "model_dump") else value
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            identifier = payload.get("imagery_id")
            if kind == "scene_search":
                for scene in payload.get("scenes", []):
                    if isinstance(scene, dict) and isinstance(scene.get("key"), str):
                        self.add({**scene, "id": scene["key"], "entity_type": "satellite_scene", "cached": False})
                self.refresh_scenes()
            elif kind == "preview" and identifier and name in {"fetch_scene", "prepare_map_roi"}:
                meta = {"band_roles": result.metadata.get("band_roles") or {}}
                if name == "prepare_map_roi":
                    meta.update(band_count=4, alpha_bands=[4], quality_mask=None)
                self.add(image_fact(identifier, meta))
                self.request["active_imagery_id"] = identifier
            elif kind == "report" and payload.get("download_url"):
                self.add({**payload, "id": payload["download_url"], "entity_type": "report"})
            elif kind in REPORTABLE and identifier:
                self.add({**payload, "id": f"{identifier}:{kind}", "entity_type": RESULT_TYPES.get(kind, "analysis_result"), "reportable": True})
                if kind == "raster_inspect":
                    previous = next((e for e in self.entities if e["entity_type"] == "imagery" and e["id"] == identifier), {})
                    self.add(image_fact(identifier, {**previous, **(result.metadata.get("inspect") or {}), **payload}))
        if name == "parse_document" and result.metadata.get("document_id"):
            self.add({**result.metadata, "id": result.metadata["document_id"], "entity_type": "document_text"})
        elif name == "look_at_location" and result.metadata.get("map_target"):
            self.add({**result.metadata["map_target"], "id": f"location:{result.query}",
                "entity_type": "map_location", "display_name": result.metadata.get("display_name")})
        elif name == "web_search" and result.result_count > 0:
            self.add({"id": f"search:{len(self.entities)}", "entity_type": "search_evidence",
                "query": result.query, "result_count": result.result_count})
        if name != "history":
            self.add({"id": f"execution:{name}:{len(self.entities)}", "entity_type": "tool_execution", "tool_name": name, "status": "complete"})

    def reject(self, tool_name: str, arguments: dict) -> str | None:
        self.refresh_scenes()
        bindings = [a for a in self.router.schema.bindings.action_bindings if a.tool_name == tool_name]
        identity = arguments.get("imagery_id") or arguments.get("document_id") or arguments.get("scene_key")
        # Personal topology cannot move a built-in requirement onto an unrelated entity.
        baseline = OntologyRouter(self.router.baseline)
        for binding in baseline.schema.bindings.action_bindings:
            if binding.tool_name != tool_name:
                continue
            source = baseline.relations[binding.relationship_id].source_entity
            facts = [e for e in self.entities if baseline.is_type(e["entity_type"], source)
                and (not identity or e["id"] == identity or e.get("imagery_id") == identity)]
            routes = [baseline.evaluate(binding, e, self.request, arguments) for e in facts]
            if routes and all(r.status == "blocked" for r in routes):
                return "；".join(dict.fromkeys(reason for r in routes for reason in r.reasons))
        routes = []
        for binding in bindings:
            relation = self.router.relations[binding.relationship_id]
            candidates = [e for e in self.entities if self.router.is_type(e["entity_type"], relation.source_entity)
                and (not identity or e["id"] == identity or e.get("imagery_id") == identity)]
            # No local snapshot is not proof of denial. The unchanged access guard checks it.
            if not candidates:
                continue
            routes.extend(self.router.evaluate(binding, e, self.request, arguments) for e in candidates)
        if routes and all(r.status == "blocked" for r in routes):
            return "；".join(dict.fromkeys(reason for r in routes for reason in r.reasons))
        return None

    def context(self, enabled: set[str]):
        self.refresh_scenes()
        active = self.request.get("active_imagery_id")
        ordered = sorted(self.entities, key=lambda e: (e.get("imagery_id") != active, e["entity_type"] != "request"))
        return self.router.context(ordered, self.request, enabled)


async def create_session(request, user_id: str | None) -> OntologySession | None:
    from app.core.settings import get_settings
    if not get_settings().ontology_enabled:
        return None
    from app.agent.imagery_access import iter_user_imagery_metadata
    from app.agent.stac_search.cache import get_scene
    from app.db.pool import fetch_optional_pool
    from app.db.repositories.conversation import get_conversation
    from app.db.repositories.document import list_documents
    from app.db.repositories.message import list_recent_analysis_results
    from app.agent.types import ToolRunResult

    base, _, _ = await asyncio.to_thread(build_catalog, discover=False)
    overlay = {}
    if user_id:
        try:
            overlay, _, _ = await read_overlay(user_id)
        except OntologyStorageUnavailable:
            # Preserve existing tools if the optional personal editor store is offline.
            logger.warning("Personal ontology unavailable; using platform definitions")
    try:
        schema = merge_custom(base, overlay)
    except ValueError:
        logger.warning("Personal ontology references changed; using platform definitions")
        schema = base
    session = OntologySession(OntologyRouter(schema, mandatory=load_schema()),
        {"active_imagery_id": (request.metadata or {}).get("active_imagery_id"), "conversation_id": request.conversation_id},
        user_id=user_id)
    session.add({"id": "current_request", "entity_type": "request"})
    if request.analysis_roi:
        session.add({"id": "current_region", "entity_type": "region", **request.analysis_roi.model_dump(exclude_none=True)})
    for identifier, meta in await iter_user_imagery_metadata(user_id):
        session.add(image_fact(identifier, meta))
    for message in request.messages[-2:]:
        for key in re.findall(r"\b[a-f0-9]{12}\b", message.content):
            record = get_scene(user_id, key)
            if record:
                session.add({"id": key, "key": key, "entity_type": "satellite_scene", "cached": True})
    pool = await fetch_optional_pool()
    if pool and user_id:
        try:
            async with pool.acquire() as conn:
                for doc in await list_documents(conn, user_id=user_id):
                    session.add({"id": str(doc["id"]), "entity_type": "document"})
                if request.conversation_id and await get_conversation(conn, request.conversation_id, user_id):
                    session.add({"id": request.conversation_id, "entity_type": "conversation", "user_id": user_id})
                    for entry in await list_recent_analysis_results(conn, conversation_id=request.conversation_id, user_id=user_id, limit=20):
                        session.observe("history", ToolRunResult(tool_context="", geospatial_result=entry.get("geospatial_result"), tool_result=entry.get("tool_result")))
        except Exception:
            logger.warning("Ontology history unavailable; runtime resource checks remain active")
    return session


def current_session() -> OntologySession | None:
    return _current.get()


@contextmanager
def ontology_scope(session: OntologySession | None):
    previous = _current.get()
    _current.set(session)
    try:
        yield session
    finally:
        _current.set(previous)
