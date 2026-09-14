"""OCR using pytesseract."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import dotenv
import numpy as np
from PIL import Image
import pytesseract

# Checked when TESSERACT_CMD isn't set and tesseract isn't on PATH, so a
# packaged build works against a stock Tesseract install without the user
# having to write a config file first.
_TESSERACT_FALLBACKS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _load_env() -> None:
    """
    Read .env. Under PyInstaller this module lives in a temporary extraction
    directory, so dotenv's usual search upward from __file__ finds nothing -
    look beside the executable instead, which is where a packaged build's .env
    sits.
    """
    if getattr(sys, "frozen", False):
        beside_exe = Path(sys.executable).with_name(".env")
        if beside_exe.is_file():
            dotenv.load_dotenv(beside_exe)
            return
    dotenv.load_dotenv()


def _resolve_tesseract() -> None:
    """Point pytesseract at a tesseract binary, if one can be found."""
    configured = os.environ.get("TESSERACT_CMD", "").strip()
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured
        return
    if shutil.which("tesseract"):
        return  # on PATH - pytesseract's default already works
    for candidate in _TESSERACT_FALLBACKS:
        if os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


_load_env()
_resolve_tesseract()

_MULTIPLIER_RE = re.compile(r'(\d+\.\d+)\s*x?', re.IGNORECASE)
# Running full-layout OCR (image_to_data) on the full-resolution captured
# frame takes ~900ms on a retina-size window - far too slow for a real-time
# loop. Searching a downscaled copy for "FLEW AWAY" first cuts that down a
# lot; the found box is then scaled back up to locate the crop on the full-res
# image, which is still used for the actual multiplier digits so read accuracy
# for the small text isn't affected.
#
# The downscale has to be chosen against the *window size*, not fixed. The
# banner has to survive it: Tesseract needs roughly 10px of glyph height, and
# the banner is only ~28-40px tall at full resolution (and animates in, so it
# spends part of each round smaller still). A hardcoded 0.25 put a 28px banner
# at 7px - unreadable at every window size tested - so rounds were silently
# missed unless the banner happened to be caught at its largest, which is what
# made detection look intermittent. Scaling to a target width keeps the banner
# legible on any window while still avoiding full-resolution OCR on the common
# case (no banner on screen at all).
_SEARCH_TARGET_WIDTH = 1200
_SEARCH_MIN_SCALE = 0.25


def _search_scale(width: int) -> float:
    """Downscale factor for the coarse 'FLEW AWAY' pass on a `width`px frame."""
    if width <= _SEARCH_TARGET_WIDTH:
        return 1.0
    return max(_SEARCH_MIN_SCALE, _SEARCH_TARGET_WIDTH / width)
_TESSERACT_NOT_FOUND_MSG = (
    "Tesseract OCR is not installed or not on your PATH.\n"
    "  - Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
    "  - Or set TESSERACT_CMD in .env to the full path to tesseract.exe\n"
    "    e.g. TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
)


def image_to_text(image: Image.Image) -> str:
    """Extract text from a PIL Image using Tesseract OCR."""
    try:
        return pytesseract.image_to_string(image).strip()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(_TESSERACT_NOT_FOUND_MSG) from None


def _find_flew_away_box(data: dict) -> tuple[int, int, int, int] | None:
    """
    Find the "FLEW" word in OCR word-box data, then pair it with a nearby
    "AWAY" word. Returns their combined bounding box, or None.

    Grouping by Tesseract's (block_num, par_num, line_num) and unioning the
    whole line is unreliable on this UI: unrelated text elsewhere on screen
    (sidebar labels, bet-table amounts, history chips) can land on the same
    OCR "line" purely by sharing a vertical pixel row across the full window
    width, silently pulling in e.g. a bet amount like "100.00" alongside
    "FLEW AWAY!" and blowing up the crop region. Pairing the two words
    directly by proximity avoids that.
    """
    words = data["text"]
    n = len(words)
    for i in range(n):
        if not (words[i] or "").strip().upper().startswith("FLEW"):
            continue
        top_i, height_i = data["top"][i], data["height"][i]
        right_i = data["left"][i] + data["width"][i]
        for j in range(i + 1, min(i + 5, n)):
            word_j = (words[j] or "").strip().upper()
            if not word_j:
                continue
            if not word_j.startswith("AWAY"):
                break
            # Must be roughly on the same line and immediately to the right -
            # not just anywhere else on screen at a similar height.
            if abs(data["top"][j] - top_i) > height_i:
                break
            if data["left"][j] - right_i > height_i * 4:
                break
            return (
                min(data["left"][i], data["left"][j]),
                min(top_i, data["top"][j]),
                max(right_i, data["left"][j] + data["width"][j]),
                max(top_i + height_i, data["top"][j] + data["height"][j]),
            )
    return None


def detect_multiplier(image: Image.Image) -> str | None:
    """
    Find 'FLEW AWAY' on the captured frame via OCR word boxes, then OCR just
    the (upscaled) multiplier text below it.

    Running OCR over the whole window and pattern-matching the resulting text
    is unreliable here: the window also contains balance/bet/history text
    (round decimal amounts like "10.00"/"100.00") that Tesseract can pick up
    instead of the actual crash multiplier. Cropping to just the multiplier
    region and OCR-ing that in isolation avoids grabbing the wrong number.

    Note: this stays in color (no grayscale conversion) - the multiplier is
    drawn in red on a dark background, and converting to grayscale collapses
    that contrast (red has low luminance), making the text harder to read.
    """
    search_scale = _search_scale(image.width)
    search_image = image.resize(
        (max(1, int(image.width * search_scale)), max(1, int(image.height * search_scale)))
    )
    try:
        coarse_data = pytesseract.image_to_data(search_image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(_TESSERACT_NOT_FOUND_MSG) from None

    coarse_box = _find_flew_away_box(coarse_data)
    if coarse_box is None:
        return None

    # The downscaled box only gives an approximate location - text that's a
    # few pixels tall at this scale loses enough definition that Tesseract's
    # bounding box can be off by several pixels, which becomes a large error
    # once scaled back up (e.g. 4x at _SEARCH_SCALE=0.25). Re-run OCR at full
    # resolution, but only on a small, generously padded crop around that
    # approximate area, to get a precise box without paying for full-frame
    # full-resolution OCR.
    inv_scale = 1.0 / search_scale
    approx_left, approx_top, approx_right, approx_bottom = (int(v * inv_scale) for v in coarse_box)
    approx_height = approx_bottom - approx_top
    locate_pad = max(120, approx_height * 3)
    locate_box = (
        max(0, approx_left - locate_pad),
        max(0, approx_top - locate_pad),
        min(image.width, approx_right + locate_pad),
        min(image.height, approx_bottom + locate_pad),
    )
    locate_crop = image.crop(locate_box)
    locate_data = pytesseract.image_to_data(locate_crop, output_type=pytesseract.Output.DICT)
    precise_box = _find_flew_away_box(locate_data)
    if precise_box is None:
        return None

    # Convert back to full-image coordinates.
    ox, oy = locate_box[0], locate_box[1]
    left, top, right, bottom = (
        precise_box[0] + ox,
        precise_box[1] + oy,
        precise_box[2] + ox,
        precise_box[3] + oy,
    )
    line_height = bottom - top

    # The multiplier is drawn in a larger font just below "FLEW AWAY!". Crop a
    # generous region around and below it first, since font size varies.
    rough_box = (
        max(0, left - line_height),
        bottom,
        min(image.width, right + line_height),
        min(image.height, bottom + line_height * 6),
    )
    if rough_box[3] <= rough_box[1] or rough_box[2] <= rough_box[0]:
        return None

    rough_crop = image.crop(rough_box)

    # Find the tight bounding box of the multiplier text by color instead of
    # a second OCR pass: it's drawn in solid red on a dark background. An
    # OCR-based line-detection pass here proved fragile - depending on exact
    # crop boundaries it would sometimes drop the decimal point (or other
    # thin strokes) from the recognized word's bounding box, silently
    # cropping it out before the final read. Thresholding on "red and bright"
    # pixels directly gives the true extent of the digits regardless of
    # whether Tesseract can transcribe them at this stage.
    arr = np.asarray(rough_crop)
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    red_mask = (r > 140) & (r - g > 40) & (r - b > 40)
    ys, xs = np.where(red_mask)
    if len(xs) == 0:
        return None
    # Only the topmost cluster of red pixels (a small vertical gap of a few
    # rows separates the multiplier from anything unrelated further down).
    row_has_red = np.zeros(red_mask.shape[0], dtype=bool)
    row_has_red[ys] = True
    gap_rows = np.flatnonzero(~row_has_red)
    first_gap_after_start = gap_rows[gap_rows > ys.min()]
    cutoff = first_gap_after_start[0] if len(first_gap_after_start) else red_mask.shape[0]
    in_band = ys < cutoff
    xs, ys = xs[in_band], ys[in_band]
    if len(xs) == 0:
        return None

    pad = 4
    tight_box = (
        max(0, int(xs.min()) - pad),
        max(0, int(ys.min()) - pad),
        min(rough_crop.width, int(xs.max()) + pad),
        min(rough_crop.height, int(ys.max()) + pad),
    )
    if tight_box[3] <= tight_box[1] or tight_box[2] <= tight_box[0]:
        return None

    crop = rough_crop.crop(tight_box)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    number_text = pytesseract.image_to_string(
        crop, config="--psm 7 -c tessedit_char_whitelist=0123456789.x"
    )
    match = _MULTIPLIER_RE.search(number_text)
    if not match:
        return None
    value = match.group(1)
    # A crash-game multiplier is always >= 1.00x; "0.00"-style reads are OCR
    # noise (e.g. from an empty/transitioning display), not a real round.
    try:
        if float(value) < 1.0:
            return None
    except ValueError:
        return None
    return value + "x"
