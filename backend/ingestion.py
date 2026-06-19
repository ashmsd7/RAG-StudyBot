import os
import json
import uuid
import logging
import re
from collections import Counter
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
    "concept": "General Notes",
    "parent_concept": "Uploaded Material",
    "difficulty": "medium",
    "is_tagged": False,
}

STOPWORDS = {
    "about", "above", "after", "again", "also", "and", "are", "because", "been",
    "between", "both", "can", "chapter", "could", "definition", "does", "for",
    "from", "have", "into", "lesson", "material", "notes", "page", "part", "pdf",
    "section", "shall", "should", "study", "that", "the", "their", "there", "these",
    "this", "through", "topic", "unit", "using", "with", "would",
}

DIFFICULTY_VALUES = {"easy", "medium", "hard"}


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


def _title_case_label(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())


def _normalize_label(value: Optional[object], fallback: str) -> str:
    if value is None:
        return fallback
    label = re.sub(r"\s+", " ", str(value)).strip(" -_:;,.[]{}()\"'")
    if not label or label.lower() in {"unknown", "none", "null", "n/a", "general"}:
        return fallback
    return _title_case_label(label[:80])


def _normalize_difficulty(value: Optional[object]) -> str:
    difficulty = str(value or "").strip().lower()
    if difficulty in {"novice", "basic", "simple"}:
        return "easy"
    if difficulty in {"intermediate", "moderate"}:
        return "medium"
    if difficulty in {"advanced", "difficult", "complex"}:
        return "hard"
    return difficulty if difficulty in DIFFICULTY_VALUES else "medium"


def infer_topic_from_text(text: str, fallback: str = "General Notes") -> str:
    words = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text)
        if token.lower() not in STOPWORDS and not token.isdigit()
    ]
    if not words:
        return fallback

    phrases = []
    for size in (3, 2):
        for idx in range(0, max(len(words) - size + 1, 0)):
            phrase_words = words[idx : idx + size]
            if any(word in STOPWORDS for word in phrase_words):
                continue
            phrases.append(" ".join(phrase_words))
        if phrases:
            phrase, _ = Counter(phrases).most_common(1)[0]
            return _title_case_label(phrase)

    word, _ = Counter(words).most_common(1)[0]
    return _title_case_label(word)


def _fallback_metadata_for_chunk(text: str, parent_fallback: str = "Uploaded Material") -> Dict[str, Optional[str]]:
    concept = infer_topic_from_text(text)
    return {
        "concept": concept,
        "parent_concept": parent_fallback,
        "difficulty": "medium",
        "is_tagged": False,
    }


def _normalize_tag(raw: Dict[str, object], chunk_text: str) -> Dict[str, Optional[str]]:
    fallback = infer_topic_from_text(chunk_text)
    concept = _normalize_label(raw.get("concept"), fallback)
    parent = _normalize_label(raw.get("parent_concept"), "Uploaded Material")
    if parent == concept:
        parent = "Uploaded Material"
    return {
        "concept": concept,
        "parent_concept": parent,
        "difficulty": _normalize_difficulty(raw.get("difficulty")),
        "is_tagged": bool(raw.get("is_tagged", True)),
    }


def extract_document_concepts(full_text: str, document_title: str, db: Session) -> List[Dict[str, str]]:
    """Extract major concepts from the full document text using Gemini."""
    if not ENABLE_CONCEPT_TAGGING:
        logger.info("Concept tagging disabled, using fallback for document-level concepts")
        return [{"concept": "General Notes", "parent_concept": "Uploaded Material", "difficulty": "medium"}]

    # Truncate text if too long for Gemini
    max_text_length = 50000
    truncated_text = full_text[:max_text_length] if len(full_text) > max_text_length else full_text

    prompt = f"""
Analyze this document and extract the 5-15 most important technical concepts.
For each concept, provide:
- concept: The specific technical topic (short, precise name)
- parent_concept: The broader category it belongs to (use null if unknown)
- difficulty: easy, medium, or hard

Document title: {document_title}

Document text:
{truncated_text}

Return only a JSON array of objects with these exact keys: concept, parent_concept, difficulty.
Focus on technical, domain-specific concepts. Avoid generic terms like "introduction", "overview", "general".
"""

    logger.info("Sending document-level concept extraction request for %s (%d chars)", document_title, len(prompt))

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="ingestion"
        )
        raw_text = getattr(response, "text", "")
        logger.debug("Gemini document concept extraction raw response: %s", raw_text[:2000])
        clean_text = _clean_json_payload(raw_text)
        data = json.loads(clean_text)
        
        if not isinstance(data, list):
            raise ValueError("Expected JSON array from Gemini")

        # Normalize and validate concepts
        normalized_concepts = []
        for item in data:
            if not isinstance(item, dict):
                continue
            concept = _normalize_label(item.get("concept"), "General Notes")
            parent = _normalize_label(item.get("parent_concept"), "Uploaded Material")
            if parent == concept:
                parent = "Uploaded Material"
            difficulty = _normalize_difficulty(item.get("difficulty"))
            
            normalized_concepts.append({
                "concept": concept,
                "parent_concept": parent,
                "difficulty": difficulty
            })

        logger.info("Extracted %d document-level concepts for %s", len(normalized_concepts), document_title)
        for idx, concept in enumerate(normalized_concepts):
            logger.info("  Concept %d: %s (parent: %s, difficulty: %s)", idx, concept["concept"], concept["parent_concept"], concept["difficulty"])

        return normalized_concepts if normalized_concepts else [{"concept": "General Notes", "parent_concept": "Uploaded Material", "difficulty": "medium"}]

    except Exception as e:
        logger.warning("Document-level concept extraction failed, using fallback: %s", e)
        return [{"concept": "General Notes", "parent_concept": "Uploaded Material", "difficulty": "medium"}]


def map_chunk_to_concept(chunk_text: str, document_concepts: List[Dict[str, str]]) -> Dict[str, Optional[str]]:
    """Map a chunk to the most relevant concept from the document-level concept list."""
    if not document_concepts:
        return _fallback_metadata_for_chunk(chunk_text)

    # Simple keyword matching for now - can be improved with semantic similarity
    chunk_lower = chunk_text.lower()
    best_match = None
    best_score = 0

    for concept_data in document_concepts:
        concept = concept_data["concept"].lower()
        parent = concept_data["parent_concept"].lower()
        
        # Score based on concept and parent presence in chunk
        score = 0
        if concept in chunk_lower:
            score += 2
        if parent in chunk_lower:
            score += 1
        
        # Bonus for exact concept matches or multi-word concepts
        if len(concept.split()) > 1 and concept in chunk_lower:
            score += 1
        
        if score > best_score:
            best_score = score
            best_match = concept_data

    if best_match and best_score > 0:
        return {
            "concept": best_match["concept"],
            "parent_concept": best_match["parent_concept"],
            "difficulty": best_match["difficulty"],
            "is_tagged": True
        }
    
    # Fallback if no good match
    return _fallback_metadata_for_chunk(chunk_text)


def extract_concepts_from_chunks(chunks: List[str], db: Session) -> List[Dict[str, Optional[str]]]:
    """Batch multiple chunks into a single Gemini call and return concept tags for each chunk."""
    if not chunks:
        return []

    if not ENABLE_CONCEPT_TAGGING:
        logger.info("Concept tagging disabled, using fallback metadata for %d chunks", len(chunks))
        return [_fallback_metadata_for_chunk(chunk) for chunk in chunks]

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
        raw_text = getattr(response, "text", "")
        logger.debug("Gemini concept extraction raw response: %s", raw_text[:2000])
        clean_text = _clean_json_payload(raw_text)
        data = json.loads(clean_text)
        if not isinstance(data, list):
            raise ValueError("Expected JSON array from Gemini")

        results = [_fallback_metadata_for_chunk(chunk) for chunk in chunks]
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

            item["is_tagged"] = True
            results[index] = _normalize_tag(item, chunks[index])

        for idx, tag in enumerate(results):
            logger.info(
                "Chunk %d concept tag: concept=%s parent=%s difficulty=%s tagged=%s",
                idx,
                tag["concept"],
                tag["parent_concept"],
                tag["difficulty"],
                tag["is_tagged"],
            )

        return results

    except Exception as e:
        logger.warning("Concept extraction failed, using fallback metadata: %s", e)
        return [_fallback_metadata_for_chunk(chunk) for chunk in chunks]


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
    """Orchestrates extraction, chunking, and tagging for a document using document-level concepts."""
    processed_chunks = []

    # Extract full text for document-level concept extraction
    if filename.lower().endswith(".pdf"):
        full_text, page_offsets = _extract_pdf_text_and_offsets(file_bytes)
        logger.info("Extracted %d chars from %d PDF pages for %s", len(full_text), len(page_offsets), filename)
    else:
        full_text = file_bytes.decode("utf-8", errors="ignore")
        page_offsets = []
        logger.info("Extracted %d chars from text document %s", len(full_text), filename)

    if not full_text:
        logger.warning("No text extracted from %s", filename)
        return []

    # Step 1: Extract document-level concepts
    logger.info("Step 1: Extracting document-level concepts for %s", filename)
    document_concepts = extract_document_concepts(full_text, filename, db)

    # Step 2: Create chunks and map them to document concepts
    logger.info("Step 2: Creating chunks and mapping to document concepts for %s", filename)
    
    chunk_items: List[Dict[str, object]] = []
    if filename.lower().endswith(".pdf"):
        for chunk_data in _chunk_text_with_positions(full_text, chunk_size=2000, overlap=400):
            chunk_text_val = chunk_data["text"]
            if len(chunk_text_val.strip()) < 50:
                continue
            page_number = _get_page_number_for_offset(chunk_data["start"], page_offsets)
            chunk_items.append({"text": chunk_text_val, "page_number": page_number})
    else:
        for chunk_data in _chunk_text_with_positions(full_text, chunk_size=2000, overlap=400):
            chunk_text_val = chunk_data["text"]
            if len(chunk_text_val.strip()) < 50:
                continue
            chunk_items.append({"text": chunk_text_val, "page_number": 1})

    # Step 3: Map each chunk to the best matching document concept
    logger.info("Step 3: Mapping %d chunks to document concepts for %s", len(chunk_items), filename)
    for item in chunk_items:
        chunk_text = str(item["text"])
        concept_mapping = map_chunk_to_concept(chunk_text, document_concepts)
        
        processed_chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "text": chunk_text,
            "concept": concept_mapping["concept"],
            "parent_concept": concept_mapping["parent_concept"],
            "difficulty": concept_mapping["difficulty"],
            "is_tagged": concept_mapping.get("is_tagged", False),
            "page_number": item["page_number"],
            "document_title": filename,
        })

    # Log statistics
    tagged_count = sum(1 for chunk in processed_chunks if chunk.get("is_tagged", False))
    logger.info(
        "Document processing complete for %s: %d chunks, %d tagged (%.1f%%), %d fallback",
        filename,
        len(processed_chunks),
        tagged_count,
        (tagged_count / len(processed_chunks) * 100) if processed_chunks else 0,
        len(processed_chunks) - tagged_count
    )

    return processed_chunks
