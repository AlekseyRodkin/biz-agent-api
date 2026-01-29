# API Contract v1.8.0

## Overview

This document defines the stable API contracts for Biz Agent API.
Breaking changes require version bump and migration.

---

## Authentication

### Admin Token

Protected endpoints require `X-Admin-Token` header.

**Environment variable:** `ADMIN_TOKEN`

**Example:**
```bash
curl -H "X-Admin-Token: your_secret_token" http://localhost:8000/dashboard/exec
```

### Protected Endpoints

| Endpoint | Method |
|----------|--------|
| `/dashboard/exec` | GET |
| `/export/decisions` | GET |
| `/export/actions` | GET |
| `/export/metrics` | GET |
| `/export/plans` | GET |
| `/session/architect/save` | POST |
| `/module/summary` | POST |
| `/actions/from-plan` | POST |
| `/actions/{id}/start` | POST |
| `/actions/{id}/complete` | POST |
| `/actions/{id}/block` | POST |
| `/actions/{id}/link-metric` | POST |
| `/metrics/create` | POST |
| `/metrics/{id}/update` | POST |

### Open Endpoints

| Endpoint | Method |
|----------|--------|
| `/health` | GET |
| `/study/*` | ALL |
| `/decisions/*` | ALL |
| `/course/*` | GET |
| `/module/review` | POST |
| `/module/status/{module}` | GET |
| `/session/architect` | POST |
| `/actions` | GET |
| `/actions/status` | GET |
| `/actions/{id}` | GET |
| `/actions/{id}/metric` | GET |
| `/metrics` | GET |
| `/metrics/impact` | GET |
| `/metrics/{id}` | GET |
| `/ritual/*` | GET |
| `/ui/exec` | GET |

### Error Responses

**401 Unauthorized:**
```json
{"detail": "Missing X-Admin-Token header"}
{"detail": "Invalid admin token"}
{"detail": "ADMIN_TOKEN not configured on server"}
```

---

## Enums & Constants

### memory_type (company_memory)
```
decision        # User decision from study mode
company_context # Company context information
note            # General note
module_summary  # Module completion summary
architect_plan  # Structured implementation plan
```

### action.status (action_items)
```
planned      # Initial state
in_progress  # Work started
done         # Completed with optional result
blocked      # Blocked with required reason
```

### metric.status (metrics)
```
active     # Being tracked
achieved   # Target reached
abandoned  # No longer tracked
```

### memory.status (company_memory)
```
active      # Current version
superseded  # Replaced by newer version
```

### scope (metrics, architect_session)
```
company     # Company-wide
department  # Department-level
process     # Single process
```

---

## Endpoints

### Health & Info

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check with version info |

**Response:**
```json
{
  "status": "ok",
  "timestamp": "ISO8601",
  "version": "1.8.0",
  "schema_version": "0006"
}
```

---

### Study Mode

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/study/start` | POST | - | Reset progress |
| `/study/next` | POST | - | Get next block |
| `/study/answer` | POST | `answer` | Process answer |
| `/study/progress` | GET | - | Get progress |

**POST /study/answer Request:**
```json
{
  "answer": "string (required)",
  "topic": "string (optional)",
  "question": "string (optional)"
}
```

---

### Decisions

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/decisions/review` | GET | - | List decisions |
| `/decisions/refine` | POST | `decision_id`, `updated_decision` | Update decision |

**POST /decisions/refine Request:**
```json
{
  "decision_id": "uuid (required)",
  "updated_decision": "string (required)"
}
```

---

### Course Navigation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/course/map` | GET | Full course structure |
| `/course/progress` | GET | User progress |

---

### Module Review

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/module/review` | POST | `module` | Review module |
| `/module/summary` | POST | `module`, `summary` | Save summary |
| `/module/status/{module}` | GET | - | Check completion |

---

### Architect Session

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/session/architect` | POST | `goal` | Run session |
| `/session/architect/save` | POST | `goal`, `plan` | Save plan |

**POST /session/architect Request:**
```json
{
  "goal": "string (required)",
  "scope": "company|department|process (default: company)",
  "constraints": "array<string> (default: [])",
  "time_horizon_days": "int (default: 14)"
}
```

**POST /session/architect/save Request:**
```json
{
  "goal": "string (required, min 3 chars)",
  "plan": "string (required, min 50 chars)"
}
```

---

### Actions

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/actions/from-plan` | POST | `plan_id` | Generate actions |
| `/actions` | GET | - | List actions |
| `/actions/status` | GET | - | Status summary |
| `/actions/{id}` | GET | - | Get action |
| `/actions/{id}/start` | POST | - | Start action |
| `/actions/{id}/complete` | POST | - | Complete action |
| `/actions/{id}/block` | POST | `reason` | Block action |
| `/actions/{id}/link-metric` | POST | `metric_id` | Link metric |
| `/actions/{id}/metric` | GET | - | Get linked metric |

**POST /actions/from-plan Request:**
```json
{
  "plan_id": "uuid (required, must exist, must be architect_plan)"
}
```

**POST /actions/{id}/block Request:**
```json
{
  "reason": "string (required, min 3 chars)"
}
```

---

### Metrics

| Endpoint | Method | Required Fields | Description |
|----------|--------|-----------------|-------------|
| `/metrics/create` | POST | `name` | Create metric |
| `/metrics` | GET | - | List metrics |
| `/metrics/impact` | GET | - | Impact analysis |
| `/metrics/{id}` | GET | - | Get metric |
| `/metrics/{id}/update` | POST | `current_value` | Update value |

**POST /metrics/create Request:**
```json
{
  "name": "string (required, min 3 chars)",
  "description": "string (optional)",
  "scope": "company|department|process (default: company)",
  "baseline_value": "number (optional)",
  "target_value": "number (optional)",
  "current_value": "number (optional, defaults to baseline)",
  "unit": "string (optional)",
  "related_plan_id": "uuid (optional, must exist if provided)"
}
```

**POST /metrics/{id}/update Request:**
```json
{
  "current_value": "number (required)"
}
```

---

### Rituals

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ritual/daily` | GET | Daily focus report |
| `/ritual/weekly` | GET | Weekly review |

---

### Dashboard & Exports

| Endpoint | Method | Query Params | Description |
|----------|--------|--------------|-------------|
| `/dashboard/exec` | GET | - | Executive dashboard |
| `/export/decisions` | GET | `format` | Export decisions |
| `/export/actions` | GET | `format` | Export actions |
| `/export/metrics` | GET | `format` | Export metrics |
| `/export/plans` | GET | `format` | Export plans |

**format param:** `json` (default), `csv`, `md`

---

## Breaking Change Rules

### What requires migration:
- Adding required column to existing table
- Changing column type
- Renaming column
- Adding new enum value to CHECK constraint
- Changing foreign key relationships

### What requires version bump:
- Adding new endpoint
- Adding required field to request
- Removing field from response
- Changing response structure
- Changing validation rules

### What is NOT breaking:
- Adding optional field to request
- Adding new field to response
- Adding new optional endpoint
- Performance improvements
- Bug fixes in existing logic

---

## Error Codes

| Code | Meaning |
|------|---------|
| 400 | Bad Request - validation failed |
| 401 | Unauthorized - missing or invalid token |
| 404 | Not Found - resource doesn't exist |
| 409 | Conflict - operation violates constraints |
| 500 | Internal Error |

---

## Data Integrity Rules

1. **architect_plan with actions**: Cannot delete plan if actions exist
2. **metric with actions**: Cannot delete metric if linked to actions
3. **superseded memory**: Cannot change status back to active
4. **action status flow**: planned → in_progress → done|blocked
5. **metric auto-achieve**: status changes to "achieved" when target reached

---

## Version History

| Version | Schema | Changes |
|---------|--------|---------|
| 1.0.0 | 0001 | Initial: study, decisions |
| 1.1.0 | 0004 | Architect session |
| 1.2.0 | 0005 | Actions tracking |
| 1.3.0 | 0005 | Rituals |
| 1.4.0 | 0006 | Metrics |
| 1.5.0 | 0006 | Dashboard, exports |
| 1.6.0 | 0006 | Guardrails, contracts |
| 1.7.1 | 0006 | Bootstrap UI |
| 1.8.0 | 0006 | Admin token auth |
