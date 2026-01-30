#!/usr/bin/env python3
"""
Scale clean_content to all methodology chunks.

Only processes:
- speaker_type = 'methodology'
- content_type != 'student_comment'

Uses batch processing to avoid Supabase limits.

Usage:
    python scripts/clean_methodology.py --dry-run
    python scripts/clean_methodology.py --apply
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.supabase_client import get_client

# Safety guards
MIN_RATIO = 0.6
MIN_CLEAN_LEN = 800
BATCH_SIZE = 50

# Sentence boundary pattern
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

# NARROW noise patterns - only obvious tech/org noise
NOISE_PATTERNS = [
    # Zoom/online attendance
    re.compile(r'.*выключиться в zoom.*', re.IGNORECASE),
    re.compile(r'.*послушать удаленно.*', re.IGNORECASE),
    re.compile(r'.*подключитесь.*zoom.*', re.IGNORECASE),
    re.compile(r'.*если вы не можете.*zoom.*', re.IGNORECASE),
    # Audio/video checks
    re.compile(r'.*слышно ли меня.*', re.IGNORECASE),
    re.compile(r'.*меня слышно.*', re.IGNORECASE),
    re.compile(r'.*вы меня слышите.*', re.IGNORECASE),
    re.compile(r'.*включите микрофон.*', re.IGNORECASE),
    re.compile(r'.*выключите микрофон.*', re.IGNORECASE),
    re.compile(r'.*видно ли экран.*', re.IGNORECASE),
    # Session management
    re.compile(r'^раз,?\s*два,?\s*три.*', re.IGNORECASE),
    re.compile(r'.*проверка связи.*', re.IGNORECASE),
    # Org/housekeeping (narrow)
    re.compile(r'.*академические правила такие.*', re.IGNORECASE),
    re.compile(r'.*присутствие на модулях.*', re.IGNORECASE),
    re.compile(r'.*напишите.*в чатик.*', re.IGNORECASE),
    re.compile(r'.*пишите в чат(?!gpt).*', re.IGNORECASE),
]

# Keywords that PROTECT sentence from removal
PROTECTED_KEYWORDS = [
    'методология', 'трансформация', 'бизнес-процесс', 'внедрение',
    'искусственный интеллект', 'ии', 'ai', 'llm', 'языковая модель',
    'эффект', 'результат', 'ценность', 'важно', 'ключевой',
    'стратегия', 'цель', 'задача', 'проблема', 'решение',
]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = SENTENCE_SPLIT.split(text.strip())
    result = []
    for s in sentences:
        parts = re.split(r'\n\s*\n', s)
        result.extend([p.strip() for p in parts if p.strip()])
    return result


def is_noise_sentence(sentence: str) -> bool:
    """Check if sentence matches noise patterns."""
    sentence_lower = sentence.lower()
    for keyword in PROTECTED_KEYWORDS:
        if keyword in sentence_lower:
            return False

    for pattern in NOISE_PATTERNS:
        if pattern.match(sentence):
            return True

    return False


def clean_content(text: str) -> tuple[str, dict]:
    """Clean text by removing noise sentences."""
    sentences = split_sentences(text)
    kept = []
    removed = []

    for sentence in sentences:
        if is_noise_sentence(sentence):
            removed.append(sentence)
        else:
            kept.append(sentence)

    cleaned = '\n\n'.join(kept)

    stats = {
        'total_sentences': len(sentences),
        'kept_sentences': len(kept),
        'removed_sentences': len(removed),
        'removed_examples': removed[:2],
    }

    return cleaned, stats


def get_methodology_chunks(client, offset: int, limit: int) -> list[dict]:
    """Get methodology chunks (excluding student_comment) with pagination."""
    result = client.table("course_chunks") \
        .select("chunk_id, lecture_id, content, clean_content, metadata, content_type") \
        .eq("speaker_type", "methodology") \
        .neq("content_type", "student_comment") \
        .order("lecture_id") \
        .order("sequence_order") \
        .range(offset, offset + limit - 1) \
        .execute()
    return result.data or []


def count_methodology_chunks(client) -> int:
    """Count total methodology chunks."""
    result = client.table("course_chunks") \
        .select("chunk_id", count="exact") \
        .eq("speaker_type", "methodology") \
        .neq("content_type", "student_comment") \
        .execute()
    return result.count or 0


def update_chunk(client, chunk_id: str, clean_text: str | None, metadata: dict | None) -> bool:
    """Update clean_content and metadata."""
    update_data = {"clean_content": clean_text}
    if metadata is not None:
        update_data["metadata"] = metadata

    result = client.table("course_chunks") \
        .update(update_data) \
        .eq("chunk_id", chunk_id) \
        .execute()
    return len(result.data) > 0 if result.data else False


def main():
    parser = argparse.ArgumentParser(description="Clean all methodology chunks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned")
    parser.add_argument("--apply", action="store_true", help="Apply cleaning to database")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Error: specify --dry-run or --apply")
        sys.exit(1)

    client = get_client()

    total_chunks = count_methodology_chunks(client)
    print(f"Total methodology chunks (excl. student_comment): {total_chunks}")
    print(f"Safety: MIN_RATIO={MIN_RATIO}, MIN_CLEAN_LEN={MIN_CLEAN_LEN}")
    print(f"Batch size: {BATCH_SIZE}")
    print()

    # Stats
    accepted = []
    skipped = []
    skip_reasons = {}
    examples = []

    offset = 0
    while offset < total_chunks:
        chunks = get_methodology_chunks(client, offset, BATCH_SIZE)
        if not chunks:
            break

        print(f"Processing batch {offset // BATCH_SIZE + 1} ({offset}-{offset + len(chunks) - 1})...")

        for chunk in chunks:
            raw = chunk["content"]
            raw_len = len(raw)

            cleaned, stats = clean_content(raw)
            clean_len = len(cleaned)
            ratio = clean_len / raw_len if raw_len > 0 else 1.0

            # Check safety guards
            skip_reason = None
            if ratio < MIN_RATIO:
                skip_reason = f"ratio<{MIN_RATIO}"
            elif clean_len < MIN_CLEAN_LEN:
                skip_reason = f"len<{MIN_CLEAN_LEN}"

            if skip_reason:
                skipped.append(chunk['chunk_id'])
                skip_reasons[skip_reason] = skip_reasons.get(skip_reason, 0) + 1

                if args.apply:
                    meta = chunk.get('metadata') or {}
                    meta['clean_skipped_reason'] = skip_reason
                    update_chunk(client, chunk['chunk_id'], None, meta)
            else:
                accepted.append({
                    'chunk_id': chunk['chunk_id'],
                    'lecture_id': chunk['lecture_id'],
                    'ratio': ratio,
                    'removed': stats['removed_sentences'],
                })

                # Collect examples
                if stats['removed_sentences'] > 0 and len(examples) < 5:
                    examples.append({
                        'chunk_id': chunk['chunk_id'],
                        'raw_excerpt': raw[:150],
                        'clean_excerpt': cleaned[:150],
                        'removed': stats['removed_examples'],
                    })

                if args.apply:
                    update_chunk(client, chunk['chunk_id'], cleaned, None)

        offset += BATCH_SIZE

    # QC Report
    print()
    print("=" * 60)
    print("QC REPORT")
    print("=" * 60)
    print()
    print(f"Total methodology chunks: {total_chunks}")
    print(f"Updated (clean_content set): {len(accepted)}")
    print(f"Skipped: {len(skipped)}")
    print()

    if skip_reasons:
        print("Skip reasons:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
        print()

    if accepted:
        avg_ratio = sum(a['ratio'] for a in accepted) / len(accepted)
        with_removal = [a for a in accepted if a['removed'] > 0]
        total_removed = sum(a['removed'] for a in accepted)
        print(f"Avg ratio (accepted): {avg_ratio:.3f}")
        print(f"Chunks with sentences removed: {len(with_removal)}")
        print(f"Total sentences removed: {total_removed}")
        print()

    # Examples
    if examples:
        print("=" * 60)
        print(f"EXAMPLES ({len(examples)} chunks with removals)")
        print("=" * 60)
        for ex in examples:
            print()
            print(f"--- {ex['chunk_id']} ---")
            print(f"Removed: {ex['removed']}")
            print(f"Raw: {ex['raw_excerpt']}...")
            print(f"Clean: {ex['clean_excerpt']}...")

    # Verify case_study not touched
    print()
    print("=" * 60)
    print("VERIFICATION: case_study NOT touched")
    print("=" * 60)
    case_study = client.table("course_chunks") \
        .select("chunk_id", count="exact") \
        .eq("speaker_type", "case_study") \
        .not_.is_("clean_content", "null") \
        .execute()
    print(f"case_study chunks with clean_content: {case_study.count}")
    if case_study.count == 0:
        print("✅ case_study NOT touched")
    else:
        print("⚠️ WARNING: some case_study chunks have clean_content!")

    print()
    if args.dry_run:
        print("[DRY RUN] No changes made")
    elif args.apply:
        print(f"[APPLIED] Updated {len(accepted)} chunks, skipped {len(skipped)}")


if __name__ == "__main__":
    main()
