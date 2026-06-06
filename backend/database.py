import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import chromadb

AUTH_DATABASE_URL = os.getenv("AUTH_DATABASE_URL", "sqlite:///./credentials.db")
STUDY_DATABASE_URL = os.getenv("STUDY_DATABASE_URL", "sqlite:///./adaptive_study.db")

auth_engine = create_engine(AUTH_DATABASE_URL, connect_args={"check_same_thread": False})
study_engine = create_engine(STUDY_DATABASE_URL, connect_args={"check_same_thread": False})

AuthSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)
StudySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=study_engine)
Base = declarative_base()

# ChromaDB Setup
chroma_client = chromadb.PersistentClient(path="./chroma_db")

def get_user_vector_collection(user_id: str):
    return chroma_client.get_or_create_collection(name=f"user_{user_id}_chunks")


def get_auth_db():
    db = AuthSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_study_db():
    db = StudySessionLocal()
    try:
        yield db
    finally:
        db.close()
