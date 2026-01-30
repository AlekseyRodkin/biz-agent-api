#!/usr/bin/env python3
"""
Clean lecture content: remove timecodes and tech noise.

Usage:
    python scripts/clean_lecture.py --lecture-id M1-D1-L05 --dry-run
    python scripts/clean_lecture.py --lecture-id M1-D1-L05 --apply
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.supabase_client import get_client

# Timecode patterns: 00:12:34, [00:12:34], 12:34, (00:12:34)
TIMECODE_PATTERNS = [
    re.compile(r'\[?\(?\d{1,2}:\d{2}(:\d{2})?\]?\)?'),
]

# Tech noise phrases (case insensitive)
# NOTE: Patterns must be specific to avoid false positives
TECH_NOISE_PHRASES = [
    # Audio/video checks (specific phrases only)
    r'слышно ли меня\??',
    r'меня слышно\??',
    r'вы меня слышите\??',
    r'включите микрофон',
    r'выключите микрофон',
    # Zoom/online specific
    r'подключитесь.*zoom',
    r'в zoom.*подключ',
    r'через zoom',
    # Chat instructions
    r'напишите в чат',
    r'пишите в чатик',
    r'в чатик напишите',
    # Session start phrases
    r'^раз,?\s*два,?\s*три',
    r'проверка связи',
]

TECH_NOISE_COMPILED = [re.compile(p, re.IGNORECASE) for p in TECH_NOISE_PHRASES]


def clean_timecodes(text: str) -> str:
    """Remove timecodes from text."""
    result = text
    for pattern in TIMECODE_PATTERNS:
        result = pattern.sub('', result)
    return result


def clean_tech_noise(text: str) -> str:
    """Remove lines containing tech noise phrases."""
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        # Check if line contains tech noise
        is_noise = False
        for pattern in TECH_NOISE_COMPILED:
            if pattern.search(line):
                is_noise = True
                break

        if not is_noise:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace: remove extra spaces and blank lines."""
    # Replace multiple spaces with single space
    text = re.sub(r'[ \t]+', ' ', text)
    # Replace multiple newlines with double newline (preserve paragraphs)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    # Strip lines
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


def clean_content(text: str) -> str:
    """Apply all cleaning steps."""
    result = text
    result = clean_timecodes(result)
    result = clean_tech_noise(result)
    result = normalize_whitespace(result)
    return result


def get_lecture_chunks(client, lecture_id: str) -> list[dict]:
    """Get all chunks for a lecture."""
    result = client.table("course_chunks") \
        .select("chunk_id, content, clean_content") \
        .eq("lecture_id", lecture_id) \
        .order("sequence_order") \
        .execute()
    return result.data or []


def update_clean_content(client, chunk_id: str, clean_text: str) -> bool:
    """Update clean_content for a chunk."""
    result = client.table("course_chunks") \
        .update({"clean_content": clean_text}) \
        .eq("chunk_id", chunk_id) \
        .execute()
    return len(result.data) > 0 if result.data else False


def main():
    parser = argparse.ArgumentParser(description="Clean lecture content")
    parser.add_argument("--lecture-id", required=True, help="Lecture ID to clean (e.g., M1-D1-L05)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned")
    parser.add_argument("--apply", action="store_true", help="Apply cleaning to database")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Error: specify --dry-run or --apply")
        sys.exit(1)

    client = get_client()
    chunks = get_lecture_chunks(client, args.lecture_id)

    if not chunks:
        print(f"No chunks found for lecture {args.lecture_id}")
        sys.exit(1)

    print(f"Lecture: {args.lecture_id}")
    print(f"Chunks: {len(chunks)}")
    print()

    total_raw_chars = 0
    total_clean_chars = 0

    for chunk in chunks:
        raw = chunk["content"]
        cleaned = clean_content(raw)

        total_raw_chars += len(raw)
        total_clean_chars += len(cleaned)

        diff = len(raw) - len(cleaned)
        if diff > 0:
            print(f"{chunk['chunk_id']}: {len(raw)} -> {len(cleaned)} chars (-{diff})")
            if args.dry_run:
                # Show first difference
                for i, (r, c) in enumerate(zip(raw[:200], cleaned[:200])):
                    if r != c:
                        print(f"  First diff at pos {i}")
                        print(f"  Raw:   ...{raw[max(0,i-20):i+50]}...")
                        print(f"  Clean: ...{cleaned[max(0,i-20):i+50]}...")
                        break

        if args.apply:
            update_clean_content(client, chunk["chunk_id"], cleaned)

    print()
    reduction = total_raw_chars - total_clean_chars
    pct = (reduction / total_raw_chars * 100) if total_raw_chars > 0 else 0
    print(f"Total: {total_raw_chars} -> {total_clean_chars} chars ({reduction} removed, {pct:.1f}%)")

    if args.dry_run:
        print("\n[DRY RUN] No changes made")
    elif args.apply:
        print(f"\n[APPLIED] Updated {len(chunks)} chunks")


if __name__ == "__main__":
    main()
