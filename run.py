"""
run.py
------
One-click launcher for the Walmart Scraper POC API.
Run with:  python run.py
"""

import subprocess
import sys
import os

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("=" * 60)
    print("  Walmart U.S. Live Product Scraper — POC API")
    print("=" * 60)
    print("  Server : http://127.0.0.1:8000")
    print("  Docs   : http://127.0.0.1:8000/docs")
    print("  Health : http://127.0.0.1:8000/health")
    print("=" * 60)
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
            "--log-level", "info",
        ],
        check=True,
    )
