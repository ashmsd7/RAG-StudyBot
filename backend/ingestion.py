import os
import json
import uuid
import logging
from typing import List, Dict, Optional, Tuple, Union
from sqlalchemy.orm import Session
from pypdf import PdfReader
from io import BytesIO
from gemini_client import generate_content_with_limit

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BATCH_CHUNK_SIZE = int(os.environ.get("GEMINI_BATCH_CHUNK_SIZE", "500"))
MAX_BATCH_CHARS = int(os.environ.get("GEMINI_BATCH_CHARS", "250000"))
ENABLE_CONCEPT_TAGGING = os.environ.get("ENABLE_CONCEPT_TAGGING", "true").lower() in ("1", "true", "yes")

DEFAULT_CONCEPT_METADATA = {
    "concept": "unknown",
    "parent_concept": "",
    "difficulty": "medium",
    "is_tagged": False,
}


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


def extract_concepts_from_chunks(chunks: List[str], db: Session) -> List[Dict[str, Optional[str]]]:
    """Batch multiple chunks into a single Gemini call and return concept tags for each chunk."""
    if not chunks:
        return []

    if not ENABLE_CONCEPT_TAGGING:
        logger.info("Concept tagging disabled, using fallback metadata for %d chunks", len(chunks))
        return [DEFAULT_CONCEPT_METADATA.copy() for _ in chunks]

    prompt_chunks = [
        f"{idx}: {chunk}"
        for idx, chunk in enumerate(chunks)
    ]
    joined_chunks = "\n---CHUNK---\n".join(prompt_chunks)
    prompt = f"""
Return only a JSON array. For each numbered study chunk, infer:
chunk_index, concept, parent_concept, difficulty.
Keep concept names short. Use null when parent_concept is unknown.

Chunks:
{joined_chunks}
    """

    logger.info("Sending one concept extraction request for %d chunks (%d chars)", len(chunks), len(prompt))

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="ingestion"
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)
        if not isinstance(data, list):
            raise ValueError("Expected JSON array from Gemini")

        results = [DEFAULT_CONCEPT_METADATA.copy() for _ in chunks]
        for item in data:
            if not isinstance(item, dict):
                continue
            index = item.get("chunk_index")
            try:
                index = int(index)
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(chunks):
                continue

            results[index] = {
                "concept": item.get("concept", "unknown") or "unknown",
                "parent_concept": item.get("parent_concept") or "",
                "difficulty": item.get("difficulty", "medium") or "medium",
                "is_tagged": True,
            }

        return results

    except Exception as e:
        logger.warning("Concept extraction failed, using fallback metadata: %s", e)
        return [DEFAULT_CONCEPT_METADATA.copy() for _ in chunks]


def _batch_chunk_items_by_size(chunk_items: List[Dict[str, object]], max_items: int, max_chars: int) -> List[List[Dict[str, object]]]:
    batches: List[List[Dict[str, object]]] = []
    current_batch: List[Dict[str, object]] = []
    current_chars = 0

    for item in chunk_items:
        chunk_len = len(str(item["text"]))
        if current_batch and (len(current_batch) >= max_items or current_chars + chunk_len > max_chars):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(item)
        current_chars += chunk_len

    if current_batch:
        batches.append(current_batch)

    return batches


def _chunk_text_with_positions(text: str, chunk_size: int = 2000, overlap: int = 400) -> List[Dict[str, Union[int, str]]]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append({"start": start, "text": text[start:end]})
        start += chunk_size - overlap
    return chunks


def _get_page_number_for_offset(offset: int, page_offsets: List[Dict[str, int]]) -> int:
    for page_index, bounds in enumerate(page_offsets, start=1):
        if offset < bounds["end"]:
            return page_index
    return len(page_offsets) if page_offsets else 1


def _extract_pdf_text_and_offsets(file_bytes: bytes) -> Tuple[str, List[Dict[str, int]]]:
    reader = PdfReader(BytesIO(file_bytes))
    page_texts: List[str] = []
    page_offsets: List[Dict[str, int]] = []
    current_offset = 0
    separator = "\n\n"

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            page_texts.append(page_text)
        else:
            page_texts.append("")

    full_text = separator.join(page_texts).strip()

    for idx, page_text in enumerate(page_texts):
        page_length = len(page_text)
        page_offsets.append({"start": current_offset, "end": current_offset + page_length})
        current_offset += page_length
        if idx < len(page_texts) - 1:
            current_offset += len(separator)

    return full_text, page_offsets


def process_document(file_bytes: bytes, filename: str, db: Session) -> List[Dict]:
    """Orchestrates extraction, chunking, and tagging for a document using the full text."""
    processed_chunks = []

    def tag_chunk_items(chunk_items: List[Dict[str, object]]):
        if not chunk_items:
            return

        batch_list = _batch_chunk_items_by_size(
            chunk_items,
            BATCH_CHUNK_SIZE,
            MAX_BATCH_CHARS,
        )

        logger.info(
            "Tagging %d full-document chunks for %s in %d Gemini batch(es)",
            len(chunk_items),
            filename,
            len(batch_list),
        )
        for batch_index, batch_items in enumerate(batch_list, start=1):
            batch_texts = [str(item["text"]) for item in batch_items]
            logger.info("Sending full-document chunk batch %d/%d to Gemini", batch_index, len(batch_list))
            tags_batch = extract_concepts_from_chunks(batch_texts, db)
            for item, tags in zip(batch_items, tags_batch):
                processed_chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "text": item["text"],
                    "concept": tags["concept"],
                    "parent_concept": tags["parent_concept"],
                    "difficulty": tags["difficulty"],
                    "is_tagged": tags.get("is_tagged", False),
                    "page_number": item["page_number"],
                    "document_title": filename,
                })

    chunk_items: List[Dict[str, object]] = []

    if filename.lower().endswith(".pdf"):
        full_text, page_offsets = _extract_pdf_text_and_offsets(file_bytes)
        logger.info("Extracted %d chars from %d PDF pages for %s", len(full_text), len(page_offsets), filename)
        if full_text:
            for chunk_data in _chunk_text_with_positions(full_text, chunk_size=2000, overlap=400):
                chunk_text_val = chunk_data["text"]
                if len(chunk_text_val.strip()) < 50:
                    continue
                page_number = _get_page_number_for_offset(chunk_data["start"], page_offsets)
                chunk_items.append({"text": chunk_text_val, "page_number": page_number})
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        logger.info("Extracted %d chars from text document %s", len(text), filename)
        for chunk_data in _chunk_text_with_positions(text, chunk_size=2000, overlap=400):
            chunk_text_val = chunk_data["text"]
            if len(chunk_text_val.strip()) < 50:
                continue
            chunk_items.append({"text": chunk_text_val, "page_number": 1})

    tag_chunk_items(chunk_items)
    return processed_chunks
