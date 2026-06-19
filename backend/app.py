# Test comment: Antigravity is connected!
import os
import uuid
import datetime
import logging
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import (
    Base,
    auth_engine,
    study_engine,
    get_auth_db,
    get_study_db,
    get_user_vector_collection,
)
import models
import schemas
import auth

logger = logging.getLogger(__name__)

EMPTY_CONCEPT_VALUES = {"", "unknown", "none", "null", "n/a", "general", "general notes", "uploaded material"}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploaded_documents")


def _clean_metadata_label(value, fallback: str) -> str:
    label = " ".join(str(value or "").strip().split())
    if label.lower() in EMPTY_CONCEPT_VALUES:
        return fallback
    return label[:120]


def _clean_difficulty(value) -> str:
    difficulty = str(value or "").strip().lower()
    if difficulty in {"easy", "medium", "hard"}:
        return difficulty
    if difficulty in {"novice", "basic", "simple"}:
        return "easy"
    if difficulty in {"intermediate", "moderate"}:
        return "medium"
    if difficulty in {"advanced", "difficult", "complex"}:
        return "hard"
    return "medium"

Base.metadata.create_all(bind=auth_engine, tables=[models.User.__table__])
Base.metadata.create_all(
    bind=study_engine,
    tables=[
        models.Document.__table__,
        models.Chunk.__table__,
        models.StudentState.__table__,
        models.ChatUsage.__table__,
        models.RecentQuizHistory.__table__,
        models.ApiUsage.__table__,
    ],
)

def _generated_username(user_id: str) -> str:
    digits = "".join(ch for ch in user_id if ch.isdigit())
    if len(digits) < 4:
        digits = str(abs(hash(user_id)) % 10000).zfill(4)
    return f"User{digits[-4:]}"


def _ensure_username(user: models.User, db: Session) -> str:
    if user.username:
        return user.username
    user.username = _generated_username(user.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.username


def migrate_users_table() -> None:
    with auth_engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(users)"))
        columns = {row[1] for row in result.fetchall()}
        if "username" not in columns:
            logger.info("Migrating users table: adding username")
            conn.execute(text("ALTER TABLE users ADD COLUMN username TEXT"))


def migrate_chunks_table() -> None:
    """Add columns that older SQLite study DBs may be missing."""
    with study_engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(chunks)"))
        columns = {row[1] for row in result.fetchall()}
        required_columns = {
            "page_number": "ALTER TABLE chunks ADD COLUMN page_number INTEGER DEFAULT 1",
            "is_tagged": "ALTER TABLE chunks ADD COLUMN is_tagged BOOLEAN DEFAULT 0",
            "document_title": "ALTER TABLE chunks ADD COLUMN document_title TEXT DEFAULT ''",
        }

        for column_name, statement in required_columns.items():
            if column_name not in columns:
                logger.info("Migrating chunks table: adding %s", column_name)
                conn.execute(text(statement))


migrate_users_table()
migrate_chunks_table()


def migrate_documents_table() -> None:
    with study_engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(documents)"))
        columns = {row[1] for row in result.fetchall()}
        if "file_path" not in columns:
            logger.info("Migrating documents table: adding file_path")
            conn.execute(text("ALTER TABLE documents ADD COLUMN file_path TEXT"))


migrate_documents_table()

app = FastAPI(title="Adaptive AI Study Coach API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Adaptive AI Study Coach API"}

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    import ingestion

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        doc_id = str(uuid.uuid4())
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        safe_name = os.path.basename(file.filename or "document")
        stored_filename = f"{doc_id}_{safe_name}"
        file_path = os.path.join(UPLOAD_DIR, stored_filename)
        with open(file_path, "wb") as stored_file:
            stored_file.write(content)

        doc = models.Document(
            id=doc_id,
            user_id=current_user.id,
            title=file.filename,
            upload_date=datetime.datetime.now().isoformat(),
            file_path=file_path,
        )
        db.add(doc)

        processed_chunks = ingestion.process_document(content, file.filename, db)
        if processed_chunks is None:
            processed_chunks = []

        collection = get_user_vector_collection(current_user.id)

        for c_data in processed_chunks:
            text_value = str(c_data.get("text") or "")
            inferred_concept = ingestion.infer_topic_from_text(text_value) if hasattr(ingestion, "infer_topic_from_text") else "General Notes"
            concept = _clean_metadata_label(c_data.get("concept"), inferred_concept)
            parent_concept = _clean_metadata_label(c_data.get("parent_concept"), "Uploaded Material")
            difficulty = _clean_difficulty(c_data.get("difficulty"))
            page_number = int(c_data.get("page_number", 1) or 1)
            document_title = _clean_metadata_label(c_data.get("document_title"), file.filename)
            is_tagged = bool(c_data.get("is_tagged", False))
            logger.info(
                "Saving chunk metadata: chunk_id=%s concept=%s parent=%s difficulty=%s page=%s tagged=%s",
                c_data.get("chunk_id"),
                concept,
                parent_concept,
                difficulty,
                page_number,
                is_tagged,
            )

            c = models.Chunk(
                id=c_data["chunk_id"],
                document_id=doc_id,
                text=text_value,
                concept=concept,
                parent_concept=parent_concept,
                difficulty=difficulty,
                is_tagged=is_tagged,
                page_number=page_number,
                document_title=document_title,
            )
            db.add(c)
            collection.add(
                documents=[text_value],
                metadatas=[
                    {
                        "concept": concept,
                        "parent_concept": parent_concept,
                        "difficulty": difficulty,
                        "page_number": page_number,
                        "document_title": document_title,
                        "document_id": doc_id,
                        "is_tagged": is_tagged,
                    }
                ],
                ids=[c_data["chunk_id"]],
            )

        db.commit()
        return {"message": f"Uploaded and processed {len(processed_chunks)} chunks for {file.filename}."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

@app.post("/signup")
def signup(request: schemas.SignupRequest, db: Session = Depends(get_auth_db)):
    existing = db.query(models.User).filter(models.User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = auth.hash_password(request.password)
    user_id = str(uuid.uuid4())
    username = request.username or _generated_username(user_id)
    user = models.User(id=user_id, email=request.email, hashed_password=hashed, username=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User created successfully"}

@app.post("/login")
def login(response: Response, request: schemas.LoginRequest, db: Session = Depends(get_auth_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user or not auth.verify_password(user.hashed_password, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    username = _ensure_username(user, db)
    auth.set_access_token(response, user.id)
    token = auth.create_access_token({"sub": user.id})
    return {"message": "Logged in successfully", "access_token": token, "token_type": "bearer", "username": username}

@app.post("/logout")
def logout(response: Response):
    auth.clear_access_token(response)
    return {"message": "Logged out successfully"}

@app.get("/me")
def get_current_user_endpoint(current_user: auth.User = Depends(auth.get_current_user), db: Session = Depends(get_auth_db)):
    username = _ensure_username(current_user, db)
    return {"user_id": current_user.id, "email": current_user.email, "username": username}

@app.patch("/me")
def update_current_user_profile(
    request: schemas.ProfileUpdateRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_auth_db),
):
    current_user.username = request.username.strip()[:32]
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"user_id": current_user.id, "email": current_user.email, "username": current_user.username}

@app.get("/documents")
def list_documents(
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    docs = (
        db.query(models.Document)
        .filter(models.Document.user_id == current_user.id)
        .order_by(models.Document.upload_date.desc())
        .all()
    )
    return [
        {"id": doc.id, "title": doc.title, "upload_date": doc.upload_date}
        for doc in docs
    ]

@app.get("/documents/{doc_id}/file")
def get_document_file(
    doc_id: str,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    doc = (
        db.query(models.Document)
        .filter(models.Document.id == doc_id, models.Document.user_id == current_user.id)
        .first()
    )
    if not doc or not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="Document file not found")
    return FileResponse(doc.file_path, media_type="application/pdf", filename=doc.title or "document.pdf")

@app.get("/student/state")
def student_state(
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    states = (
        db.query(models.StudentState)
        .filter(models.StudentState.user_id == current_user.id)
        .all()
    )
    return [
        {
            "concept": state.concept,
            "mastery_score": state.mastery_score,
            "attempts": state.attempts,
            "mistakes": state.mistakes or [],
        }
        for state in states
    ]

@app.get("/concepts")
def get_concepts(
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    rows = (
        db.query(models.Chunk.concept, models.Chunk.parent_concept, models.Chunk.text)
        .join(models.Document, models.Chunk.document_id == models.Document.id)
        .filter(models.Document.user_id == current_user.id)
        .all()
    )
    concepts = []
    seen = set()
    for concept, parent_concept, chunk_text in rows:
        candidates = [concept, parent_concept]
        if not any(str(candidate or "").strip().lower() not in EMPTY_CONCEPT_VALUES for candidate in candidates):
            try:
                import ingestion
                candidates.append(ingestion.infer_topic_from_text(chunk_text or ""))
            except Exception:
                candidates.append("General Notes")

        for candidate in candidates:
            label = _clean_metadata_label(candidate, "")
            key = label.lower()
            if key and key not in EMPTY_CONCEPT_VALUES and key not in seen:
                concepts.append(label)
                seen.add(key)
                break

    logger.info("Returning %d concepts for user=%s: %s", len(concepts), current_user.id, concepts[:20])
    return concepts

@app.get("/recommendations", response_model=schemas.RecommendationsResponse)
def get_recommendations(
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    states = (
        db.query(models.StudentState)
        .filter(models.StudentState.user_id == current_user.id)
        .order_by(models.StudentState.mastery_score.asc(), models.StudentState.attempts.asc())
        .all()
    )
    weakest = []
    seen = set()
    for state in states:
        label = _clean_metadata_label(state.concept, "")
        key = label.lower()
        if key and key not in EMPTY_CONCEPT_VALUES and key not in seen:
            weakest.append(label)
            seen.add(key)

    if not weakest:
        for label in get_concepts(current_user=current_user, db=db):
            key = label.lower()
            if key not in seen:
                weakest.append(label)
                seen.add(key)
            if len(weakest) >= 3:
                break

    return {"weakest_concepts": weakest[:5]}

@app.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    doc = (
        db.query(models.Document)
        .filter(models.Document.id == doc_id, models.Document.user_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunk_ids = [c.id for c in db.query(models.Chunk).filter(models.Chunk.document_id == doc_id).all()]
    if chunk_ids:
        collection = get_user_vector_collection(current_user.id)
        collection.delete(ids=chunk_ids)
        db.query(models.Chunk).filter(models.Chunk.id.in_(chunk_ids)).delete(synchronize_session=False)

    file_path = doc.file_path
    db.delete(doc)
    db.commit()
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            logger.warning("Could not remove document file %s", file_path)
    return {"message": "Document and associated chunks deleted"}

@app.post("/quiz", response_model=schemas.QuestionResponse)
def get_quiz(
    request: schemas.QuizRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    state = (
        db.query(models.StudentState)
        .filter(
            models.StudentState.user_id == current_user.id,
            models.StudentState.concept == request.concept,
        )
        .first()
    )
    mastery = state.mastery_score if state else 0.0

    import orchestrator

    try:
        quiz_data = orchestrator.generate_quiz_question(
            current_user.id,
            request.concept,
            mastery,
            db,
            strict_mode=request.strict_mode,
            requested_difficulty=request.difficulty,
        )
        # Ensure the response is a dict with the expected keys.
        if not isinstance(quiz_data, dict) or "question" not in quiz_data:
            raise ValueError("Invalid quiz payload returned from orchestrator")
        return quiz_data
    except Exception as e:
        logger.exception("Quiz generation failed for user=%s concept=%s: %s", current_user.id, request.concept, e)
        # Safe fallback response matching `schemas.QuestionResponse`
        return {
            "question": "Unable to generate a quiz question right now.",
            "hints": [],
            "difficulty": "novice",
            "source_chunks": [],
            "question_id": None,
        }

@app.post("/summary", response_model=schemas.SummaryResponse)
def get_summary(
    request: schemas.SummaryRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    import orchestrator

    return orchestrator.generate_concept_summary(current_user.id, request.concept, db)

@app.post("/chat", response_model=schemas.ChatResponse)
def chat_with_documents(
    request: schemas.ChatRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    import orchestrator

    return orchestrator.generate_grounded_chat_response(
        current_user.id,
        request.message,
        db,
        concept=request.concept,
    )

@app.post("/evaluate", response_model=schemas.AnswerEvaluationResponse)
def evaluate_answer(
    request: schemas.AnswerEvaluationRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    state = (
        db.query(models.StudentState)
        .filter(
            models.StudentState.user_id == current_user.id,
            models.StudentState.concept == request.concept,
        )
        .first()
    )

    if not state:
        state = models.StudentState(
            user_id=current_user.id,
            concept=request.concept,
            mastery_score=0.0,
            attempts=0,
            mistakes=[],
        )
        db.add(state)
        db.commit()
        db.refresh(state)

    current_mastery = state.mastery_score
    import orchestrator

    eval_data = orchestrator.evaluate_answer(
        current_user.id,
        request.concept,
        request.question,
        request.answer,
        current_mastery,
        db,
        strict_mode=request.strict_mode,
    )

    state.mastery_score = eval_data.get("new_mastery_score", current_mastery)
    state.attempts += 1

    mistake = eval_data.get("mistake_logged")
    if mistake:
        current_mistakes = state.mistakes or []
        current_mistakes.append(mistake)
        state.mistakes = current_mistakes[:]

    db.commit()
    return eval_data

@app.get("/api/usage")
def get_api_usage(db: Session = Depends(get_study_db)):
    import gemini_client

    daily_req, daily_tokens = gemini_client.get_daily_usage(db)
    monthly_req, monthly_tokens = gemini_client.get_monthly_usage(db)
    return {
        "daily": {
            "requests": daily_req,
            "requests_limit": gemini_client.DAILY_REQ_LIMIT,
            "tokens": daily_tokens,
            "tokens_limit": gemini_client.DAILY_TOKEN_LIMIT,
        },
        "monthly": {
            "requests": monthly_req,
            "requests_limit": gemini_client.MONTHLY_REQ_LIMIT,
            "tokens": monthly_tokens,
            "tokens_limit": gemini_client.MONTHLY_TOKEN_LIMIT,
        },
    }
