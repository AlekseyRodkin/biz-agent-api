"""Export module: decisions, actions, metrics, plans in JSON/CSV/MD formats."""
import csv
import io
from datetime import datetime
from app.db.supabase_client import get_client

API_VERSION = "1.5.0"


def _export_metadata(user_id: str) -> dict:
    """Generate export metadata."""
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "api_version": API_VERSION,
        "user_id": user_id
    }


def _to_csv(data: list[dict], fields: list[str]) -> str:
    """Convert list of dicts to CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in data:
        # Flatten nested values
        flat_row = {k: str(v) if v is not None else "" for k, v in row.items()}
        writer.writerow(flat_row)
    return output.getvalue()


def _to_markdown_table(data: list[dict], fields: list[str], title: str) -> str:
    """Convert list of dicts to Markdown table."""
    lines = [f"# {title}", "", f"*Exported: {datetime.utcnow().isoformat()}*", ""]

    if not data:
        lines.append("*No data*")
        return "\n".join(lines)

    # Header
    header = "| " + " | ".join(fields) + " |"
    separator = "| " + " | ".join(["---"] * len(fields)) + " |"
    lines.append(header)
    lines.append(separator)

    # Rows
    for row in data:
        values = []
        for f in fields:
            val = row.get(f, "")
            if val is None:
                val = ""
            # Escape pipes and truncate long values
            val = str(val).replace("|", "\\|")[:100]
            values.append(val)
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


# --- Decisions Export ---

def export_decisions(user_id: str, format: str = "json") -> dict | str:
    """Export all decisions."""
    client = get_client()

    result = client.table("company_memory") \
        .select("id, memory_type, status, related_topic, user_decision_raw, user_decision_normalized, related_module, created_at, updated_at") \
        .eq("user_id", user_id) \
        .eq("memory_type", "decision") \
        .order("created_at", desc=True) \
        .execute()

    decisions = result.data or []

    # Simplify for export
    export_data = [
        {
            "id": str(d["id"]),
            "topic": d.get("related_topic", ""),
            "decision": d.get("user_decision_normalized") or d.get("user_decision_raw", "")[:200],
            "module": d.get("related_module"),
            "status": d.get("status", "active"),
            "created_at": d.get("created_at", "")
        }
        for d in decisions
    ]

    if format == "csv":
        return _to_csv(export_data, ["id", "topic", "decision", "module", "status", "created_at"])

    if format == "md":
        return _to_markdown_table(export_data, ["topic", "decision", "module", "status"], "Decisions Export")

    return {
        "metadata": _export_metadata(user_id),
        "total": len(export_data),
        "decisions": export_data
    }


# --- Actions Export ---

def export_actions(user_id: str, format: str = "json") -> dict | str:
    """Export all actions."""
    client = get_client()

    result = client.table("action_items") \
        .select("id, title, description, status, result, block_reason, day_range, sequence_order, metric_id, created_at, updated_at") \
        .eq("user_id", user_id) \
        .order("sequence_order", desc=False) \
        .execute()

    actions = result.data or []

    export_data = [
        {
            "id": str(a["id"]),
            "title": a.get("title", "")[:100],
            "status": a.get("status", "planned"),
            "day_range": a.get("day_range", ""),
            "result": (a.get("result") or "")[:100],
            "block_reason": a.get("block_reason") or "",
            "has_metric": "yes" if a.get("metric_id") else "no",
            "created_at": a.get("created_at", "")
        }
        for a in actions
    ]

    if format == "csv":
        return _to_csv(export_data, ["id", "title", "status", "day_range", "result", "block_reason", "has_metric", "created_at"])

    if format == "md":
        return _to_markdown_table(export_data, ["title", "status", "day_range", "result", "block_reason"], "Actions Export")

    return {
        "metadata": _export_metadata(user_id),
        "total": len(export_data),
        "actions": export_data
    }


# --- Metrics Export ---

def export_metrics(user_id: str, format: str = "json") -> dict | str:
    """Export all metrics with impact data."""
    client = get_client()

    result = client.table("metrics") \
        .select("id, name, description, scope, baseline_value, target_value, current_value, unit, status, created_at, updated_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .execute()

    metrics = result.data or []

    export_data = []
    for m in metrics:
        baseline = m.get("baseline_value")
        target = m.get("target_value")
        current = m.get("current_value")

        # Calculate delta and progress
        delta = None
        progress = None
        if baseline is not None and current is not None:
            delta = round(float(current) - float(baseline), 2)
        if baseline is not None and target is not None and current is not None:
            target_delta = float(target) - float(baseline)
            if target_delta != 0:
                progress = round(((float(current) - float(baseline)) / target_delta) * 100, 1)

        export_data.append({
            "id": str(m["id"]),
            "name": m.get("name", ""),
            "scope": m.get("scope", "company"),
            "baseline": baseline,
            "target": target,
            "current": current,
            "unit": m.get("unit") or "",
            "delta": delta,
            "progress_percent": progress,
            "status": m.get("status", "active"),
            "created_at": m.get("created_at", "")
        })

    if format == "csv":
        return _to_csv(export_data, ["id", "name", "scope", "baseline", "target", "current", "unit", "delta", "progress_percent", "status"])

    if format == "md":
        return _to_markdown_table(export_data, ["name", "baseline", "target", "current", "delta", "progress_percent", "status"], "Metrics Export")

    return {
        "metadata": _export_metadata(user_id),
        "total": len(export_data),
        "metrics": export_data
    }


# --- Plans Export ---

def export_plans(user_id: str, format: str = "json") -> dict | str:
    """Export all architect plans."""
    client = get_client()

    result = client.table("company_memory") \
        .select("id, related_topic, user_decision_raw, user_decision_normalized, status, created_at") \
        .eq("user_id", user_id) \
        .eq("memory_type", "architect_plan") \
        .order("created_at", desc=True) \
        .execute()

    plans = result.data or []

    export_data = [
        {
            "id": str(p["id"]),
            "title": p.get("related_topic", "План")[:100],
            "summary": (p.get("user_decision_normalized") or "")[:200],
            "status": p.get("status", "active"),
            "created_at": p.get("created_at", "")
        }
        for p in plans
    ]

    if format == "csv":
        return _to_csv(export_data, ["id", "title", "summary", "status", "created_at"])

    if format == "md":
        # For plans, include full content in MD
        lines = ["# Architect Plans Export", "", f"*Exported: {datetime.utcnow().isoformat()}*", ""]

        for p in plans:
            lines.append(f"## {p.get('related_topic', 'План')}")
            lines.append(f"*Status: {p.get('status', 'active')} | Created: {p.get('created_at', '')}*")
            lines.append("")
            content = p.get("user_decision_normalized") or p.get("user_decision_raw", "")
            lines.append(content[:1000])
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    return {
        "metadata": _export_metadata(user_id),
        "total": len(export_data),
        "plans": export_data
    }
