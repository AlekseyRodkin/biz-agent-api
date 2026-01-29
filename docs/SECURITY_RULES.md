# Security Rules

## What is a Secret?

- `APP_PASSWORD` — login password
- `SESSION_SECRET` — session signing key
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service key
- `DEEPSEEK_API_KEY` — LLM API key
- Any string matching: `sk-*`, `sb_secret_*`, `eyJhbGci*` (JWT)
- Passwords, private keys, certificates

## Rules

1. **NEVER** print secrets to stdout/logs
2. **NEVER** include secrets in reports/wiki
3. **NEVER** commit secrets to git
4. Show only `REDACTED` (preferred) or first 4 chars + `...`

## In Reports

```
BAD:  Password: mySecretPass123
GOOD: Password: REDACTED

BAD:  SESSION_SECRET=abc123def456...
GOOD: SESSION_SECRET=REDACTED
```

## On Password Leak

1. Change `APP_PASSWORD` in `.env` immediately
2. Restart service: `pm2 restart biz-agent-api`
3. All existing sessions remain valid until TTL expires
4. If needed, change `SESSION_SECRET` to invalidate all sessions

## Pre-commit Check

Run before commit: `./scripts/scan_secrets.sh`

## Environment Variables (never commit)

```bash
# Required for auth - NEVER commit real values
APP_USERNAME=alexey
APP_PASSWORD=<REDACTED>
SESSION_SECRET=<REDACTED>

# Other secrets
SUPABASE_SERVICE_ROLE_KEY=<REDACTED>
DEEPSEEK_API_KEY=<REDACTED>
```
