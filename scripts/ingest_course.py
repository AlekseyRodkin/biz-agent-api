#!/usr/bin/env python3
"""
Course ingestion script.
Reads lectures from manifest, chunks them, computes embeddings, uploads to Supabase.

Usage:
  python scripts/ingest_course.py                    # All lectures
  python scripts/ingest_course.py --module 1         # Module 1 only
  python scripts/ingest_course.py --lecture-id M1-D1-L02  # Single lecture
  python scripts/ingest_course.py --dry-run          # Preview only, no DB writes
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingest.chunker import chunk_text

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "lectures_manifest.csv")
COURSE_DIR = os.path.join(DATA_DIR, "course")


def read_manifest() -> list[dict]:
    """Read all lectures from manifest CSV."""
    lectures = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lectures.append(row)
    return lectures


def filter_lectures(lectures: list[dict], lecture_id: str = None, module: int = None) -> list[dict]:
    """Filter lectures by lecture_id or module."""
    if lecture_id:
        return [l for l in lectures if l["lecture_id"] == lecture_id]
    if module:
        return [l for l in lectures if int(l["module"]) == module]
    return lectures


def read_lecture_file(filename: str) -> str:
    """Read lecture text file."""
    filepath = os.path.join(COURSE_DIR, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Lecture file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def upsert_lecture(client, lecture: dict) -> None:
    """Upsert lecture metadata into course_lectures table."""
    client.table("course_lectures").upsert({
        "lecture_id": lecture["lecture_id"],
        "module": int(lecture["module"]),
        "day": int(lecture["day"]),
        "lecture_order": int(lecture["lecture_order"]),
        "lecture_title": lecture["lecture_title"],
        "speaker_name": lecture["speaker_name"],
        "speaker_type": lecture["speaker_type"],
        "source_file": lecture["source_file"]
    }, on_conflict="lecture_id").execute()


def delete_old_chunks(client, lecture_id: str) -> None:
    """Delete existing chunks for a lecture."""
    client.table("course_chunks").delete().eq("lecture_id", lecture_id).execute()


def insert_chunks(client, lecture: dict, chunks: list[dict], embed_fn) -> int:
    """Insert chunks with embeddings into course_chunks table."""
    if not chunks:
        return 0

    records = []
    for chunk in chunks:
        chunk_id = f"{lecture['lecture_id']}-{chunk['sequence_order']:04d}"
        embedding = embed_fn(chunk["content"])

        records.append({
            "chunk_id": chunk_id,
            "lecture_id": lecture["lecture_id"],
            "module": int(lecture["module"]),
            "day": int(lecture["day"]),
            "speaker_type": lecture["speaker_type"],
            "speaker_name": lecture["speaker_name"],
            "content_type": chunk["content_type"],
            "sequence_order": chunk["sequence_order"],
            "parent_topic": lecture["lecture_title"],
            "content": chunk["content"],
            "embedding": embedding,
            "metadata": {}
        })

    client.table("course_chunks").insert(records).execute()
    return len(records)


def process_lecture_dry_run(lecture: dict) -> dict:
    """Process lecture in dry-run mode (no DB writes)."""
    try:
        text = read_lecture_file(lecture["source_file"])
        chunks = list(chunk_text(text))
        content_types = {}
        for c in chunks:
            ct = c["content_type"]
            content_types[ct] = content_types.get(ct, 0) + 1
        return {
            "lecture_id": lecture["lecture_id"],
            "title": lecture["lecture_title"],
            "speaker_type": lecture["speaker_type"],
            "chunks": len(chunks),
            "content_types": content_types,
            "text_length": len(text),
            "error": None
        }
    except Exception as e:
        return {
            "lecture_id": lecture["lecture_id"],
            "title": lecture["lecture_title"],
            "speaker_type": lecture["speaker_type"],
            "chunks": 0,
            "content_types": {},
            "text_length": 0,
            "error": str(e)
        }


def ingest_lecture(client, lecture: dict, embed_fn) -> int:
    """Process single lecture: read, chunk, embed, upload."""
    print(f"  Processing: {lecture['lecture_id']} - {lecture['lecture_title']}")

    text = read_lecture_file(lecture["source_file"])
    chunks = list(chunk_text(text))

    upsert_lecture(client, lecture)
    delete_old_chunks(client, lecture["lecture_id"])
    count = insert_chunks(client, lecture, chunks, embed_fn)

    print(f"    -> {count} chunks created")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Ingest course lectures into Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ingest_course.py                    # All lectures
  python scripts/ingest_course.py --module 1         # Module 1 only
  python scripts/ingest_course.py --lecture-id M1-D1-L02  # Single lecture
  python scripts/ingest_course.py --dry-run          # Preview, no DB writes
        """
    )
    parser.add_argument("--lecture-id", type=str, help="Process single lecture by ID")
    parser.add_argument("--module", type=int, help="Process all lectures in module")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without writing to DB")
    args = parser.parse_args()

    print("Course Ingestion Pipeline")
    print("=" * 50)

    # Read and filter lectures
    all_lectures = read_manifest()
    lectures = filter_lectures(all_lectures, args.lecture_id, args.module)

    if not lectures:
        print("No lectures found matching criteria")
        return

    filter_desc = "all"
    if args.lecture_id:
        filter_desc = f"lecture_id={args.lecture_id}"
    elif args.module:
        filter_desc = f"module={args.module}"

    print(f"Manifest: {len(all_lectures)} total lectures")
    print(f"Filter: {filter_desc} -> {len(lectures)} lectures to process")

    if args.dry_run:
        print("\n[DRY-RUN MODE] No data will be written to database\n")
        print("-" * 50)

        total_chunks = 0
        by_speaker_type = {"methodology": 0, "case_study": 0}
        by_content_type = {"theory": 0, "assignment": 0, "example": 0, "tool": 0}
        errors = []

        for lecture in lectures:
            result = process_lecture_dry_run(lecture)
            if result["error"]:
                errors.append(result)
                print(f"  [ERROR] {result['lecture_id']}: {result['error']}")
            else:
                print(f"  {result['lecture_id']}: {result['chunks']} chunks ({result['text_length']} chars)")
                total_chunks += result["chunks"]
                by_speaker_type[result["speaker_type"]] = by_speaker_type.get(result["speaker_type"], 0) + result["chunks"]
                for ct, count in result["content_types"].items():
                    by_content_type[ct] = by_content_type.get(ct, 0) + count

        print("-" * 50)
        print(f"\nDRY-RUN SUMMARY:")
        print(f"  Lectures: {len(lectures)}")
        print(f"  Total chunks: {total_chunks}")
        print(f"  By speaker_type: {by_speaker_type}")
        print(f"  By content_type: {by_content_type}")
        if errors:
            print(f"  Errors: {len(errors)} lectures failed")
            for e in errors:
                print(f"    - {e['lecture_id']}: {e['error']}")
        return

    # Real ingestion
    from app.db.supabase_client import get_client
    from app.embeddings.embedder import embed_query

    client = get_client()
    total_chunks = 0
    errors = []

    for lecture in lectures:
        try:
            count = ingest_lecture(client, lecture, embed_query)
            total_chunks += count
        except Exception as e:
            print(f"    ERROR: {e}")
            errors.append({"lecture_id": lecture["lecture_id"], "error": str(e)})

    print("=" * 50)
    print(f"Done! Processed {len(lectures)} lectures, {total_chunks} total chunks")
    if errors:
        print(f"Errors: {len(errors)} lectures failed")
        for e in errors:
            print(f"  - {e['lecture_id']}: {e['error']}")


if __name__ == "__main__":
    main()
