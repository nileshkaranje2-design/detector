"""Diagnostic: report which stage of detect_multiplier() fails on real frames.

Detection is a pipeline, and a miss at any stage looks identical from the GUI
("Last detected" just never changes). This prints a per-frame verdict naming
the stage that failed, and saves the frames so the failure can be inspected.

Usage:
    # watch a live window for 60s
    .venv\\Scripts\\python.exe diagnose_ocr.py --window "Aviator"

    # or analyse a saved screenshot (e.g. one taken at the FLEW AWAY moment)
    .venv\\Scripts\\python.exe diagnose_ocr.py --image "path\\to\\shot.png"

This is a throwaway debugging aid - delete it once detection is behaving.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import numpy as np
import pytesseract
from PIL import Image

from src import capture, ocr

DUMP_DIR = "ocr_debug"


def analyse(img: Image.Image, tag: str, dump: bool) -> str:
    """Walk detect_multiplier()'s stages and report where it gives up."""
    # Stage 1: find "FLEW AWAY" on the downscaled search image.
    scale = ocr._search_scale(img.width)
    search = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    coarse_data = pytesseract.image_to_data(search, output_type=pytesseract.Output.DICT)
    words = [w for w in coarse_data["text"] if (w or "").strip()]
    coarse_box = ocr._find_flew_away_box(coarse_data)

    if coarse_box is None:
        # Was the text there at all, just not recognised at this scale?
        full_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        full_box = ocr._find_flew_away_box(full_data)
        if full_box is not None:
            heights = [
                full_data["height"][i]
                for i, w in enumerate(full_data["text"])
                if (w or "").strip().upper().startswith(("FLEW", "AWAY"))
            ]
            verdict = (
                f"STAGE 1 FAIL (downscale): 'FLEW AWAY' IS present at full "
                f"resolution (banner text ~{max(heights)}px tall -> "
                f"~{max(heights) * scale:.1f}px at scale={scale:.2f}, too small "
                f"for Tesseract). Raise _SEARCH_TARGET_WIDTH in src/ocr.py."
            )
        else:
            verdict = (
                "no 'FLEW AWAY' on this frame at any scale "
                "(normal between rounds; a problem only if it never appears)"
            )
        if dump:
            _dump(img, tag, "stage1")
        return f"{verdict}\n      coarse OCR words: {words[:14]}"

    # Stage 2: re-locate precisely on a padded full-res crop.
    inv = 1.0 / scale
    al, at, ar, ab = (int(v * inv) for v in coarse_box)
    pad = max(120, (ab - at) * 3)
    lbox = (max(0, al - pad), max(0, at - pad), min(img.width, ar + pad), min(img.height, ab + pad))
    lcrop = img.crop(lbox)
    precise = ocr._find_flew_away_box(
        pytesseract.image_to_data(lcrop, output_type=pytesseract.Output.DICT)
    )
    if precise is None:
        if dump:
            _dump(lcrop, tag, "stage2")
        return "STAGE 2 FAIL: found 'FLEW AWAY' downscaled but not on the full-res crop."

    left, top, right, bottom = (
        precise[0] + lbox[0], precise[1] + lbox[1], precise[2] + lbox[0], precise[3] + lbox[1],
    )
    lh = bottom - top

    # Stage 3: isolate the red multiplier digits below the banner.
    rough = (
        max(0, left - lh), bottom,
        min(img.width, right + lh), min(img.height, bottom + lh * 6),
    )
    rcrop = img.crop(rough)
    arr = np.asarray(rcrop)
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (r > 140) & (r - g > 40) & (r - b > 40)
    if not mask.any():
        if dump:
            _dump(rcrop, tag, "stage3-nored")
        return (
            f"STAGE 3 FAIL: no red pixels under the banner "
            f"(brightest pixel r={r.max()}, max r-g={int((r - g).max())}). "
            f"Multiplier may not be red on this skin - loosen the threshold."
        )

    result = ocr.detect_multiplier(img)
    if result is None:
        if dump:
            _dump(rcrop, tag, "stage4")
        return "STAGE 4 FAIL: red digits found but Tesseract could not read them."
    return f"OK -> {result}"


def _dump(img: Image.Image, tag: str, stage: str) -> None:
    os.makedirs(DUMP_DIR, exist_ok=True)
    path = os.path.join(DUMP_DIR, f"{tag}_{stage}.png")
    img.save(path)
    print(f"      saved {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", help="window title substring to watch live")
    ap.add_argument("--image", help="analyse a saved screenshot instead")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--no-dump", action="store_true", help="don't save failing frames")
    args = ap.parse_args()
    dump = not args.no_dump

    if args.image:
        img = Image.open(args.image).convert("RGB")
        print(f"{args.image}  ({img.width}x{img.height})")
        print(f"  -> {analyse(img, 'image', dump)}")
        return

    if not args.window:
        ap.error("pass --window or --image")

    print(f"Watching windows matching {args.window!r} for {args.seconds:.0f}s...")
    print("Let at least one round fly away while this runs.\n")
    end = time.time() + args.seconds
    frames = hits = 0
    while time.time() < end:
        win = capture.get_window(args.window)
        if win is None:
            print("  window not found - is the title right? (Refresh list in the GUI)")
            time.sleep(2)
            continue
        img = capture.capture_true_window(win)
        if img is None:
            time.sleep(0.5)
            continue
        frames += 1
        tag = datetime.now().strftime("%H%M%S")
        verdict = analyse(img, tag, dump)
        if verdict.startswith("OK"):
            hits += 1
        if not verdict.startswith("no 'FLEW AWAY'"):
            print(f"  [{tag}] {img.width}x{img.height}  {verdict}")
        time.sleep(0.4)

    print(f"\n{frames} frames examined, {hits} multiplier(s) read.")
    if frames and not hits:
        print("No multiplier was ever read - the stage lines above say why.")


if __name__ == "__main__":
    main()
