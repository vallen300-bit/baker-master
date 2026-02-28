"""
Baker Email API — send and draft emails via Baker's Gmail account (bakerai200@gmail.com).
Service-level OAuth2 auth (refresh token, no per-user flow).

Routes:
  POST /api/email/send   — send immediately
  POST /api/email/draft  — save as draft for review

Deprecation check: 2026-09-01 (Gmail API v1 + OAuth2 token policy).
"""
import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr

logger = logging.getLogger("baker.email")

# ---------------------------------------------------------------------------
# Auth — mirrors dashboard.py verify_api_key (local copy avoids circular import)
# ---------------------------------------------------------------------------
_BAKER_API_KEY = os.getenv("BAKER_API_KEY", "")


async def _verify_key(x_baker_key: str = Header(None, alias="X-Baker-Key")):
    if not _BAKER_API_KEY:
        logger.warning("BAKER_API_KEY not set — email API is unauthenticated!")
        return
    if x_baker_key != _BAKER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-Baker-Key"},
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(tags=["email"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    html: bool = False


# ---------------------------------------------------------------------------
# Gmail service factory
# ---------------------------------------------------------------------------
def _get_gmail_service():
    """Build Gmail API service using Baker's OAuth2 refresh token."""
    client_id = os.getenv("BAKER_GMAIL_CLIENT_ID", "")
    client_secret = os.getenv("BAKER_GMAIL_CLIENT_SECRET", "")
    refresh_token = os.getenv("BAKER_GMAIL_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "Missing Gmail credentials: BAKER_GMAIL_CLIENT_ID, "
            "BAKER_GMAIL_CLIENT_SECRET, BAKER_GMAIL_REFRESH_TOKEN"
        )

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        # scopes omitted — refresh token carries its originally granted scopes
    )
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------
def _build_raw_message(to: str, subject: str, body: str, html: bool) -> str:
    """Return base64url-encoded RFC 2822 message."""
    sender = os.getenv("BAKER_EMAIL_ADDRESS", "bakerai200@gmail.com")
    if html:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["From"] = sender
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
    else:
        msg = MIMEText(body, "plain")
        msg["To"] = to
        msg["From"] = sender
        msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return raw


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/api/email/send", dependencies=[Depends(_verify_key)])
async def send_email(req: EmailRequest):
    """Send an email from Baker's Gmail account."""
    if not req.to or not req.subject or not req.body:
        raise HTTPException(status_code=400, detail="to, subject, and body are required")

    try:
        service = _get_gmail_service()
        raw = _build_raw_message(req.to, req.subject, req.body, req.html)
        result = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        logger.info(f"Email sent to {req.to}: {req.subject} (id={result.get('id')})")
        return {
            "status": "sent",
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
        }
    except Exception as e:
        logger.error(f"Gmail send failed: {e}")
        raise HTTPException(status_code=503, detail="Email service temporarily unavailable")


@router.post("/api/email/draft", dependencies=[Depends(_verify_key)])
async def create_draft(req: EmailRequest):
    """Create a draft in Baker's Gmail account."""
    if not req.to or not req.subject or not req.body:
        raise HTTPException(status_code=400, detail="to, subject, and body are required")

    try:
        service = _get_gmail_service()
        raw = _build_raw_message(req.to, req.subject, req.body, req.html)
        result = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()
        msg = result.get("message", {})
        logger.info(f"Draft created for {req.to}: {req.subject} (draft_id={result.get('id')})")
        return {
            "status": "drafted",
            "draft_id": result.get("id"),
            "message_id": msg.get("id"),
        }
    except Exception as e:
        logger.error(f"Gmail draft failed: {e}")
        raise HTTPException(status_code=503, detail="Email service temporarily unavailable")
