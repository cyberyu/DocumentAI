#!/usr/bin/env python3
import requests
import json

# Login
resp = requests.post('http://localhost:8929/auth/jwt/login', 
    data={"username": "shee.yu@gmail.com", "password": "password"})

if resp.status_code != 200:
    print(f"Login failed: {resp.status_code}")
    print(resp.text)
    exit(1)

token = resp.json()["access_token"]

# Get LLM configs
headers = {"Authorization": f"Bearer {token}"}
resp = requests.get("http://localhost:8929/api/v1/new-llm-configs?search_space_id=2", 
    headers=headers)

print("Status:", resp.status_code)
print("Response:")
print(json.dumps(resp.json(), indent=2))

#Also check searchspace details
resp2 = requests.get("http://localhost:8929/api/v1/searchspaces/2", headers=headers)
print("\n\nSearch space:")
print(json.dumps(resp2.json(), indent=2))
