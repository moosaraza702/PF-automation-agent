"""
PF Automation Agent — main orchestrator.

Runs as a daemon:
  1. Every POLL_INTERVAL_SECONDS: fetch unread PF emails from Gmail
  2. For each email: extract fields → enrich from HR DB → write to Excel
  3. At end of each day (or on demand): run validation agent over today's entries

Usage:
  python main.py              # start the polling daemon
  python main.py --validate   # run validation on today's entries and exit
  python main.py --once       # process emails once and exit (useful for cron)
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import schedule
from loguru import logger

import config.settings as cfg
from utils.gmail_client import get_gmail_service, fetch_unread_pf_emails, mark_as_read
from utils.hr_lookup import load_hr_data
from utils.excel_manager import append_entry
from agents.extraction_agent import extract_from_email
from agents.validation_agent import validate_today


# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(log_dir / "pf_agent_{time:YYYY-MM-DD}.log",
               rotation="1 day", retention="30 days", level="DEBUG",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}")


# ── Core processing ───────────────────────────────────────────────────────────

def process_emails(service) -> int:
    """
    Fetch unread PF emails, extract data, write to Excel.
    Returns the number of entries successfully written.
    """
    attachment_dir = Path("attachments") / datetime.now().strftime("%Y-%m-%d")
    emails = fetch_unread_pf_emails(service, attachment_dir)

    if not emails:
        logger.info("No new PF emails found.")
        return 0

    processed = 0
    for email_data in emails:
        gmail_id = email_data["gmail_id"]
        logger.info("Processing email from {} | subject: '{}'",
                    email_data.get("sender", "?"), email_data.get("subject", "")[:60])
        try:
            result = extract_from_email(email_data)
            if result is None:
                logger.warning("Could not extract PF data from email {}. Skipping.", gmail_id)
                continue

            if result.get("confidence") == "low":
                logger.warning(
                    "Low-confidence extraction for email {} — "
                    "still logging but marked for review. Notes: {}",
                    gmail_id, result.get("notes", "")
                )

            wb_path, row = append_entry(result, validation_status="Pending")
            logger.success(
                "✓ Logged entry → emp={} amount=PKR {:,.0f} sheet={}",
                result.get("employee_index"), result.get("amount") or 0, wb_path
            )

            mark_as_read(service, gmail_id)
            processed += 1

        except Exception as e:
            logger.error("Error processing email {}: {}", gmail_id, e)

    logger.info("Batch complete: {}/{} emails processed.", processed, len(emails))
    return processed


def run_end_of_day_validation():
    """Run the validation agent and log the summary."""
    logger.info("─── Running end-of-day validation ───")
    summary = validate_today()
    logger.info(
        "Validation summary: total={} ok={} warnings={} errors={}",
        summary["total"], summary["ok"], summary["warnings"], summary["errors"]
    )
    if summary["issues"]:
        logger.warning("Issues found:")
        for iss in summary["issues"]:
            prefix = "🚨" if iss["severity"] == "error" else "⚠️"
            logger.warning("  {} [{}] Row {} {}: {}",
                           prefix, iss["code"], iss["row"],
                           iss.get("employee_index", ""), iss["description"])
    else:
        logger.success("All entries passed validation.")
    return summary


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_daemon():
    setup_logging()
    logger.info("PF Automation Agent starting up…")
    logger.info("Poll interval : {} seconds", cfg.POLL_INTERVAL_SECONDS)
    logger.info("Gmail query   : {}", cfg.GMAIL_SEARCH_QUERY)
    logger.info("Excel output  : {}/", cfg.EXCEL_OUTPUT_DIR)

    load_hr_data()
    service = get_gmail_service()

    # First run immediately
    n = process_emails(service)
    if n > 0:
        run_end_of_day_validation()

    # Schedule polling
    schedule.every(cfg.POLL_INTERVAL_SECONDS).seconds.do(process_emails, service=service)

    # Schedule end-of-day validation at 18:00
    def process_and_validate(service):
        n = process_emails(service)
        if n > 0:
            run_end_of_day_validation()

    schedule.every(cfg.POLL_INTERVAL_SECONDS).seconds.do(process_and_validate, service=service)

    logger.info("Daemon running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Agent stopped by user.")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PF Automation Agent")
    parser.add_argument("--validate", action="store_true",
                        help="Run validation on today's entries and exit")
    parser.add_argument("--once", action="store_true",
                        help="Process emails once and exit (for cron use)")
    args = parser.parse_args()

    setup_logging()
    load_hr_data()

    if args.validate:
        run_end_of_day_validation()
        return

    if args.once:
        service = get_gmail_service()
        n = process_emails(service)
        logger.info("Done. {} entries written.", n)
        if n > 0:
            logger.info("Running validation on today's entries...")
            run_end_of_day_validation()
    return

    start_daemon()


if __name__ == "__main__":
    main()
