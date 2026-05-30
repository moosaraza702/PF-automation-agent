"""
Test the full pipeline without Gmail/Outlook.
Simulates emails directly so you can verify extraction,
HR lookup, Excel writing, and validation all work correctly.
"""

from utils.hr_lookup import load_hr_data
from utils.excel_manager import append_entry
from agents.extraction_agent import extract_from_email
from agents.validation_agent import validate_today

# ── Fake emails — edit these to match your real email format ──────────────────
FAKE_EMAILS = [
    {
        "gmail_id": "test-001",
        "subject":  "PF Withdrawal Request",
        "sender":   "ali.hassan@company.com",
        "date":     "2025-05-15",
        "body":     """
            Dear HR,
            I employee EMP-0001 request withdrawal of PKR 150,000
            from my provident fund for my child's university admission.
            Please process urgently.
            Regards, Ali Hassan
        """,
        "attachments": [],
    },
    {
        "gmail_id": "test-002",
        "subject":  "PF Request - Medical Emergency",
        "sender":   "sara.khan@company.com",
        "date":     "2025-05-15",
        "body":     """
            To Whom It May Concern,
            This is to request PF advance of Rs. 85,000 for
            medical treatment. My employee number is EMP-0002.
            Sara Khan
        """,
        "attachments": [],
    },
    {
        "gmail_id": "test-003",
        "subject":  "Provident Fund Advance",
        "sender":   "unknown.person@company.com",
        "date":     "2025-05-15",
        "body":     """
            Hi,
            Please process my PF withdrawal.
            Amount needed urgently.
            Thanks
        """,
        "attachments": [],
    },
    {
        "gmail_id": "test-004",
        "subject":  "PF Withdrawal Request",
        "sender":   "usman.tariq@company.com",
        "date":     "2025-05-15",
        "body":     """
            Dear Sir,
            I am EMP-0003 requesting provident fund withdrawal
            of PKR 600,000 for house construction.
            Usman Tariq
        """,
        "attachments": [],
    },
]

def run_test():
    print("\n" + "="*60)
    print("  PF AGENT — FULL PIPELINE TEST")
    print("="*60)

    # Step 1: Load HR data
    print("\n[1/3] Loading HR database...")
    load_hr_data()
    print("      ✓ HR data loaded")

    # Step 2: Process each fake email
    print("\n[2/3] Processing test emails...\n")
    for i, email in enumerate(FAKE_EMAILS, 1):
        print(f"  Email {i}: {email['subject']} — from {email['sender']}")
        result = extract_from_email(email)

        if result is None:
            print(f"  ✗ Could not extract data\n")
            continue

        print(f"  ✓ Employee  : {result.get('employee_index') or 'NOT FOUND'}")
        print(f"  ✓ Amount    : PKR {result.get('amount') or 'NOT FOUND'}")
        print(f"  ✓ Reason    : {result.get('reason') or 'NOT FOUND'}")
        print(f"  ✓ Name      : {result.get('name') or 'Not in HR DB'}")
        print(f"  ✓ Department: {result.get('department') or '—'}")
        print(f"  ✓ Confidence: {result.get('confidence')}")

        wb_path, row = append_entry(result, validation_status="Pending")
        print(f"  ✓ Written to Excel → row {row}\n")

    # Step 3: Run validation
    print("[3/3] Running validation agent...\n")
    summary = validate_today()

    print(f"  Total entries : {summary['total']}")
    print(f"  ✓ Valid        : {summary['ok']}")
    print(f"  ⚠ Warnings    : {summary['warnings']}")
    print(f"  ✗ Errors      : {summary['errors']}")

    if summary["issues"]:
        print("\n  Issues found:")
        for iss in summary["issues"]:
            icon = "✗" if iss["severity"] == "error" else "⚠"
            print(f"    {icon} Row {iss['row']} [{iss['code']}]: {iss['description']}")

    print("\n" + "="*60)
    print(f"  Excel file saved in: data/")
    print("  Open it to see the full output with colour coding.")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_test()
