import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import chromadb

# SQLite Setup
DATABASE_URL = "sqlite:///./adaptive_study.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ChromaDB Setup
chroma_client = chromadb.PersistentClient(path="./chroma_db")
vector_collection = chroma_client.get_or_create_collection(name="chunks")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
