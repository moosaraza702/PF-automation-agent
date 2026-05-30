import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY", "")
GMAIL_CREDENTIALS_FILE   = os.getenv("GMAIL_CREDENTIALS_FILE", "config/credentials.json")
GMAIL_TOKEN_FILE         = os.getenv("GMAIL_TOKEN_FILE", "config/token.json")
GMAIL_SEARCH_QUERY       = os.getenv("GMAIL_SEARCH_QUERY", "subject:(provident fund OR PF withdrawal) is:unread")

EXCEL_OUTPUT_DIR         = os.getenv("EXCEL_OUTPUT_DIR", "data")
EXCEL_ROTATION_MONTHS    = int(os.getenv("EXCEL_ROTATION_MONTHS", "4"))

HR_DATA_FILE             = os.getenv("HR_DATA_FILE", "data/hr_employees.csv")

MAX_SINGLE_WITHDRAWAL    = int(os.getenv("MAX_SINGLE_WITHDRAWAL", "500000"))
REQUIRE_REASON           = os.getenv("REQUIRE_REASON", "true").lower() == "true"
FLAG_DUPLICATE_DAYS      = int(os.getenv("FLAG_DUPLICATE_WITHIN_DAYS", "30"))

POLL_INTERVAL_SECONDS    = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
ALERT_EMAIL              = os.getenv("ALERT_EMAIL", "")

CLAUDE_MODEL             = "claude-opus-4-5"
