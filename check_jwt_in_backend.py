#!/usr/bin/env python3
"""
Run this INSIDE the backend container to check JWT_SECRET configuration
"""
import os
import sys

print("="*60)
print("JWT_SECRET Configuration Check")
print("="*60)

# Check environment variable
jwt_from_env = os.getenv('JWT_SECRET')
print(f"\n1. Environment Variable JWT_SECRET:")
print(f"   Type: {type(jwt_from_env)}")
print(f"   Value: {repr(jwt_from_env)}")
print(f"   Length: {len(jwt_from_env) if jwt_from_env else 0}")

# Try to import the app configuration
print(f"\n2. Attempting to load app configuration...")
try:
    sys.path.insert(0, '/app')
    from app.config import settings
    print("   ✅ Imported settings successfully")
    
    # Check if settings has JWT_SECRET
    if hasattr(settings, 'JWT_SECRET'):
        jwt_from_settings = settings.JWT_SECRET
        print(f"   settings.JWT_SECRET exists")
        print(f"   Type: {type(jwt_from_settings)}")
        print(f"   Value: {repr(jwt_from_settings)[:50]}...")
    else:
        print("   ❌ settings.JWT_SECRET does NOT exist")
        print(f"   Available attributes: {[a for a in dir(settings) if 'JWT' in a.upper() or 'SECRET' in a.upper()]}")
        
except ImportError as e:
    print(f"   ⚠️  Could not import from app.config: {e}")
    print(f"   Trying alternative imports...")
    
    try:
        from app.core.config import settings
        print("   ✅ Imported from app.core.config")
        if hasattr(settings, 'JWT_SECRET'):
            print(f"   settings.JWT_SECRET: {repr(settings.JWT_SECRET)[:50]}...")
        else:
            print(f"   ❌ No JWT_SECRET attribute")
    except Exception as e2:
        print(f"   ❌ Failed: {e2}")

# Check if pydantic settings is being used
print(f"\n3. Checking for Pydantic Settings...")
try:
    from pydantic_settings import BaseSettings
    print("   ✅ Pydantic Settings available")
except:
    try:
        from pydantic import BaseSettings
        print("   ✅ Pydantic BaseSettings available (old import)")
    except:
        print("   ❌ Pydantic Settings not available")

print("\n" + "="*60)
print("Recommendations:")
print("="*60)
if jwt_from_env:
    print("✅ JWT_SECRET is set in environment")
    print("   The issue might be in how the app loads configuration")
else:
    print("❌ JWT_SECRET is NOT set in environment")
    print("   This is the root cause!")
