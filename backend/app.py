# Test comment: Antigravity is connected!
import os
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, Base, get_db, vector_collection
import models
import schemas
import auth
from typing import List

# Create tables
Base.metadata.create_all(bind=engine)

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
async def upload_document(file: UploadFile = File(...), current_user: auth.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    import uuid, datetime
    import ingestion
    content = await file.read()
    doc_id = str(uuid.uuid4())
    doc = models.Document(
        id=doc_id,
        user_id=current_user.id,
        title=file.filename,
        upload_date=datetime.datetime.now().isoformat()
    )
    db.add(doc)
    processed_chunks = ingestion.process_document(content, file.filename, db)
    for c_data in processed_chunks:
        c = models.Chunk(
            id=c_data["chunk_id"],
            document_id=doc_id,
            text=c_data["text"],
            concept=c_data["concept"],
            parent_concept=c_data["parent_concept"],
            difficulty=c_data["difficulty"],
            page_number=c_data.get("page_number", 1),
            document_title=c_data.get("document_title", file.filename)
        )
        db.add(c)
        vector_collection.add(
            documents=[c_data["text"]],
            metadatas=[{
                "concept": c_data["concept"], 
                "parent_concept": c_data["parent_concept"], 
                "difficulty": c_data["difficulty"],
                "page_number": c_data.get("page_number", 1),
                "document_title": c_data.get("document_title", file.filename)
            }],
            ids=[c_data["chunk_id"]]
        )
        
    db.commit()
    return {"message": f"Uploaded and processed {len(processed_chunks)} chunks for {file.filename}."}
@app.post("/signup")
def signup(request: schemas.SignupRequest, db: Session = Depends(get_db)):
    from uuid import uuid4
    existing = db.query(models.User).filter(models.User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = auth.hash_password(request.password)
    user = models.User(id=str(uuid4()), email=request.email, hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User created successfully"}

@app.post("/login")
def login(response: Response, request: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user or not auth.verify_password(user.hashed_password, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    auth.set_access_token(response, user.id)
    return {"message": "Logged in successfully"}

@app.post("/logout")
def logout(response: Response):
    auth.clear_access_token(response)
    return {"message": "Logged out successfully"}

@app.get("/me")
def get_current_user_endpoint(current_user: auth.User = Depends(auth.get_current_user)):
    return {"user_id": current_user.id, "email": current_user.email}

def get_student_state(current_user: auth.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    states = db.query(models.StudentState).filter(models.StudentState.user_id == current_user.id).all()
    return states

@app.get("/concepts")
def get_concepts(db: Session = Depends(get_db)):
    concepts = db.query(models.Chunk.concept).distinct().all()
    return [c[0] for c in concepts if c[0]]

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, current_user: auth.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    # Verify ownership
    doc = db.query(models.Document).filter(models.Document.id == doc_id, models.Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # Delete associated chunks
    chunk_ids = [c.id for c in db.query(models.Chunk).filter(models.Chunk.document_id == doc_id).all()]
    if chunk_ids:
        vector_collection.delete(ids=chunk_ids)
        db.query(models.Chunk).filter(models.Chunk.id.in_(chunk_ids)).delete(synchronize_session=False)
    db.delete(doc)
    db.commit()
    return {"message": "Document and associated chunks deleted"}

def get_documents(current_user: auth.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    docs = db.query(models.Document).filter(models.Document.user_id == current_user.id).all()
    return docs

@app.post("/quiz", response_model=schemas.QuestionResponse)
def get_quiz(request: schemas.QuizRequest, db: Session = Depends(get_db)):
    # Find student state
    state = db.query(models.StudentState).filter(
        models.StudentState.user_id == request.user_id,
        models.StudentState.concept == request.concept
    ).first()
    
    mastery = state.mastery_score if state else 0.0
    
    import orchestrator  # absolute import — works from backend/
    quiz_data = orchestrator.generate_quiz_question(
        request.concept, 
        mastery, 
        db,
        strict_mode=request.strict_mode
    )
    
    return quiz_data

@app.post("/evaluate", response_model=schemas.AnswerEvaluationResponse)
def evaluate_answer(request: schemas.AnswerEvaluationRequest, db: Session = Depends(get_db)):
    state = db.query(models.StudentState).filter(
        models.StudentState.user_id == request.user_id,
        models.StudentState.concept == request.concept
    ).first()
    
    if not state:
        state = models.StudentState(
            user_id=request.user_id,
            concept=request.concept,
            mastery_score=0.0,
            attempts=0,
            mistakes=[]
        )
        db.add(state)
        db.commit()
        db.refresh(state)
        
    current_mastery = state.mastery_score
    
    import orchestrator  # absolute import — works from backend/
    eval_data = orchestrator.evaluate_answer(
        request.concept, 
        request.question, 
        request.answer, 
        current_mastery,
        db,
        strict_mode=request.strict_mode
    )
    
    # Update state
    state.mastery_score = eval_data.get("new_mastery_score", current_mastery)
    state.attempts += 1
    
    mistake = eval_data.get("mistake_logged")
    if mistake:
        current_mistakes = state.mistakes or []
        current_mistakes.append(mistake)
        # SQLAlchemy JSON mutation detection workaround
        state.mistakes = current_mistakes[:]
        
    db.commit()
    return eval_data

@app.get("/api/usage")
def get_api_usage(db: Session = Depends(get_db)):
    import gemini_client  # absolute import — works from backend/
    daily_req, daily_tokens = gemini_client.get_daily_usage(db)
    monthly_req, monthly_tokens = gemini_client.get_monthly_usage(db)
    return {
        "daily": {
            "requests": daily_req,
            "requests_limit": gemini_client.DAILY_REQ_LIMIT,
            "tokens": daily_tokens,
            "tokens_limit": gemini_client.DAILY_TOKEN_LIMIT
        },
        "monthly": {
            "requests": monthly_req,
            "requests_limit": gemini_client.MONTHLY_REQ_LIMIT,
            "tokens": monthly_tokens,
            "tokens_limit": gemini_client.MONTHLY_TOKEN_LIMIT
        }
    }
