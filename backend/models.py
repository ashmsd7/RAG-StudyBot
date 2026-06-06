from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, JSON
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True)
    title = Column(String)
    upload_date = Column(String)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(String, primary_key=True, index=True)
    document_id = Column(String, ForeignKey("documents.id"))
    text = Column(Text)
    concept = Column(String)
    parent_concept = Column(String)
    difficulty = Column(String)
    page_number = Column(Integer, default=1)
    document_title = Column(String)

class StudentState(Base):
    __tablename__ = "student_state"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    concept = Column(String, index=True)
    mastery_score = Column(Float, default=0.0)
    attempts = Column(Integer, default=0)
    mistakes = Column(JSON, default=list)

class ApiUsage(Base):
    __tablename__ = "api_usage"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, index=True)
    endpoint = Column(String)
    model_name = Column(String)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    status = Column(String, default="success")

