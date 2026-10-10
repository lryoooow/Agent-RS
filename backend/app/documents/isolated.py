"""Bounded parser subprocesses; cancellation kills and reaps before deleting input."""
from __future__ import annotations
import asyncio
from contextlib import suppress
import json
import os
import sys
import tempfile
import weakref
from pathlib import Path
from app.documents.parser import DocumentParseError, ParsedDocument

_limits=weakref.WeakKeyDictionary()


async def parse_document_file(*, temp_path, filename, content_type, title, settings):
    loop=asyncio.get_running_loop()
    limit=_limits.setdefault(loop,asyncio.Semaphore(settings.document_parse_max_concurrent))
    async with limit:
        with tempfile.TemporaryDirectory(prefix="agent-rs-doc-") as directory:
            root=Path(directory); request=root/"request.json"; output=root/"result.json"
            fields={key:getattr(settings,key) for key in type(settings).model_fields if key.startswith("document_")}
            request.write_text(json.dumps({"path":str(Path(temp_path).resolve()),"filename":filename,
                "content_type":content_type,"title":title,"settings":fields}),encoding="utf-8")
            env=os.environ.copy()
            # BLAS reserves a large virtual stack per thread. Under RLIMIT_AS,
            # importing NumPy via openpyxl can fail before parsing one cell.
            # Bound native parallelism in this disposable worker only.
            for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                env[key] = "1"
            backend=str(Path(__file__).resolve().parents[2])
            env["PYTHONPATH"]=backend+os.pathsep+env.get("PYTHONPATH","")
            spawn=asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,"-B","-m","app.documents.worker",
                str(request),str(output),env=env,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL))
            process=None
            try:
                process=await asyncio.shield(spawn)
                try:
                    await asyncio.wait_for(process.wait(),settings.document_parse_timeout_seconds)
                except TimeoutError as exc:
                    raise DocumentParseError("DOCUMENT_PARSE_TIMEOUT","Document parsing exceeded the time limit.",413) from exc
                if process.returncode != 0 or not output.is_file():
                    raise DocumentParseError("DOCUMENT_WORKER_FAILED","Document parser terminated without a complete result.",422)
                if output.stat().st_size > settings.document_max_text_chars*8+1024*1024:
                    raise DocumentParseError("DOCUMENT_TEXT_TOO_LARGE","Document parser result exceeds its size limit.",413)
                try:
                    payload=json.loads(output.read_text(encoding="utf-8"))
                    if "error" in payload: raise DocumentParseError(**payload["error"])
                    return ParsedDocument(**payload["document"])
                except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                    raise DocumentParseError("DOCUMENT_WORKER_FAILED", "Document parser returned an invalid result.", 422) from exc
            finally:
                # A spawn already in progress must settle before it can be killed.
                while process is None:
                    if spawn.cancelled(): break
                    try: process=await asyncio.shield(spawn)
                    except asyncio.CancelledError: continue
                    except Exception: break
                if process is not None and process.returncode is None:
                    with suppress(ProcessLookupError): process.kill()
                    reaped=asyncio.create_task(process.wait())
                    while not reaped.done():
                        try: await asyncio.shield(reaped)
                        except asyncio.CancelledError: continue
