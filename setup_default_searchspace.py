#!/usr/bin/env python3
"""
Create a default search space with LLM configured.
This allows immediate document uploads without manual LLM setup.
"""
import requests
import json

BACKEND_URL = "http://localhost:8929"
EMAIL = "searchspace_setup@test.com"
PASSWORD = "setup123456"

def register():
    """Register new user account"""
    print("📝 Registering new account")
    response = requests.post(
        f"{BACKEND_URL}/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code in [200, 201]:
        print("✅ Registration successful")
        return True
    elif "already exists" in response.text.lower() or "registered" in response.text.lower():
        print("   Account already exists, will try login")
        return True
    else:
        print(f"⚠️  Registration response: {response.status_code}")
        return True  # Try login anyway

def login():
    """Login and get access token"""
    print("🔐 Logging in...")
    response = requests.post(
        f"{BACKEND_URL}/auth/jwt/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code}")
        print(response.text)
        return None
    
    token = response.json()["access_token"]
    print(f"✅ Logged in successfully")
    return token

def get_search_spaces(token):
    """Get all search spaces"""
    print("\n📋 Getting existing search spaces...")
    response = requests.get(
        f"{BACKEND_URL}/api/v1/searchspaces",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code != 200:
        print(f"❌ Failed to get search spaces: {response.status_code}")
        return []
    
    spaces = response.json()
    print(f"   Found {len(spaces)} search spaces")
    for space in spaces:
        print(f"   - {space.get('name', 'Unnamed')}: agent_llm_id={space.get('agent_llm_id', 'None')}")
    
    return spaces

def create_default_search_space(token):
    """Create a default search space with LLM configured"""
    print("\n🏗️  Creating default search space...")
    
    # Create search space with default LLM ID
    payload = {
        "name": "Default Search Space",
        "description": "Auto-created search space for document uploads",
        "agent_llm_id": -1,  # First LLM in global_llm_config.yaml
        "embedder_llm_id": -1,  # Use default embedder
        "chunk_size": 512,
        "chunk_overlap": 50
    }
    
    response = requests.post(
        f"{BACKEND_URL}/api/v1/searchspaces",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload
    )
    
    if response.status_code in [200, 201]:
        space = response.json()
        print(f"✅ Search space created: {space.get('name')}")
        print(f"   ID: {space.get('id')}")
        print(f"   agent_llm_id: {space.get('agent_llm_id')}")
        return space
    else:
        print(f"❌ Failed to create search space: {response.status_code}")
        print(response.text)
        return None

def update_search_space_llm(token, space_id, agent_llm_id=-1):
    """Update an existing search space to set LLM ID"""
    print(f"\n🔧 Updating search space {space_id} with agent_llm_id={agent_llm_id}...")
    
    # Try PUT first
    response = requests.put(
        f"{BACKEND_URL}/api/v1/searchspaces/{space_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={"agent_llm_id": agent_llm_id}
    )
    
    if response.status_code in [200, 201]:
        space = response.json()
        print(f"✅ Search space updated: agent_llm_id={space.get('agent_llm_id')}")
        return space
    
    # Try PATCH if PUT failed
    print(f"   PUT failed ({response.status_code}), trying PATCH...")
    response = requests.patch(
        f"{BACKEND_URL}/api/v1/searchspaces/{space_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={"agent_llm_id": agent_llm_id}
    )
    
    if response.status_code in [200, 201]:
        space = response.json()
        print(f"✅ Search space updated: agent_llm_id={space.get('agent_llm_id')}")
        return space
    else:
        print(f"❌ Failed to update search space: {response.status_code}")
        print(response.text)
        
        # Try to get full space data and update with all fields
        print("   Trying full GET+PUT...")
        get_response = requests.get(
            f"{BACKEND_URL}/api/v1/searchspaces/{space_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if get_response.status_code == 200:
            space_data = get_response.json()
            space_data['agent_llm_id'] = agent_llm_id
            
            put_response = requests.put(
                f"{BACKEND_URL}/api/v1/searchspaces/{space_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=space_data
            )
            
            if put_response.status_code in [200, 201]:
                space = put_response.json()
                print(f"✅ Search space updated: agent_llm_id={space.get('agent_llm_id')}")
                return space
        
        return None

def main():
    print("=" * 70)
    print("  SEARCH SPACE LLM SETUP")
    print("  Configuring default LLM to enable document uploads")
    print("=" * 70)
    
    # Register account if needed
    register()
    
    # Login
    token = login()
    if not token:
        return
    
    # Get existing search spaces
    spaces = get_search_spaces(token)
    
    # Check if any space already has LLM configured
    configured_spaces = [s for s in spaces if s.get('agent_llm_id') is not None]
    
    if configured_spaces:
        print(f"\n✅ Found {len(configured_spaces)} search space(s) with LLM configured")
        print("   You can now upload documents!")
        return
    
    # If no configured spaces, either create new or update existing
    if spaces:
        # Update first existing space
        first_space = spaces[0]
        print(f"\n🔧 Updating existing search space: {first_space.get('name')}")
        update_search_space_llm(token, first_space['id'], agent_llm_id=-1)
    else:
        # Create new default space
        create_default_search_space(token)
    
    print("\n" + "=" * 70)
    print("✅ SETUP COMPLETE!")
    print("   You can now upload documents via the Web UI")
    print("   http://localhost:3929")
    print("=" * 70)

if __name__ == "__main__":
    main()
