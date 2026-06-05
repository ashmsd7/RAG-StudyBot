import os
import json
import uuid
from typing import List, Dict
from sqlalchemy.orm import Session
from pypdf import PdfReader
from io import BytesIO
from gemini_client import generate_content_with_limit

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """Splits text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

def extract_concepts_from_chunk(chunk_text: str, db: Session) -> Dict[str, str]:
    """
    Uses Gemini Flash to analyze the chunk and assign a concept tag, wrapping calls with safety limits.
    Returns: {"concept": "string", "parent_concept": "string", "difficulty": "string"}
    """
    prompt = f"""
    Analyze the following text from a study document and determine its core concept.
    Text:
    \"\"\"{chunk_text}\"\"\"
    
    Output JSON strictly in this format:
    {{
        "concept": "Primary specific concept discussed (e.g., 'Dynamic Programming')",
        "parent_concept": "Broader topic (e.g., 'Algorithms')",
        "difficulty": "Easy, Medium, or Hard based on the topic complexity"
    }}
    Ensure the concept is concise and specific.
    """
    
    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="ingestion"
        )
        clean_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(clean_text)
        return {
            "concept": data.get("concept", "General"),
            "parent_concept": data.get("parent_concept", "General"),
            "difficulty": data.get("difficulty", "Medium")
        }
    except Exception as e:
        print(f"Concept extraction failed: {e}")
        return {
            "concept": "General Concept",
            "parent_concept": "General Domain",
            "difficulty": "Medium"
        }

def process_document(file_bytes: bytes, filename: str, db: Session) -> List[Dict]:
    """Orchestrates extraction, chunking, and tagging for a document. Page-by-page for PDFs."""
    processed_chunks = []
    
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(file_bytes))
        for page_idx, page in enumerate(reader.pages):
            page_num = page_idx + 1
            page_text = page.extract_text()
            if not page_text or len(page_text.strip()) < 10:
                continue
                
            # Chunk the page text with slightly smaller size since it is a single page
            chunks = chunk_text(page_text, chunk_size=800, overlap=100)
            for chunk in chunks:
                if len(chunk.strip()) < 50:
                    continue
                    
                tags = extract_concepts_from_chunk(chunk, db)
                processed_chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "text": chunk,
                    "concept": tags["concept"],
                    "parent_concept": tags["parent_concept"],
                    "difficulty": tags["difficulty"],
                    "page_number": page_num,
                    "document_title": filename
                })
    else:
        # Fallback to plain text
        text = file_bytes.decode("utf-8", errors="ignore")
        chunks = chunk_text(text)
        for chunk in chunks:
            if len(chunk.strip()) < 50:
                continue
                
            tags = extract_concepts_from_chunk(chunk, db)
            processed_chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "text": chunk,
                "concept": tags["concept"],
                "parent_concept": tags["parent_concept"],
                "difficulty": tags["difficulty"],
                "page_number": 1,
                "document_title": filename
            })
            
    return processed_chunks
