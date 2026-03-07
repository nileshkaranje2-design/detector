"""Run this to install project dependencies: pip install -r requirements.txt."""

import subprocess
import sys
from pathlib import Path

def main():
    req = Path(__file__).resolve().parent / "requirements.txt"
    if not req.is_file():
        print("requirements.txt not found.", file=sys.stderr)
        sys.exit(1)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        check=True,
    )
    print("Dependencies installed.")

if __name__ == "__main__":
    main()
