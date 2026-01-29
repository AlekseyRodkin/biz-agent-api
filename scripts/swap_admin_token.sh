#!/bin/bash
# Token Swap Script - Complete Rotation
# Usage: ./scripts/swap_admin_token.sh
#
# Moves ADMIN_TOKEN_NEXT -> ADMIN_TOKEN_CURRENT
# Removes ADMIN_TOKEN_NEXT
# Old token becomes invalid

set -e

ENV_FILE="/opt/biz-agent-api-git/biz-agent-api/.env"
API_URL="http://127.0.0.1:8000"

echo "=== Admin Token Swap (Step 2) ==="
echo ""

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found"
    exit 1
fi

# Check if NEXT token exists
NEXT_TOKEN=$(grep "^ADMIN_TOKEN_NEXT=" "$ENV_FILE" | cut -d'=' -f2)
if [ -z "$NEXT_TOKEN" ]; then
    echo "ERROR: ADMIN_TOKEN_NEXT not found in .env"
    echo "Run rotate_admin_token.sh first"
    exit 1
fi

# Backup
BACKUP_FILE="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
cp "$ENV_FILE" "$BACKUP_FILE"
echo "[1/4] Backup created: $BACKUP_FILE"

# Update CURRENT with NEXT value
if grep -q "^ADMIN_TOKEN_CURRENT=" "$ENV_FILE"; then
    sed -i "s/^ADMIN_TOKEN_CURRENT=.*/ADMIN_TOKEN_CURRENT=$NEXT_TOKEN/" "$ENV_FILE"
else
    # Maybe using old ADMIN_TOKEN format
    if grep -q "^ADMIN_TOKEN=" "$ENV_FILE"; then
        sed -i "s/^ADMIN_TOKEN=.*/ADMIN_TOKEN_CURRENT=$NEXT_TOKEN/" "$ENV_FILE"
    else
        echo "ADMIN_TOKEN_CURRENT=$NEXT_TOKEN" >> "$ENV_FILE"
    fi
fi
echo "[2/4] ADMIN_TOKEN_CURRENT updated"

# Remove NEXT token
sed -i '/^ADMIN_TOKEN_NEXT=/d' "$ENV_FILE"
echo "[3/4] ADMIN_TOKEN_NEXT removed"

# Restart service
pm2 restart biz-agent-api > /dev/null 2>&1
sleep 3

# Health check
AUTH_STATUS=$(curl -s "$API_URL/auth/status" 2>/dev/null || echo '{}')
NEXT_SET=$(echo "$AUTH_STATUS" | grep -o '"next_token_set":false' || echo "unknown")

if [ "$NEXT_SET" = '"next_token_set":false' ]; then
    echo "[4/4] Swap complete (next_token_set: false)"
else
    echo "[4/4] WARNING: Check /auth/status manually"
fi

echo ""
echo "=== Rotation Complete ==="
echo ""
echo "Old token is now INVALID"
echo "Only the new token works"
echo ""
