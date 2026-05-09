#!/usr/bin/env python3
"""Quick single test - check what backend receives"""
import requests
import json
import os

TOKEN = os.getenv('TOKEN')  # Get from env
if not TOKEN:
    print("Set TOKEN env var first:")
    print('TOKEN=$(curl -s -X POST http://localhost:8929/auth/jwt/login -H "Content-Type: application/x-www-form-urlencoded" -d "username=shee.yu@gmail.com&password=YOUR_PASSWORD" | jq -r .access_token)')
    exit(1)

MODELS = ["fastembed/bge-base-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"]

with open("MSFT_FY26Q1_10Q.docx", "rb") as f:
    response = requests.post(
        "http://localhost:8929/api/v1/documents/fileupload",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"files": ("MSFT_FY26Q1_10Q.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={
            "search_space_id": "2",
            "embedding_models": json.dumps(MODELS)
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    doc_id = response.json().get("document_ids", [None])[0]
    print(f"\n✅ Doc ID: {doc_id}")
    print("\nNow check logs:")
    print(f"sudo docker logs surfsense-adaptable-rag-backend-1 2>&1 | grep 'DEBUG.*embedding_models' | tail -3")
    print(f"sleep 20 && sudo docker logs surfsense-adaptable-rag-celery_worker-1 2>&1 | grep 'doc_id={doc_id}' -A 5 | grep embedding_config")
