"""把项目已有的 RAG 与长期记忆接进 AutoGen 的 `Memory` 协议。

## 为什么用 Memory 协议而不是继续手工拼 prompt

多步链路中模型跑完第一个工具后还要继续决策，检索必须能在后续模型调用前按当前问题更新，
而不是只依赖回合开始时的一份快照。

AutoGen 的 `AssistantAgent` **每一轮模型调用前**都会调
`_update_model_context_with_memory()`（`_assistant_agent.py:940`），
逐个 memory 的 `update_context()` 往上下文里注入。接进这个协议就意味着：
多步链路的每一步都能拿到针对当前状态的检索结果，而不是回合开始时那一份快照。

## 检索管线本身一行不改

`RagMemory` 内部调的还是 `app/agent/rag/service.py` 那条管线
（向量 + 全文 + RRF + rerank + MMR + 相邻块扩展，含中文 bigram 修复）。
这里只做协议适配，不重写检索——那是这个项目做得最好的部分之一。
"""

from app.agent.engine.memory.pg_memory import PgVectorMemory
from app.agent.engine.memory.rag_memory import RagMemory

__all__ = ["PgVectorMemory", "RagMemory"]
