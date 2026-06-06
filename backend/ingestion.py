import os
import json
import uuid
from typing import List, Dict
from sqlalchemy.orm import Session
from pypdf import PdfReader
from io import BytesIO
from gemini_client import generate_content_with_limit

BATCH_CHUNK_SIZE = int(os.environ.get("GEMINI_BATCH_CHUNK_SIZE", "20"))
MAX_BATCH_CHARS = int(os.environ.get("GEMINI_BATCH_CHARS", "22000"))


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 400) -> List[str]:
    """Splits text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _clean_json_payload(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    if text.endswith("```"):
        text = text[: -3].strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def extract_concepts_from_chunks(chunks: List[str], db: Session) -> List[Dict[str, str]]:
    """Batch multiple chunks into a single Gemini call and return concept tags for each chunk."""
    prompt_chunks = []
    for idx, chunk in enumerate(chunks, start=1):
        prompt_chunks.append(
            f"CHUNK {idx}:\n'''\n{chunk}\n'''\n"
        )

    joined_chunks = "\n\n".join(prompt_chunks)
    prompt = f"""
    Analyze each of the following text chunks from a study document and determine its core concept.
    For each chunk, return an object with these keys: concept, parent_concept, difficulty.
    Output a JSON array in the same order as the input chunks.

    Each object must follow this exact format:
    [
      {{
        "concept": "Primary specific concept discussed",
        "parent_concept": "Broader topic",
        "difficulty": "Easy, Medium, or Hard"
      }},
      ...
    ]

    Chunks:
    {joined_chunks}
    """

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="ingestion"
        )
        clean_text = _clean_json_payload(response.text)
        data = json.loads(clean_text)
        if not isinstance(data, list):
            raise ValueError("Expected JSON array from Gemini")

        results: List[Dict[str, str]] = []
        for item in data:
            results.append({
                "concept": item.get("concept", "General"),
                "parent_concept": item.get("parent_concept", "General"),
                "difficulty": item.get("difficulty", "Medium"),
            })

        # If the model returned fewer objects than requested, fill in defaults.
        while len(results) < len(chunks):
            results.append({
                "concept": "General Concept",
                "parent_concept": "General Domain",
                "difficulty": "Medium",
            })

        return results

    except Exception as e:
        print(f"Concept extraction failed: {e}")
        return [
            {
                "concept": "General Concept",
                "parent_concept": "General Domain",
                "difficulty": "Medium",
            }
            for _ in chunks
        ]


def _batch_items(items: List[Dict], size: int) -> List[List[Dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _batch_chunks_by_size(chunks: List[str], max_items: int, max_chars: int) -> List[List[str]]:
    batches: List[List[str]] = []
    current_batch: List[str] = []
    current_chars = 0

    for chunk in chunks:
        chunk_len = len(chunk)
        if current_batch and (len(current_batch) >= max_items or current_chars + chunk_len > max_chars):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(chunk)
        current_chars += chunk_len

    if current_batch:
        batches.append(current_batch)

    return batches


def process_document(file_bytes: bytes, filename: str, db: Session) -> List[Dict]:
    """Orchestrates extraction, chunking, and tagging for a document. Page-by-page for PDFs."""
    processed_chunks = []

    def process_chunk_items(chunk_items: List[Dict[str, object]], page_number: int):
        if not chunk_items:
            return

        chunk_texts = [item["text"] for item in chunk_items]
        for batch_texts in _batch_chunks_by_size(chunk_texts, BATCH_CHUNK_SIZE, MAX_BATCH_CHARS):
            tags_batch = extract_concepts_from_chunks(batch_texts, db)
            for item, tags in zip(chunk_items[: len(tags_batch)], tags_batch):
                processed_chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "text": item["text"],
                    "concept": tags["concept"],
                    "parent_concept": tags["parent_concept"],
                    "difficulty": tags["difficulty"],
                    "page_number": item["page_number"],
                    "document_title": filename,
                })
            chunk_items = chunk_items[len(tags_batch):]

    if filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(file_bytes))
        for page_idx, page in enumerate(reader.pages):
            page_num = page_idx + 1
            page_text = page.extract_text()
            if not page_text or len(page_text.strip()) < 10:
                continue

            chunk_items = []
            for chunk in chunk_text(page_text, chunk_size=2000, overlap=400):
                if len(chunk.strip()) < 50:
                    continue
                chunk_items.append({"text": chunk, "page_number": page_num})

            process_chunk_items(chunk_items, page_num)
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        chunk_items = []
        for chunk in chunk_text(text, chunk_size=2000, overlap=400):
            if len(chunk.strip()) < 50:
                continue
            chunk_items.append({"text": chunk, "page_number": 1})

        process_chunk_items(chunk_items, 1)

    return processed_chunks
