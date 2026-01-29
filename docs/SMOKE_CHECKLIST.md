# Smoke Test Checklist

Quick verification that all systems are operational.
Expected time: 10-15 minutes.

---

## Prerequisites

```bash
# Set base URL
export BASE_URL="http://89.104.70.108:8000"
# or for local: export BASE_URL="http://localhost:8000"
```

---

## 1. Health Check

```bash
curl -s $BASE_URL/health | jq
```

**Expected:**
- `status: "ok"`
- `version: "1.6.0"` (or current)
- `schema_version: "0006"` (or current)

---

## 2. Study Mode

```bash
# Get progress
curl -s $BASE_URL/study/progress | jq '.status'

# Get next block (may timeout if LLM slow)
curl -s --max-time 60 $BASE_URL/study/next -X POST | jq '.topic'
```

**Expected:**
- Progress returns status
- Next returns topic and content

---

## 3. Decisions

```bash
curl -s $BASE_URL/decisions/review | jq '.total_decisions'
```

**Expected:**
- Returns count of decisions

---

## 4. Course Map

```bash
curl -s $BASE_URL/course/map | jq '.total_lectures'
curl -s $BASE_URL/course/progress | jq '.progress_percent'
```

**Expected:**
- Map returns lecture count
- Progress returns percentage

---

## 5. Architect Session

```bash
# Note: This calls LLM, may take 30-60 seconds
curl -s --max-time 90 $BASE_URL/session/architect \
  -H "Content-Type: application/json" \
  -d '{"goal": "Smoke test", "time_horizon_days": 7}' \
  -X POST | jq '.goal'
```

**Expected:**
- Returns goal echo and plan

---

## 6. Actions

```bash
# List actions
curl -s $BASE_URL/actions | jq '.total'

# Status summary
curl -s $BASE_URL/actions/status | jq
```

**Expected:**
- Returns action count
- Status shows planned/in_progress/done/blocked

---

## 7. Metrics

```bash
# List metrics
curl -s $BASE_URL/metrics | jq '.total'

# Impact analysis
curl -s $BASE_URL/metrics/impact | jq '.summary'
```

**Expected:**
- Returns metric count
- Impact shows on_track/off_track/exceeded

---

## 8. Rituals

```bash
# Daily focus (calls LLM)
curl -s --max-time 60 $BASE_URL/ritual/daily | jq '.date'

# Weekly review (calls LLM)
curl -s --max-time 60 $BASE_URL/ritual/weekly | jq '.week_start'
```

**Expected:**
- Daily returns current date
- Weekly returns week boundaries

---

## 9. Dashboard

```bash
curl -s $BASE_URL/dashboard/exec | jq '{
  course: .course_progress.progress_percent,
  actions: .actions.total,
  metrics: .metrics.total,
  risks: (.key_risks | length)
}'
```

**Expected:**
- Returns aggregated data
- No errors

---

## 10. Exports

```bash
# JSON
curl -s "$BASE_URL/export/actions" | jq '.total'

# CSV
curl -s "$BASE_URL/export/actions?format=csv" | head -2

# Markdown
curl -s "$BASE_URL/export/metrics?format=md" | head -5
```

**Expected:**
- JSON has metadata and data
- CSV has headers
- MD has title and table

---

## 11. Guardrails (Negative Tests)

```bash
# Empty plan save (should fail)
curl -s $BASE_URL/session/architect/save \
  -H "Content-Type: application/json" \
  -d '{"goal": "", "plan": ""}' \
  -X POST | jq '.detail'

# Invalid plan_id (should fail)
curl -s $BASE_URL/actions/from-plan \
  -H "Content-Type: application/json" \
  -d '{"plan_id": "00000000-0000-0000-0000-000000000000"}' \
  -X POST | jq '.detail'

# Empty block reason (should fail)
curl -s "$BASE_URL/actions/fake-id/block" \
  -H "Content-Type: application/json" \
  -d '{"reason": ""}' \
  -X POST | jq '.detail'
```

**Expected:**
- All return 400 with error message

---

## 12. Database Connectivity

```bash
# This implicitly tests DB via health
curl -s $BASE_URL/health | jq '.status'

# And via any data endpoint
curl -s $BASE_URL/metrics | jq '.total'
```

**Expected:**
- No connection errors

---

## Quick Summary Table

| # | Test | Command | Pass Criteria |
|---|------|---------|---------------|
| 1 | Health | `/health` | status=ok |
| 2 | Study | `/study/progress` | returns status |
| 3 | Decisions | `/decisions/review` | returns total |
| 4 | Course | `/course/map` | returns lectures |
| 5 | Architect | `/session/architect` | returns plan |
| 6 | Actions | `/actions` | returns list |
| 7 | Metrics | `/metrics/impact` | returns summary |
| 8 | Daily | `/ritual/daily` | returns date |
| 9 | Weekly | `/ritual/weekly` | returns week |
| 10 | Dashboard | `/dashboard/exec` | returns aggregates |
| 11 | Export | `/export/actions` | returns data |
| 12 | Guardrails | invalid inputs | returns 400 |

---

## Troubleshooting

### API not responding
```bash
# Check PM2 status
pm2 status biz-agent-api
pm2 logs biz-agent-api --lines 50
```

### LLM timeouts
- DeepSeek API may be slow
- Use `--max-time 90` for LLM endpoints
- Check `DEEPSEEK_API_KEY` in env

### Database errors
```bash
# Check Supabase connectivity
curl -s $BASE_URL/health
# If fails, check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
```

---

*Last updated: 2026-01-29*
