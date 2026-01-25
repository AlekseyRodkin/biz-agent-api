#!/usr/bin/env python3
"""
Course QC (Quality Control) script.
Generates a report on loaded course data in Supabase.

Usage:
  python scripts/qc_course.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.supabase_client import get_client


def get_counts(client) -> dict:
    """Get total counts of lectures and chunks."""
    lectures = client.table("course_lectures").select("lecture_id", count="exact").execute()
    chunks = client.table("course_chunks").select("id", count="exact").execute()
    return {
        "lectures": lectures.count,
        "chunks": chunks.count
    }


def get_speaker_type_distribution(client) -> dict:
    """Get chunk distribution by speaker_type."""
    result = client.table("course_chunks").select("speaker_type").execute()
    dist = {}
    for row in result.data:
        st = row["speaker_type"]
        dist[st] = dist.get(st, 0) + 1
    return dist


def get_content_type_distribution(client) -> dict:
    """Get chunk distribution by content_type."""
    result = client.table("course_chunks").select("content_type").execute()
    dist = {}
    for row in result.data:
        ct = row["content_type"]
        dist[ct] = dist.get(ct, 0) + 1
    return dist


def get_top_lectures_by_chunks(client, limit: int = 10) -> list[dict]:
    """Get top N lectures by number of chunks."""
    result = client.table("course_chunks").select("lecture_id").execute()

    counts = {}
    for row in result.data:
        lid = row["lecture_id"]
        counts[lid] = counts.get(lid, 0) + 1

    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"lecture_id": k, "chunks": v} for k, v in sorted_counts[:limit]]


def get_lectures_with_zero_chunks(client) -> list[str]:
    """Find lectures that have zero chunks (bug indicator)."""
    lectures = client.table("course_lectures").select("lecture_id").execute()
    chunks = client.table("course_chunks").select("lecture_id").execute()

    all_lecture_ids = {l["lecture_id"] for l in lectures.data}
    lecture_ids_with_chunks = {c["lecture_id"] for c in chunks.data}

    zero_chunks = all_lecture_ids - lecture_ids_with_chunks
    return sorted(list(zero_chunks))


def get_methodology_order(client) -> list[dict]:
    """Get methodology lectures in correct order (module, day, lecture_order)."""
    result = client.table("course_lectures") \
        .select("lecture_id, module, day, lecture_order, lecture_title") \
        .eq("speaker_type", "methodology") \
        .order("module", desc=False) \
        .order("day", desc=False) \
        .order("lecture_order", desc=False) \
        .execute()
    return result.data


def main():
    print("=" * 60)
    print("COURSE QC REPORT")
    print("=" * 60)

    client = get_client()

    # 1. Total counts
    counts = get_counts(client)
    print(f"\n1. TOTAL COUNTS")
    print(f"   Lectures: {counts['lectures']}")
    print(f"   Chunks:   {counts['chunks']}")

    # 2. Speaker type distribution
    speaker_dist = get_speaker_type_distribution(client)
    print(f"\n2. CHUNKS BY SPEAKER_TYPE")
    for st, count in sorted(speaker_dist.items()):
        pct = (count / counts['chunks'] * 100) if counts['chunks'] > 0 else 0
        print(f"   {st}: {count} ({pct:.1f}%)")

    # 3. Content type distribution
    content_dist = get_content_type_distribution(client)
    print(f"\n3. CHUNKS BY CONTENT_TYPE")
    for ct, count in sorted(content_dist.items()):
        pct = (count / counts['chunks'] * 100) if counts['chunks'] > 0 else 0
        print(f"   {ct}: {count} ({pct:.1f}%)")

    # 4. Top 10 lectures by chunks
    top_lectures = get_top_lectures_by_chunks(client, 10)
    print(f"\n4. TOP-10 LECTURES BY CHUNK COUNT")
    for i, lec in enumerate(top_lectures, 1):
        print(f"   {i:2d}. {lec['lecture_id']}: {lec['chunks']} chunks")

    # 5. Lectures with zero chunks
    zero_chunk_lectures = get_lectures_with_zero_chunks(client)
    print(f"\n5. LECTURES WITH ZERO CHUNKS")
    if zero_chunk_lectures:
        print(f"   [BUG!] Found {len(zero_chunk_lectures)} lectures with no chunks:")
        for lid in zero_chunk_lectures:
            print(f"   - {lid}")
    else:
        print("   All lectures have at least one chunk. OK!")

    # 6. Methodology order
    methodology = get_methodology_order(client)
    print(f"\n6. METHODOLOGY LECTURES ORDER (Study mode sequence)")
    print(f"   Total methodology lectures: {len(methodology)}")
    for i, lec in enumerate(methodology, 1):
        print(f"   {i:2d}. M{lec['module']}-D{lec['day']}-L{lec['lecture_order']:02d} {lec['lecture_id']}: {lec['lecture_title']}")

    print("\n" + "=" * 60)
    print("QC REPORT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
