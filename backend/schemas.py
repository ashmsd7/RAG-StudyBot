from __future__ import annotations
import re
from typing import Annotated, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

class SourceChunk(BaseModel):
    chunk_id: str
    document_title: str
    page_number: int

class QuizRequest(BaseModel):
    user_id: Optional[str] = None
    concept: str
    strict_mode: Optional[bool] = True
    difficulty: Optional[str] = None

class SummaryRequest(BaseModel):
    concept: str

class ChatUsageLimits(BaseModel):
    max_message_chars: int
    max_context_chunks: int
    max_chat_requests: int
    remaining_chat_requests: int

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
    concept: Optional[str] = None

class QuestionResponse(BaseModel):
    question: str
    hints: List[str]
    difficulty: str
    source_chunks: Optional[List[SourceChunk]] = None
    question_id: Optional[str] = None

class SummaryResponse(BaseModel):
    summary: str
    key_points: List[str]
    source_chunks: Optional[List[SourceChunk]] = None

class ChatResponse(BaseModel):
    answer: str
    source_chunks: Optional[List[SourceChunk]] = None
    usage_limits: ChatUsageLimits

class AnswerEvaluationRequest(BaseModel):
    user_id: Optional[str] = None
    concept: str
    question: str
    answer: str
    strict_mode: Optional[bool] = True

class AnswerEvaluationResponse(BaseModel):
    is_correct: bool
    feedback: str
    new_mastery_score: float
    correctness_score: Optional[float] = None
    mistake_logged: Optional[str] = None
    source_chunks: Optional[List[SourceChunk]] = None

GmailEmail = Annotated[EmailStr, Field(pattern=r"^[^@\s]+@gmail\.com$")]

SPECIAL_CHAR_REGEX = re.compile(r"[!@#$%^&*()_+\-=[\]{}; '\\:\"|,.<>\/?]")

class SignupRequest(BaseModel):
    email: GmailEmail
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not SPECIAL_CHAR_REGEX.search(value):
            raise ValueError("Password must include at least one special character")
        return value

class LoginRequest(BaseModel):
    email: GmailEmail
    password: str
