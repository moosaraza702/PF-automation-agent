# PF Automation Agent

A fully automated Provident Fund (PF) request processing system that reads Gmail, extracts structured data using Claude AI, writes to a daily-rotating Excel ledger, and runs an AI validation pass — replacing the manual bookkeeper workflow entirely.

---

## Architecture

```
Gmail (unread PF emails)
        │
        ▼
 Gmail API client          ← fetches email body + PDF/DOCX attachments
        │
        ▼
 Extraction Agent (Ollama/LLaMA 3.2) ← extracts Employee Index, Amount, Reason
        │
        ▼
 HR Lookup                 ← auto-fills Name, Department, Grade, PF Balance
        │
        ▼
 Excel Logger              ← writes to daily sheet, rotates file every 3–4 months
        │
        ▼
 Validation Agent (Claude) ← checks duplicates, limits, suspicious entries
        │
        ▼
 Excel file updated        ← status column coloured: OK / Warning / Error
```

---

## Quick Setup

### 1. Install dependencies

```bash
cd pf_agent
pip install -r requirements.txt
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in your GEMINI_API_KEY or other AI provider key
```

### 3. Set up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → **Enable Gmail API**
3. Go to **APIs & Services → Credentials → Create OAuth 2.0 Client ID**
4. Choose **Desktop app** → Download the JSON
5. Save it as `config/credentials.json`

First run will open a browser window for you to authorise your Gmail account. The token is saved automatically for future runs.

### 4. Set up your HR data

Edit `data/hr_employees.csv` (or point `HR_DATA_FILE` in `.env` to your existing Excel/CSV):

```
employee_index,name,department,grade,pf_balance
EMP-0001,Ali Hassan,Finance,G-9,420000
...
```

### 5. Run

```bash
# Start the polling daemon (checks Gmail every 2 minutes)
python main.py

# Process emails once (good for testing or cron)
python main.py --once

# Run validation on today's entries only
python main.py --validate
```

---

## Excel Output

Files are saved to `data/` as `PF_Requests_YYYY-P1.xlsx` (rotating every 4 months by default).

Each file has one sheet per day named `YYYY-MM-DD`. Columns:

| Column | Content |
|--------|---------|
| # | Serial number |
| Timestamp | Date and time entry was logged |
| Employee Index | Extracted from email (e.g. EMP-0001) |
| Name | Auto-filled from HR database |
| Department | Auto-filled from HR database |
| Grade | Auto-filled from HR database |
| PF Balance (PKR) | Auto-filled from HR database |
| Amount Requested (PKR) | Extracted from email |
| Reason | Extracted from email |
| Source | email / pdf / docx |
| Confidence | high / medium / low |
| Gmail Message ID | For traceability |
| Validation Status | OK / Warning / Error (colour-coded) |

---

## Validation Rules

### Rule-based (instant, deterministic)
- Missing Employee Index → **Error**
- Missing Amount → **Error**
- Amount > PKR 500,000 → **Warning** (configurable via `MAX_SINGLE_WITHDRAWAL`)
- Amount ≤ 0 → **Error**
- Amount > PF Balance → **Error**
- Employee not in HR database → **Warning**
- Duplicate employee index on same day → **Error**
- Missing reason (if required) → **Warning**

### AI-based (Claude)
- Vague or suspicious reasons
- Amounts disproportionate to grade/balance
- Subtle duplicates (same request, slightly different wording)
- Non-compliant or incomplete requests

---

## Cron Setup (Linux/Mac)

To run automatically every 5 minutes during work hours:

```cron
*/5 8-18 * * 1-6 cd /path/to/pf_agent && python main.py --once >> logs/cron.log 2>&1
```

End-of-day validation at 6 PM (daemon handles this; or manually):

```cron
0 18 * * 1-6 cd /path/to/pf_agent && python main.py --validate >> logs/validation.log 2>&1
```

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Your Claude API key |
| `GMAIL_CREDENTIALS_FILE` | `config/credentials.json` | OAuth credentials |
| `GMAIL_TOKEN_FILE` | `config/token.json` | Saved OAuth token |
| `GMAIL_SEARCH_QUERY` | `subject:(provident fund OR PF withdrawal) is:unread` | Gmail search filter |
| `EXCEL_OUTPUT_DIR` | `data` | Where Excel files are saved |
| `EXCEL_ROTATION_MONTHS` | `4` | New file every N months |
| `HR_DATA_FILE` | `data/hr_employees.csv` | Employee database (CSV or XLSX) |
| `MAX_SINGLE_WITHDRAWAL` | `500000` | Flag amount above this |
| `REQUIRE_REASON` | `true` | Warn if reason is missing |
| `FLAG_DUPLICATE_WITHIN_DAYS` | `30` | Flag same employee within N days |
| `POLL_INTERVAL_SECONDS` | `120` | Gmail polling frequency |

---

## File Structure

```
pf_agent/
├── main.py                     ← entry point / daemon
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.py             ← loads all config from .env
│   ├── credentials.json        ← Gmail OAuth (you provide)
│   └── token.json              ← auto-generated after first auth
├── agents/
│   ├── extraction_agent.py     ← Claude extraction logic
│   └── validation_agent.py     ← rule + Claude validation
├── utils/
│   ├── gmail_client.py         ← Gmail API wrapper
│   ├── doc_parser.py           ← PDF + DOCX text extraction
│   ├── hr_lookup.py            ← employee database
│   └── excel_manager.py        ← Excel read/write/rotate
├── data/
│   ├── hr_employees.csv        ← your HR data
│   └── PF_Requests_*.xlsx      ← generated output files
├── attachments/                ← downloaded email attachments
└── logs/                       ← rotating daily log files
```

---

## Handling Scanned PDFs

If your PDF attachments are scanned (image-based, not text-based), install OCR support:

```bash
sudo apt install tesseract-ocr   # Ubuntu/Debian
brew install tesseract            # macOS
pip install pytesseract pillow
```

Then the doc_parser will automatically fall back to OCR for image-only PDFs.

---

## Troubleshooting

**"Gmail credentials not found"**
→ Download `credentials.json` from Google Cloud Console (see Step 3 above).

**"No emails found but I have PF emails in inbox"**
→ Adjust `GMAIL_SEARCH_QUERY` in `.env` to match your email subject format.

**"Extraction confidence is always low"**
→ Your emails may use non-standard employee ID formats. Check `raw_employee_ref` in the logs and update the extraction prompt in `agents/extraction_agent.py` with examples.

**"HR data not loading"**
→ Check that `HR_DATA_FILE` path is correct and the CSV has the exact column names: `employee_index, name, department, grade, pf_balance`.
