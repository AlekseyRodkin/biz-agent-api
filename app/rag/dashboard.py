"""Executive dashboard: aggregated view for management."""
from datetime import datetime, timedelta
from app.db.supabase_client import get_client
from app.rag.metrics import calculate_impact


def get_course_progress_summary(user_id: str) -> dict:
    """Get course progress summary."""
    client = get_client()

    # Get user progress
    progress = client.table("user_progress") \
        .select("current_lecture_id, lectures_completed") \
        .eq("user_id", user_id) \
        .single() \
        .execute()

    # Get total methodology lectures
    total = client.table("course_lectures") \
        .select("lecture_id", count="exact") \
        .eq("speaker_type", "methodology") \
        .execute()

    total_lectures = total.count or 0
    completed = 0
    current = None

    if progress.data:
        completed = progress.data.get("lectures_completed", 0)
        current = progress.data.get("current_lecture_id")

    progress_pct = round((completed / total_lectures * 100) if total_lectures > 0 else 0, 1)

    return {
        "total_lectures": total_lectures,
        "completed": completed,
        "progress_percent": progress_pct,
        "current_lecture": current
    }


def get_active_plans_summary(user_id: str) -> list[dict]:
    """Get active architect plans summary."""
    client = get_client()

    plans = client.table("company_memory") \
        .select("id, related_topic, created_at") \
        .eq("user_id", user_id) \
        .eq("memory_type", "architect_plan") \
        .eq("status", "active") \
        .order("created_at", desc=True) \
        .limit(5) \
        .execute()

    return [
        {
            "id": str(p["id"]),
            "title": p.get("related_topic", "План")[:100],
            "created_at": p["created_at"]
        }
        for p in (plans.data or [])
    ]


def get_actions_summary(user_id: str, days: int = 7) -> dict:
    """Get actions summary for period."""
    client = get_client()

    # Get all actions
    all_actions = client.table("action_items") \
        .select("id, status, updated_at, block_reason, created_at") \
        .eq("user_id", user_id) \
        .execute()

    actions = all_actions.data or []

    # Calculate period boundary
    period_start = datetime.utcnow() - timedelta(days=days)

    stats = {
        "total": len(actions),
        "planned": 0,
        "in_progress": 0,
        "done": 0,
        "blocked": 0,
        "done_this_period": 0,
        "period_days": days
    }

    blocked_details = []

    for a in actions:
        status = a.get("status", "planned")
        stats[status] = stats.get(status, 0) + 1

        # Count done in period
        if status == "done":
            updated = a.get("updated_at", "")
            if updated:
                try:
                    updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    if updated_dt.replace(tzinfo=None) >= period_start:
                        stats["done_this_period"] += 1
                except (ValueError, TypeError):
                    pass

        # Collect blocked details
        if status == "blocked":
            created = a.get("created_at", "")
            days_blocked = 0
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_blocked = (datetime.utcnow() - created_dt.replace(tzinfo=None)).days
                except (ValueError, TypeError):
                    pass

            blocked_details.append({
                "id": str(a["id"]),
                "reason": a.get("block_reason", "Причина не указана"),
                "days_blocked": days_blocked,
                "critical": days_blocked >= 3
            })

    stats["blocked_details"] = blocked_details

    return stats


def get_metrics_summary(user_id: str) -> dict:
    """Get metrics summary from impact calculation."""
    impact = calculate_impact(user_id)
    return impact["summary"]


def get_key_risks(user_id: str) -> list[dict]:
    """Get key risks: blocked actions and off-track metrics."""
    risks = []

    # Blocked actions (critical if > 3 days)
    client = get_client()
    blocked = client.table("action_items") \
        .select("id, title, block_reason, created_at") \
        .eq("user_id", user_id) \
        .eq("status", "blocked") \
        .execute()

    for a in (blocked.data or []):
        created = a.get("created_at", "")
        days_blocked = 0
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days_blocked = (datetime.utcnow() - created_dt.replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        risks.append({
            "type": "blocked_action",
            "severity": "critical" if days_blocked >= 3 else "warning",
            "title": a.get("title", "")[:100],
            "reason": a.get("block_reason", ""),
            "days": days_blocked
        })

    # Off-track metrics
    impact = calculate_impact(user_id)
    for m in impact["metrics"]:
        if m["status"] == "off_track":
            risks.append({
                "type": "off_track_metric",
                "severity": "warning",
                "title": m["name"],
                "progress_percent": m.get("progress_percent"),
                "target": m.get("target"),
                "current": m.get("current")
            })

    # Sort by severity (critical first)
    risks.sort(key=lambda x: 0 if x["severity"] == "critical" else 1)

    return risks


def executive_dashboard(user_id: str) -> dict:
    """Generate executive dashboard."""
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "course_progress": get_course_progress_summary(user_id),
        "active_plans": get_active_plans_summary(user_id),
        "actions": get_actions_summary(user_id),
        "metrics": get_metrics_summary(user_id),
        "key_risks": get_key_risks(user_id),
        "api_version": "1.5.0"
    }
