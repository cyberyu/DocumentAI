#!/usr/bin/env python3
"""Get all chunks for doc 391 from OpenSearch, concatenate, check offsets."""
import requests, json, sys

os_url = "http://localhost:9200"
doc_id = 391

all_texts = []
offset = 0
chunk_boundaries = []  # (chunk_order, start_offset, end_offset)

for idx_name in ["surfsense_chunks_1_sandwitch_chunk"]:
    # Scroll through all chunks
    scroll_size = 500
    resp = requests.post(
        f"{os_url}/{idx_name}/_search?scroll=2m",
        json={
            "query": {"term": {"metadata.document_id": doc_id}},
            "size": scroll_size,
            "sort": [{"metadata.chunk_order": {"order": "asc"}}],
            "_source": ["content", "metadata.chunk_order"]
        },
        timeout=30
    )
    data = resp.json()
    scroll_id = data.get("_scroll_id")
    hits = data.get("hits", {}).get("hits", [])
    
    while hits:
        for h in hits:
            src = h["_source"]
            content = src.get("content", "")
            chunk_order = src.get("metadata", {}).get("chunk_order", 0)
            start = offset
            all_texts.append(content)
            offset += len(content)
            chunk_boundaries.append((chunk_order, start, offset, len(content)))
        
        # Scroll
        resp = requests.post(
            f"{os_url}/_search/scroll",
            json={"scroll": "2m", "scroll_id": scroll_id},
            timeout=30
        )
        data = resp.json()
        scroll_id = data.get("_scroll_id")
        hits = data.get("hits", {}).get("hits", [])
    
    # Clear scroll
    if scroll_id:
        requests.delete(f"{os_url}/_search/scroll", json={"scroll_id": scroll_id})

full_text = "".join(all_texts)
print(f"Total chunks: {len(chunk_boundaries)}")
print(f"Total text length: {len(full_text)}")
print(f"Text at 35180-35183: {repr(full_text[35180:35183])}")
print(f"Context: ...{repr(full_text[35170:35200])}...")

# Find ".80"
idx80 = full_text.find('.80')
print(f"\nFirst '.80' at offset: {idx80}")
if idx80 >= 0:
    print(f"Context: ...{repr(full_text[max(0,idx80-40):idx80+40])}...")
else:
    # Try searching for "80" only
    idx80b = full_text.find('80')
    print(f"First '80' at offset: {idx80b}")
    print(f"Context: ...{repr(full_text[max(0,idx80b-40):idx80b+40])}...")

# Check the document-level offset from df_santic_qa.json
print(f"\n--- Checking df_qa.json offsets vs chunk text ---")
offset_35180 = 35180
print(f"Text from the QA file offsets ({offset_35180}-{offset_35180+3}): {repr(full_text[offset_35180:offset_35180+3])}")
print(f"Context around that: ...{repr(full_text[max(0,offset_35180-40):offset_35180+40])}...")

# Find which chunk contains offset 35180
for co, start, end, clen in chunk_boundaries:
    if start <= offset_35180 < end:
        chunk_local = offset_35180 - start
        print(f"\nOffset {offset_35180} is in chunk_order={co} (chunk local offset: {chunk_local})")
        # Get the chunk content from all_texts
        print(f"Chunk content length: {clen}")
        print(f"Chunk local [{chunk_local-5}:{chunk_local+10}]: ...{repr(full_text[start+max(0,chunk_local-5):start+chunk_local+10])}...")
        break
