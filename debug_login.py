#!/usr/bin/env python3
"""
Comprehensive login debugging script
Tests the entire authentication flow and diagnoses issues
"""
import requests
import json
import sys

BACKEND_URL = "http://localhost:8929"
FRONTEND_URL = "http://localhost:3929"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_backend_health():
    print_section("1. Backend Health Check")
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"✅ Backend is responding: {resp.status_code}")
        print(f"Response: {resp.text}")
        return True
    except Exception as e:
        print(f"❌ Backend health check failed: {e}")
        return False

def test_jwt_secret():
    print_section("2. JWT Secret Configuration")
    
    # Test login with wrong credentials to see error type
    try:
        resp = requests.post(
            f"{BACKEND_URL}/auth/jwt/login",
            data={"username": "nonexistent@test.com", "password": "wrongpass"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5
        )
        
        print(f"Response Status: {resp.status_code}")
        print(f"Response Body: {resp.text[:500]}")
        
        if resp.status_code == 500:
            print("❌ 500 Error detected - JWT_SECRET issue likely!")
            return False
        elif resp.status_code == 400:
            data = resp.json()
            if "LOGIN_BAD_CREDENTIALS" in str(data):
                print("✅ JWT is working (got proper 400 for bad credentials)")
                return True
        
        return True
    except Exception as e:
        print(f"❌ JWT test failed: {e}")
        return False

def test_existing_users():
    print_section("3. Check Existing Users")
    # We'll try to login with known users
    test_users = [
        ("shi.yu@broadridge.com", ""),
        ("shee.yu@gmail.com", "")
    ]
    
    print("Testing if users exist (expecting 400 bad credentials):")
    for email, _ in test_users:
        try:
            resp = requests.post(
                f"{BACKEND_URL}/auth/jwt/login",
                data={"username": email, "password": "testpassword123"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5
            )
            
            if resp.status_code == 400:
                data = resp.json()
                if "LOGIN_BAD_CREDENTIALS" in str(data):
                    print(f"  ✅ User {email} exists (bad password)")
            elif resp.status_code == 500:
                print(f"  ❌ User {email} - 500 ERROR (JWT issue)")
            else:
                print(f"  ⚠️  User {email} - Unexpected: {resp.status_code}")
        except Exception as e:
            print(f"  ❌ Error testing {email}: {e}")

def test_registration():
    print_section("4. Test Registration Flow")
    
    import time
    test_email = f"debugtest_{int(time.time())}@test.com"
    test_password = "DebugTest123!"
    
    print(f"Registering new user: {test_email}")
    
    try:
        resp = requests.post(
            f"{BACKEND_URL}/auth/register",
            json={
                "email": test_email,
                "password": test_password
            },
            timeout=10
        )
        
        print(f"Registration Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")
        
        if resp.status_code in [200, 201]:
            print("✅ Registration successful!")
            return test_email, test_password
        else:
            print(f"⚠️  Registration returned: {resp.status_code}")
            return None, None
            
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        return None, None

def test_login_with_credentials(email, password):
    print_section("5. Test Login with Valid Credentials")
    
    print(f"Attempting login: {email}")
    
    try:
        resp = requests.post(
            f"{BACKEND_URL}/auth/jwt/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        
        print(f"Login Status: {resp.status_code}")
        print(f"Response Headers: {dict(resp.headers)}")
        print(f"Response Body: {resp.text[:500]}")
        
        if resp.status_code == 200:
            print("✅ LOGIN SUCCESSFUL!")
            # Try to extract token
            try:
                data = resp.json()
                if 'access_token' in data:
                    print(f"✅ Got access token: {data['access_token'][:50]}...")
                    return True
            except:
                pass
            return True
        elif resp.status_code == 400:
            print("❌ Login failed: Bad credentials")
            return False
        elif resp.status_code == 500:
            print("❌ Login failed: 500 Internal Server Error (JWT issue!)")
            return False
        else:
            print(f"⚠️  Unexpected status: {resp.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Login request failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cors():
    print_section("6. Test CORS Configuration")
    
    try:
        resp = requests.options(
            f"{BACKEND_URL}/auth/jwt/login",
            headers={
                "Origin": FRONTEND_URL,
                "Access-Control-Request-Method": "POST"
            },
            timeout=5
        )
        
        print(f"CORS Status: {resp.status_code}")
        print(f"CORS Headers:")
        for header in ['access-control-allow-origin', 'access-control-allow-methods', 'access-control-allow-credentials']:
            value = resp.headers.get(header, 'NOT SET')
            print(f"  {header}: {value}")
        
        if resp.status_code == 200:
            print("✅ CORS configured correctly")
            return True
        else:
            print("⚠️  CORS check returned unexpected status")
            return False
            
    except Exception as e:
        print(f"❌ CORS test failed: {e}")
        return False

def main():
    print("\n" + "="*60)
    print("  SURFSENSE LOGIN DEBUGGING TOOL")
    print("="*60)
    
    results = {
        "backend_health": False,
        "jwt_working": False,
        "cors_working": False,
        "login_working": False
    }
    
    # Run all tests
    results["backend_health"] = test_backend_health()
    
    if not results["backend_health"]:
        print("\n❌ CRITICAL: Backend is not responding. Fix this first!")
        sys.exit(1)
    
    results["jwt_working"] = test_jwt_secret()
    test_existing_users()
    results["cors_working"] = test_cors()
    
    # Try registration and login
    email, password = test_registration()
    
    if email and password:
        results["login_working"] = test_login_with_credentials(email, password)
    else:
        print("\n⚠️  Could not test login (registration failed)")
    
    # Final summary
    print_section("SUMMARY")
    
    print("\nTest Results:")
    for test, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test:20s}: {status}")
    
    if all(results.values()):
        print("\n✅ ALL TESTS PASSED - Login should be working!")
        print("\nIf frontend still shows 'Connection failed', the issue is CLIENT-SIDE.")
        print("Possible causes:")
        print("  1. Browser cache (hard refresh: Ctrl+Shift+R)")
        print("  2. Frontend environment variables not applied")
        print("  3. Frontend build issue")
    else:
        print("\n❌ SOME TESTS FAILED")
        print("\nRecommended actions:")
        if not results["jwt_working"]:
            print("  - JWT_SECRET not working properly")
            print("  - Check backend logs: sudo docker logs surfsense-adaptable-rag-backend-1 --tail 50")
        if not results["cors_working"]:
            print("  - CORS misconfigured")
        if not results["login_working"]:
            print("  - Login endpoint has issues")

if __name__ == "__main__":
    main()
