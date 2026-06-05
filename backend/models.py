from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base

# User model for authentication
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    # Relationship to documents and student state
    documents = relationship("Document", back_populates="owner")
    states = relationship("StudentState", back_populates="user")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    title = Column(String)
    upload_date = Column(String)
    
    # Relationships
    owner = relationship("User", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document")

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
    
    document = relationship("Document", back_populates="chunks")

class StudentState(Base):
    __tablename__ = "student_state"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    user = relationship("User", back_populates="states")
    concept = Column(String, index=True)
    mastery_score = Column(Float, default=0.0)
    attempts = Column(Integer, default=0)
    mistakes = Column(JSON, default=list)  # List of strings

class ApiUsage(Base):
    __tablename__ = "api_usage"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, index=True)  # Store in YYYY-MM-DD HH:MM:SS format
    endpoint = Column(String)               # 'ingestion' / 'quiz' / 'evaluate'
    model_name = Column(String)             # 'gemini-1.5-flash'
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    status = Column(String, default="success") # 'success' or 'failed'

