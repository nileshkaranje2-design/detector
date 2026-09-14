#!/usr/bin/env bash
# Launch the Multiplier Detection GUI app.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -x ".venv/bin/python" ]; then
    echo "Virtual environment not found. Creating one and installing dependencies..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python app.py "$@"
