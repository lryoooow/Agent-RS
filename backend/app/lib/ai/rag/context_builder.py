from app.lib.ai.rag.retriever import RetrievedContext


def build_context_block(contexts: list[RetrievedContext]) -> str:
    return "\n\n".join(context.content for context in contexts if context.content.strip())
