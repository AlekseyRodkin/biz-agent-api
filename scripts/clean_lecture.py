#!/usr/bin/env python3
"""
Clean lecture content: sentence-level removal of tech noise.

Safety guards:
- Only removes sentences matching NOISE_PATTERNS
- Skips chunk if ratio < 0.6 or clean_len < 800
- Never removes sentences with METHOD_KEYWORDS

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

# Minimum ratio of clean/raw to accept cleaning
MIN_RATIO = 0.6
# Minimum clean content length to accept
MIN_CLEAN_LEN = 800

# Sentence boundary pattern (split on . ! ? followed by space/newline or end)
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

# NARROW noise patterns - only obvious tech/org noise
# These must match ENTIRE sentence to trigger removal
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

# Keywords that PROTECT sentence from removal (never remove if contains these)
PROTECTED_KEYWORDS = [
    'методология', 'трансформация', 'бизнес-процесс', 'внедрение',
    'искусственный интеллект', 'ии', 'ai', 'llm', 'языковая модель',
    'эффект', 'результат', 'ценность', 'важно', 'ключевой',
    'стратегия', 'цель', 'задача', 'проблема', 'решение',
]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # First split by sentence boundaries
    sentences = SENTENCE_SPLIT.split(text.strip())
    # Also handle paragraph breaks
    result = []
    for s in sentences:
        # Split by double newlines (paragraphs)
        parts = re.split(r'\n\s*\n', s)
        result.extend([p.strip() for p in parts if p.strip()])
    return result


def is_noise_sentence(sentence: str) -> bool:
    """Check if sentence matches noise patterns."""
    # First check if sentence is protected
    sentence_lower = sentence.lower()
    for keyword in PROTECTED_KEYWORDS:
        if keyword in sentence_lower:
            return False  # Protected, never remove

    # Check against noise patterns
    for pattern in NOISE_PATTERNS:
        if pattern.match(sentence):
            return True

    return False


def clean_content(text: str) -> tuple[str, dict]:
    """
    Clean text by removing noise sentences.

    Returns:
        tuple: (cleaned_text, stats_dict)
    """
    sentences = split_sentences(text)
    kept = []
    removed = []

    for sentence in sentences:
        if is_noise_sentence(sentence):
            removed.append(sentence)
        else:
            kept.append(sentence)

    # Reconstruct with paragraph breaks where appropriate
    cleaned = '\n\n'.join(kept)

    stats = {
        'total_sentences': len(sentences),
        'kept_sentences': len(kept),
        'removed_sentences': len(removed),
        'removed_examples': removed[:3],  # First 3 removed for debugging
    }

    return cleaned, stats


def get_lecture_chunks(client, lecture_id: str) -> list[dict]:
    """Get all chunks for a lecture."""
    result = client.table("course_chunks") \
        .select("chunk_id, content, clean_content, metadata") \
        .eq("lecture_id", lecture_id) \
        .order("sequence_order") \
        .execute()
    return result.data or []


def update_chunk(client, chunk_id: str, clean_text: str | None, metadata: dict | None) -> bool:
    """Update clean_content and optionally metadata for a chunk."""
    update_data = {"clean_content": clean_text}
    if metadata:
        update_data["metadata"] = metadata

    result = client.table("course_chunks") \
        .update(update_data) \
        .eq("chunk_id", chunk_id) \
        .execute()
    return len(result.data) > 0 if result.data else False


def main():
    parser = argparse.ArgumentParser(description="Clean lecture content (sentence-level)")
    parser.add_argument("--lecture-id", required=True, help="Lecture ID to clean")
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
    print(f"Safety: MIN_RATIO={MIN_RATIO}, MIN_CLEAN_LEN={MIN_CLEAN_LEN}")
    print()

    # QC stats
    accepted = []
    skipped = []

    for chunk in chunks:
        raw = chunk["content"]
        raw_len = len(raw)

        cleaned, stats = clean_content(raw)
        clean_len = len(cleaned)
        ratio = clean_len / raw_len if raw_len > 0 else 1.0

        # Check safety guards
        skip_reason = None
        if ratio < MIN_RATIO:
            skip_reason = f"ratio={ratio:.2f}<{MIN_RATIO}"
        elif clean_len < MIN_CLEAN_LEN:
            skip_reason = f"clean_len={clean_len}<{MIN_CLEAN_LEN}"

        if skip_reason:
            skipped.append({
                'chunk_id': chunk['chunk_id'],
                'raw_len': raw_len,
                'clean_len': clean_len,
                'ratio': ratio,
                'reason': skip_reason,
                'removed': stats['removed_sentences'],
            })
            if args.apply:
                # Set clean_content to NULL and record skip reason
                meta = chunk.get('metadata') or {}
                meta['clean_skipped_reason'] = skip_reason
                update_chunk(client, chunk['chunk_id'], None, meta)
        else:
            accepted.append({
                'chunk_id': chunk['chunk_id'],
                'raw_len': raw_len,
                'clean_len': clean_len,
                'ratio': ratio,
                'removed': stats['removed_sentences'],
                'removed_examples': stats['removed_examples'],
                'clean_preview': cleaned[:200],
            })
            if args.apply:
                update_chunk(client, chunk['chunk_id'], cleaned, None)

    # Print QC report
    print("=" * 60)
    print("QC REPORT")
    print("=" * 60)
    print()
    print(f"ACCEPTED: {len(accepted)} chunks")
    print("-" * 40)
    for a in accepted:
        print(f"  {a['chunk_id']}: {a['raw_len']} -> {a['clean_len']} (ratio={a['ratio']:.2f}, removed={a['removed']})")

    print()
    print(f"SKIPPED: {len(skipped)} chunks")
    print("-" * 40)
    for s in skipped:
        print(f"  {s['chunk_id']}: {s['raw_len']} -> {s['clean_len']} ({s['reason']}, removed={s['removed']})")

    # Stats
    if accepted:
        avg_ratio = sum(a['ratio'] for a in accepted) / len(accepted)
        print()
        print(f"Avg ratio (accepted): {avg_ratio:.2f}")

    # Examples
    if accepted and args.dry_run:
        print()
        print("=" * 60)
        print("EXAMPLES (3 accepted chunks)")
        print("=" * 60)
        for a in accepted[:3]:
            print()
            print(f"--- {a['chunk_id']} ---")
            print(f"Removed sentences: {a['removed_examples']}")
            print(f"Clean preview: {a['clean_preview']}...")

    print()
    if args.dry_run:
        print("[DRY RUN] No changes made")
    elif args.apply:
        print(f"[APPLIED] Updated {len(accepted)} chunks, skipped {len(skipped)}")


if __name__ == "__main__":
    main()
