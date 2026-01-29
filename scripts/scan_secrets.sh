#!/bin/bash
# Secret Scanner - Pre-commit check
# Usage: ./scripts/scan_secrets.sh [files...]
# Exit 1 if secrets found, 0 if clean

set -e

# Patterns to detect (regex)
# Note: patterns match hex/alphanumeric tokens, excluding REDACTED and placeholders
PATTERNS=(
    'ADMIN_TOKEN=[a-f0-9]{16,}'            # ADMIN_TOKEN=hex_value (hex 16+ chars)
    'ADMIN_TOKEN_CURRENT=[a-f0-9]{16,}'    # Full token values (hex 16+ chars)
    'ADMIN_TOKEN_NEXT=[a-f0-9]{16,}'       # Full token values (hex 16+ chars)
    'sb_secret_[a-zA-Z0-9]+'               # Supabase secret keys
    'eyJhbGci[a-zA-Z0-9_-]+'               # JWT tokens
    'sk-[a-zA-Z0-9]{20,}'                  # OpenAI-style keys
    'DEEPSEEK_API_KEY=sk-[a-zA-Z0-9]+'     # DeepSeek keys (sk-xxx format)
    'SUPABASE_SERVICE_ROLE_KEY=eyJ'        # Supabase service key
)

# Files to scan (default: staged files or all tracked)
if [ $# -gt 0 ]; then
    FILES="$@"
else
    # Check staged files first, fallback to all tracked
    FILES=$(git diff --cached --name-only 2>/dev/null || git ls-files 2>/dev/null || find . -type f -name "*.md" -o -name "*.py" -o -name "*.sh" -o -name "*.json")
fi

# Exclude patterns (include scanner and rotation scripts - they write to .env, not reports)
EXCLUDE_PATTERNS="\.env$|\.env\.bak|node_modules|\.git|__pycache__|\.pyc$|scan_secrets\.sh$|rotate_admin_token\.sh$|swap_admin_token\.sh$"

FOUND=0
echo "=== Secret Scanner ==="
echo ""

for pattern in "${PATTERNS[@]}"; do
    MATCHES=$(echo "$FILES" | grep -vE "$EXCLUDE_PATTERNS" | xargs grep -l -E "$pattern" 2>/dev/null || true)
    if [ -n "$MATCHES" ]; then
        echo "FOUND pattern: $pattern"
        echo "In files:"
        echo "$MATCHES" | sed 's/^/  - /'
        echo ""
        FOUND=1
    fi
done

if [ $FOUND -eq 1 ]; then
    echo "=== FAIL: Secrets detected ==="
    echo ""
    echo "Fix: Replace values with REDACTED or remove"
    echo "Then: git add <files> && ./scripts/scan_secrets.sh"
    exit 1
else
    echo "=== PASS: No secrets detected ==="
    exit 0
fi
