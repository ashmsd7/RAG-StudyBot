import os
import time
import datetime
import logging
from dotenv import load_dotenv
import google.generativeai as genai
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
import models

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Load environment variables
# Try loading from parent directory first if backend is run from root, otherwise current dir
if os.path.exists("../.env"):
    load_dotenv("../.env")
else:
    load_dotenv()

# Configure GenAI
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY or API_KEY == "your_gemini_api_key_here":
    API_KEY = "placeholder"

genai.configure(api_key=API_KEY)

# Load limits
DAILY_REQ_LIMIT = int(os.environ.get("GEMINI_DAILY_REQ_LIMIT", 100))
DAILY_TOKEN_LIMIT = int(os.environ.get("GEMINI_DAILY_TOKEN_LIMIT", 200000))
MONTHLY_REQ_LIMIT = int(os.environ.get("GEMINI_MONTHLY_REQ_LIMIT", 2000))
MONTHLY_TOKEN_LIMIT = int(os.environ.get("GEMINI_MONTHLY_TOKEN_LIMIT", 4000000))
MAX_GEMINI_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "2"))
GEMINI_RETRY_BASE_SECONDS = int(os.environ.get("GEMINI_RETRY_BASE_SECONDS", "5"))


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


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "429" in message
        or "rate limit" in message
        or "quota" in message
        or "too many requests" in message
    )


def _log_failed_usage(db: Session, endpoint: str, model_name: str, error_message: str) -> None:
    try:
        usage_log = models.ApiUsage(
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            endpoint=endpoint,
            model_name=model_name,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            status=f"failed: {error_message[:100]}"
        )
        db.add(usage_log)
        db.commit()
    except Exception as db_err:
        logger.warning("Error logging failed API call to DB: %s", db_err)


def generate_content_with_limit(
    model_name: str,
    prompt: str,
    db: Session,
    endpoint: str,
    generation_config: dict = None,
):
    """
    Wraps Gemini generation calls. Checks limits before making the call,
    and logs token usage in SQLite after a successful call.
    """
    daily_req, daily_tokens = get_daily_usage(db)
    monthly_req, monthly_tokens = get_monthly_usage(db)

    if daily_req >= DAILY_REQ_LIMIT:
        logger.warning("Daily Gemini request limit reached before %s call (%s/%s)", endpoint, daily_req, DAILY_REQ_LIMIT)
        raise HTTPException(
            status_code=429,
            detail=f"Daily Gemini API request limit of {DAILY_REQ_LIMIT} reached. (Current: {daily_req})",
        )
    if daily_tokens >= DAILY_TOKEN_LIMIT:
        logger.warning("Daily Gemini token limit reached before %s call (%s/%s)", endpoint, daily_tokens, DAILY_TOKEN_LIMIT)
        raise HTTPException(
            status_code=429,
            detail=f"Daily Gemini API token limit of {DAILY_TOKEN_LIMIT} reached. (Current: {daily_tokens})",
        )
    if monthly_req >= MONTHLY_REQ_LIMIT:
        logger.warning("Monthly Gemini request limit reached before %s call (%s/%s)", endpoint, monthly_req, MONTHLY_REQ_LIMIT)
        raise HTTPException(
            status_code=429,
            detail=f"Monthly Gemini API request limit of {MONTHLY_REQ_LIMIT} reached. (Current: {monthly_req})",
        )
    if monthly_tokens >= MONTHLY_TOKEN_LIMIT:
        logger.warning("Monthly Gemini token limit reached before %s call (%s/%s)", endpoint, monthly_tokens, MONTHLY_TOKEN_LIMIT)
        raise HTTPException(
            status_code=429,
            detail=f"Monthly Gemini API token limit of {MONTHLY_TOKEN_LIMIT} reached. (Current: {monthly_tokens})",
        )

    model = genai.GenerativeModel(model_name)
    attempts = 0
    last_exception = None

    while attempts <= MAX_GEMINI_RETRIES:
        try:
            response = model.generate_content(prompt, generation_config=generation_config)

            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                total_tokens = getattr(response.usage_metadata, "total_token_count", 0) or 0

            usage_log = models.ApiUsage(
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                endpoint=endpoint,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                status="success",
            )
            db.add(usage_log)
            db.commit()
            return response

        except Exception as exc:
            last_exception = exc
            if attempts < MAX_GEMINI_RETRIES and _is_rate_limit_error(exc):
                wait = GEMINI_RETRY_BASE_SECONDS * (2 ** attempts)
                logger.warning(
                    "Gemini rate limit hit for endpoint=%s model=%s prompt_chars=%d; retrying in %ss (attempt %s/%s)",
                    endpoint,
                    model_name,
                    len(prompt),
                    wait,
                    attempts + 1,
                    MAX_GEMINI_RETRIES,
                )
                time.sleep(wait)
                attempts += 1
                continue

            _log_failed_usage(db, endpoint, model_name, str(exc))
            if _is_rate_limit_error(exc):
                logger.error(
                    "Gemini rate limit failed after retries for endpoint=%s model=%s prompt_chars=%d: %s",
                    endpoint,
                    model_name,
                    len(prompt),
                    exc,
                )
            raise exc

    if last_exception:
        _log_failed_usage(db, endpoint, model_name, str(last_exception))
        if _is_rate_limit_error(last_exception):
            logger.error(
                "Gemini rate limit failed after retries for endpoint=%s model=%s prompt_chars=%d: %s",
                endpoint,
                model_name,
                len(prompt),
                last_exception,
            )
        raise last_exception
