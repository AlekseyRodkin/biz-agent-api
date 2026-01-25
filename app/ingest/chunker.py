import re
from typing import Generator

MIN_CHUNK_SIZE = 2500
MAX_CHUNK_SIZE = 4500
OVERLAP_SIZE = 400

ASSIGNMENT_MARKERS = re.compile(
    r'\b(задание|домашк|сделайте|нужно ?подготовить|заполните)\b',
    re.IGNORECASE
)
EXAMPLE_MARKERS = re.compile(
    r'\b(пример|кейс|в компании|мы делали)\b',
    re.IGNORECASE
)


def detect_content_type(text: str) -> str:
    """Detect content type based on markers in text."""
    if ASSIGNMENT_MARKERS.search(text):
        return "assignment"
    if EXAMPLE_MARKERS.search(text):
        return "example"
    return "theory"


def split_into_paragraphs(text: str) -> list[str]:
    """Split text by empty lines into paragraphs."""
    paragraphs = re.split(r'\n\s*\n', text.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def chunk_text(text: str) -> Generator[dict, None, None]:
    """
    Split text into chunks with overlap.
    
    Yields dicts with:
      - content: chunk text
      - content_type: theory/assignment/example
      - sequence_order: 1-based index
    """
    paragraphs = split_into_paragraphs(text)
    
    current_chunk = ""
    sequence_order = 0
    overlap_text = ""
    
    for paragraph in paragraphs:
        test_chunk = current_chunk + ("\n\n" if current_chunk else "") + paragraph
        
        if len(test_chunk) > MAX_CHUNK_SIZE and current_chunk:
            sequence_order += 1
            content_type = detect_content_type(current_chunk)
            
            yield {
                "content": current_chunk,
                "content_type": content_type,
                "sequence_order": sequence_order
            }
            
            overlap_text = current_chunk[-OVERLAP_SIZE:] if len(current_chunk) > OVERLAP_SIZE else current_chunk
            current_chunk = overlap_text + "\n\n" + paragraph
        else:
            current_chunk = test_chunk
    
    if current_chunk.strip():
        sequence_order += 1
        content_type = detect_content_type(current_chunk)
        
        yield {
            "content": current_chunk,
            "content_type": content_type,
            "sequence_order": sequence_order
        }
