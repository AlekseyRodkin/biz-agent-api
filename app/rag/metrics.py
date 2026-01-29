"""Metrics and outcomes tracking."""
from datetime import datetime
from typing import Optional
from app.db.supabase_client import get_client


def create_metric(
    user_id: str,
    name: str,
    description: Optional[str] = None,
    scope: str = "company",
    baseline_value: Optional[float] = None,
    target_value: Optional[float] = None,
    current_value: Optional[float] = None,
    unit: Optional[str] = None,
    related_plan_id: Optional[str] = None
) -> dict:
    """Create a new metric."""
    client = get_client()

    record = {
        "user_id": user_id,
        "name": name,
        "description": description,
        "scope": scope,
        "baseline_value": baseline_value,
        "target_value": target_value,
        "current_value": current_value if current_value is not None else baseline_value,
        "unit": unit,
        "related_plan_id": related_plan_id,
        "status": "active"
    }

    result = client.table("metrics").insert(record).execute()
    return result.data[0] if result.data else None


def get_metrics(user_id: str, status: Optional[str] = None) -> list[dict]:
    """Get all metrics for user, optionally filtered by status."""
    client = get_client()

    query = client.table("metrics") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True)

    if status:
        query = query.eq("status", status)

    result = query.execute()
    return result.data or []


def get_metric(user_id: str, metric_id: str) -> Optional[dict]:
    """Get a single metric by ID."""
    client = get_client()

    result = client.table("metrics") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("id", metric_id) \
        .single() \
        .execute()

    return result.data


def update_metric_value(user_id: str, metric_id: str, current_value: float) -> Optional[dict]:
    """Update the current value of a metric."""
    client = get_client()

    result = client.table("metrics") \
        .update({
            "current_value": current_value,
            "updated_at": datetime.utcnow().isoformat()
        }) \
        .eq("user_id", user_id) \
        .eq("id", metric_id) \
        .execute()

    if result.data:
        # Check if target achieved
        metric = result.data[0]
        if metric.get("target_value") is not None:
            target = float(metric["target_value"])
            current = float(current_value)
            baseline = float(metric.get("baseline_value") or 0)

            # Determine direction (improvement = moving from baseline toward target)
            if target > baseline:
                # Higher is better
                if current >= target:
                    _set_metric_status(client, metric_id, "achieved")
            else:
                # Lower is better
                if current <= target:
                    _set_metric_status(client, metric_id, "achieved")

        return result.data[0]
    return None


def _set_metric_status(client, metric_id: str, status: str):
    """Internal: set metric status."""
    client.table("metrics") \
        .update({"status": status, "updated_at": datetime.utcnow().isoformat()}) \
        .eq("id", metric_id) \
        .execute()


def abandon_metric(user_id: str, metric_id: str) -> Optional[dict]:
    """Mark metric as abandoned."""
    client = get_client()

    result = client.table("metrics") \
        .update({
            "status": "abandoned",
            "updated_at": datetime.utcnow().isoformat()
        }) \
        .eq("user_id", user_id) \
        .eq("id", metric_id) \
        .execute()

    return result.data[0] if result.data else None


def calculate_impact(user_id: str) -> dict:
    """Calculate impact across all active metrics."""
    client = get_client()

    # Get all metrics (active and achieved)
    result = client.table("metrics") \
        .select("*") \
        .eq("user_id", user_id) \
        .in_("status", ["active", "achieved"]) \
        .order("created_at", desc=True) \
        .execute()

    metrics = result.data or []

    impact_list = []
    summary = {
        "total": len(metrics),
        "on_track": 0,
        "off_track": 0,
        "exceeded": 0,
        "no_target": 0
    }

    for m in metrics:
        baseline = m.get("baseline_value")
        target = m.get("target_value")
        current = m.get("current_value")

        impact_item = {
            "id": str(m["id"]),
            "name": m["name"],
            "unit": m.get("unit", ""),
            "baseline": baseline,
            "target": target,
            "current": current,
            "delta": None,
            "delta_percent": None,
            "progress_percent": None,
            "status": "no_target"
        }

        # Calculate delta from baseline
        if baseline is not None and current is not None:
            delta = float(current) - float(baseline)
            impact_item["delta"] = round(delta, 2)
            if float(baseline) != 0:
                impact_item["delta_percent"] = round((delta / float(baseline)) * 100, 1)

        # Calculate status relative to target
        if target is not None and baseline is not None and current is not None:
            target_f = float(target)
            baseline_f = float(baseline)
            current_f = float(current)

            # Determine direction
            target_delta = target_f - baseline_f
            current_delta = current_f - baseline_f

            if target_delta == 0:
                # Target equals baseline, check if maintained
                if current_f == target_f:
                    impact_item["status"] = "on_track"
                    impact_item["progress_percent"] = 100.0
                    summary["on_track"] += 1
                else:
                    impact_item["status"] = "off_track"
                    impact_item["progress_percent"] = 0.0
                    summary["off_track"] += 1
            else:
                progress = (current_delta / target_delta) * 100
                impact_item["progress_percent"] = round(progress, 1)

                if progress >= 100:
                    impact_item["status"] = "exceeded" if progress > 100 else "on_track"
                    summary["exceeded" if progress > 100 else "on_track"] += 1
                elif progress >= 70:
                    impact_item["status"] = "on_track"
                    summary["on_track"] += 1
                else:
                    impact_item["status"] = "off_track"
                    summary["off_track"] += 1
        else:
            summary["no_target"] += 1

        impact_list.append(impact_item)

    return {
        "metrics": impact_list,
        "summary": summary
    }


def get_metrics_for_weekly(user_id: str) -> str:
    """Get metrics context for weekly review."""
    impact = calculate_impact(user_id)

    if not impact["metrics"]:
        return ""

    lines = ["[ЭФФЕКТ ЗА НЕДЕЛЮ]"]

    for m in impact["metrics"]:
        name = m["name"]
        unit = m.get("unit") or ""
        delta = m.get("delta")
        delta_pct = m.get("delta_percent")
        status = m["status"]

        if delta is not None:
            if delta_pct is not None:
                if delta >= 0:
                    change_str = f"+{delta_pct}%"
                else:
                    change_str = f"{delta_pct}%"
            else:
                if delta >= 0:
                    change_str = f"+{delta} {unit}".strip()
                else:
                    change_str = f"{delta} {unit}".strip()

            status_emoji = "✅" if status in ["on_track", "exceeded"] else "⚠️" if status == "off_track" else ""
            lines.append(f"- {name}: {change_str} {status_emoji}")
        else:
            lines.append(f"- {name}: без изменений")

    return "\n".join(lines)


def link_action_to_metric(user_id: str, action_id: str, metric_id: str) -> Optional[dict]:
    """Link an action item to a metric."""
    client = get_client()

    result = client.table("action_items") \
        .update({
            "metric_id": metric_id,
            "updated_at": datetime.utcnow().isoformat()
        }) \
        .eq("user_id", user_id) \
        .eq("id", action_id) \
        .execute()

    return result.data[0] if result.data else None


def get_metrics_for_action(user_id: str, action_id: str) -> Optional[dict]:
    """Get the metric linked to an action."""
    client = get_client()

    # Get action with metric_id
    action = client.table("action_items") \
        .select("metric_id") \
        .eq("user_id", user_id) \
        .eq("id", action_id) \
        .single() \
        .execute()

    if not action.data or not action.data.get("metric_id"):
        return None

    # Get metric
    metric = client.table("metrics") \
        .select("*") \
        .eq("id", action.data["metric_id"]) \
        .single() \
        .execute()

    return metric.data
