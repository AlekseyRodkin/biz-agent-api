#!/usr/bin/env python3
"""Export lectures and chunks as JSON for MCP ingestion."""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
MANIFEST = os.path.join(DATA_DIR, 'lectures_manifest.csv')
COURSE_DIR = os.path.join(DATA_DIR, 'course')

from app.embeddings.embedder import embed_query
from app.ingest.chunker import chunk_text

with open(MANIFEST) as f:
    lectures = list(csv.DictReader(f))[:5]

all_lectures = []
all_chunks = []

for lec in lectures:
    filepath = os.path.join(COURSE_DIR, lec['source_file'])
    with open(filepath) as f:
        text = f.read()
    
    all_lectures.append({
        'lecture_id': lec['lecture_id'],
        'module': int(lec['module']),
        'day': int(lec['day']),
        'lecture_order': int(lec['lecture_order']),
        'lecture_title': lec['lecture_title'],
        'speaker_name': lec['speaker_name'],
        'speaker_type': lec['speaker_type'],
        'source_file': lec['source_file']
    })
    
    for chunk in chunk_text(text):
        chunk_id = f"{lec['lecture_id']}-{chunk['sequence_order']:04d}"
        emb = embed_query(chunk['content'])
        
        all_chunks.append({
            'chunk_id': chunk_id,
            'lecture_id': lec['lecture_id'],
            'module': int(lec['module']),
            'day': int(lec['day']),
            'speaker_type': lec['speaker_type'],
            'speaker_name': lec['speaker_name'],
            'content_type': chunk['content_type'],
            'sequence_order': chunk['sequence_order'],
            'parent_topic': lec['lecture_title'],
            'content': chunk['content'],
            'embedding': emb
        })

print(json.dumps({'lectures': all_lectures, 'chunks': all_chunks}))
