import asyncio
from app.db import async_session_maker
from app.retriever.chunks_hybrid_search import ChucksHybridSearchRetriever

async def main():
    query = (
        "change in total dollar amount of common stock repurchased "
        "between First Quarter Fiscal Year 2025 and First Quarter Fiscal Year 2026"
    )
    async with async_session_maker() as session:
        r = ChucksHybridSearchRetriever(session)

        print("=== WITHOUT EXPANSION ===")
        res = await r.hybrid_search(
            query_text=query, top_k=10, search_space_id=1,
            expand_adjacent_chunks=False,
        )
        for doc in res:
            for c in doc.get("chunks", []):
                cid = c.get("chunk_id") or c.get("id")
                snippet = (c.get("content") or "")[:120].replace("\n", " ")
                print(f"  chunk={cid}  {snippet}")

        print()
        print("=== WITH EXPANSION window=2 ===")
        res2 = await r.hybrid_search(
            query_text=query, top_k=10, search_space_id=1,
            expand_adjacent_chunks=True, adjacent_chunks_window=2,
        )
        for doc in res2:
            for c in doc.get("chunks", []):
                cid = c.get("chunk_id") or c.get("id")
                snippet = (c.get("content") or "")[:120].replace("\n", " ")
                print(f"  chunk={cid}  {snippet}")

asyncio.run(main())
