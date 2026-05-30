"""
Outlook client: MSAL authentication, email polling, attachment extraction.
Replaces gmail_client.py — all other files stay the same.
"""

import os
import json
import requests
from pathlib import Path
from typing import Optional

import msal
from loguru import logger

CLIENT_ID     = os.getenv("OUTLOOK_CLIENT_ID", "")
TENANT_ID     = os.getenv("OUTLOOK_TENANT_ID", "common")
USER_EMAIL    = os.getenv("OUTLOOK_EMAIL", "")
SUBJECT_FILTER = os.getenv("OUTLOOK_SUBJECT_FILTER", "provident fund")
TOKEN_FILE    = Path("config/outlook_token.json")

SCOPES = ["Mail.Read", "Mail.ReadWrite"]
GRAPH  = "https://graph.microsoft.com/v1.0"


def get_outlook_token() -> str:
    """
    Get a valid access token using MSAL device flow.
    On first run, prints a URL + code for you to open in browser.
    Token is cached in config/outlook_token.json for future runs.
    """
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=_load_cache(),
    )

    # Try silent (cached) login first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(app.token_cache)
            return result["access_token"]

    # First time — device flow (no browser popup needed, works on servers too)
    flow = app.initiate_device_flow(scopes=SCOPES)
    print("\n" + "="*60)
    print("OUTLOOK LOGIN REQUIRED")
    print(f"1. Open this URL: {flow['verification_uri']}")
    print(f"2. Enter this code: {flow['user_code']}")
    print("="*60 + "\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Outlook login failed: {result.get('error_description')}")

    _save_cache(app.token_cache)
    logger.info("Outlook token obtained and saved.")
    return result["access_token"]


def fetch_unread_pf_emails(token: str, attachment_dir: Path) -> list[dict]:
    """
    Fetch unread emails whose subject contains the configured filter keyword.
    Returns the same dict structure as the old gmail_client so nothing else changes.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Search unread emails with subject filter
    url = (
        f"{GRAPH}/me/mailFolders/inbox/messages"
        f"?$filter=isRead eq false and contains(subject,'{SUBJECT_FILTER}')"
        f"&$select=id,subject,from,receivedDateTime,body"
        f"&$top=50"
    )

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    messages = response.json().get("value", [])
    logger.info("Found {} unread PF emails in Outlook", len(messages))

    emails = []
    for msg in messages:
        try:
            email_data = _parse_message(msg, token, attachment_dir)
            emails.append(email_data)
        except Exception as e:
            logger.error("Failed to parse Outlook message {}: {}", msg["id"], e)

    return emails


def _parse_message(msg: dict, token: str, attachment_dir: Path) -> dict:
    headers  = {"Authorization": f"Bearer {token}"}
    msg_id   = msg["id"]

    body = msg.get("body", {}).get("content", "")
    # Strip basic HTML tags if body is HTML
    if msg.get("body", {}).get("contentType") == "html":
        import re
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

    attachments = _download_attachments(msg_id, token, attachment_dir)

    return {
        "gmail_id":    msg_id,          # key name kept as gmail_id so extraction_agent works unchanged
        "subject":     msg.get("subject", ""),
        "sender":      msg.get("from", {}).get("emailAddress", {}).get("address", ""),
        "date":        msg.get("receivedDateTime", ""),
        "body":        body,
        "attachments": attachments,
    }


def _download_attachments(msg_id: str, token: str, attachment_dir: Path) -> list[dict]:
    attachment_dir.mkdir(parents=True, exist_ok=True)
    headers  = {"Authorization": f"Bearer {token}"}
    saved    = []

    url      = f"{GRAPH}/me/messages/{msg_id}/attachments"
    response = requests.get(url, headers=headers)
    if not response.ok:
        return []

    for att in response.json().get("value", []):
        name      = att.get("name", "attachment")
        mime_type = att.get("contentType", "")

        if mime_type not in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            continue

        import base64
        data     = base64.b64decode(att.get("contentBytes", ""))
        out_path = attachment_dir / f"{msg_id[:8]}_{name}"
        out_path.write_bytes(data)

        saved.append({
            "filename":  name,
            "path":      out_path,
            "mime_type": mime_type,
        })
        logger.debug("Saved Outlook attachment: {}", out_path)

    return saved


def mark_as_read(token: str, msg_id: str):
    """Mark a message as read after processing."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    requests.patch(
        f"{GRAPH}/me/messages/{msg_id}",
        headers=headers,
        json={"isRead": True},
    )
    logger.debug("Marked Outlook message {} as read", msg_id[:12])


# ── Token cache helpers ───────────────────────────────────────────────────────

def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_FILE.exists():
        cache.deserialize(TOKEN_FILE.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(cache.serialize())
