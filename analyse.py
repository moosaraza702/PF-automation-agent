"""
Run the PF Analyser Agent manually.

Commands:
    python analyse.py                   # analyse all data
    python analyse.py --month 2026-05   # specific month only
    python analyse.py --all             # explicitly all periods
"""

import argparse
import os
import subprocess
import sys
from dotenv import load_dotenv
load_dotenv()

from agents.analyser_agent import run_analysis
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="PF Analyser Agent")
    parser.add_argument("--month",
        help="Filter by month e.g. 2026-05", default=None)
    parser.add_argument("--all", action="store_true",
        help="Analyse all periods")
    args = parser.parse_args()

    logger.info("Starting PF Analysis...")
    pdf_path = run_analysis(
        filter_month=args.month,
        analyse_all=args.all,
    )

    if pdf_path and pdf_path.exists():
        logger.success("Report generated: {}", pdf_path)
        print(f"\n{'='*50}")
        print(f"  Report saved to: {pdf_path}")
        print(f"{'='*50}\n")

        # Auto open the PDF
        if sys.platform == "win32":
            os.startfile(str(pdf_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(pdf_path)])
        else:
            subprocess.run(["xdg-open", str(pdf_path)])
    else:
        logger.error("Report generation failed.")


if __name__ == "__main__":
    main()
