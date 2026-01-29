# Security Rules

## What is a Secret?

- `ADMIN_TOKEN*` — API admin tokens
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service key
- `DEEPSEEK_API_KEY` — LLM API key
- Any string matching: `sk-*`, `sb_secret_*`, `eyJhbGci*` (JWT)
- Passwords, private keys, certificates

## Rules

1. **NEVER** print secrets to stdout/logs
2. **NEVER** include secrets in reports/wiki
3. **NEVER** commit secrets to git
4. Show only first 4 chars + `...` or `REDACTED`

## In Reports

```
BAD:  Token: abc123def456...
GOOD: Token: REDACTED
GOOD: Token: abc1...
```

## On Leak

1. Rotate immediately: `./scripts/rotate_admin_token.sh && ./scripts/swap_admin_token.sh`
2. Old token becomes invalid
3. Distribute new token securely

## Pre-commit Check

Run before commit: `./scripts/scan_secrets.sh`
