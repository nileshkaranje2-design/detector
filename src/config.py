"""Local persistence for user-configurable settings (currently just the
OpenAI API key).

Stored under the user's home directory rather than in the repo/.env so the
key survives across runs without ever needing to live in a project file -
it's set once via the GUI's "Set API Key" dialog.
"""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path.home() / ".multiplier_detector" / "config.json"


def _read() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_api_key() -> str:
    return (_read().get("openai_api_key") or "").strip()


def save_api_key(key: str) -> None:
    key = key.strip()
    data = _read()
    data["openai_api_key"] = key
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2))
