# Test comment: Antigravity is connected!
import os
import uuid
import datetime
import logging
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Response
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

Base.metadata.create_all(bind=auth_engine, tables=[models.User.__table__])
Base.metadata.create_all(
    bind=study_engine,
    tables=[
        models.Document.__table__,
        models.Chunk.__table__,
        models.StudentState.__table__,
        models.ApiUsage.__table__,
    ],
)

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


migrate_chunks_table()

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
        doc = models.Document(
            id=doc_id,
            user_id=current_user.id,
            title=file.filename,
            upload_date=datetime.datetime.now().isoformat(),
        )
        db.add(doc)

        processed_chunks = ingestion.process_document(content, file.filename, db)
        if processed_chunks is None:
            processed_chunks = []

        collection = get_user_vector_collection(current_user.id)

        for c_data in processed_chunks:
            c = models.Chunk(
                id=c_data["chunk_id"],
                document_id=doc_id,
                text=c_data["text"],
                concept=c_data["concept"],
                parent_concept=c_data["parent_concept"],
                difficulty=c_data["difficulty"],
                is_tagged=c_data.get("is_tagged", False),
                page_number=c_data.get("page_number", 1),
                document_title=c_data.get("document_title", file.filename),
            )
            db.add(c)
            collection.add(
                documents=[c_data["text"]],
                metadatas=[
                    {
                        "concept": c_data["concept"],
                        "parent_concept": c_data["parent_concept"],
                        "difficulty": c_data["difficulty"],
                        "page_number": c_data.get("page_number", 1),
                        "document_title": c_data.get("document_title", file.filename),
                        "is_tagged": c_data.get("is_tagged", False),
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
    user = models.User(id=str(uuid.uuid4()), email=request.email, hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User created successfully"}

@app.post("/login")
def login(response: Response, request: schemas.LoginRequest, db: Session = Depends(get_auth_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user or not auth.verify_password(user.hashed_password, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    auth.set_access_token(response, user.id)
    token = auth.create_access_token({"sub": user.id})
    return {"message": "Logged in successfully", "access_token": token, "token_type": "bearer"}

@app.post("/logout")
def logout(response: Response):
    auth.clear_access_token(response)
    return {"message": "Logged out successfully"}

@app.get("/me")
def get_current_user_endpoint(current_user: auth.User = Depends(auth.get_current_user)):
    return {"user_id": current_user.id, "email": current_user.email}

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
    concepts = (
        db.query(models.Chunk.concept)
        .join(models.Document, models.Chunk.document_id == models.Document.id)
        .filter(models.Document.user_id == current_user.id)
        .distinct()
        .all()
    )
    return [c[0] for c in concepts if c[0]]

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

    db.delete(doc)
    db.commit()
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

    quiz_data = orchestrator.generate_quiz_question(
        current_user.id,
        request.concept,
        mastery,
        db,
        strict_mode=request.strict_mode,
    )
    return quiz_data

@app.post("/summary", response_model=schemas.SummaryResponse)
def get_summary(
    request: schemas.SummaryRequest,
    current_user: auth.User = Depends(auth.get_current_user),
    db: Session = Depends(get_study_db),
):
    import orchestrator

    return orchestrator.generate_concept_summary(current_user.id, request.concept, db)

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
