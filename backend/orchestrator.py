import os
import json
import logging
import datetime
from typing import List, Optional, Dict, Tuple
import random
from sqlalchemy.orm import Session
from database import get_user_vector_collection
from gemini_client import generate_content_with_limit
import models

logger = logging.getLogger(__name__)

# --- Configurable thresholds ---
# Similarity threshold: ChromaDB uses L2 distance by default (lower = more similar).
# These defaults work well with the default sentence-transformers embedding model.
SIMILARITY_THRESHOLD = float(os.environ.get("RAG_SIMILARITY_THRESHOLD", "1.2"))
MAX_RETRIEVE_CHUNKS = int(os.environ.get("RAG_MAX_RETRIEVE_CHUNKS", "15"))
MAX_CONTEXT_CHUNKS = int(os.environ.get("RAG_MAX_CONTEXT_CHUNKS", "8"))
CHAT_MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "1200"))
CHAT_MAX_SESSION_MESSAGES = int(os.environ.get("CHAT_MAX_SESSION_MESSAGES", "25"))
RECENT_QUESTION_LIMIT = int(os.environ.get("RECENT_QUESTION_LIMIT", "12"))

QUIZ_DIFFICULTY_LEVELS = {
    "easy": {
        "level": "easy",
        "instruction": "Ask one simple recall or definition question. The answer should be a short phrase or 1-2 sentences from the context.",
    },
    "medium": {
        "level": "medium",
        "instruction": "Ask one understanding question about how two details in the context connect. Avoid multi-step reasoning.",
    },
    "hard": {
        "level": "hard",
        "instruction": "Ask one deeper analysis question, but keep it answerable from the context and avoid obscure wording.",
    },
}


def evaluate_mastery(mastery: float) -> str:
    if mastery < 0.4:
        return "novice"
    elif mastery < 0.7:
        return "intermediate"
    else:
        return "advanced"


def _normalize_quiz_difficulty(value: Optional[str], mastery: float) -> str:
    if value:
        normalized = value.strip().lower()
        if normalized in QUIZ_DIFFICULTY_LEVELS:
            return normalized

    mastery_level = evaluate_mastery(mastery)
    if mastery_level == "advanced":
        return "medium"
    return "easy"


def _can_use_db(db: Session) -> bool:
    return hasattr(db, "query") and hasattr(db, "commit")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _chat_usage_for_user(user_id: str, db: Optional[Session] = None) -> Dict[str, int]:
    used = 0
    if db is not None and _can_use_db(db):
        row = db.query(models.ChatUsage).filter(models.ChatUsage.user_id == user_id).first()
        if row:
            used = int(row.used_count or 0)

    remaining = max(CHAT_MAX_SESSION_MESSAGES - used, 0)
    return {
        "max_message_chars": CHAT_MAX_MESSAGE_CHARS,
        "max_context_chunks": MAX_CONTEXT_CHUNKS,
        "max_chat_requests": CHAT_MAX_SESSION_MESSAGES,
        "remaining_chat_requests": remaining,
    }


def _increment_chat_usage(user_id: str, db: Session) -> Dict[str, int]:
    if not _can_use_db(db):
        return _chat_usage_for_user(user_id, db)

    row = db.query(models.ChatUsage).filter(models.ChatUsage.user_id == user_id).first()
    if not row:
        row = models.ChatUsage(user_id=user_id, used_count=0, updated_at=_now_iso())
        db.add(row)

    row.used_count = int(row.used_count or 0) + 1
    row.updated_at = _now_iso()
    db.commit()
    return _chat_usage_for_user(user_id, db)


def _get_recent_question_ids(db: Session, user_id: str, concept: str, difficulty: str) -> List[str]:
    if not _can_use_db(db):
        return []

    row = (
        db.query(models.RecentQuizHistory)
        .filter(
            models.RecentQuizHistory.user_id == user_id,
            models.RecentQuizHistory.concept == concept.strip().lower(),
            models.RecentQuizHistory.difficulty == difficulty,
        )
        .first()
    )
    if not row or not isinstance(row.question_ids, list):
        return []
    return [str(question_id) for question_id in row.question_ids if question_id]


def _save_recent_question_ids(
    db: Session,
    user_id: str,
    concept: str,
    difficulty: str,
    question_ids: List[str],
) -> None:
    if not _can_use_db(db):
        return

    normalized_concept = concept.strip().lower()
    row = (
        db.query(models.RecentQuizHistory)
        .filter(
            models.RecentQuizHistory.user_id == user_id,
            models.RecentQuizHistory.concept == normalized_concept,
            models.RecentQuizHistory.difficulty == difficulty,
        )
        .first()
    )
    if not row:
        row = models.RecentQuizHistory(
            user_id=user_id,
            concept=normalized_concept,
            difficulty=difficulty,
            question_ids=[],
            updated_at=_now_iso(),
        )
        db.add(row)

    row.question_ids = question_ids[-RECENT_QUESTION_LIMIT:]
    row.updated_at = _now_iso()
    db.commit()


def _remember_question(
    db: Session,
    user_id: str,
    concept: str,
    difficulty: str,
    question_id: Optional[str],
) -> None:
    if not question_id:
        return
    recent = _get_recent_question_ids(db, user_id, concept, difficulty)
    if question_id in recent:
        recent.remove(question_id)
    recent.append(question_id)
    _save_recent_question_ids(db, user_id, concept, difficulty, recent)


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


def _source_chunks_from_results(
    results, chunk_texts: Optional[List[str]] = None
) -> List[dict]:
    """Build source chunk metadata from ChromaDB query results."""
    source_chunks = []
    if not results or not results.get("ids"):
        return source_chunks

    ids = results.get("ids", [[]])[0]
    metadatas = (
        results.get("metadatas", [[]])[0]
        if results.get("metadatas")
        else []
    )
    for idx, cid in enumerate(ids):
        meta = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
        entry = {
            "chunk_id": cid,
            "document_title": meta.get("document_title", "Unknown"),
            "page_number": int(meta.get("page_number", 1) or 1),
            "document_id": meta.get("document_id"),
        }
        # Include a preview of the chunk text if available (for debugging/audit)
        if chunk_texts and idx < len(chunk_texts):
            entry["preview"] = chunk_texts[idx][:200]
        source_chunks.append(entry)
    return source_chunks


def _attach_document_availability(source_chunks: List[dict], db: Session) -> List[dict]:
    doc_ids = {chunk.get("document_id") for chunk in source_chunks if chunk.get("document_id")}
    if not doc_ids:
        return source_chunks

    docs = db.query(models.Document.id, models.Document.file_path).filter(models.Document.id.in_(doc_ids)).all()
    available = {doc.id: bool(doc.file_path and os.path.exists(doc.file_path)) for doc in docs}
    for chunk in source_chunks:
        doc_id = chunk.get("document_id")
        if doc_id:
            chunk["document_available"] = available.get(doc_id, False)
    return source_chunks


def _tokenize_query(text: str) -> List[str]:
    return [
        token
        for token in "".join(char.lower() if char.isalnum() else " " for char in text).split()
        if len(token) >= 3
    ]


def _retrieve_chunks_from_sqlite(
    user_id: str,
    query_texts: List[str],
    db: Session,
    max_chunks: int = MAX_CONTEXT_CHUNKS,
) -> Tuple[str, List[dict], List[dict]]:
    if not _can_use_db(db):
        return "", [], []

    query_text = " ".join(query_texts).strip()
    query_terms = set(_tokenize_query(query_text))
    rows = (
        db.query(models.Chunk)
        .join(models.Document, models.Chunk.document_id == models.Document.id)
        .filter(models.Document.user_id == user_id)
        .all()
    )
    if not rows:
        return "", [], []

    scored_rows = []
    for row in rows:
        concept = (row.concept or "").lower()
        parent_concept = (row.parent_concept or "").lower()
        text = row.text or ""
        haystack = f"{concept} {parent_concept} {text}".lower()
        score = sum(3 if term in concept else 1 for term in query_terms if term in haystack)
        if query_text and query_text.lower() in haystack:
            score += 5
        scored_rows.append((score, row))

    scored_rows.sort(key=lambda item: item[0], reverse=True)
    selected_rows = [row for score, row in scored_rows if score > 0][:max_chunks]
    if not selected_rows:
        selected_rows = [row for _, row in scored_rows[:max_chunks]]

    selected_chunks = []
    source_chunks = []
    context_parts = []
    for row in selected_rows:
        metadata = {
            "document_title": row.document_title or "Unknown",
            "document_id": row.document_id,
            "page_number": int(row.page_number or 1),
            "concept": row.concept or "",
            "difficulty": row.difficulty or "medium",
        }
        selected_chunks.append({
            "chunk_id": row.id,
            "text": row.text or "",
            "metadata": metadata,
            "best_distance": 0.0,
        })
        source_chunks.append({
            "chunk_id": row.id,
            "document_title": metadata["document_title"],
            "page_number": metadata["page_number"],
            "document_id": metadata["document_id"],
        })
        context_parts.append(
            f"[Source: {metadata['document_title']}, page {metadata['page_number']}]\n{row.text or ''}"
        )

    return "\n\n---\n\n".join(context_parts), _attach_document_availability(source_chunks, db), selected_chunks


def _retrieve_and_rerank(
    user_id: str,
    query_texts: List[str],
    db: Session,
    max_chunks: int = MAX_RETRIEVE_CHUNKS,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> Tuple[str, List[dict], List[dict]]:
    """
    Retrieve chunks from ChromaDB, filter by similarity threshold, deduplicate,
    and re-rank by relevance. Returns (context_string, source_chunks, selected_chunks).
    
    This is the core grounding layer — it ensures ONLY high-quality,
    relevant chunks are passed to the LLM.
    """
    try:
        collection = get_user_vector_collection(user_id)

        # Query ChromaDB with a larger pool for re-ranking
        results = collection.query(
            query_texts=query_texts,
            n_results=max_chunks,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Chroma retrieval failed for user=%s query=%s: %s", user_id, query_texts, exc)
        return _retrieve_chunks_from_sqlite(user_id, query_texts, db, max_chunks=MAX_CONTEXT_CHUNKS)

    if not results or not results.get("ids"):
        return _retrieve_chunks_from_sqlite(user_id, query_texts, db, max_chunks=MAX_CONTEXT_CHUNKS)

    ids_list = results.get("ids", [[]])
    docs_list = results.get("documents", [[]])
    meta_list = results.get("metadatas", [[]])
    dist_list = results.get("distances", [[]])

    # Collect all candidate chunks across query texts with their distances
    candidates: Dict[str, Dict] = {}

    for q_idx in range(len(query_texts)):
        if q_idx >= len(ids_list):
            continue
        ids = ids_list[q_idx]
        docs = docs_list[q_idx] if q_idx < len(docs_list) else []
        metas = meta_list[q_idx] if q_idx < len(meta_list) else []
        dists = dist_list[q_idx] if q_idx < len(dist_list) else []

        for c_idx, cid in enumerate(ids):
            distance = dists[c_idx] if c_idx < len(dists) else float("inf")

            # --- Similarity Threshold Filter ---
            # Skip chunks that are too far (not semantically similar enough)
            if distance > similarity_threshold:
                continue

            if cid not in candidates:
                candidates[cid] = {
                    "chunk_id": cid,
                    "text": docs[c_idx] if c_idx < len(docs) else "",
                    "metadata": metas[c_idx] if c_idx < len(metas) else {},
                    "best_distance": distance,
                }
            else:
                # Keep the best (lowest) distance across queries
                if distance < candidates[cid]["best_distance"]:
                    candidates[cid]["best_distance"] = distance

    if not candidates:
        logger.warning(
            "Similarity threshold filtered out all results for user=%s query=%s. Falling back to top-ranked chunks.",
            user_id,
            query_texts,
        )
        # Fall back to the first query's results if available, even if they are outside the threshold.
        fallback_ids = ids_list[0] if ids_list else []
        fallback_docs = docs_list[0] if docs_list else []
        fallback_metas = meta_list[0] if meta_list else []
        fallback_dists = dist_list[0] if dist_list else []
        fallback_items = []
        for c_idx, cid in enumerate(fallback_ids):
            if c_idx >= MAX_CONTEXT_CHUNKS:
                break
            fallback_items.append({
                "chunk_id": cid,
                "text": fallback_docs[c_idx] if c_idx < len(fallback_docs) else "",
                "metadata": fallback_metas[c_idx] if c_idx < len(fallback_metas) else {},
                "best_distance": fallback_dists[c_idx] if c_idx < len(fallback_dists) else float("inf"),
            })

        if not fallback_items:
            return _retrieve_chunks_from_sqlite(user_id, query_texts, db, max_chunks=MAX_CONTEXT_CHUNKS)

        selected = fallback_items
    else:
        # --- Re-ranking: Sort by best distance (most relevant first) ---
        sorted_candidates = sorted(candidates.values(), key=lambda x: x["best_distance"])
        # Take top N after re-ranking
        selected = sorted_candidates[:MAX_CONTEXT_CHUNKS]

    # Build context string
    context_parts = []
    for item in selected:
        meta = item["metadata"]
        doc_title = meta.get("document_title", "Unknown")
        page = meta.get("page_number", "?")
        context_parts.append(
            f"[Source: {doc_title}, page {page}]\n{item['text']}"
        )

    context = "\n\n---\n\n".join(context_parts)

    missing_doc_ids = [item["chunk_id"] for item in selected if not item["metadata"].get("document_id")]
    doc_id_by_chunk = {}
    if missing_doc_ids:
        rows = db.query(models.Chunk.id, models.Chunk.document_id).filter(models.Chunk.id.in_(missing_doc_ids)).all()
        doc_id_by_chunk = {row.id: row.document_id for row in rows}

    # Build source chunk references for citation
    source_chunks = [
        {
            "chunk_id": item["chunk_id"],
            "document_title": item["metadata"].get("document_title", "Unknown"),
            "page_number": int(item["metadata"].get("page_number", 1) or 1),
            "document_id": item["metadata"].get("document_id") or doc_id_by_chunk.get(item["chunk_id"]),
        }
        for item in selected
    ]

    logger.info(
        "Retrieved %d chunks for user=%s, filtered to %d quality chunks after re-ranking",
        sum(len(ids) for ids in ids_list),
        user_id,
        len(selected),
    )

    return context, _attach_document_availability(source_chunks, db), selected


def _fallback_question(
    level: str,
    source_chunks: Optional[List[dict]] = None,
    concept: str = "this topic",
    has_context: bool = False,
) -> dict:
    if has_context:
        if level == "hard":
            question = f"Using the uploaded material, explain why {concept} matters in this section."
        elif level == "medium":
            question = f"According to the uploaded material, what are the main details connected to {concept}?"
        else:
            question = f"In your own words, what does the uploaded material say about {concept}?"
        return {
            "question": question,
            "hints": ["Use only the cited source pages shown below."],
            "difficulty": level,
            "source_chunks": source_chunks or [],
        }

    return {
        "question": "Insufficient information found in uploaded material to generate a question on this topic.",
        "hints": ["Try selecting a concept that appears directly in your uploaded document."],
        "difficulty": level,
        "source_chunks": source_chunks or [],
    }


def _compact_context_preview(context: str, max_chars: int = 700) -> str:
    clean = " ".join(context.split())
    return clean[:max_chars].strip()


def _fallback_summary_from_context(context: str, concept: str) -> Tuple[str, List[str]]:
    preview = _compact_context_preview(context, 650)
    if not preview:
        return "No relevant uploaded material was found for this concept.", []

    summary = (
        f"Your uploaded material connects {concept} to this section: {preview}"
        if concept
        else f"Your uploaded material says: {preview}"
    )
    sentences = [
        sentence.strip()
        for sentence in preview.replace("?", ".").replace("!", ".").split(".")
        if len(sentence.strip()) > 30
    ]
    key_points = sentences[:3]
    return summary, key_points


def _score_answer_against_context(answer: str, context: str) -> float:
    answer_terms = set(_tokenize_query(answer))
    context_terms = set(_tokenize_query(context))
    if not answer_terms or not context_terms:
        return 0.0
    matched = answer_terms.intersection(context_terms)
    coverage = len(matched) / max(len(answer_terms), 1)
    return max(0.0, min(1.0, coverage))


def _student_state_for_chat(user_id: str, concept: str, message: str, db: Session) -> Optional[dict]:
    if not _can_use_db(db):
        return None

    query = db.query(models.StudentState).filter(models.StudentState.user_id == user_id)
    state = None
    if concept:
        state = query.filter(models.StudentState.concept == concept).first()
    if not state:
        message_lower = message.lower()
        states = query.all()
        state = next(
            (
                item for item in states
                if item.concept and item.concept.lower() in message_lower
            ),
            None,
        )
    if not state:
        return None
    return {
        "concept": state.concept,
        "mastery_score": float(state.mastery_score or 0.0),
        "attempts": int(state.attempts or 0),
        "mistakes": state.mistakes or [],
    }


def generate_concept_summary(user_id: str, concept: str, db: Session) -> dict:
    # Use the new retrieval pipeline
    context, source_chunks, _ = _retrieve_and_rerank(
        user_id,
        query_texts=[concept],
        db=db,
    )

    if not context:
        return {
            "summary": "No relevant uploaded material was found for this concept.",
            "key_points": [],
            "source_chunks": [],
        }

    prompt = f"""
SYSTEM:
You are a document-grounded study assistant. Explain the requested concept using ONLY the provided uploaded material context.
Rules:
- Use ONLY the uploaded material context below. Do NOT use outside knowledge.
- If the context does not contain enough information about the concept, say so explicitly.
- Keep the explanation concise, clear, and grounded in the source material.
- Cite page numbers naturally if helpful.

Concept: {concept}

Uploaded Material Context:
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
        summary, key_points = _fallback_summary_from_context(context, concept)
        return {
            "summary": summary,
            "key_points": key_points,
            "source_chunks": source_chunks,
        }


def generate_grounded_chat_response(
    user_id: str,
    message: str,
    db: Session,
    concept: Optional[str] = None,
) -> dict:
    clean_message = (message or "").strip()
    clean_concept = (concept or "").strip()
    usage_limits = _chat_usage_for_user(user_id, db)

    if not clean_message:
        return {
            "answer": "Please enter a question about your uploaded study material.",
            "source_chunks": [],
            "usage_limits": usage_limits,
        }

    if usage_limits["remaining_chat_requests"] <= 0:
        return {
            "answer": "You have used the available chat turns for this session. Start a fresh server session or continue with quizzes and summaries.",
            "source_chunks": [],
            "usage_limits": usage_limits,
        }

    if len(clean_message) > CHAT_MAX_MESSAGE_CHARS:
        clean_message = clean_message[:CHAT_MAX_MESSAGE_CHARS]

    query_texts = [clean_message]
    if clean_concept:
        query_texts.append(clean_concept)

    context, source_chunks, _ = _retrieve_and_rerank(
        user_id,
        query_texts=query_texts,
        db=db,
    )

    usage_limits = _increment_chat_usage(user_id, db)

    if not context:
        # When no context is found, allow external source access
        external_prompt = f"""
SYSTEM:
You are a knowledgeable tutor. The student's question is not covered in their uploaded study material.

PERMISSION:
You have permission to use your general knowledge and external sources to answer this question.

REQUIREMENTS:
1. Provide the best possible answer using your knowledge.
2. If the question involves a numerical problem or algorithm:
   - Present the question clearly and neatly
   - Provide a step-by-step solved answer
   - Show all calculations/logic clearly
3. At the end, mention the source/link where this information can be verified
4. Be concise, direct, and professional
5. Use short readable paragraphs. Bullets are fine when they improve clarity
6. Bold important concepts, topic names, and keywords with Markdown

Student Question:
{clean_message}

Output JSON strictly in this format:
{{
  "answer": "your comprehensive answer with step-by-step solution if numerical, ending with source citation"
}}
"""

        try:
            response = generate_content_with_limit(
                model_name="gemini-flash-latest",
                prompt=external_prompt,
                db=db,
                endpoint="chat",
            )
            clean_text = _clean_json_payload(getattr(response, "text", ""))
            data = json.loads(clean_text)
            answer = str(data.get("answer") or "").strip()
            if not answer:
                answer = "I could not generate an answer for this question."

            return {
                "answer": answer,
                "source_chunks": [],
                "usage_limits": usage_limits,
            }
        except Exception as e:
            logger.warning("Error in external chat response for user=%s: %s", user_id, e)
            return {
                "answer": "Unable to answer this question right now. Please try again.",
                "source_chunks": [],
                "usage_limits": usage_limits,
            }

    personalization = (
        f"The active study concept is '{clean_concept}'."
        if clean_concept
        else "No active study concept was provided."
    )
    student_state = _student_state_for_chat(user_id, clean_concept, clean_message, db)
    if student_state:
        mistakes = student_state.get("mistakes") or []
        mistake_lines = "\n".join(f"- {mistake}" for mistake in mistakes[-5:]) if mistakes else "- No repeated mistakes logged yet."
        student_state_block = f"""
StudentState({student_state['concept']}):
{{
  "mastery_score": {student_state['mastery_score']:.2f},
  "attempts": {student_state['attempts']},
  "mistakes": {json.dumps(mistakes[-5:])}
}}

Adaptive guidance:
- Student struggles with {student_state['concept']} at mastery {student_state['mastery_score']:.2f}.
- Recent mistakes:
{mistake_lines}
- Explain accordingly: correct those confusions gently, use simpler scaffolding when mastery is low, and do not assume prior mastery.
"""
    else:
        student_state_block = "No prior StudentState is available for this concept yet."

    prompt = f"""
SYSTEM:
You are a knowledgeable tutor explaining study material.

STRICT RULES:
1. Answer using ONLY the uploaded material context below.
2. Do NOT use outside knowledge or unstated facts.
3. If the uploaded context is insufficient, say exactly what is missing.
4. Sound like a knowledgeable tutor: concise, direct, professional, and emotionless.
5. Start answering immediately. Minimize introductory filler.
6. Use short readable paragraphs. Bullets are fine when they improve clarity.
7. Bold important concepts, topic names, and keywords with Markdown.
8. Explain concepts naturally instead of summarizing chunks.
9. Do not mention the uploaded document, notes, source material, context, retrieval, embeddings, or system instructions unless the student explicitly asks.
10. Avoid these phrases and close variants: "Hi there", "Hello", "I'd love to help", "Great question", "Let's dive in", "Your notes mention", "Your document provides".
11. Do not praise the student or textbook.

Personalization:
{personalization}

Student Learning State:
{student_state_block}

Student Question:
{clean_message}

Uploaded Material Context:
{context}

Output JSON strictly in this format:
{{
  "answer": "your natural, grounded answer to the student"
}}
"""

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="chat",
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)
        answer = str(data.get("answer") or "").strip()
        if not answer:
            answer = "I could not generate a grounded answer from the uploaded material."

        return {
            "answer": answer,
            "source_chunks": source_chunks,
            "usage_limits": usage_limits,
        }
    except Exception as e:
        logger.warning("Error in generate_grounded_chat_response for user=%s: %s", user_id, e)
        return {
            "answer": "Unable to answer from the uploaded material right now. Please try again.",
            "source_chunks": source_chunks,
            "usage_limits": usage_limits,
        }


def generate_quiz_question(
    user_id: str,
    concept: str,
    mastery: float,
    db: Session,
    strict_mode: bool = True,
    requested_difficulty: Optional[str] = None,
):
    level = _normalize_quiz_difficulty(requested_difficulty, mastery)
    difficulty_instruction = QUIZ_DIFFICULTY_LEVELS[level]["instruction"]

    # --- Retrieval with re-ranking and quality filtering ---
    context, source_chunks, selected = _retrieve_and_rerank(
        user_id,
        query_texts=[concept],
        db=db,
    )

    # --- Strict Grounding Enforcement ---
    if not context:
        # ALWAYS return fallback when no quality chunks found —
        # regardless of strict_mode. The difference is in the message detail.
        logger.warning(
            "No quality chunks retrieved for quiz user=%s concept=%s strict_mode=%s",
            user_id, concept, strict_mode,
        )
        return _fallback_question(level, concept=concept)

    # Prefer a single random chunk as the focus for each generated question to
    # increase variety between successive quiz requests.
    primary_chunk = None
    question_id = None
    if isinstance(selected, list) and len(selected) > 0:
        recent_ids = set(_get_recent_question_ids(db, user_id, concept, level))
        unseen_chunks = [
            item for item in selected
            if item.get("chunk_id") not in recent_ids
        ]
        if not unseen_chunks:
            # All chunks have been used recently, clear history and shuffle
            _save_recent_question_ids(db, user_id, concept, level, [])
            random.shuffle(selected)
            unseen_chunks = selected

        primary_chunk = random.choice(unseen_chunks)
        primary_meta = primary_chunk.get("metadata", {}) if primary_chunk else {}
        doc_title = primary_meta.get("document_title", "Unknown")
        page = int(primary_meta.get("page_number", 1) or 1)
        # Build a compact context focused on the chosen chunk
        context = f"[Source: {doc_title}, page {page}]\n{primary_chunk.get('text', '')}"
        # Generate a unique question ID using chunk ID and timestamp to avoid collisions
        question_id = f"{primary_chunk.get('chunk_id')}_{int(datetime.datetime.now().timestamp() * 1000)}"

    # --- Grounded Quiz Generation Prompt ---
    prompt = f"""
SYSTEM:
You are a document-grounded quiz coach. Generate a helpful practice question using ONLY the provided uploaded material context.

STRICT RULES:
1. Every question MUST be 100% answerable using ONLY the context below.
2. Do NOT use any general domain knowledge not present in the context.
3. Do NOT introduce concepts, facts, or terminology not found in the uploaded material.
4. Since source context is available, prefer asking a smaller, simpler question about what is present instead of refusing.
5. If the context truly cannot support any question about '{concept}', output a JSON with:
   {{"question": "The uploaded material does not contain sufficient information about this topic.", "hints": [], "difficulty": "{level}"}}
6. Target difficulty: {level}.
7. Difficulty behavior: {difficulty_instruction}
8. Use direct, student-friendly wording. Avoid trick questions and overly broad questions.

Uploaded Material Context:
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
            endpoint="quiz",
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)

        question_text = str(data.get("question") or "").strip()

        # --- Post-hoc grounding validation ---
        # If the model returned an insufficient-context message, treat as fallback
        if (
            "does not contain" in question_text.lower()
            or "insufficient" in question_text.lower()
            or "no information" in question_text.lower()
            or not question_text
            or len(question_text) < 10
        ):
            return _fallback_question(level, source_chunks, concept=concept, has_context=bool(source_chunks))

        _remember_question(db, user_id, concept, level, question_id)
        return {
            "question": question_text,
            "hints": _normalize_hints(data.get("hints") or data.get("hint")),
            "difficulty": str(data.get("difficulty") or level),
            "source_chunks": source_chunks,
            "question_id": question_id,
        }
    except Exception as e:
        logger.warning("Error in generate_quiz_question for user=%s concept=%s: %s", user_id, concept, e)
        return _fallback_question(level, source_chunks, concept=concept, has_context=bool(source_chunks))


def evaluate_answer(
    user_id: str,
    concept: str,
    question: str,
    answer: str,
    current_mastery: float,
    db: Session,
    strict_mode: bool = True,
):
    level = evaluate_mastery(current_mastery)

    # --- Retrieval with re-ranking — query by BOTH concept and question ---
    context, source_chunks, selected = _retrieve_and_rerank(
        user_id,
        query_texts=[concept, question],
        db=db,
    )

    # --- Strict Grounding Enforcement ---
    if not context:
        logger.warning(
            "No quality chunks retrieved for evaluation user=%s concept=%s strict_mode=%s",
            user_id, concept, strict_mode,
        )
        return {
            "is_correct": False,
            "feedback": "This information is not available in the uploaded material. No relevant document chunks were found to evaluate your answer against.",
            "correctness_score": 0.0,
            "mistake_logged": "Insufficient context — no matching material found",
            "new_mastery_score": current_mastery,
            "source_chunks": [],
        }

    # --- Grounded Evaluation Prompt ---
    prompt = f"""
SYSTEM:
You are a document-grounded study assistant evaluating a student's answer.

EVALUATION PRINCIPLES:
1. Focus on CONCEPTUAL UNDERSTANDING rather than exact wording or phrasing.
2. Allow students to use their own lingo, wording, and examples to demonstrate understanding.
3. Examples that illustrate the concept correctly should NOT be penalized, even if not from the source material.
4. The core concepts and relationships must align with the uploaded material, but expression can vary.
5. Give generous partial credit when the student demonstrates understanding of the main ideas.
6. Only penalize if the answer contains FACTUAL ERRORS about the core concepts from the material.
7. Be encouraging and recognize good understanding even with different wording/examples.

SCORING GUIDELINES (correctness_score 0.0 to 1.0):
- 0.9-1.0 = Excellent understanding, core concepts fully grasped (even with different examples/wording)
- 0.7-0.9 = Good understanding, minor gaps or slightly different expression
- 0.5-0.7 = Partial understanding, some key concepts missing or confused
- 0.3-0.5 = Weak understanding, significant conceptual gaps
- 0.0-0.3 = Little to no understanding of the core concepts

For the "mistake_logged" field: provide a concise 1-sentence description of conceptual errors (or null if the core understanding is sound).

Uploaded Material Context:
{context}

Evaluation Task:
- Concept: {concept}
- Difficulty Level: {level}
- Question: {question}
- Student Answer: {answer}

Output JSON strictly in this format:
{{
    "is_correct": true or false,
    "correctness_score": 0.0,
    "feedback": "Your encouraging feedback here. Focus on whether they understand the core concepts, allowing for their own wording and examples.",
    "mistake_logged": "short description of conceptual mistake or null if understanding is sound"
}}
"""

    try:
        response = generate_content_with_limit(
            model_name="gemini-flash-latest",
            prompt=prompt,
            db=db,
            endpoint="evaluate",
        )
        clean_text = _clean_json_payload(getattr(response, "text", ""))
        data = json.loads(clean_text)

        try:
            correctness_score = float(data.get("correctness_score", 1.0 if data.get("is_correct") else 0.0))
        except (TypeError, ValueError):
            correctness_score = 1.0 if data.get("is_correct") else 0.0
        correctness_score = max(0.0, min(1.0, correctness_score))
        is_correct = correctness_score >= 0.75

        # --- Post-hoc validation: ensure feedback references the context ---
        feedback = str(data.get("feedback") or "").strip()
        if not feedback or len(feedback) < 5:
            feedback = (
                "Your answer has been evaluated against the uploaded material. "
                + ("It appears correct based on the source document." if is_correct
                   else "It does not align with the information found in your uploaded material.")
            )

        # Calculate new mastery
        if correctness_score >= 0.75:
            new_mastery = min(1.0, current_mastery + 0.15)
        elif correctness_score >= 0.4:
            new_mastery = min(1.0, current_mastery + 0.07)
        elif correctness_score > 0:
            new_mastery = min(1.0, current_mastery + 0.03)
        else:
            new_mastery = max(0.0, current_mastery - 0.03)

        mistake = data.get("mistake_logged")
        if mistake is not None:
            mistake = str(mistake).strip()
            if mistake.lower() in ("null", "none", "", "n/a"):
                mistake = None

        return {
            "is_correct": is_correct,
            "feedback": feedback,
            "correctness_score": correctness_score,
            "mistake_logged": mistake,
            "new_mastery_score": new_mastery,
            "source_chunks": source_chunks,
        }

    except Exception as e:
        logger.error("Error in evaluate_answer for user=%s concept=%s: %s", user_id, concept, e)
        correctness_score = _score_answer_against_context(answer, context)
        if correctness_score >= 0.75:
            new_mastery = min(1.0, current_mastery + 0.15)
        elif correctness_score >= 0.4:
            new_mastery = min(1.0, current_mastery + 0.07)
        elif correctness_score > 0:
            new_mastery = min(1.0, current_mastery + 0.03)
        else:
            new_mastery = max(0.0, current_mastery - 0.03)

        return {
            "is_correct": correctness_score >= 0.75,
            "feedback": (
                "I could not get the model evaluation, so I compared your answer with the retrieved source text. "
                f"Your answer appears to match about {(correctness_score * 100):.0f}% of the key wording from the uploaded material."
            ),
            "correctness_score": correctness_score,
            "mistake_logged": "Model evaluation fallback used",
            "new_mastery_score": new_mastery,
            "source_chunks": source_chunks if source_chunks else [],
        }
