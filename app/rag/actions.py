"""Action items: execution and tracking of plans."""
import re
from datetime import datetime, timedelta
from app.db.supabase_client import get_client


def parse_plan_to_actions(plan_text: str) -> list[dict]:
    """Parse [ПЛАН НА N ДНЕЙ] section into action items."""
    actions = []

    # Find the plan section
    plan_match = re.search(r'\[ПЛАН НА \d+ ДНЕЙ\](.*?)(?:\[|$)', plan_text, re.DOTALL)
    if not plan_match:
        return actions

    plan_section = plan_match.group(1)

    # Parse day ranges and actions
    # Pattern: День X-Y: or День X:
    day_pattern = re.compile(r'(?:\*\*)?День\s*(\d+)(?:-(\d+))?(?:\*\*)?[:\s]+(.+?)(?=(?:\*\*)?День|\[|$)', re.DOTALL | re.IGNORECASE)

    for match in day_pattern.finditer(plan_section):
        day_start = match.group(1)
        day_end = match.group(2) or day_start
        content = match.group(3).strip()

        # Clean up content
        content = re.sub(r'\n\s*\*\s*', '\n• ', content)
        content = content.strip()

        # Extract title (first line or up to first newline/bullet)
        lines = content.split('\n')
        title = lines[0].strip()
        if title.startswith('**'):
            title = title.strip('*').strip()

        # Truncate title if too long
        if len(title) > 100:
            title = title[:97] + "..."

        description = content

        actions.append({
            "day_range": f"{day_start}-{day_end}" if day_end != day_start else day_start,
            "title": title,
            "description": description,
            "sequence_order": int(day_start)
        })

    return actions


def create_actions_from_plan(user_id: str, plan_id: str) -> list[dict]:
    """Create action items from an architect_plan."""
    client = get_client()

    # Get the plan
    plan_result = client.table("company_memory") \
        .select("*") \
        .eq("id", plan_id) \
        .eq("user_id", user_id) \
        .execute()

    if not plan_result.data:
        return []

    plan = plan_result.data[0]
    plan_text = plan.get("user_decision_raw", "")

    # Parse plan into actions
    parsed_actions = parse_plan_to_actions(plan_text)

    if not parsed_actions:
        return []

    # Create action items
    created = []
    for action in parsed_actions:
        record = {
            "user_id": user_id,
            "source_plan_id": plan_id,
            "title": action["title"],
            "description": action["description"],
            "day_range": action["day_range"],
            "sequence_order": action["sequence_order"],
            "status": "planned"
        }
        result = client.table("action_items").insert(record).execute()
        if result.data:
            created.append(result.data[0])

    return created


def get_actions(user_id: str, status: str = None) -> list[dict]:
    """Get action items for user, optionally filtered by status."""
    client = get_client()

    query = client.table("action_items") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("sequence_order", desc=False)

    if status:
        query = query.eq("status", status)

    result = query.execute()
    return result.data or []


def get_action(user_id: str, action_id: str) -> dict | None:
    """Get a single action item."""
    client = get_client()
    result = client.table("action_items") \
        .select("*") \
        .eq("id", action_id) \
        .eq("user_id", user_id) \
        .execute()
    return result.data[0] if result.data else None


def start_action(user_id: str, action_id: str) -> dict | None:
    """Set action status to in_progress."""
    client = get_client()
    result = client.table("action_items") \
        .update({"status": "in_progress", "updated_at": datetime.utcnow().isoformat()}) \
        .eq("id", action_id) \
        .eq("user_id", user_id) \
        .execute()
    return result.data[0] if result.data else None


def complete_action(user_id: str, action_id: str, result_text: str = None) -> dict | None:
    """Set action status to done with optional result."""
    client = get_client()
    update_data = {
        "status": "done",
        "updated_at": datetime.utcnow().isoformat()
    }
    if result_text:
        update_data["result"] = result_text

    result = client.table("action_items") \
        .update(update_data) \
        .eq("id", action_id) \
        .eq("user_id", user_id) \
        .execute()
    return result.data[0] if result.data else None


def block_action(user_id: str, action_id: str, reason: str) -> dict | None:
    """Set action status to blocked with reason."""
    client = get_client()
    result = client.table("action_items") \
        .update({
            "status": "blocked",
            "block_reason": reason,
            "updated_at": datetime.utcnow().isoformat()
        }) \
        .eq("id", action_id) \
        .eq("user_id", user_id) \
        .execute()
    return result.data[0] if result.data else None


def get_actions_status(user_id: str) -> dict:
    """Get summary of action items status."""
    client = get_client()
    result = client.table("action_items") \
        .select("status") \
        .eq("user_id", user_id) \
        .execute()

    actions = result.data or []

    status_counts = {
        "total": len(actions),
        "planned": 0,
        "in_progress": 0,
        "done": 0,
        "blocked": 0
    }

    for a in actions:
        status = a.get("status", "planned")
        if status in status_counts:
            status_counts[status] += 1

    # Calculate progress percentage
    status_counts["progress_percent"] = round(
        (status_counts["done"] / status_counts["total"] * 100) if status_counts["total"] > 0 else 0,
        1
    )

    return status_counts


def get_current_actions(user_id: str) -> list[dict]:
    """Get in_progress and planned actions for agent context."""
    client = get_client()
    result = client.table("action_items") \
        .select("id, title, status, day_range") \
        .eq("user_id", user_id) \
        .in_("status", ["in_progress", "planned"]) \
        .order("sequence_order", desc=False) \
        .limit(5) \
        .execute()
    return result.data or []


def build_actions_context(user_id: str) -> str:
    """Build context string for agent with current actions."""
    actions = get_current_actions(user_id)

    if not actions:
        return ""

    lines = ["[ТЕКУЩИЕ ДЕЙСТВИЯ]"]
    for a in actions:
        status_icon = "🔄" if a["status"] == "in_progress" else "📋"
        lines.append(f"{status_icon} День {a['day_range']}: {a['title']}")

    return "\n".join(lines)
