#!/usr/bin/env python3
"""Debug G3-027: show full model streaming response."""
import json, urllib.request, urllib.parse, re, sys
sys.path.insert(0, "/home/shiyu/Documents/surfsense")
from scripts.run_surfsense_benchmark import SurfSenseClient

BASE_URL = "http://localhost:8929"
USERNAME = "shi.yu@broadridge.com"
PASSWORD = "Lexar1357!!"
SEARCH_SPACE_ID = 1

QUESTION = (
    "In MSFT_FY26Q1_10Q.docx, what was the change in the total dollar amount "
    "of common stock repurchased between the First Quarter of Fiscal Year 2025 "
    "and the First Quarter of Fiscal Year 2026? Return only the numeric change "
    "with sign and unit. Search the full document before answering."
)

client = SurfSenseClient(BASE_URL)
client.login(USERNAME, PASSWORD)
print("Logged in.")

thread_id = client.create_thread(search_space_id=SEARCH_SPACE_ID, title="debug-g3027")
print(f"Thread: {thread_id}")

# Manually call the stream endpoint and capture raw SSE
status, body, headers = client._request(
    "POST",
    "/api/v1/new_chat",
    json_body={
        "chat_id": thread_id,
        "user_query": QUESTION,
        "search_space_id": SEARCH_SPACE_ID,
        "disabled_tools": ["web_search", "scrape_webpage"],
    },
    extra_headers={"Accept": "text/event-stream"},
)
print(f"Stream status: {status}")
raw = body.decode("utf-8", errors="replace")

# Show the raw stream first 3000 chars
print("RAW STREAM (first 3000 chars):")
print(raw[:3000])
print("...")

# Collect full text from text-delta events
text_parts = []
tool_calls = []
for line in raw.splitlines():
    line = line.strip()
    if not line or not line.startswith("data:"):
        continue
    part = line[5:].strip()
    try:
        obj = json.loads(part)
        if obj.get("type") == "text-delta":
            text_parts.append(obj.get("delta", ""))
        elif obj.get("type") == "tool-input-available":
            tool_calls.append(f"TOOL: {obj.get('toolName')} INPUT: {json.dumps(obj.get('input', {}))[:200]}")
        elif obj.get("type") == "tool-output-available":
            tool_calls.append(f"  OUTPUT: {json.dumps(obj.get('output', {}))[:200]}")
    except:
        pass

print("\n=== TOOL CALLS ===")
for tc in tool_calls:
    print(tc)

full_text = "".join(text_parts)
print("\n" + "="*60)
print("FULL MODEL RESPONSE:")
print("="*60)
print(full_text)
print("="*60)

# Also try to get messages from thread
print("\nFetching thread messages...")
msgs = client.list_messages(thread_id=thread_id, limit=20)
for m in msgs:
    role = m.get("role", "?")
    content = m.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                print(f"\n[{role}]: {item.get('text', '')[:2000]}")
    elif isinstance(content, str):
        print(f"\n[{role}]: {content[:2000]}")
