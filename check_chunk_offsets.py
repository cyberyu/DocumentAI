#!/usr/bin/env python3
"""Check chunk text from OpenSearch to verify document offsets."""
import requests, json

os_url = "http://localhost:9200"
doc_id = 391

indices = [
    "surfsense_chunks_1_sandwitch_chunk",
    "surfsense_chunks_1_chunk_hybrid",
    "surfsense_chunks_1_chunk_text",
    "surfsense_chunks_1_chunk_recursive",
]

for idx in indices:
    try:
        resp = requests.post(
            f"{os_url}/{idx}/_search",
            json={
                "query": {"term": {"metadata.document_id": doc_id}},
                "size": 200,
                "sort": [{"metadata.chunk_order": {"order": "asc"}}],
                "_source": ["content", "metadata.chunk_order"]
            },
            timeout=10
        )
        if resp.status_code != 200:
            continue
        hits = resp.json().get("hits", {}).get("hits", [])
        if not hits:
            continue
        texts = []
        for h in hits:
            src = h["_source"]
            texts.append((src.get("metadata", {}).get("chunk_order", 0), src.get("content", "")))
        texts.sort(key=lambda x: x[0])
        all_text = "\n".join(t[1] for t in texts)
        print(f"Index: {idx}")
        print(f"  Chunks: {len(texts)}, Total length: {len(all_text)}")
        print(f"  Text at 35180-35183: {repr(all_text[35180:35183])}")
        print(f"  Context: ...{repr(all_text[35170:35200])}...")
        idx80 = all_text.find('.80')
        print(f"  First '.80' at offset: {idx80}")
        if idx80 >= 0:
            print(f"  Context: ...{repr(all_text[max(0,idx80-30):idx80+30])}...")
        print()
        break
    except Exception as e:
        print(f"Error with {idx}: {e}")
