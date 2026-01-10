#!/bin/bash

# Test connection script
# Tests MongoDB and Vultr Object Storage connections

set -e

echo "=== Connection Test Script ==="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create .env from .env.example"
    exit 1
fi

# Source .env file
source .env

echo "Testing connections..."
echo ""

# Check if backend is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Backend service is not running on port 8000"
    echo "Please start the services first:"
    echo "  docker compose up -d"
    exit 1
fi

echo "✓ Backend service is running"
echo ""

# Test MongoDB connection
echo "Testing MongoDB connection..."
MONGODB_RESULT=$(curl -s http://localhost:8000/health/db 2>/dev/null || echo "ERROR")

if echo "$MONGODB_RESULT" | grep -q '"status": "connected"'; then
    echo "✓ MongoDB Atlas: Connected"
    echo "$MONGODB_RESULT" | python3 -m json.tool 2>/dev/null || echo "$MONGODB_RESULT"
else
    echo "❌ MongoDB Atlas: Connection failed"
    echo "$MONGODB_RESULT"
fi

echo ""
echo "---"
echo ""

# Test Object Storage connection
echo "Testing Vultr Object Storage connection..."
STORAGE_RESULT=$(curl -s http://localhost:8000/health/storage 2>/dev/null || echo "ERROR")

if echo "$STORAGE_RESULT" | grep -q '"status": "connected"'; then
    echo "✓ Vultr Object Storage: Connected"
    echo "$STORAGE_RESULT" | python3 -m json.tool 2>/dev/null || echo "$STORAGE_RESULT"
elif echo "$STORAGE_RESULT" | grep -q "not configured"; then
    echo "⚠ Vultr Object Storage: Not configured"
    echo "   This is optional. If you want to use it, set VULTR_ENDPOINT, VULTR_ACCESS_KEY, and VULTR_SECRET_KEY in .env"
else
    echo "❌ Vultr Object Storage: Connection failed"
    echo "$STORAGE_RESULT"
fi

echo ""
echo "=== Connection tests complete ==="
