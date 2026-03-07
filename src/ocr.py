"""OCR using pytesseract."""

from __future__ import annotations

import os
import re
import dotenv
from PIL import Image
import pytesseract

dotenv.load_dotenv()
tesseract_cmd = os.environ.get("TESSERACT_CMD", "").strip()
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def image_to_text(image: Image.Image) -> str:
    """Extract text from a PIL Image using Tesseract OCR."""
    try:
        return pytesseract.image_to_string(image).strip()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR is not installed or not on your PATH.\n"
            "  - Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  - Or set TESSERACT_CMD in .env to the full path to tesseract.exe\n"
            "    e.g. TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        ) from None

def detect_multiplier(text: str) -> str | None:
    """Detect 'FLEW AWAY' and return the multiplier below it if found."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    flew_away_idx = -1
    for i, line in enumerate(lines):
        if "FLEW AWAY" in line.upper():
            flew_away_idx = i
            break
            
    if flew_away_idx != -1 and flew_away_idx + 1 < len(lines):
        # We look at the next line or the one after for the multiplier
        for j in range(flew_away_idx + 1, min(flew_away_idx + 3, len(lines))):
            match = re.search(r'(\d+\.\d+)x?', lines[j], re.IGNORECASE)
            if match:
                return match.group(1) + "x"
    return None
