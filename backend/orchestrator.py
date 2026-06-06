import os
import json
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from database import get_user_vector_collection
from gemini_client import generate_content_with_limit

logger = logging.getLogger(__name__)


def evaluate_mastery(mastery: float) -> str:
    if mastery < 0.4:
        return "novice"
    elif mastery < 0.7:
        return "intermediate"
    else:
        return "advanced"


def _clean_json_payload(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    elif text.startswith("```"):
        text = text[len("```"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def _normalize_hints(value) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _source_chunks_from_results(results) -> List[dict]:
    source_chunks = []
    if not results or not results.get("ids"):
        return source_chunks

    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
    for idx, cid in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
        source_chunks.append({
            "chunk_id": cid,
            "document_title": meta.get("document_title", "Unknown"),
            "page_number": int(meta.get("page_number", 1) or 1),
        })
    return source_chunks


def _fallback_question(level: str, source_chunks: Optional[List[dict]] = None) -> dict:
    return {
        "question": "Insufficient information found in uploaded material.",
        "hints": ["Try selecting a concept that appears directly in your uploaded document."],
        "difficulty": level,
        "source_chunks": source_chunks or [],
    }


def generate_concept_summary(user_id: str, concept: str, db: Session) -> dict:
    collection = get_user_vector_collection(user_id)
    results = collection.query(
        query_texts=[concept],
        n_results=3,
    )

    has_chunks = (
        results
        and results.get("documents")
        and len(results["documents"]) > 0
        and len(results["documents"][0]) > 0
    )

    if not has_chunks:
        return {
            "summary": "No relevant uploaded material was found for this concept.",
            "key_points": [],
            "source_chunks": [],
        }

    context = "\n".join(results["documents"][0])
    source_chunks = _source_chunks_from_results(results)
    prompt = f"""
SYSTEM:
Explain the requested concept using ONLY the uploaded material context.
Do not use outside knowledge. Keep the explanation short and grounded.

Concept:
{concept}

Context:
{context}

Output JSON strictly in this exact shape:
{{
  "summary": "short explanation of the concept from the uploaded material",
  "key_points": ["key point 1", "key point 2", "..."]
}}
"""

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="summary",
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)
        key_points = data.get("key_points", [])
        if isinstance(key_points, str):
            key_points = [key_points]
        if not isinstance(key_points, list):
            key_points = []

        return {
            "summary": str(data.get("summary") or "No summary was returned for this concept."),
            "key_points": [str(point) for point in key_points if point is not None],
            "source_chunks": source_chunks,
        }
    except Exception as e:
        logger.warning("Error in generate_concept_summary for user=%s concept=%s: %s", user_id, concept, e)
        return {
            "summary": "Unable to generate a summary from the uploaded material right now.",
            "key_points": [],
            "source_chunks": source_chunks,
        }


def generate_quiz_question(user_id: str, concept: str, mastery: float, db: Session, strict_mode: bool = True):
    level = evaluate_mastery(mastery)
    collection = get_user_vector_collection(user_id)
    
    # 1. Retrieve chunks (3-5 chunks max)
    results = collection.query(
        query_texts=[concept],
        n_results=3
    )
    
    # 2. Retrieval Validation Layer
    has_chunks = (
        results 
        and results.get("documents") 
        and len(results["documents"]) > 0 
        and len(results["documents"][0]) > 0
    )
    
    if not has_chunks:
        if strict_mode:
            return _fallback_question(level)
        context = ""
    else:
        context = "\n".join(results["documents"][0])
        
    # Extract citation sources
    source_chunks = _source_chunks_from_results(results) if has_chunks else []

    # 3. Grounded Quiz Generation Prompt
    prompt = f"""
    SYSTEM:
    Generate quiz questions ONLY from the provided context.
    
    Rules:
    - Every question must be answerable using the context.
    - Do not use general domain knowledge.
    - Do not introduce concepts not found in the context.
    - If insufficient content exists, generate fewer questions instead of hallucinating.
    - Focus on '{concept}' at a '{level}' difficulty level.
    
    Context:
    {context}
    
    Output JSON strictly in this format:
    {{
        "question": "The question text here",
        "hints": ["hint 1", "hint 2"],
        "difficulty": "{level}"
    }}
    """
    
    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="quiz"
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)
        return {
            "question": str(data.get("question") or "Insufficient information found in uploaded material."),
            "hints": _normalize_hints(data.get("hints") or data.get("hint")),
            "difficulty": str(data.get("difficulty") or level),
            "source_chunks": source_chunks,
        }
    except Exception as e:
        logger.warning("Error in generate_quiz_question for user=%s concept=%s: %s", user_id, concept, e)
        return _fallback_question(level, source_chunks)

def evaluate_answer(
    user_id: str,
    concept: str, 
    question: str, 
    answer: str, 
    current_mastery: float, 
    db: Session, 
    strict_mode: bool = True
):
    level = evaluate_mastery(current_mastery)
    collection = get_user_vector_collection(user_id)
    
    # 1. Retrieve chunks (3-5 chunks max)
    results = collection.query(
        query_texts=[question, concept],
        n_results=3
    )
    
    # 2. Retrieval Validation Layer
    has_chunks = (
        results 
        and results.get("documents") 
        and len(results["documents"]) > 0 
        and len(results["documents"][0]) > 0
    )
    
    if not has_chunks:
        if strict_mode:
            return {
                "is_correct": False,
                "feedback": "This information is not available in the uploaded material.",
                "mistake_logged": "Insufficient context",
                "new_mastery_score": current_mastery,
                "source_chunks": []
            }
        context = ""
    else:
        context = "\n".join(results["documents"][0])
        
    # Extract citation sources
    source_chunks = _source_chunks_from_results(results) if has_chunks else []

    # 3. Grounded Prompting for Evaluation
    prompt = f"""
    SYSTEM:
    You are a document-grounded study assistant.
    
    Rules:
    - Use ONLY the provided context.
    - Do NOT use external knowledge.
    - Do NOT infer concepts not explicitly mentioned.
    - Do NOT generate questions or evaluations from outside the provided material.
    - If the answer cannot be found in the context, reply that "This information is not available in the uploaded material." and mark as incorrect.
    
    Context:
    {context}
    
    The student is answering a question about '{concept}'.
    Question: {question}
    Student Answer: {answer}
    
    Output JSON strictly in this format:
    {{
        "is_correct": true/false,
        "feedback": "Your feedback here. Be encouraging.",
        "mistake_logged": "short description of mistake" (or null if correct)
    }}
    """
    
    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="evaluate"
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)
        
        # Calculate new mastery
        if data.get("is_correct"):
            new_mastery = min(1.0, current_mastery + 0.15)
        else:
            new_mastery = max(0.0, current_mastery - 0.05)
            
        data["new_mastery_score"] = new_mastery
        data["source_chunks"] = source_chunks
        return data
    except Exception as e:
        print(f"Error in evaluate_answer: {e}")
        return {
            "is_correct": False,
            "feedback": "This information is not available in the uploaded material.",
            "mistake_logged": "Evaluation error",
            "new_mastery_score": current_mastery,
            "source_chunks": []
        }
