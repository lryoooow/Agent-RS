"""Routes expected by the vendored SatVis GP loader."""
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from app.services.satellite_catalog import GROUPS, get_catalog

router = APIRouter(tags=["satellites"])


@router.get("/groups.json")
async def satellite_groups():
    catalog = get_catalog()
    await catalog.ready()
    return JSONResponse(catalog.status(), headers={"Cache-Control": "private, no-store"})


@router.get("/gp/{name}.json")
async def satellite_group(name: str):
    if name not in GROUPS:
        raise HTTPException(status_code=404, detail="未知卫星分组")
    catalog = get_catalog()
    await catalog.ready()
    return Response(catalog.payloads[name], media_type="application/json", headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=300"})
