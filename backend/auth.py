import os
import datetime
from typing import Optional
import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from models import User
from database import get_db

# Load secret key from env (fallback to placeholder)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "changeme_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

ph = PasswordHasher()

def hash_password(password: str) -> str:
    """Hash a plain password using Argon2id."""
    return ph.hash(password)

def verify_password(hashed_password: str, password: str) -> bool:
    try:
        return ph.verify(hashed_password, password)
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def set_access_token(response: Response, user_id: str):
    token = create_access_token({"sub": user_id})
    # HttpOnly cookie, secure flag omitted for local dev
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60, path="/", domain="localhost", samesite="none", secure=False)

def clear_access_token(response: Response):
    response.delete_cookie(key="access_token", path="/")
