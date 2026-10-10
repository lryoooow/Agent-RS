from __future__ import annotations
import json
import time
import uuid
import pytest
from app.core.settings import Settings
from app.db.repositories._pg.identity import ensure_default_identity
from app.db.repositories._pg.conversation import create_conversation
from app.db.repositories._pg.message import list_conversation_messages
from app.db.repositories._pg.memory import list_relevant_memories
from app.db.repositories._pg.vector_search import search_vector_only
from app.db.vector import encode_vector

pytestmark=pytest.mark.asyncio(loop_scope="session")


async def test_pages_follow_seq_with_equal_times_and_random_uuid(pg_conn):
    settings=Settings(_env_file=None); owner,_=await ensure_default_identity(pg_conn,settings)
    convo=await create_conversation(pg_conn,user_id=owner,settings=settings)
    other=await create_conversation(pg_conn,user_id=owner,settings=settings)
    ids=[str(uuid.uuid4()) for _ in range(9)]
    for i,identity in enumerate(ids):
        await pg_conn.execute("INSERT INTO agent_rs.messages(id,conversation_id,role,content,status,created_at) VALUES($1::uuid,$2::uuid,'user',$3,'complete','2020-01-01')",identity,convo,str(i))
    page=await list_conversation_messages(pg_conn,conversation_id=convo,user_id=owner,limit=3)
    assert [row["content"] for row in page]==["6","7","8"]
    earlier=await list_conversation_messages(pg_conn,conversation_id=convo,user_id=owner,limit=3,before=page[0]["id"])
    assert [row["content"] for row in earlier]==["3","4","5"]
    oldest=await list_conversation_messages(pg_conn,conversation_id=convo,user_id=owner,limit=3,before=earlier[0]["id"])
    assert [row["content"] for row in oldest]==["0","1","2"]
    assert await list_conversation_messages(pg_conn,conversation_id=other,user_id=owner,before=ids[3])==[]
    assert await list_conversation_messages(pg_conn,conversation_id=convo,user_id=str(uuid.uuid4()),before=ids[3])==[]


async def test_default_identity_fast_path_preserves_rows_without_updates(pg_conn):
    settings=Settings(_env_file=None); owner,workspace=await ensure_default_identity(pg_conn,settings)
    before=await pg_conn.fetchrow("SELECT xmin::text,name FROM agent_rs.users WHERE id=$1::uuid",owner)
    for i in range(4): await ensure_default_identity(pg_conn,settings)
    after=await pg_conn.fetchrow("SELECT xmin::text,name FROM agent_rs.users WHERE id=$1::uuid",owner)
    assert dict(before)==dict(after)
    await pg_conn.execute("DELETE FROM agent_rs.memberships WHERE workspace_id=$1::uuid",workspace)
    await ensure_default_identity(pg_conn,settings)
    assert await pg_conn.fetchval("SELECT count(*) FROM agent_rs.memberships WHERE workspace_id=$1::uuid",workspace)==1


async def test_parent_index_used_for_selective_document_query(pg_conn):
    ids=[str(uuid.uuid4()) for _ in range(20)]
    for identity in ids:
        await pg_conn.execute("INSERT INTO public.documents(id,title,content,created_by_user_id) VALUES($1::uuid,'title','content','owner')",identity)
        await pg_conn.execute("INSERT INTO public.document_chunks(document_id,chunk_index,content) SELECT $1::uuid,i,'chunk' FROM generate_series(1,50) i",identity)
    await pg_conn.execute("ANALYZE public.document_chunks")
    plan=await pg_conn.fetchval("EXPLAIN (ANALYZE,FORMAT JSON) SELECT * FROM public.document_chunks WHERE document_id=$1::uuid",ids[0])
    decoded=json.loads(plan)
    assert "idx_document_chunks_document_id" in json.dumps(decoded)
    assert decoded[0]["Plan"]["Actual Rows"]==50


async def test_exact_tenant_recall_and_tie_order_survive_global_hnsw(pg_conn):
    query=encode_vector([1.0,0.0]+[0.0]*1534)
    foreign=encode_vector([1.0,.001]+[0.0]*1534)
    own=encode_vector([1.0,.2]+[0.0]*1534)
    doc=str(uuid.uuid4()); other=str(uuid.uuid4())
    for identity,owner in [(doc,'a'),(other,'b')]:
        await pg_conn.execute("INSERT INTO public.documents(id,title,content,created_by_user_id) VALUES($1::uuid,'t','c',$2)",identity,owner)
    await pg_conn.execute("INSERT INTO public.document_chunks(document_id,chunk_index,content,embedding) SELECT $1::uuid,i,'foreign',$2::vector FROM generate_series(1,512) i",other,foreign)
    await pg_conn.execute("INSERT INTO public.document_chunks(document_id,chunk_index,content,embedding) SELECT $1::uuid,i,'owned',$2::vector FROM generate_series(1,16) i",doc,own)
    await pg_conn.execute("INSERT INTO public.memories(user_id,content,embedding) SELECT 'b','foreign',$1::vector FROM generate_series(1,512)",foreign)
    await pg_conn.execute("INSERT INTO public.memories(user_id,content,embedding) SELECT 'a','owned',$1::vector FROM generate_series(1,16)",own)
    started=time.monotonic()
    rows=await search_vector_only(pg_conn,embedding=[1.0,0.0]+[0.0]*1534,limit=10,user_id='a')
    memory=await list_relevant_memories(pg_conn,embedding=[1.0,0.0]+[0.0]*1534,limit=20,user_id='a')
    assert len(rows)==10 and len(memory)==16
    assert all(row['document_id']==doc and row['content']=='owned' for row in rows)
    assert all(row['content']=='owned' for row in memory)
    assert time.monotonic()-started < 2  # controlled fixture budget, not a production SLA
    assert await search_vector_only(pg_conn,embedding=[1.0,0.0]+[0.0]*1534,limit=10,user_id=None)==[]


async def test_default_identity_conflict_never_attaches_another_user(pg_conn):
    settings=Settings(_env_file=None)
    other=str(uuid.uuid4())
    await pg_conn.execute("INSERT INTO agent_rs.users(id,email,password_hash,name) VALUES($1::uuid,$2,'disabled','other')",other,settings.default_user_email)
    with pytest.raises(RuntimeError,match="identity configuration conflicts"):
        await ensure_default_identity(pg_conn,settings)
    assert await pg_conn.fetchval("SELECT count(*) FROM agent_rs.memberships WHERE user_id=$1::uuid",other)==0


async def test_equivalent_parent_index_is_reused_without_duplicate(pg_conn):
    from pathlib import Path
    sql=(Path(__file__).resolve().parents[2]/"sql/migrations/0015_document_chunk_parent_index.sql").read_text()
    async with pg_conn.transaction():
        await pg_conn.execute("ALTER INDEX public.idx_document_chunks_document_id RENAME TO equivalent_document_parent")
        try:
            await pg_conn.execute(sql)
            assert await pg_conn.fetchval("SELECT to_regclass('public.idx_document_chunks_document_id')") is None
            assert await pg_conn.fetchval("SELECT to_regclass('public.equivalent_document_parent')") is not None
        finally:
            await pg_conn.execute("ALTER INDEX public.equivalent_document_parent RENAME TO idx_document_chunks_document_id")
