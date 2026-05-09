# Docker Image Verification and Cleanup Guide

## Current Status

Based on your docker-compose files, here are the images being used:

### ✅ CORRECT IMAGE (Multi-Embedding Support)
- **custom-surfsense-web:multi-embed**
  - Location: Both `docker-compose.yml` and `docker-compose-adaptable-rag.yml`
  - Built from: `source/SurfSense/surfsense_web/Dockerfile`
  - Contains: EmbeddingModelSelector component
  - **USE THIS IMAGE**

### ❌ OUTDATED/MISLEADING IMAGES

1. **ghcr.io/modsetter/surfsense-web:latest**
   - Original GitHub registry image
   - Does NOT have multi-embedding UI
   - Found in: `source/SurfSense/docker/docker-compose.yml`
   - **Should be tagged as: outdated_surfsense-web:github**

2. **documentai-frontend:latest**
   - Old local build
   - May or may not have multi-embedding
   - Was in: `docker-compose-adaptable-rag.yml` (already fixed to use custom-surfsense-web:multi-embed)
   - **Should be tagged as: outdated_documentai-frontend:local**

## Manual Verification Commands

Run these to check what's currently on your system:

```bash
# Check all frontend images
docker images | grep -E "frontend|surfsense-web"

# Check what's currently running
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" | grep frontend
```

## Tagging Outdated Images

Run these commands to rename old images:

```bash
cd /mnt/ssd1/projects/DocumentAI

# Tag GitHub registry image as outdated
docker tag ghcr.io/modsetter/surfsense-web:latest outdated_surfsense-web:github
docker rmi ghcr.io/modsetter/surfsense-web:latest

# Tag old documentai-frontend if it exists
docker tag documentai-frontend:latest outdated_documentai-frontend:local 2>/dev/null
docker rmi documentai-frontend:latest 2>/dev/null

# Verify
docker images | grep -E "surfsense-web|frontend"
```

Expected output after tagging:
```
REPOSITORY                    TAG         IMAGE ID       CREATED        SIZE
custom-surfsense-web          multi-embed <id>           X hours ago    XXX MB   ← USE THIS
outdated_surfsense-web        github      <id>           X days ago     XXX MB   ← OUTDATED
outdated_documentai-frontend  local       <id>           X days ago     XXX MB   ← OUTDATED
```

## Restart Frontend with Correct Image

```bash
cd /mnt/ssd1/projects/DocumentAI

# Using adaptable-rag compose file (since that's what you're running)
docker compose -f docker-compose-adaptable-rag.yml stop frontend
docker compose -f docker-compose-adaptable-rag.yml rm -f frontend
docker compose -f docker-compose-adaptable-rag.yml up -d frontend

# Wait for it to start
sleep 5

# Verify correct image is running
docker ps --format "table {{.Names}}\t{{.Image}}" | grep frontend
```

Expected output:
```
surfsense-adaptable-rag-frontend-1    custom-surfsense-web:multi-embed
```

## Quick Check Script

Run this script to do everything automatically:

```bash
cd /mnt/ssd1/projects/DocumentAI
chmod +x tag_outdated_images.sh
./tag_outdated_images.sh
```

## After Restart

1. Open http://localhost:3929
2. Navigate to Upload tab
3. Look for **"✨ Embedding Models"** section
4. It should appear between "Processing Mode" and "Upload" button
5. Click to expand and select multiple models

## Troubleshooting

If you still don't see the Embedding Model Selector:

1. **Verify correct image is running:**
   ```bash
   docker ps | grep frontend
   # Must show: custom-surfsense-web:multi-embed
   ```

2. **Check container logs:**
   ```bash
   docker logs surfsense-adaptable-rag-frontend-1 | tail -20
   ```

3. **Rebuild the custom image if needed:**
   ```bash
   cd source/SurfSense/surfsense_web
   docker build -t custom-surfsense-web:multi-embed .
   ```

4. **Hard refresh browser:**
   - Press Ctrl+Shift+R (Linux/Windows)
   - Or Cmd+Shift+R (Mac)
   - Or clear browser cache

## Summary

- ✅ **Use:** `custom-surfsense-web:multi-embed`
- ❌ **Avoid:** `ghcr.io/modsetter/surfsense-web:latest` (tagged as outdated)
- ❌ **Avoid:** `documentai-frontend:latest` (tagged as outdated)
