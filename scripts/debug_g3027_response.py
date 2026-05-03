#!/usr/bin/env python3
"""Quick script to show the FULL model response for G3-027."""
import json, urllib.request, urllib.parse, sys, re

BASE_URL = "http://localhost:8929"
USERNAME = "shi.yu@broadridge.com"
PASSWORD = "Lexar1357!!"
SEARCH_SPACE_ID = 1

QUESTION = (
    "In MSFT_FY26Q1_10Q.docx, what was the change in the total dollar amount "
    "of common stock repurchased between the First Quarter of Fiscal Year 2025 "
    "and the First Quarter of Fiscal Year 2026? Return only the numeric change "
    "with sign and unit."
)

def _req(path, data=None, method="GET", form=False, token=None):
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None
    if data is not None:
        if form:
            payload = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            payload = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {}

# Login
print("Logging in...")
status, body, _ = _req("/auth/jwt/login", {"username": USERNAME, "password": PASSWORD}, form=True)
token = json.loads(body.decode()).get("access_token")
print(f"Token obtained (first 20 chars): {token[:20]}...")

# Create a new thread
status, thbody, _ = _req("/api/v1/new_chat_threads/create", {}, method="POST", token=token)
print(f"Thread status: {status}, body: {thbody.decode()[:200]}")
thread_id = json.loads(thbody.decode()).get("id", 1600)
print(f"Thread ID: {thread_id}")

print("Asking question via stream...")
status, body, _ = _req("/api/v1/new_chat", {
    "chat_id": thread_id,
    "user_query": QUESTION,
    "search_space_id": SEARCH_SPACE_ID,
    "disabled_tools": ["web_search", "scrape_webpage"],
}, token=token)

# Capture stream
print(f"\nStreaming response (status {status}):\n")
raw = body.decode("utf-8", errors="replace")
full_text = []
for line in raw.split("\n"):
    line = line.strip()
    if not line:
        continue
    # Vercel AI SDK style: 0:"text" or 2:[{"type":"text","text":"..."}]
    if line.startswith("0:"):
        try:
            txt = json.loads(line[2:])
            full_text.append(txt)
        except:
            pass
    # Print raw lines too to understand the format
    if any(kw in line.lower() for kw in ["repurchas", "1,446", "1,155", "3,955", "2,800", "1,543", "chunk", "source"]):
        print(f"  >> {line[:300]}")

print("\n\n=== FULL ASSISTANT TEXT ===")
print("".join(full_text))
