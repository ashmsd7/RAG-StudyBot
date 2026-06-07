import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as app_module
import auth
import ingestion
import models
import orchestrator
from database import Base


class FakeCollection:
    def add(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        raise RuntimeError("force sqlite retrieval fallback")


def fake_gemini_response(*args, **kwargs):
    endpoint = kwargs.get("endpoint")
    if endpoint == "chat":
        return types.SimpleNamespace(text='{"answer": "This matches your uploaded notes."}')
    if endpoint == "summary":
        return types.SimpleNamespace(text='{"summary": "Search algorithms are covered in these notes.", "key_points": ["Uninformed search has no goal information.", "Informed search uses heuristics."]}')
    if endpoint == "quiz":
        return types.SimpleNamespace(text='{"question": "What does uninformed search lack?", "hints": ["Look at the search comparison."], "difficulty": "easy"}')
    if endpoint == "evaluate":
        return types.SimpleNamespace(text='{"is_correct": false, "correctness_score": 0.6, "feedback": "Partially correct from the notes.", "mistake_logged": "Needs the heuristic contrast."}')
    return types.SimpleNamespace(text="{}")


@pytest.fixture()
def client_and_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'study.db'}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.Document.__table__,
            models.Chunk.__table__,
            models.StudentState.__table__,
            models.ChatUsage.__table__,
            models.RecentQuizHistory.__table__,
            models.ApiUsage.__table__,
        ],
    )

    def override_study_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_user():
        return types.SimpleNamespace(id="test-user", email="student@gmail.com")

    monkeypatch.setattr(app_module, "get_user_vector_collection", lambda user_id: FakeCollection())
    monkeypatch.setattr(orchestrator, "get_user_vector_collection", lambda user_id: FakeCollection())
    monkeypatch.setattr(orchestrator, "generate_content_with_limit", fake_gemini_response)
    monkeypatch.setattr(
        ingestion,
        "process_document",
        lambda content, filename, db: [
            {
                "chunk_id": "chunk-a",
                "text": "Uninformed search has no additional information about the goal node.",
                "concept": "Search Algorithms",
                "parent_concept": "AI Search",
                "difficulty": "easy",
                "is_tagged": True,
                "page_number": 1,
                "document_title": filename,
            },
            {
                "chunk_id": "chunk-b",
                "text": "Informed search uses heuristic information to guide search efficiency.",
                "concept": "Search Algorithms",
                "parent_concept": "AI Search",
                "difficulty": "medium",
                "is_tagged": True,
                "page_number": 2,
                "document_title": filename,
            },
        ],
    )
    monkeypatch.setattr(orchestrator.random, "choice", lambda items: items[0])

    app_module.app.dependency_overrides[app_module.get_study_db] = override_study_db
    app_module.app.dependency_overrides[auth.get_current_user] = override_user

    try:
        yield TestClient(app_module.app), TestingSessionLocal
    finally:
        app_module.app.dependency_overrides.clear()


def test_upload_chat_quiz_evaluate_summary_persistence_flow(client_and_db):
    client, SessionLocal = client_and_db

    upload = client.post(
        "/upload",
        files={"file": ("notes.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )
    assert upload.status_code == 200

    chat = client.post("/chat", json={"message": "Compare informed and uninformed search.", "concept": "Search Algorithms"})
    assert chat.status_code == 200
    chat_data = chat.json()
    assert chat_data["usage_limits"]["remaining_chat_requests"] == 24
    assert chat_data["source_chunks"]

    summary = client.post("/summary", json={"concept": "Search Algorithms"})
    assert summary.status_code == 200
    assert summary.json()["key_points"]

    quiz_one = client.post("/quiz", json={"concept": "Search Algorithms", "difficulty": "easy"})
    assert quiz_one.status_code == 200
    first_question_id = quiz_one.json()["question_id"]
    assert first_question_id == "chunk-a"

    quiz_two = client.post("/quiz", json={"concept": "Search Algorithms", "difficulty": "easy"})
    assert quiz_two.status_code == 200
    assert quiz_two.json()["question_id"] == "chunk-b"

    evaluation = client.post(
        "/evaluate",
        json={
            "concept": "Search Algorithms",
            "question": quiz_two.json()["question"],
            "answer": "Uninformed search does not use goal information, while informed search uses heuristic guidance.",
        },
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["correctness_score"] == 0.6
    assert evaluation.json()["new_mastery_score"] > 0

    db = SessionLocal()
    try:
        assert db.query(models.Chunk).count() == 2
        assert db.query(models.ChatUsage).filter_by(user_id="test-user").one().used_count == 1
        history = db.query(models.RecentQuizHistory).filter_by(
            user_id="test-user",
            concept="search algorithms",
            difficulty="easy",
        ).one()
        assert history.question_ids == ["chunk-a", "chunk-b"]
        state = db.query(models.StudentState).filter_by(
            user_id="test-user",
            concept="Search Algorithms",
        ).one()
        assert state.attempts == 1
        assert state.mastery_score > 0
    finally:
        db.close()
