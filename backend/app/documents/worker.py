"""One document parser process; OS memory limit before importing format libraries."""
from __future__ import annotations
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

_job = None


def limit_memory(size):
    global _job
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(size,size))
        return
    import ctypes as c
    from ctypes import wintypes as w
    class Basic(c.Structure):
        _fields_=[("ProcessTime",c.c_longlong),("JobTime",c.c_longlong),("Flags",w.DWORD),
            ("MinWorkingSet",c.c_size_t),("MaxWorkingSet",c.c_size_t),("ActiveProcesses",w.DWORD),
            ("Affinity",c.c_size_t),("Priority",w.DWORD),("Scheduling",w.DWORD)]
    class IO(c.Structure):
        _fields_=[(n,c.c_ulonglong) for n in ("ReadOps","WriteOps","OtherOps","ReadBytes","WriteBytes","OtherBytes")]
    class Extended(c.Structure):
        _fields_=[("Basic",Basic),("IO",IO),("ProcessMemory",c.c_size_t),("JobMemory",c.c_size_t),
            ("PeakProcessMemory",c.c_size_t),("PeakJobMemory",c.c_size_t)]
    k=c.WinDLL("kernel32",use_last_error=True)
    k.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR]; k.CreateJobObjectW.restype=w.HANDLE
    k.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]; k.SetInformationJobObject.restype=w.BOOL
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]; k.AssignProcessToJobObject.restype=w.BOOL
    k.GetCurrentProcess.restype=w.HANDLE
    _job=k.CreateJobObjectW(None,None)
    info=Extended(); info.Basic.Flags=0x100; info.ProcessMemory=size
    if not _job or not k.SetInformationJobObject(_job,9,c.byref(info),c.sizeof(info)) or not k.AssignProcessToJobObject(_job,k.GetCurrentProcess()):
        raise OSError("unable to apply document memory limit")


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        limit_memory(request["settings"]["document_parse_memory_bytes"])
    except Exception:
        payload={"error":{"code":"DOCUMENT_RESOURCE_LIMIT_UNAVAILABLE","message":"Document resource isolation is unavailable.","status_code":503}}
    else:
        from app.core.settings import Settings
        from app.documents.parser import DocumentParseError, parse_uploaded_document
        try:
            settings=Settings(_env_file=None,**request["settings"])
            data=Path(request["path"]).read_bytes()
            parsed=parse_uploaded_document(filename=request["filename"],content_type=request["content_type"],
                data=data,title=request["title"],settings=settings)
            payload={"document":asdict(parsed)}
        except DocumentParseError as exc:
            payload={"error":{"code":exc.code,"message":exc.message,"status_code":exc.status_code}}
        except MemoryError:
            payload={"error":{"code":"DOCUMENT_RESOURCE_LIMIT","message":"Document parsing exceeded its memory budget.","status_code":413}}
        except Exception:
            payload={"error":{"code":"DOCUMENT_PARSE_FAILED","message":"Document parsing failed.","status_code":422}}
    Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")


if __name__=="__main__": main()
