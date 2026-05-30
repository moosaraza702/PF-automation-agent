"""
HR database: load employee data and expose lookup by employee index.
"""

from pathlib import Path
from typing import Optional
import csv

from loguru import logger
from config.settings import HR_DATA_FILE


_db: dict[str, dict] = {}


def load_hr_data():
    """
    Load employee data from CSV or Excel into memory.

    Expected columns (case-insensitive):
      employee_index, name, department, grade, pf_balance

    Call once at startup; call again to reload after file changes.
    """
    global _db
    path = Path(HR_DATA_FILE)

    if not path.exists():
        logger.warning("HR data file not found at {}. Creating a sample file.", path)
        _create_sample_hr_file(path)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        _db = _load_csv(path)
    elif suffix in (".xlsx", ".xls"):
        _db = _load_excel(path)
    else:
        raise ValueError(f"Unsupported HR file format: {suffix}. Use CSV or Excel.")

    logger.info("HR database loaded: {} employees", len(_db))


def lookup(employee_index: str) -> Optional[dict]:
    """
    Return employee record for given index, or None if not found.
    Normalises the index to uppercase with no extra spaces.
    """
    if not employee_index:
        return None
    key = employee_index.strip().upper()
    return _db.get(key)


def _load_csv(path: Path) -> dict:
    db = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normed = {k.strip().lower(): v.strip() for k, v in row.items()}
            idx = normed.get("employee_index", "").upper()
            if idx:
                db[idx] = {
                    "name":       normed.get("name", ""),
                    "department": normed.get("department", ""),
                    "grade":      normed.get("grade", ""),
                    "pf_balance": _parse_num(normed.get("pf_balance", "0")),
                }
    return db


def _load_excel(path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}
    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    db = {}
    for row in rows[1:]:
        normed = dict(zip(headers, row))
        idx = str(normed.get("employee_index", "")).strip().upper()
        if idx:
            db[idx] = {
                "name":       str(normed.get("name", "")),
                "department": str(normed.get("department", "")),
                "grade":      str(normed.get("grade", "")),
                "pf_balance": _parse_num(str(normed.get("pf_balance", "0"))),
            }
    wb.close()
    return db


def _parse_num(val: str) -> float:
    try:
        return float(val.replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _create_sample_hr_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = [
        ["employee_index", "name", "department", "grade", "pf_balance"],
        ["EMP-0001", "Ali Hassan",     "Finance",    "G-9",  "420000"],
        ["EMP-0002", "Sara Khan",      "HR",         "G-8",  "315000"],
        ["EMP-0003", "Usman Tariq",    "IT",         "G-7",  "198000"],
        ["EMP-0004", "Amina Yousuf",   "Operations", "G-10", "625000"],
        ["EMP-0005", "Bilal Mahmood",  "Finance",    "G-6",  "87000"],
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(sample)
    logger.info("Sample HR file created at {}", path)
