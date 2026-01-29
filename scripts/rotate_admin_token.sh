#!/bin/bash
# Token Rotation Script - No Downtime
# Usage: ./scripts/rotate_admin_token.sh
#
# Two-step rotation:
# 1. Run this script -> sets ADMIN_TOKEN_NEXT
# 2. Distribute new token to users
# 3. Run ./scripts/swap_admin_token.sh -> moves NEXT to CURRENT

set -e

ENV_FILE="/opt/biz-agent-api-git/biz-agent-api/.env"
API_URL="http://127.0.0.1:8000"

echo "=== Admin Token Rotation (Step 1) ==="
echo ""

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found"
    exit 1
fi

# Backup
BACKUP_FILE="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
cp "$ENV_FILE" "$BACKUP_FILE"
echo "[1/5] Backup created: $BACKUP_FILE"

# Generate new token (32 hex = 64 chars)
NEW_TOKEN=$(openssl rand -hex 32)
echo "[2/5] New token generated (64 chars)"

# Check if ADMIN_TOKEN_NEXT already exists
if grep -q "^ADMIN_TOKEN_NEXT=" "$ENV_FILE"; then
    # Update existing
    sed -i "s/^ADMIN_TOKEN_NEXT=.*/ADMIN_TOKEN_NEXT=$NEW_TOKEN/" "$ENV_FILE"
else
    # Add new line
    echo "ADMIN_TOKEN_NEXT=$NEW_TOKEN" >> "$ENV_FILE"
fi
echo "[3/5] ADMIN_TOKEN_NEXT written to .env"

# Restart service
pm2 restart biz-agent-api > /dev/null 2>&1
sleep 3
echo "[4/5] Service restarted"

# Health check
HEALTH=$(curl -s "$API_URL/health" 2>/dev/null || echo '{"status":"error"}')
VERSION=$(echo "$HEALTH" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
AUTH_STATUS=$(curl -s "$API_URL/auth/status" 2>/dev/null || echo '{}')
NEXT_SET=$(echo "$AUTH_STATUS" | grep -o '"next_token_set":true' || echo "false")

if [ "$NEXT_SET" = '"next_token_set":true' ]; then
    echo "[5/5] Health check PASSED (version: $VERSION, next_token_set: true)"
else
    echo "[5/5] WARNING: next_token_set not detected. Check logs."
fi

echo ""
echo "=== Rotation Step 1 Complete ==="
echo ""

# Save token to secure file (readable only by root)
TOKEN_FILE="/opt/biz-agent-api-git/biz-agent-api/.new_token"
echo "$NEW_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

echo "New token saved to: $TOKEN_FILE"
echo "To view: cat $TOKEN_FILE"
echo ""
echo "Next steps:"
echo "1. cat $TOKEN_FILE  # get the new token"
echo "2. Distribute new token to users"
echo "3. Wait for users to switch"
echo "4. Run: ./scripts/swap_admin_token.sh"
echo "5. rm $TOKEN_FILE  # cleanup"
echo ""
