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

class QuestionResponse(BaseModel):
    question: str
    hints: List[str]
    difficulty: str
    source_chunks: Optional[List[SourceChunk]] = None

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
    mistake_logged: Optional[str] = None

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
