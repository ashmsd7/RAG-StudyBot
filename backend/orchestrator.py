import os
import json
from sqlalchemy.orm import Session
from models import StudentState
from database import vector_collection
from gemini_client import generate_content_with_limit

def evaluate_mastery(mastery: float) -> str:
    if mastery < 0.4:
        return "novice"
    elif mastery < 0.7:
        return "intermediate"
    else:
        return "advanced"

def generate_quiz_question(concept: str, mastery: float, db: Session, strict_mode: bool = True):
    level = evaluate_mastery(mastery)
    
    # 1. Retrieve chunks (3-5 chunks max)
    results = vector_collection.query(
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
            # Return a response indicating insufficient information
            return {
                "question": "Insufficient information found in uploaded material.",
                "hints": ["Please upload a PDF containing details about this concept."],
                "difficulty": level,
                "source_chunks": []
            }
        context = ""
    else:
        context = "\n".join(results["documents"][0])
        
    # Extract citation sources
    source_chunks = []
    if has_chunks:
        for idx, cid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][idx] if results.get("metadatas") else {}
            source_chunks.append({
                "chunk_id": cid,
                "document_title": meta.get("document_title", "Unknown"),
                "page_number": meta.get("page_number", 1)
            })

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
        clean_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(clean_text)
        data["source_chunks"] = source_chunks
        return data
    except Exception as e:
        print(f"Error in generate_quiz_question: {e}")
        return {
            "question": "Insufficient information found in uploaded material.",
            "hints": ["Please upload a PDF containing details about this concept."],
            "difficulty": level,
            "source_chunks": []
        }

def evaluate_answer(
    concept: str, 
    question: str, 
    answer: str, 
    current_mastery: float, 
    db: Session, 
    strict_mode: bool = True
):
    level = evaluate_mastery(current_mastery)
    
    # 1. Retrieve chunks (3-5 chunks max)
    results = vector_collection.query(
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
    source_chunks = []
    if has_chunks:
        for idx, cid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][idx] if results.get("metadatas") else {}
            source_chunks.append({
                "chunk_id": cid,
                "document_title": meta.get("document_title", "Unknown"),
                "page_number": meta.get("page_number", 1)
            })

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
        clean_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
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
