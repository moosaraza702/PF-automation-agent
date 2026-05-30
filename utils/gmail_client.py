"""
Gmail client: OAuth2 authentication, email polling, attachment extraction.
"""

import os
import base64
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

from config.settings import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE, GMAIL_SEARCH_QUERY

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_service():
    """Authenticate and return a Gmail API service object."""
    creds = None
    token_path = Path(GMAIL_TOKEN_FILE)
    creds_path = Path(GMAIL_CREDENTIALS_FILE)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}.\n"
                    "Make sure credentials.json is in your config/ folder."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        logger.info("Gmail token saved to {}", token_path)

    return build("gmail", "v1", credentials=creds)


def fetch_unread_pf_emails(service, attachment_dir: Path) -> list[dict]:
    """Fetch unread PF request emails matching the configured search query."""
    results = service.users().messages().list(
        userId="me",
        q=GMAIL_SEARCH_QUERY,
        maxResults=50,
    ).execute()

    messages = results.get("messages", [])
    logger.info("Found {} unread PF emails", len(messages))

    emails = []
    for msg_stub in messages:
        msg_id = msg_stub["id"]
        try:
            email_data = _parse_message(service, msg_id, attachment_dir)
            emails.append(email_data)
        except Exception as e:
            logger.error("Failed to parse message {}: {}", msg_id, e)

    return emails


def _parse_message(service, msg_id: str, attachment_dir: Path) -> dict:
    """Fetch and parse a single Gmail message."""
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    body = _extract_body(msg["payload"])
    attachments = _extract_attachments(service, msg_id, msg["payload"], attachment_dir)

    return {
        "gmail_id": msg_id,
        "subject":  headers.get("Subject", ""),
        "sender":   headers.get("From", ""),
        "date":     headers.get("Date", ""),
        "body":     body,
        "attachments": attachments,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""


def _extract_attachments(service, msg_id: str, payload: dict, attachment_dir: Path) -> list[dict]:
    """Download and save all PDF/DOCX attachments from a message."""
    attachment_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    def _walk(part):
        filename  = part.get("filename", "")
        mime_type = part.get("mimeType", "")
        body      = part.get("body", {})

        if filename and mime_type in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            attachment_id = body.get("attachmentId")
            if attachment_id:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=attachment_id
                ).execute()
                data     = base64.urlsafe_b64decode(att["data"] + "==")
                out_path = attachment_dir / f"{msg_id}_{filename}"
                out_path.write_bytes(data)
                saved.append({
                    "filename":  filename,
                    "path":      out_path,
                    "mime_type": mime_type,
                })
                logger.debug("Saved attachment: {}", out_path)

        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return saved


def mark_as_read(service, msg_id: str):
    """Remove the UNREAD label from a processed message."""
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()
    logger.debug("Marked message {} as read", msg_id)
