#!/bin/bash

# Helper script to connect to Vultr VM
# Usage: bash scripts/connect_vultr.sh [IP_ADDRESS] [USER]

if [ -z "$1" ]; then
    echo "=== Vultr VM Connection Helper ==="
    echo ""
    echo "Usage:"
    echo "  bash scripts/connect_vultr.sh YOUR_VULTR_IP [USER]"
    echo ""
    echo "Example:"
    echo "  bash scripts/connect_vultr.sh 192.0.2.1"
    echo "  bash scripts/connect_vultr.sh 192.0.2.1 ubuntu"
    echo ""
    echo "If no USER is provided, defaults to 'root'"
    echo ""
    exit 0
fi

VULTR_IP="$1"
VULTR_USER="${2:-root}"

echo "Connecting to Vultr VM..."
echo "  IP: $VULTR_IP"
echo "  User: $VULTR_USER"
echo ""
echo "After connecting, you can:"
echo "  1. Run the setup script: bash scripts/vultr_setup.sh"
echo "  2. Clone this repository (if not already cloned)"
echo "  3. Set up .env file with your credentials"
echo "  4. Deploy: bash scripts/deploy.sh"
echo ""
echo "Connecting now..."
echo ""

ssh "$VULTR_USER@$VULTR_IP"
