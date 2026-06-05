@echo off
echo =========================================
echo    Starting RAG StudyBot
echo =========================================

echo Starting FastAPI Backend...
start "RAG Backend" cmd /k "cd backend && call venv\Scripts\activate && uvicorn app:app --reload --port 8000"

echo Starting Next.js Frontend...
start "RAG Frontend" cmd /k "cd frontend && npm run dev"

echo Both services have been launched in separate terminal windows!
echo Backend API will be at: http://localhost:8000
echo Frontend UI will be at: http://localhost:3000
