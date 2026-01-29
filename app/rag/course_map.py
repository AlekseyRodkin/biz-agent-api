"""Course map and navigation functions."""
from app.db.supabase_client import get_client


def get_course_map() -> dict:
    """
    Get full course structure: module → day → lectures.
    Only includes methodology lectures for navigation.
    Also aggregates chunk counts.
    """
    client = get_client()

    # Get all lectures
    lectures_result = client.table("course_lectures") \
        .select("lecture_id, module, day, lecture_order, lecture_title, speaker_name, speaker_type") \
        .order("module", desc=False) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .execute()

    lectures = lectures_result.data or []

    # Get chunk counts per lecture (with pagination)
    chunk_counts = {}
    offset = 0
    limit = 1000
    while True:
        result = client.table("course_chunks") \
            .select("lecture_id") \
            .range(offset, offset + limit - 1) \
            .execute()
        if not result.data:
            break
        for row in result.data:
            lid = row["lecture_id"]
            chunk_counts[lid] = chunk_counts.get(lid, 0) + 1
        if len(result.data) < limit:
            break
        offset += limit

    # Build hierarchical structure
    structure = {}
    total_methodology_lectures = 0
    total_methodology_chunks = 0

    for lec in lectures:
        module = lec["module"]
        day = lec["day"]
        is_methodology = lec["speaker_type"] == "methodology"

        if module not in structure:
            structure[module] = {"days": {}, "total_lectures": 0, "methodology_lectures": 0}

        if day not in structure[module]["days"]:
            structure[module]["days"][day] = {"lectures": []}

        lecture_info = {
            "lecture_id": lec["lecture_id"],
            "lecture_title": lec["lecture_title"],
            "speaker_name": lec["speaker_name"],
            "speaker_type": lec["speaker_type"],
            "lecture_order": lec["lecture_order"],
            "total_chunks": chunk_counts.get(lec["lecture_id"], 0),
            "is_methodology": is_methodology
        }

        structure[module]["days"][day]["lectures"].append(lecture_info)
        structure[module]["total_lectures"] += 1

        if is_methodology:
            structure[module]["methodology_lectures"] += 1
            total_methodology_lectures += 1
            total_methodology_chunks += chunk_counts.get(lec["lecture_id"], 0)

    return {
        "modules": structure,
        "summary": {
            "total_modules": len(structure),
            "total_methodology_lectures": total_methodology_lectures,
            "total_methodology_chunks": total_methodology_chunks,
            "total_lectures": len(lectures),
            "total_chunks": sum(chunk_counts.values())
        }
    }


def get_methodology_lectures_ordered() -> list[dict]:
    """Get all methodology lectures in correct order."""
    client = get_client()

    result = client.table("course_lectures") \
        .select("lecture_id, module, day, lecture_order, lecture_title") \
        .eq("speaker_type", "methodology") \
        .order("module", desc=False) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .execute()

    return result.data or []


def get_course_progress(user_id: str) -> dict:
    """
    Get user progress with percentages and preview.
    Navigation is based ONLY on methodology lectures.
    """
    client = get_client()

    # Get current progress
    progress_result = client.table("user_progress") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    progress = progress_result.data[0] if progress_result.data else None

    # Get all methodology lectures in order
    methodology_lectures = get_methodology_lectures_ordered()
    total_methodology = len(methodology_lectures)

    if not progress or not methodology_lectures:
        return {
            "started": False,
            "current": None,
            "completed_lectures": [],
            "next_lectures": methodology_lectures[:3] if methodology_lectures else [],
            "percent_methodology": 0,
            "percent_total": 0,
            "total_methodology_lectures": total_methodology
        }

    current_lecture_id = progress.get("current_lecture_id")
    current_seq = progress.get("current_sequence_order", 0)

    # Find current lecture index in methodology list
    current_index = -1
    for i, lec in enumerate(methodology_lectures):
        if lec["lecture_id"] == current_lecture_id:
            current_index = i
            break

    # Get chunk count in current lecture to calculate sub-progress
    current_lecture_chunks = 0
    if current_lecture_id:
        chunk_result = client.table("course_chunks") \
            .select("chunk_id", count="exact") \
            .eq("lecture_id", current_lecture_id) \
            .execute()
        current_lecture_chunks = chunk_result.count or 0

    # Completed lectures = all before current
    completed = methodology_lectures[:current_index] if current_index > 0 else []

    # Current lecture info
    current_lecture = methodology_lectures[current_index] if current_index >= 0 else None
    if current_lecture:
        current_lecture["current_chunk"] = current_seq
        current_lecture["total_chunks"] = current_lecture_chunks

    # Next lectures (after current)
    next_start = current_index + 1 if current_index >= 0 else 0
    next_lectures = methodology_lectures[next_start:next_start + 3]

    # Calculate percentages
    # completed_count = fully completed lectures
    # partial progress in current lecture
    completed_count = len(completed)
    partial = (current_seq / current_lecture_chunks) if current_lecture_chunks > 0 else 0

    # Methodology percent: (completed + partial) / total
    methodology_percent = ((completed_count + partial) / total_methodology * 100) if total_methodology > 0 else 0

    # Total course percent (same as methodology for now, since we track only methodology)
    total_percent = methodology_percent

    return {
        "started": True,
        "current": {
            "module": progress.get("current_module"),
            "day": progress.get("current_day"),
            "lecture_id": current_lecture_id,
            "lecture_title": current_lecture["lecture_title"] if current_lecture else None,
            "current_chunk": current_seq,
            "total_chunks": current_lecture_chunks,
            "lecture_index": current_index + 1,  # 1-based for display
            "total_lectures": total_methodology
        },
        "completed_lectures": [
            {"lecture_id": l["lecture_id"], "lecture_title": l["lecture_title"]}
            for l in completed
        ],
        "next_lectures": [
            {"lecture_id": l["lecture_id"], "lecture_title": l["lecture_title"], "module": l["module"], "day": l["day"]}
            for l in next_lectures
        ],
        "percent_methodology": round(methodology_percent, 1),
        "percent_total": round(total_percent, 1),
        "total_methodology_lectures": total_methodology
    }


def build_navigation_block(user_id: str) -> str:
    """Build navigation block for study response."""
    progress = get_course_progress(user_id)

    if not progress["started"]:
        return ""

    current = progress["current"]
    if not current:
        return ""

    lines = [
        "[НАВИГАЦИЯ ПО КУРСУ]",
        f"Ты сейчас: Модуль {current['module']} / День {current['day']} / Лекция: {current['lecture_title']}",
        f"Прогресс: {progress['percent_methodology']:.0f}% методологии ({current['lecture_index']}/{current['total_lectures']} лекций)"
    ]

    if progress["next_lectures"]:
        next_titles = [f"«{l['lecture_title']}»" for l in progress["next_lectures"][:2]]
        lines.append(f"Дальше: {' → '.join(next_titles)}")

    return "\n".join(lines)
