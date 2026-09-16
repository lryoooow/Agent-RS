"""Document retrieval requires a relevant task and a semantic match, not merely top-k rank."""
from __future__ import annotations
import json
import math
import re

_DOCUMENT = re.compile(r"文档|知识库|资料|手册|实施方案|论文|指南|章节|第.{1,5}章|这份|这篇|上文|依据.{0,12}(方案|规范)|根据.{0,12}(方案|规范)|\b(document|knowledge base|manual|paper|chapter)\b", re.I)
_OPERATION = re.compile(r"提取|分割|检测|分类|框选|影像|图层|上传|导入|重试|重投影|裁剪|预览|真彩色|假彩色|质检|体检|这张|该图|当前图|地图|[Nn][Dd][VvWwBbMm][Ii]|\b(image|imagery|raster|segment|detect|upload|import|retry)\b", re.I)
_CONCEPT = re.compile(r"原理|方法|流程|步骤|如何|怎么|为什么|区别|适用|解释|介绍|\b(how|why|explain|method)\b", re.I)

def mentions_documents(query: str) -> bool:
    return bool(_DOCUMENT.search(query))

def should_retrieve_documents(query: str) -> bool:
    text = query.strip()
    if not text or re.fullmatch(r"[你好您好谢谢好的嗯哦继续重试再来一次\s!！。,.？?]+", text):
        return False
    if mentions_documents(text):
        return True
    if _OPERATION.search(text):
        return bool(_CONCEPT.search(text)) and not re.search(r"这张|当前|框选|该影像|上传的|\bthis image\b", text, re.I)
    # Open domain questions may use relevant knowledge; greetings and actions may not.
    return len(text) >= 4

def semantic_similarity(chunk: dict, query_embedding: list[float]) -> float:
    score = chunk.get("vector_score")
    if score is not None:
        try:
            value = float(score)
            return value if math.isfinite(value) else -1.0
        except (ValueError, TypeError):
            return -1.0
    vector = chunk.get("embedding")
    if isinstance(vector, str):
        try: vector = json.loads(vector)
        except (ValueError, TypeError): return -1.0
    if vector is None or len(vector) != len(query_embedding): return -1.0
    try:
        denom = math.sqrt(sum(float(v)**2 for v in vector) * sum(float(v)**2 for v in query_embedding))
        value = sum(float(a)*float(b) for a,b in zip(vector, query_embedding)) / denom if denom else -1.0
        return value if math.isfinite(value) else -1.0
    except (ValueError, TypeError, OverflowError): return -1.0
