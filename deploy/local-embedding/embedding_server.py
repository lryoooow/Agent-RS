"""Local-only BGE-M3 inference. No runtime model downloads or cloud calls."""
import os
import secrets
import threading
from contextlib import asynccontextmanager

import torch
import torch.nn.functional as F
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoTokenizer

MODEL_PATH = os.environ.get("BGE_MODEL_PATH", "/home/LRY/models/bge-m3")
API_KEY = os.environ["LOCAL_EMBEDDING_API_KEY"]
MAX_TOKENS = 2048
tokenizer = None
model = None
lock = threading.Lock()
device = "cuda"


@asynccontextmanager
async def lifespan(app):
    global tokenizer, model
    if not torch.cuda.is_available():
        raise RuntimeError("Hygon DCU is not available to PyTorch")
    torch.set_num_threads(8)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(MODEL_PATH, local_files_only=True, trust_remote_code=False,
                                      torch_dtype=torch.float16, attn_implementation="eager").to(device).eval()
    with torch.inference_mode():
        model(**tokenizer("模型启动检测", return_tensors="pt").to(device))
    print("BGE-M3 ready on", torch.cuda.get_device_name(0), "HIP", torch.version.hip, flush=True)
    yield


app = FastAPI(title="Agent-RS local embeddings", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def size_limit(request: Request, call_next):
    from fastapi.responses import JSONResponse
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 2_000_000:
        return JSONResponse({"error": "Request too large"}, status_code=413)
    return await call_next(request)


class EmbeddingRequest(BaseModel):
    model: str = "bge-m3"
    input: str | list[str]
    dimensions: int = 1024
    encoding_format: str = "float"


@app.get("/health")
def health():
    return {"status": "ready", "model": "bge-m3", "dimensions": 1024, "max_tokens": MAX_TOKENS,
            "device": torch.cuda.get_device_name(0), "hip": torch.version.hip}


@app.post("/v1/embeddings")
def embeddings(body: EmbeddingRequest, authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, "Bearer " + API_KEY):
        raise HTTPException(401, "Invalid local service key")
    if body.model not in {"bge-m3", "BAAI/bge-m3"} or body.dimensions != 1024 or body.encoding_format != "float":
        raise HTTPException(422, "Supported: bge-m3, 1024 dimensions, float encoding")
    texts = [body.input] if isinstance(body.input, str) else body.input
    if not texts or len(texts) > 32 or any(not text.strip() or len(text) > 40000 for text in texts):
        raise HTTPException(422, "Use 1-32 nonempty texts, at most 40000 characters each")
    outputs, tokens = [], 0
    with lock, torch.inference_mode():
        lengths = [len(tokenizer.encode(text)) for text in texts]
        if max(lengths) > MAX_TOKENS:
            raise HTTPException(422, f"Split inputs longer than {MAX_TOKENS} tokens")
        for start in range(0, len(texts), 2):
            encoded = tokenizer(texts[start:start+2], padding=True, return_tensors="pt").to(device)
            output = model(**encoded).last_hidden_state[:, 0]
            vectors = F.normalize(output.float(), p=2, dim=1).cpu().tolist()
            outputs.extend(vectors)
        tokens = sum(lengths)
    return {"object": "list", "model": "bge-m3", "data": [{"object": "embedding", "index": i, "embedding": v} for i,v in enumerate(outputs)],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens}}
