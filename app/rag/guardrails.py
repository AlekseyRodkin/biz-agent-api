"""Guardrails: validation and data integrity checks."""
from typing import Optional
from app.db.supabase_client import get_client

# Current schema version (last migration number)
SCHEMA_VERSION = "0006"


class GuardrailError(Exception):
    """Custom exception for guardrail violations."""

    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(self.message)


# --- Input Validation ---

def validate_not_empty(value: str, field_name: str, min_length: int = 1) -> str:
    """Validate string is not empty and meets minimum length."""
    if not value or not value.strip():
        raise GuardrailError(f"{field_name} cannot be empty", 400)

    value = value.strip()
    if len(value) < min_length:
        raise GuardrailError(
            f"{field_name} must be at least {min_length} characters",
            400
        )
    return value


def validate_uuid(value: str, field_name: str) -> str:
    """Validate UUID format."""
    import re
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, value.lower()):
        raise GuardrailError(f"{field_name} must be a valid UUID", 400)
    return value


def validate_enum(value: str, allowed: list[str], field_name: str) -> str:
    """Validate value is in allowed enum."""
    if value not in allowed:
        raise GuardrailError(
            f"{field_name} must be one of: {', '.join(allowed)}",
            400
        )
    return value


# --- Reference Validation ---

def validate_plan_exists(plan_id: str, user_id: str) -> dict:
    """Validate architect_plan exists and belongs to user."""
    client = get_client()

    result = client.table("company_memory") \
        .select("id, memory_type, status") \
        .eq("id", plan_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data or len(result.data) == 0:
        raise GuardrailError(f"Plan {plan_id} not found", 404)

    plan = result.data[0]
    if plan.get("memory_type") != "architect_plan":
        raise GuardrailError(
            f"Memory {plan_id} is not an architect_plan",
            400
        )

    return plan


def validate_metric_exists(metric_id: str, user_id: str) -> dict:
    """Validate metric exists and belongs to user."""
    client = get_client()

    result = client.table("metrics") \
        .select("id, status") \
        .eq("id", metric_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data or len(result.data) == 0:
        raise GuardrailError(f"Metric {metric_id} not found", 404)

    return result.data[0]


def validate_action_exists(action_id: str, user_id: str) -> dict:
    """Validate action exists and belongs to user."""
    client = get_client()

    result = client.table("action_items") \
        .select("id, status") \
        .eq("id", action_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data or len(result.data) == 0:
        raise GuardrailError(f"Action {action_id} not found", 404)

    return result.data[0]


# --- Deletion Guards ---

def guard_plan_deletion(plan_id: str) -> None:
    """Prevent deletion of plan with linked actions."""
    client = get_client()

    actions = client.table("action_items") \
        .select("id", count="exact") \
        .eq("source_plan_id", plan_id) \
        .execute()

    if actions.count and actions.count > 0:
        raise GuardrailError(
            f"Cannot delete plan: {actions.count} actions are linked to it",
            409
        )


def guard_metric_deletion(metric_id: str) -> None:
    """Prevent deletion of metric linked to actions."""
    client = get_client()

    actions = client.table("action_items") \
        .select("id", count="exact") \
        .eq("metric_id", metric_id) \
        .execute()

    if actions.count and actions.count > 0:
        raise GuardrailError(
            f"Cannot delete metric: {actions.count} actions are linked to it",
            409
        )


# --- Status Guards ---

def guard_superseded_reactivation(memory_id: str) -> None:
    """Prevent reactivating superseded memory."""
    client = get_client()

    result = client.table("company_memory") \
        .select("status") \
        .eq("id", memory_id) \
        .single() \
        .execute()

    if result.data and result.data.get("status") == "superseded":
        raise GuardrailError(
            "Cannot reactivate superseded memory. Create a new version instead.",
            409
        )


# --- Duplicate Detection ---

def check_duplicate_plan(user_id: str, goal: str) -> Optional[str]:
    """Check for recent duplicate plan (same goal in last 24h)."""
    from datetime import datetime, timedelta

    client = get_client()
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    result = client.table("company_memory") \
        .select("id, related_topic") \
        .eq("user_id", user_id) \
        .eq("memory_type", "architect_plan") \
        .eq("status", "active") \
        .gte("created_at", cutoff) \
        .execute()

    for plan in (result.data or []):
        topic = plan.get("related_topic", "")
        # Simple similarity check
        if goal.lower() in topic.lower() or topic.lower() in goal.lower():
            return plan["id"]

    return None


def check_duplicate_metric(user_id: str, name: str) -> Optional[str]:
    """Check for duplicate active metric with same name."""
    client = get_client()

    result = client.table("metrics") \
        .select("id, name") \
        .eq("user_id", user_id) \
        .eq("status", "active") \
        .execute()

    for metric in (result.data or []):
        if metric.get("name", "").lower() == name.lower():
            return metric["id"]

    return None


# --- Compound Validators ---

def validate_architect_save(goal: str, plan: str) -> tuple[str, str]:
    """Validate architect plan save request."""
    goal = validate_not_empty(goal, "goal", min_length=3)
    plan = validate_not_empty(plan, "plan", min_length=50)
    return goal, plan


def validate_metric_create(
    name: str,
    scope: str,
    related_plan_id: Optional[str],
    user_id: str
) -> None:
    """Validate metric creation request."""
    validate_not_empty(name, "name", min_length=3)
    validate_enum(scope, ["company", "department", "process"], "scope")

    if related_plan_id:
        validate_uuid(related_plan_id, "related_plan_id")
        validate_plan_exists(related_plan_id, user_id)


def validate_actions_from_plan(plan_id: str, user_id: str) -> dict:
    """Validate actions from plan request."""
    validate_uuid(plan_id, "plan_id")
    return validate_plan_exists(plan_id, user_id)


def validate_action_block(reason: str) -> str:
    """Validate action block request."""
    return validate_not_empty(reason, "reason", min_length=3)


def validate_action_link_metric(
    action_id: str,
    metric_id: str,
    user_id: str
) -> None:
    """Validate action-metric link request."""
    validate_uuid(action_id, "action_id")
    validate_uuid(metric_id, "metric_id")
    validate_action_exists(action_id, user_id)
    validate_metric_exists(metric_id, user_id)
