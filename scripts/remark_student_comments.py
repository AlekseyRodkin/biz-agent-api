#!/usr/bin/env python3
"""
Remark existing chunks with student_comment content_type.

Finds chunks in course_chunks that match STUDENT_MARKERS
and updates their content_type to 'student_comment'.

Usage:
    python scripts/remark_student_comments.py --dry-run
    python scripts/remark_student_comments.py --apply
"""

import argparse
import re
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.supabase_client import get_client

STUDENT_MARKERS = re.compile(
    r'\b(вопрос из зала|студент[ыа]?|участник[иа]?|у нас проект|мы сделали|наш кейс|'
    r'у меня вопрос|в нашей компании|мы внедрили|наша команда|наш опыт)\b',
    re.IGNORECASE
)


def find_student_comment_chunks(client) -> list[dict]:
    """Find methodology chunks that contain student markers."""
    # Get all methodology chunks that are not already student_comment
    result = client.table("course_chunks") \
        .select("chunk_id, content, content_type, speaker_type") \
        .eq("speaker_type", "methodology") \
        .neq("content_type", "student_comment") \
        .execute()

    matching = []
    for chunk in result.data or []:
        if STUDENT_MARKERS.search(chunk["content"]):
            matching.append(chunk)

    return matching


def remark_chunks(client, chunk_ids: list[str]) -> int:
    """Update content_type to student_comment for given chunk_ids."""
    if not chunk_ids:
        return 0

    result = client.table("course_chunks") \
        .update({"content_type": "student_comment"}) \
        .in_("chunk_id", chunk_ids) \
        .execute()

    return len(result.data) if result.data else 0


def main():
    parser = argparse.ArgumentParser(description="Remark student comment chunks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    parser.add_argument("--apply", action="store_true", help="Actually update the database")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Error: specify --dry-run or --apply")
        sys.exit(1)

    client = get_client()

    print("Finding chunks with student markers...")
    matching = find_student_comment_chunks(client)

    print(f"\nFound {len(matching)} chunks to remark as student_comment:\n")

    for chunk in matching:
        # Find the matching marker for display
        match = STUDENT_MARKERS.search(chunk["content"])
        marker = match.group(0) if match else "?"
        preview = chunk["content"][:100].replace("\n", " ")
        print(f"  {chunk['chunk_id']}: [{marker}] {preview}...")

    if args.dry_run:
        print(f"\n[DRY RUN] Would update {len(matching)} chunks")
        return

    if args.apply:
        chunk_ids = [c["chunk_id"] for c in matching]
        updated = remark_chunks(client, chunk_ids)
        print(f"\n[APPLIED] Updated {updated} chunks to content_type='student_comment'")


if __name__ == "__main__":
    main()
