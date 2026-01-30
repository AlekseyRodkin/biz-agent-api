#!/usr/bin/env python3
"""
Course ingestion script.
Reads lectures from manifest, chunks them, computes embeddings, uploads to Supabase.

IMPORTANT: This script requires real course data:
- data/lectures_manifest.csv (manifest file)
- data/course/*.txt (lecture text files)

DISCIPLINE: Writing to Supabase requires explicit --force flag.
Without --force, only validation and dry-run are allowed.

Usage:
  python scripts/ingest_course.py --validate           # Validate manifest and files
  python scripts/ingest_course.py --dry-run            # Preview chunks, no DB writes
  python scripts/ingest_course.py --dry-run --stats    # Detailed chunking statistics
  python scripts/ingest_course.py --force              # Actually write to Supabase
  python scripts/ingest_course.py --force --module 1   # Module 1 only
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "lectures_manifest.csv")
COURSE_DIR = os.path.join(DATA_DIR, "course")


def check_manifest_exists() -> bool:
    """Check if manifest file exists."""
    return os.path.exists(MANIFEST_PATH)


def read_manifest() -> list[dict]:
    """Read all lectures from manifest CSV."""
    if not check_manifest_exists():
        return []
    lectures = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lectures.append(row)
    return lectures


def check_lecture_files(lectures: list[dict]) -> tuple[list[str], list[str]]:
    """Check which lecture files exist and which are missing.
    Returns (found_files, missing_files).
    """
    found = []
    missing = []
    for lecture in lectures:
        filepath = os.path.join(COURSE_DIR, lecture["source_file"])
        if os.path.exists(filepath):
            found.append(lecture["source_file"])
        else:
            missing.append(lecture["source_file"])
    return found, missing


def validate_manifest(lectures: list[dict]) -> dict:
    """Validate manifest and return diagnostics."""
    if not lectures:
        return {
            "valid": False,
            "total_rows": 0,
            "unique_lecture_ids": 0,
            "speaker_type_distribution": {},
            "module_distribution": {},
            "found_files": [],
            "missing_files": [],
            "errors": ["Manifest is empty or not found"]
        }

    # Count unique lecture_ids
    lecture_ids = [l["lecture_id"] for l in lectures]
    unique_ids = set(lecture_ids)

    # Speaker type distribution
    speaker_dist = {}
    for l in lectures:
        st = l.get("speaker_type", "unknown")
        speaker_dist[st] = speaker_dist.get(st, 0) + 1

    # Module distribution
    module_dist = {}
    for l in lectures:
        m = l.get("module", "unknown")
        module_dist[m] = module_dist.get(m, 0) + 1

    # Check files
    found, missing = check_lecture_files(lectures)

    errors = []
    if len(unique_ids) != len(lecture_ids):
        errors.append(f"Duplicate lecture_ids found: {len(lecture_ids) - len(unique_ids)} duplicates")
    if missing:
        errors.append(f"Missing files: {len(missing)}")

    return {
        "valid": len(missing) == 0 and len(errors) == 0,
        "total_rows": len(lectures),
        "unique_lecture_ids": len(unique_ids),
        "speaker_type_distribution": speaker_dist,
        "module_distribution": module_dist,
        "found_files": found,
        "missing_files": missing,
        "errors": errors
    }


def print_validation_report(validation: dict) -> None:
    """Print validation report."""
    print("=" * 50)
    print("MANIFEST VALIDATION REPORT")
    print("=" * 50)

    if validation["total_rows"] == 0:
        print("\n❌ VALIDATION FAILED")
        print("   Manifest is empty or not found")
        print(f"   Expected: {MANIFEST_PATH}")
        return

    print(f"\nManifest: {MANIFEST_PATH}")
    print(f"  Total rows: {validation['total_rows']}")
    print(f"  Unique lecture_ids: {validation['unique_lecture_ids']}")

    print(f"\nSpeaker type distribution:")
    for st, count in sorted(validation["speaker_type_distribution"].items()):
        pct = (count / validation["total_rows"] * 100)
        print(f"  {st}: {count} ({pct:.1f}%)")

    print(f"\nModule distribution:")
    for m, count in sorted(validation["module_distribution"].items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        print(f"  Module {m}: {count} lectures")

    print(f"\nFile check:")
    print(f"  Found: {len(validation['found_files'])} files")
    print(f"  Missing: {len(validation['missing_files'])} files")

    if validation["missing_files"]:
        print(f"\nMissing files:")
        for f in validation["missing_files"][:10]:
            print(f"  - {f}")
        if len(validation["missing_files"]) > 10:
            print(f"  ... and {len(validation['missing_files']) - 10} more")

    if validation["errors"]:
        print(f"\n❌ VALIDATION FAILED")
        for err in validation["errors"]:
            print(f"   - {err}")
    else:
        print(f"\n✅ VALIDATION PASSED")
        print("   Ready for ingestion (use --force to write to DB)")


def strict_pre_checks() -> tuple[bool, str]:
    """Perform strict pre-checks before ingestion.
    Returns (success, error_message).
    """
    # Check manifest exists
    if not check_manifest_exists():
        return False, f"Manifest not found: {MANIFEST_PATH}"

    # Read manifest
    lectures = read_manifest()
    if not lectures:
        return False, "Manifest is empty (no lectures)"

    # Check all files exist
    _, missing = check_lecture_files(lectures)
    if missing:
        return False, f"Missing {len(missing)} lecture files. Run --validate for details."

    return True, ""


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


def process_lecture_dry_run(lecture: dict, show_stats: bool = False) -> dict:
    """Process lecture in dry-run mode (no DB writes)."""
    from app.ingest.chunker import chunk_text, get_chunking_stats

    try:
        text = read_lecture_file(lecture["source_file"])

        if show_stats:
            stats = get_chunking_stats(text)
            return {
                "lecture_id": lecture["lecture_id"],
                "title": lecture["lecture_title"],
                "speaker_type": lecture["speaker_type"],
                "source_file": lecture["source_file"],
                "text_length": stats["text_length"],
                "paragraph_count": stats["paragraph_count"],
                "chunk_count": stats["chunk_count"],
                "min_chunk_size": stats["min_chunk_size"],
                "avg_chunk_size": stats["avg_chunk_size"],
                "max_chunk_size": stats["max_chunk_size"],
                "content_types": stats["content_types"],
                "error": stats.get("error")
            }
        else:
            # Pass speaker_type for content_type detection
            speaker_type = lecture.get("speaker_type", "methodology")
            chunks = list(chunk_text(text, validate=False, speaker_type=speaker_type))
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


def ingest_lecture(client, lecture: dict, embed_fn, chunk_fn) -> int:
    """Process single lecture: read, chunk, embed, upload."""
    print(f"  Processing: {lecture['lecture_id']} - {lecture['lecture_title']}")

    text = read_lecture_file(lecture["source_file"])
    # Pass speaker_type for content_type detection (student_comment only for methodology)
    speaker_type = lecture.get("speaker_type", "methodology")
    chunks = list(chunk_fn(text, speaker_type=speaker_type))

    upsert_lecture(client, lecture)
    delete_old_chunks(client, lecture["lecture_id"])
    count = insert_chunks(client, lecture, chunks, embed_fn)

    print(f"    -> {count} chunks created")
    return count


def print_stats_table(results: list[dict]) -> None:
    """Print detailed statistics table."""
    print("\n" + "=" * 120)
    print("CHUNKING STATISTICS")
    print("=" * 120)
    print(f"{'Lecture ID':<15} {'Type':<12} {'Text':<8} {'Paras':<6} {'Chunks':<7} {'Min':<6} {'Avg':<6} {'Max':<6} {'File'}")
    print("-" * 120)

    total_chunks = 0
    total_text = 0

    for r in results:
        if r.get("error"):
            print(f"{r['lecture_id']:<15} ERROR: {r['error']}")
            continue

        total_chunks += r.get("chunk_count", r.get("chunks", 0))
        total_text += r.get("text_length", 0)

        if "chunk_count" in r:  # stats mode
            print(f"{r['lecture_id']:<15} {r['speaker_type']:<12} {r['text_length']:<8} {r['paragraph_count']:<6} {r['chunk_count']:<7} {r['min_chunk_size']:<6} {r['avg_chunk_size']:<6} {r['max_chunk_size']:<6} {r['source_file'][:40]}")
        else:  # simple mode
            print(f"{r['lecture_id']:<15} {r['speaker_type']:<12} {r['text_length']:<8} {'N/A':<6} {r['chunks']:<7}")

    print("-" * 120)
    print(f"TOTAL: {len(results)} lectures, {total_text:,} chars, {total_chunks} chunks")
    if total_chunks > 0:
        print(f"Average: {total_text // total_chunks} chars/chunk, {total_chunks / len(results):.1f} chunks/lecture")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest course lectures into Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ingest_course.py --validate           # Validate manifest
  python scripts/ingest_course.py --dry-run            # Preview chunks
  python scripts/ingest_course.py --dry-run --stats    # Detailed statistics
  python scripts/ingest_course.py --force              # Write to Supabase
  python scripts/ingest_course.py --force --module 1   # Module 1 only

IMPORTANT:
- Requires real course data in data/ directory
- Writing to Supabase requires --force flag
- Without --force, only validation and dry-run are allowed
        """
    )
    parser.add_argument("--validate", action="store_true", help="Validate manifest and files only")
    parser.add_argument("--lecture-id", type=str, help="Process single lecture by ID")
    parser.add_argument("--module", type=int, help="Process all lectures in module")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without writing to DB")
    parser.add_argument("--stats", action="store_true", help="Show detailed chunking statistics (use with --dry-run)")
    parser.add_argument("--force", action="store_true", help="Actually write to Supabase (REQUIRED for ingestion)")
    args = parser.parse_args()

    # Validate mode
    if args.validate:
        lectures = read_manifest()
        validation = validate_manifest(lectures)
        print_validation_report(validation)
        sys.exit(0 if validation["valid"] else 1)

    # If neither --dry-run nor --force, show help
    if not args.dry_run and not args.force:
        print("=" * 50)
        print("INGESTION DISCIPLINE")
        print("=" * 50)
        print("\n⚠️  No action specified.")
        print("\nAvailable modes:")
        print("  --validate     Check manifest and files")
        print("  --dry-run      Preview chunks (no DB writes)")
        print("  --dry-run --stats  Detailed chunking statistics")
        print("  --force        Write to Supabase")
        print("\n❌ Without --force, NO data will be written to Supabase.")
        sys.exit(1)

    # Strict pre-checks
    print("Course Ingestion Pipeline")
    print("=" * 50)

    success, error = strict_pre_checks()
    if not success:
        print(f"\n❌ PRE-CHECK FAILED: {error}")
        print("\nRun with --validate for detailed diagnostics.")
        sys.exit(1)

    # Read and filter lectures
    all_lectures = read_manifest()
    lectures = filter_lectures(all_lectures, args.lecture_id, args.module)

    if not lectures:
        print("No lectures found matching criteria")
        sys.exit(1)

    filter_desc = "all"
    if args.lecture_id:
        filter_desc = f"lecture_id={args.lecture_id}"
    elif args.module:
        filter_desc = f"module={args.module}"

    print(f"Manifest: {len(all_lectures)} total lectures")
    print(f"Filter: {filter_desc} -> {len(lectures)} lectures to process")

    # DRY-RUN mode
    if args.dry_run:
        print("\n[DRY-RUN MODE] No data will be written to database\n")
        print("-" * 50)

        results = []
        for lecture in lectures:
            result = process_lecture_dry_run(lecture, show_stats=args.stats)
            results.append(result)
            if result.get("error"):
                print(f"  [ERROR] {result['lecture_id']}: {result['error']}")
            elif args.stats:
                print(f"  {result['lecture_id']}: {result['chunk_count']} chunks, {result['text_length']} chars")
            else:
                print(f"  {result['lecture_id']}: {result['chunks']} chunks ({result['text_length']} chars)")

        if args.stats:
            print_stats_table(results)
        else:
            print("-" * 50)
            total_chunks = sum(r.get("chunks", r.get("chunk_count", 0)) for r in results if not r.get("error"))
            errors = [r for r in results if r.get("error")]
            print(f"\nDRY-RUN SUMMARY:")
            print(f"  Lectures: {len(lectures)}")
            print(f"  Total chunks: {total_chunks}")
            if errors:
                print(f"  Errors: {len(errors)} lectures failed")

        print("\n💡 To write to Supabase, run with --force")
        return

    # FORCE mode - actual ingestion
    if args.force:
        print("\n⚠️  [FORCE MODE] Writing to Supabase database\n")

        from app.db.supabase_client import get_client
        from app.embeddings.embedder import embed_query
        from app.ingest.chunker import chunk_text

        client = get_client()
        total_chunks = 0
        errors = []

        for lecture in lectures:
            try:
                count = ingest_lecture(client, lecture, embed_query, chunk_text)
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
