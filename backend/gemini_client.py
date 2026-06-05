import os
import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
import models

# Load environment variables
# Try loading from parent directory first if backend is run from root, otherwise current dir
if os.path.exists("../.env"):
    load_dotenv("../.env")
else:
    load_dotenv()

# Configure GenAI
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY or API_KEY == "your_gemini_api_key_here":
    # Fallback to placeholder if not configured yet
    API_KEY = "placeholder"

genai.configure(api_key=API_KEY)

# Load limits
DAILY_REQ_LIMIT = int(os.environ.get("GEMINI_DAILY_REQ_LIMIT", 100))
DAILY_TOKEN_LIMIT = int(os.environ.get("GEMINI_DAILY_TOKEN_LIMIT", 200000))
MONTHLY_REQ_LIMIT = int(os.environ.get("GEMINI_MONTHLY_REQ_LIMIT", 2000))
MONTHLY_TOKEN_LIMIT = int(os.environ.get("GEMINI_MONTHLY_TOKEN_LIMIT", 4000000))

def get_today_prefix() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")

def get_month_prefix() -> str:
    return datetime.datetime.now().strftime("%Y-%m")

def get_daily_usage(db: Session):
    today = get_today_prefix()
    results = db.query(
        func.count(models.ApiUsage.id).label("req_count"),
        func.sum(models.ApiUsage.total_tokens).label("token_count")
    ).filter(
        models.ApiUsage.timestamp.like(f"{today}%"),
        models.ApiUsage.status == "success"
    ).first()
    
    req_count = results.req_count or 0
    token_count = results.token_count or 0
    return req_count, token_count

def get_monthly_usage(db: Session):
    month = get_month_prefix()
    results = db.query(
        func.count(models.ApiUsage.id).label("req_count"),
        func.sum(models.ApiUsage.total_tokens).label("token_count")
    ).filter(
        models.ApiUsage.timestamp.like(f"{month}%"),
        models.ApiUsage.status == "success"
    ).first()
    
    req_count = results.req_count or 0
    token_count = results.token_count or 0
    return req_count, token_count

def generate_content_with_limit(
    model_name: str, 
    prompt: str, 
    db: Session, 
    endpoint: str,
    generation_config: dict = None
):
    """
    Wraps Gemini generation calls. Checks limits before making the call,
    and logs token usage in SQLite after a successful call.
    """
    # 1. Check daily/monthly limits
    daily_req, daily_tokens = get_daily_usage(db)
    monthly_req, monthly_tokens = get_monthly_usage(db)
    
    if daily_req >= DAILY_REQ_LIMIT:
        raise HTTPException(
            status_code=429, 
            detail=f"Daily Gemini API request limit of {DAILY_REQ_LIMIT} reached. (Current: {daily_req})"
        )
    if daily_tokens >= DAILY_TOKEN_LIMIT:
        raise HTTPException(
            status_code=429, 
            detail=f"Daily Gemini API token limit of {DAILY_TOKEN_LIMIT} reached. (Current: {daily_tokens})"
        )
        
    if monthly_req >= MONTHLY_REQ_LIMIT:
        raise HTTPException(
            status_code=429, 
            detail=f"Monthly Gemini API request limit of {MONTHLY_REQ_LIMIT} reached. (Current: {monthly_req})"
        )
    if monthly_tokens >= MONTHLY_TOKEN_LIMIT:
        raise HTTPException(
            status_code=429, 
            detail=f"Monthly Gemini API token limit of {MONTHLY_TOKEN_LIMIT} reached. (Current: {monthly_tokens})"
        )
    
    # 2. Call Gemini API (using Flash as configured/passed)
    model = genai.GenerativeModel(model_name)
    try:
        response = model.generate_content(prompt, generation_config=generation_config)
        
        # Extract usage metadata
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens = response.usage_metadata.prompt_token_count
            completion_tokens = response.usage_metadata.candidates_token_count
            total_tokens = response.usage_metadata.total_token_count
            
        # 3. Save successful usage logs
        usage_log = models.ApiUsage(
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            endpoint=endpoint,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status="success"
        )
        db.add(usage_log)
        db.commit()
        
        return response
        
    except Exception as e:
        # Save failed log for visibility (optional, count tokens as 0)
        # Note: Do not count failures towards token limit, but record it
        try:
            usage_log = models.ApiUsage(
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                endpoint=endpoint,
                model_name=model_name,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                status=f"failed: {str(e)[:100]}"
            )
            db.add(usage_log)
            db.commit()
        except Exception as db_err:
            print(f"Error logging failed API call to DB: {db_err}")
            
        # Re-raise standard exception
        raise e
