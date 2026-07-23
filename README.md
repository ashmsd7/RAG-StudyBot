
An AI-powered study platform that uses Retrieval-Augmented Generation (RAG) to answer questions from uploaded study material and provide personalized learning experiences.

## Features

-  PDF Upload & Processing
-  Semantic Search using Vector Embeddings
-  Context-Aware Question Answering
-  AI-Generated Quizzes
-  Student Mastery Tracking
-  Adaptive Learning Based on Weak Areas
-  User Authentication

## Tech Stack

### Backend
- FastAPI
- SQLite
- SQLAlchemy
- ChromaDB
- Gemini API

### Frontend
- Next.js
- TypeScript
- Tailwind CSS

### Architecture 
PDF Upload
    ↓
Chunking
    ↓
Embeddings
    ↓
ChromaDB
    ↓
Retrieval
    ↓
Gemini
    ↓
Answer Generation

## Project Structure

```text
backend/

cd backend

python -m venv venv

venv\Scripts\activate

pip install -r requirements.txt

uvicorn app:app --reload


frontend/

cd frontend

npm install

npm run dev
```
### Author

Ashwin, AI&DS Student From CBIT Hyderabad
Manikanta , AI&DS Student From CBIT Hyderabad
