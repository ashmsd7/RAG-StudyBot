from pydantic import BaseModel
from typing import List, Optional

class SourceChunk(BaseModel):
    chunk_id: str
    document_title: str
    page_number: int

class QuizRequest(BaseModel):
    user_id: str
    concept: str
    strict_mode: Optional[bool] = True

class QuestionResponse(BaseModel):
    question: str
    hints: List[str]
    difficulty: str
    source_chunks: Optional[List[SourceChunk]] = None

class AnswerEvaluationRequest(BaseModel):
    user_id: str
    concept: str
    question: str
    answer: str
    strict_mode: Optional[bool] = True

class AnswerEvaluationResponse(BaseModel):
    is_correct: bool
    feedback: str
    new_mastery_score: float
    mistake_logged: Optional[str] = None

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str
