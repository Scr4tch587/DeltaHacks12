#!/bin/bash

# Vultr Deployment Script
# Helps deploy the application to a Vultr VM

set -e

echo "=== Vultr Deployment Script ==="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create .env from .env.example and fill in your credentials:"
    echo "  cp .env.example .env"
    echo "  nano .env  # or use your preferred editor"
    exit 1
fi

echo "✓ .env file found"
echo ""

# Check required variables in .env
source .env

REQUIRED_VARS=("MONGODB_URI" "MONGODB_DB")
MISSING_VARS=()

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -ne 0 ]; then
    echo "❌ Error: Missing required environment variables:"
    printf '  - %s\n' "${MISSING_VARS[@]}"
    echo "Please update your .env file"
    exit 1
fi

echo "✓ Required environment variables present"
echo ""

# Check if this is running on the Vultr VM or locally
if [ -z "$VULTR_IP" ]; then
    echo "This script should be run ON the Vultr VM."
    echo ""
    echo "To connect to your Vultr VM:"
    echo "  1. Get your VM's IP address from Vultr dashboard"
    echo "  2. SSH into it:"
    echo "     ssh root@YOUR_VULTR_IP"
    echo "     # or"
    echo "     ssh ubuntu@YOUR_VULTR_IP  # if using Ubuntu"
    echo ""
    echo "  3. Once connected, run this script again on the VM"
    echo ""
    echo "Or, if you want to deploy from your local machine:"
    echo "  export VULTR_IP=YOUR_VULTR_IP"
    echo "  export VULTR_USER=root  # or ubuntu"
    echo "  bash scripts/deploy.sh"
    exit 0
fi

echo "Starting deployment..."
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Running setup script..."
    bash scripts/vultr_setup.sh
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available"
    exit 1
fi

echo "✓ Docker and Docker Compose are installed"
echo ""

# Pull latest code (if git is available and in a repo)
if command -v git &> /dev/null && [ -d ".git" ]; then
    echo "Pulling latest code..."
    git pull || echo "⚠ Could not pull latest code (continuing anyway)"
    echo ""
fi

# Build and start services
echo "Building and starting services..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Checking service status..."
docker compose -f docker-compose.prod.yml ps

echo ""
echo "Testing health endpoints..."
sleep 2

echo ""
echo "Backend health:"
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/health

echo ""
echo ""
echo "Services should now be running!"
echo "Backend is accessible at: http://$(hostname -I | awk '{print $1}'):8000"
echo ""
