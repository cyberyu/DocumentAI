#!/usr/bin/env python3
"""Test multi-embedding by calling the API directly."""

import requests
import json
import sys
import os

# Top 3 embedding models to test
EMBEDDING_MODELS = [
    "fastembed/bge-base-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5"
]

# API endpoint
BASE_URL = "http://localhost:8929"
UPLOAD_URL = f"{BASE_URL}/api/v1/documents"

# Test file path (use existing test document)
TEST_FILE = "MSFT_FY26Q1_10Q.docx"

# Test user credentials
TEST_USER_EMAIL = "shee.yu@gmail.com"
TEST_PASSWORD = "19771106"

def login(password):
    """Login and get JWT token."""
    login_url = f"{BASE_URL}/auth/jwt/login"
    response = requests.post(
        login_url,
        data={"username": TEST_USER_EMAIL, "password": password},  # form data, not JSON
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    if response.status_code != 200:
        raise requests.HTTPError(f"{TEST_USER_EMAIL}: {response.status_code} {response.text}")

    data = response.json()
    return data.get("access_token"), TEST_USER_EMAIL

def upload_document(token, embedding_models):
    """Upload document with multiple embedding models."""
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    # Prepare multipart form data - files and form fields separately
    with open(TEST_FILE, "rb") as f:
        files = {
            "files": (TEST_FILE, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }
        
        data = {
            "search_space_id": "2",  # Default search space
            "embedding_models": json.dumps(embedding_models)  # JSON array as string
        }
        
        print(f"\n{'='*60}")
        print("📤 Uploading document with multi-embeddings")
        print(f"{'='*60}")
        print(f"Embedding models: {embedding_models}")
        print(f"File: {TEST_FILE}")
        print(f"Search space: {data['search_space_id']}")
        print(f"\nRequest form data:")
        print(f"  - embedding_models: {data['embedding_models']}")
        print(f"{'='*60}\n")
        
        response = requests.post(
            UPLOAD_URL + "/fileupload",  # Correct endpoint
            headers=headers,
            files=files,
            data=data
        )
        
        print(f"Response status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error response: {response.text}")
        print(f"Response body: {json.dumps(response.json(), indent=2)}")
        
        response.raise_for_status()
        return response.json()

def main():
    try:
        # Check if file exists
        if not __import__('os').path.exists(TEST_FILE):
            print(f"❌ Test file not found: {TEST_FILE}")
            print(f"Please make sure {TEST_FILE} is in the current directory.")
            sys.exit(1)
        
        # Use hardcoded credentials (user requested)
        password = TEST_PASSWORD
        
        # Login
        print("🔐 Logging in...")
        token, used_email = login(password)
        print(f"✅ Got token: {token[:20]}...")
        print(f"✅ Authenticated as: {used_email}")
        
        # Upload with multiple embeddings
        result = upload_document(token, EMBEDDING_MODELS)
        
        doc_ids = result.get("document_ids", [])
        print(f"\n✅ Documents uploaded successfully!")
        print(f"Document IDs: {doc_ids}")
        print(f"Message: {result.get('message')}")
        
        if doc_ids:
            doc_id = doc_ids[0]
            print(f"\n{'='*60}")
            print("🔍 Now check celery logs for:")
            print("  1. [indexing] Received embedding_config: ...")
            print("  2. [indexing] use_multi_embedding=True/False")
            print(f"{'='*60}")
            print(f"\nCommand to check logs:")
            print(f"sudo docker logs surfsense-adaptable-rag-celery_worker-1 2>&1 | grep -E 'embedding_config|use_multi_embedding' | tail -20")
            print(f"\nOr for this specific document (ID {doc_id}):")
            print(f"sudo docker logs surfsense-adaptable-rag-celery_worker-1 2>&1 | grep -A 5 'doc_id={doc_id}'")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
