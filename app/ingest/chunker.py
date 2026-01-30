"""
Text chunking module for course content.

Chunk parameters:
- Target size: 1500-3000 characters
- Overlap: 10-15% (150-400 characters)

Algorithm:
1. Split by empty lines (paragraphs)
2. If paragraph > max_size -> split by sentences
3. Guarantee: if text > 5000 chars -> must produce >1 chunk
"""

import re
from typing import Generator

MIN_CHUNK_SIZE = 1500
MAX_CHUNK_SIZE = 3000
OVERLAP_RATIO = 0.12  # 12% overlap

ASSIGNMENT_MARKERS = re.compile(
    r'\b(задание|домашк|сделайте|нужно ?подготовить|заполните)\b',
    re.IGNORECASE
)
EXAMPLE_MARKERS = re.compile(
    r'\b(пример|кейс|в компании|мы делали)\b',
    re.IGNORECASE
)
# Markers for student/participant comments in transcripts
STUDENT_MARKERS = re.compile(
    r'\b(вопрос из зала|студент[ыа]?|участник[иа]?|у нас проект|мы сделали|наш кейс|'
    r'у меня вопрос|в нашей компании|мы внедрили|наша команда|наш опыт)\b',
    re.IGNORECASE
)

# Sentence boundaries (period, exclamation, question followed by space/newline)
SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')


def detect_content_type(text: str, speaker_type: str = "methodology") -> str:
    """Detect content type based on markers in text.

    Args:
        text: Chunk text content
        speaker_type: Source speaker type (methodology, case_study)

    Returns:
        Content type: theory, assignment, example, student_comment
    """
    # Student comments only detected in methodology transcripts
    # (case_study speakers are expected to share their experience)
    if speaker_type == "methodology" and STUDENT_MARKERS.search(text):
        return "student_comment"
    if ASSIGNMENT_MARKERS.search(text):
        return "assignment"
    if EXAMPLE_MARKERS.search(text):
        return "example"
    return "theory"


def split_into_paragraphs(text: str) -> list[str]:
    """Split text by empty lines into paragraphs."""
    paragraphs = re.split(r'\n\s*\n', text.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences by sentence boundaries."""
    sentences = SENTENCE_BOUNDARY.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def split_long_paragraph(paragraph: str, max_size: int) -> list[str]:
    """Split paragraph that exceeds max_size into smaller pieces by sentences."""
    if len(paragraph) <= max_size:
        return [paragraph]

    sentences = split_into_sentences(paragraph)
    if len(sentences) <= 1:
        # Can't split further, return as is
        return [paragraph]

    pieces = []
    current = ""

    for sentence in sentences:
        test = current + (" " if current else "") + sentence
        if len(test) > max_size and current:
            pieces.append(current)
            current = sentence
        else:
            current = test

    if current:
        pieces.append(current)

    return pieces


def chunk_text(text: str, validate: bool = True, speaker_type: str = "methodology") -> Generator[dict, None, None]:
    """
    Split text into chunks with overlap.

    Args:
        text: Input text to chunk
        validate: If True, raise error if text > 5000 chars produces <=1 chunk
        speaker_type: Source speaker type for content_type detection

    Yields dicts with:
      - content: chunk text
      - content_type: theory/assignment/example/student_comment
      - sequence_order: 1-based index
      - char_count: length of content

    Raises:
        ValueError: If text > 5000 chars but produces <=1 chunk (when validate=True)
    """
    paragraphs = split_into_paragraphs(text)

    # Split long paragraphs into smaller pieces
    all_pieces = []
    for para in paragraphs:
        if len(para) > MAX_CHUNK_SIZE:
            all_pieces.extend(split_long_paragraph(para, MAX_CHUNK_SIZE))
        else:
            all_pieces.append(para)

    overlap_size = int(MAX_CHUNK_SIZE * OVERLAP_RATIO)
    current_chunk = ""
    sequence_order = 0
    chunks_yielded = 0

    for piece in all_pieces:
        test_chunk = current_chunk + ("\n\n" if current_chunk else "") + piece

        # If adding this piece exceeds max and we have content, yield current chunk
        if len(test_chunk) > MAX_CHUNK_SIZE and current_chunk:
            sequence_order += 1
            chunks_yielded += 1
            content_type = detect_content_type(current_chunk, speaker_type)

            yield {
                "content": current_chunk,
                "content_type": content_type,
                "sequence_order": sequence_order,
                "char_count": len(current_chunk)
            }

            # Overlap: take last N chars from current chunk
            overlap_text = current_chunk[-overlap_size:] if len(current_chunk) > overlap_size else current_chunk
            current_chunk = overlap_text + "\n\n" + piece
        else:
            current_chunk = test_chunk

    # Yield remaining content
    if current_chunk.strip():
        sequence_order += 1
        chunks_yielded += 1
        content_type = detect_content_type(current_chunk, speaker_type)

        yield {
            "content": current_chunk,
            "content_type": content_type,
            "sequence_order": sequence_order,
            "char_count": len(current_chunk)
        }

    # Validation: if text is long but produced only 1 chunk, something is wrong
    if validate and len(text) > 5000 and chunks_yielded <= 1:
        raise ValueError(
            f"Chunking error: text has {len(text)} chars but produced only {chunks_yielded} chunk(s). "
            f"Expected >1 chunk for text > 5000 chars."
        )


def get_chunking_stats(text: str) -> dict:
    """
    Get detailed chunking statistics for a text without validation errors.

    Returns dict with:
      - text_length: original text length
      - paragraph_count: number of paragraphs
      - chunk_count: number of chunks
      - chunk_sizes: list of chunk sizes
      - min_chunk_size: smallest chunk
      - max_chunk_size: largest chunk
      - avg_chunk_size: average chunk size
      - content_types: dict of content_type counts
    """
    paragraphs = split_into_paragraphs(text)

    try:
        chunks = list(chunk_text(text, validate=False))
    except Exception as e:
        return {
            "text_length": len(text),
            "paragraph_count": len(paragraphs),
            "chunk_count": 0,
            "chunk_sizes": [],
            "min_chunk_size": 0,
            "max_chunk_size": 0,
            "avg_chunk_size": 0,
            "content_types": {},
            "error": str(e)
        }

    chunk_sizes = [c["char_count"] for c in chunks]
    content_types = {}
    for c in chunks:
        ct = c["content_type"]
        content_types[ct] = content_types.get(ct, 0) + 1

    return {
        "text_length": len(text),
        "paragraph_count": len(paragraphs),
        "chunk_count": len(chunks),
        "chunk_sizes": chunk_sizes,
        "min_chunk_size": min(chunk_sizes) if chunk_sizes else 0,
        "max_chunk_size": max(chunk_sizes) if chunk_sizes else 0,
        "avg_chunk_size": int(sum(chunk_sizes) / len(chunk_sizes)) if chunk_sizes else 0,
        "content_types": content_types,
        "error": None
    }
