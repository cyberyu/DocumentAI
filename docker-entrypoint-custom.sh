#!/bin/sh
set -e

# Standard NEXT_PUBLIC_* placeholder replacement (for browser-side code)
node /app/docker-entrypoint.js

# Patch server-side chunks to use the internal Docker service name.
# The image was built before FASTAPI_BACKEND_INTERNAL_URL was supported,
# so localhost:8929 gets hardcoded in server chunks — which doesn't resolve
# inside the container. Replace it with the internal Docker service URL.
PUBLIC_URL="${NEXT_PUBLIC_FASTAPI_BACKEND_URL:-http://localhost:8000}"
INTERNAL_URL="http://backend:8000"

if [ "$PUBLIC_URL" != "$INTERNAL_URL" ]; then
    find /app/.next/server -name "*.js" \
        -exec sed -i "s|${PUBLIC_URL}|${INTERNAL_URL}|g" {} \;
    echo "[entrypoint] Patched server chunks: ${PUBLIC_URL} -> ${INTERNAL_URL}"
fi

exec node server.js
