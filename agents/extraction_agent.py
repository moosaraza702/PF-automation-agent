"""
Extraction agent: uses local Ollama (no API key, no cost) to extract
PF request fields from email body text or attachment text.
"""

import os
import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import ollama
from loguru import logger

from utils.doc_parser import extract_text
from utils.hr_lookup import lookup

OLLAMA_MODEL = "llama3.2"   # change to "llama3.2:1b" if you used the smaller version

SYSTEM_PROMPT = """You are a Provident Fund (PF) request data extractor for a Pakistani company.
Given text from an email, PDF, or Word document, extract the PF withdrawal request details.

Respond ONLY with a valid JSON object — no markdown, no explanation, no preamble.

Required JSON structure:
{
  "employee_index": "employee ID such as EMP-1234 or null if not found",
  "amount": <numeric PKR amount as a number, or null if not found>,
  "reason": "brief reason (max 15 words) or null",
  "confidence": "high | medium | low",
  "raw_employee_ref": "exact text used to identify the employee in the document",
  "notes": "any ambiguities, multiple values found, or empty string"
}

Rules:
- employee_index: look for patterns like EMP-XXXX, employee number, staff ID, payroll number
- amount: extract the numeric value only (no PKR/Rs symbols), handle commas (1,50,000 = 150000)
- confidence: high if all three fields are clear; medium if one is inferred; low if two or more are missing
- Pakistani amount formats: 1,50,000 and 150,000 both mean 150000
- Return ONLY the JSON object, nothing else"""


def extract_from_email(email_data: dict) -> Optional[dict]:
    source_texts = []

    for att in email_data.get("attachments", []):
        att_path = att.get("path")
        if att_path:
            text = extract_text(Path(att_path))
            if text:
                source_texts.append({
                    "text": text,
                    "source": att["filename"],
                    "source_type": _mime_to_type(att["mime_type"]),
                })

    body = email_data.get("body", "").strip()
    if body:
        source_texts.append({
            "text": f"Subject: {email_data.get('subject', '')}\n\n{body}",
            "source": "email_body",
            "source_type": "email",
        })

    if not source_texts:
        logger.warning("No text to extract from email {}", email_data.get("gmail_id"))
        return None

    combined = "\n\n---\n\n".join(
        f"[Source: {s['source']}]\n{s['text']}" for s in source_texts
    )

    result = _call_ollama(combined)
    if not result:
        return None

    emp_data = lookup(result.get("employee_index") or "")
    result["name"]       = emp_data["name"]       if emp_data else ""
    result["department"] = emp_data["department"] if emp_data else ""
    result["grade"]      = emp_data["grade"]       if emp_data else ""
    result["pf_balance"] = emp_data["pf_balance"] if emp_data else None
    result["hr_found"]   = emp_data is not None

    result["gmail_id"]   = email_data.get("gmail_id", "")
    result["source"]     = source_texts[0]["source_type"]
    result["sender"]     = email_data.get("sender", "")
    result["email_date"] = email_data.get("date", "")
    result["subject"]    = email_data.get("subject", "")

    logger.info(
        "Extracted: emp={} amount={} confidence={} hr_found={}",
        result.get("employee_index"), result.get("amount"),
        result.get("confidence"), result.get("hr_found"),
    )
    return result


def _call_ollama(text: str) -> Optional[dict]:
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
        )
        raw = response["message"]["content"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Ollama returned invalid JSON: {}", e)
        return None
    except Exception as e:
        logger.error("Ollama error during extraction: {}", e)
        return None


def _mime_to_type(mime: str) -> str:
    if "pdf" in mime:
        return "pdf"
    if "word" in mime or "docx" in mime or "msword" in mime:
        return "docx"
    return "email"
