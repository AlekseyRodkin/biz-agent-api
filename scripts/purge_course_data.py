#!/usr/bin/env python3
"""
Purge all course data from Supabase.
Deletes all records from course_chunks and course_lectures tables.

Usage:
  python scripts/purge_course_data.py          # Show counts only (dry-run)
  python scripts/purge_course_data.py --force  # Actually delete data
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.supabase_client import get_client


def get_counts(client) -> dict:
    """Get current counts of lectures and chunks."""
    lectures = client.table("course_lectures").select("lecture_id", count="exact").execute()
    chunks = client.table("course_chunks").select("id", count="exact").execute()
    return {
        "lectures": lectures.count or 0,
        "chunks": chunks.count or 0
    }


def purge_data(client) -> dict:
    """Delete all course data. Returns counts before deletion."""
    # Get counts before
    before = get_counts(client)

    # Delete chunks first (FK constraint)
    client.table("course_chunks").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # Delete lectures
    client.table("course_lectures").delete().neq("lecture_id", "").execute()

    # Get counts after
    after = get_counts(client)

    return {
        "before": before,
        "after": after,
        "deleted_lectures": before["lectures"] - after["lectures"],
        "deleted_chunks": before["chunks"] - after["chunks"]
    }


def main():
    parser = argparse.ArgumentParser(
        description="Purge course data from Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/purge_course_data.py          # Show counts (dry-run)
  python scripts/purge_course_data.py --force  # Delete all data
        """
    )
    parser.add_argument("--force", action="store_true", help="Actually delete data (default is dry-run)")
    args = parser.parse_args()

    print("=" * 50)
    print("COURSE DATA PURGE")
    print("=" * 50)

    client = get_client()
    counts = get_counts(client)

    print(f"\nCurrent counts:")
    print(f"  course_lectures: {counts['lectures']}")
    print(f"  course_chunks:   {counts['chunks']}")

    if not args.force:
        print("\n[DRY-RUN] No data deleted.")
        print("Use --force to actually delete data.")
        return

    if counts["lectures"] == 0 and counts["chunks"] == 0:
        print("\nNo data to delete. Tables are already empty.")
        return

    print("\n⚠️  DELETING ALL COURSE DATA...")
    result = purge_data(client)

    print(f"\n✅ Purge complete!")
    print(f"  Deleted lectures: {result['deleted_lectures']}")
    print(f"  Deleted chunks:   {result['deleted_chunks']}")
    print(f"\nCounts after purge:")
    print(f"  course_lectures: {result['after']['lectures']}")
    print(f"  course_chunks:   {result['after']['chunks']}")


if __name__ == "__main__":
    main()
