#!/usr/bin/env python3
"""
Course ingestion script.
Reads lectures from manifest, chunks them, computes embeddings, uploads to Supabase.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.supabase_client import get_client
from app.embeddings.embedder import embed_query
from app.ingest.chunker import chunk_text

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "lectures_manifest.csv")
COURSE_DIR = os.path.join(DATA_DIR, "course")


def read_manifest(limit: int | None = None) -> list[dict]:
    """Read lectures manifest CSV."""
    lectures = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            lectures.append(row)
    return lectures


def read_lecture_file(filename: str) -> str:
    """Read lecture text file."""
    filepath = os.path.join(COURSE_DIR, filename)
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


def insert_chunks(client, lecture: dict, chunks: list[dict]) -> int:
    """Insert chunks with embeddings into course_chunks table."""
    if not chunks:
        return 0
    
    records = []
    for chunk in chunks:
        chunk_id = f"{lecture['lecture_id']}-{chunk['sequence_order']:04d}"
        embedding = embed_query(chunk["content"])
        
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


def ingest_lecture(client, lecture: dict) -> int:
    """Process single lecture: read, chunk, embed, upload."""
    print(f"  Processing: {lecture['lecture_id']} - {lecture['lecture_title']}")
    
    text = read_lecture_file(lecture["source_file"])
    chunks = list(chunk_text(text))
    
    upsert_lecture(client, lecture)
    delete_old_chunks(client, lecture["lecture_id"])
    count = insert_chunks(client, lecture, chunks)
    
    print(f"    -> {count} chunks created")
    return count


def main():
    parser = argparse.ArgumentParser(description="Ingest course lectures into Supabase")
    parser.add_argument("--limit", type=int, help="Limit number of lectures to process")
    args = parser.parse_args()
    
    print("Course Ingestion Pipeline")
    print("=" * 40)
    
    lectures = read_manifest(args.limit)
    print(f"Found {len(lectures)} lectures in manifest")
    
    client = get_client()
    total_chunks = 0
    
    for lecture in lectures:
        try:
            count = ingest_lecture(client, lecture)
            total_chunks += count
        except Exception as e:
            print(f"    ERROR: {e}")
    
    print("=" * 40)
    print(f"Done! Processed {len(lectures)} lectures, {total_chunks} total chunks")


if __name__ == "__main__":
    main()
