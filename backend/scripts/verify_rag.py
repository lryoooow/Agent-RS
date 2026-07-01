# -*- coding: utf-8 -*-
"""
RAG Chain Verification Script
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agent.embedding.service import get_embedding_service
from app.agent.rag.service import retrieve_rag_context
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool


async def verify_rag_chain():
    print("=" * 60)
    print("RAG Retrieval Chain Verification")
    print("=" * 60)

    settings = get_settings()
    pool = await fetch_optional_pool()

    if not pool:
        print("[ERROR] Database not enabled or connection failed")
        return False

    # 1. Check embedding service
    print("\n[1/5] Checking Embedding Service...")
    embedding_service = get_embedding_service()
    print(f"[OK] Embedding service configured")
    print(f"   Base URL: {settings.embedding_base_url or '(default)'}")
    print(f"   Model: {settings.embedding_model}")

    # 2. Test embedding generation
    print("\n[2/5] Testing Embedding Generation...")
    try:
        test_query = "NDVI vegetation index in remote sensing"
        embedding = await embedding_service.embed_text(test_query)
        print(f"[OK] Embedding generated successfully")
        print(f"   Dimension: {len(embedding)}")
    except Exception as e:
        print(f"[ERROR] Embedding generation failed: {e}")
        return False

    # 3. Check document data
    print("\n[3/5] Checking Document Data...")
    async with pool.acquire() as conn:
        doc_count = await conn.fetchval("SELECT COUNT(*) FROM public.documents")
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM public.document_chunks")
    print(f"[OK] Database connection successful")
    print(f"   Documents: {doc_count}")
    print(f"   Chunks: {chunk_count}")

    if chunk_count == 0:
        print("\n[WARN] No documents available for retrieval")
        print("   Please upload test documents to verify RAG functionality")
        return True

    # 4. Test retrieval
    print("\n[4/5] Testing Document Retrieval...")
    try:
        trace = {}
        result = await retrieve_rag_context(
            pool,
            query=test_query,
            embedding=embedding,
            user_id=None,
            trace=trace,
        )
        print(f"[OK] Retrieval successful")
        print(f"   Candidates: {trace.get('candidates', 0)}")
        print(f"   Recall time: {trace.get('recall_ms', 0)}ms")
        print(f"   Rerank time: {trace.get('rerank_ms', 0)}ms")
        print(f"   Retrieved chunks: {result.retrieved_chunks}")

        if result.retrieved_chunks == 0:
            print("\n[WARN] No results returned")
    except Exception as e:
        print(f"[ERROR] Retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 5. Show current configuration
    print("\n[5/5] Current RAG Configuration:")
    print(f"   Candidate limit: {settings.rag_candidate_limit}")
    print(f"   Retrieval limit: {settings.rag_retrieval_limit}")
    print(f"   RRF K: {settings.rag_rrf_k}")
    print(f"   MMR enabled: {settings.rag_mmr_enabled}")
    print(f"   MMR lambda: {settings.rag_mmr_lambda}")
    print(f"   Context expansion: {settings.rag_context_expansion_enabled}")
    print(f"   Expansion radius: {settings.rag_context_expansion_radius}")
    print(f"   Rerank enabled: {settings.rerank_enabled}")
    print(f"   Rerank model: {settings.rerank_model}")
    print(f"   Rerank top-N: {settings.rerank_top_n}")

    print("\n" + "=" * 60)
    print("[OK] RAG Chain Verification Complete")
    print("=" * 60)

    # Optimization suggestions
    print("\nOptimization Suggestions:")
    if chunk_count == 0:
        print("   1. Upload test documents to verify end-to-end functionality")
    if settings.rag_candidate_limit < 20:
        print(f"   2. Increase candidate limit (current: {settings.rag_candidate_limit}, suggest: 20-30)")
    if not settings.rag_mmr_enabled:
        print("   3. Enable MMR for better diversity")
    if settings.rag_context_expansion_radius == 0:
        print("   4. Increase context expansion radius (suggest: 1-2)")

    return True


async def main():
    try:
        success = await verify_rag_chain()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
