"""Entry point: parse args, load config, run capture loop or list windows."""

from __future__ import annotations

import argparse
import os

import dotenv

from src import capture, runner


def main() -> None:
    dotenv.load_dotenv()

    # Optional: path to tesseract.exe if not on PATH (e.g. Windows)
    tesseract_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        import pytesseract as _pt
        _pt.pytesseract.tesseract_cmd = tesseract_cmd

    parser = argparse.ArgumentParser(description="Capture a window or region and run real-time OCR or video capture.")
    parser.add_argument("--list-windows", action="store_true", help="List window titles and exit.")
    parser.add_argument("--window", "-w", type=str, default="Chrome", help="Window title substring (default: Chrome).")
    parser.add_argument("--interval", "-i", type=float, default=None, help="Capture interval in seconds (overrides .env).")
    parser.add_argument("--region", "-r", type=str, default=None, help="Capture region as X,Y,W,H (e.g. 100,100,800,600).")
    parser.add_argument("--fps", type=float, default=None, help="Frames per second for region capture (default: 15).")
    parser.add_argument("--video", "-v", type=str, default=None, help="Output video file path (MP4) for region capture.")
    args = parser.parse_args()

    if args.list_windows:
        for title, desc in capture.list_windows():
            print(desc)
        return

    base = os.path.abspath(os.environ.get("OUTPUT_DIR", "captures").strip())
    frames_name = (os.environ.get("FRAMES_DIR", "frames") or "frames").strip().replace("./", "").replace(".\\", "") or "frames"
    texts_name = (os.environ.get("TEXTS_DIR", "texts") or "texts").strip().replace("./", "").replace(".\\", "") or "texts"
    frames_dir = os.path.join(base, frames_name)
    texts_dir = os.path.join(base, texts_name)

    if args.region:
        parts = [p.strip() for p in args.region.split(",")]
        if len(parts) != 4:
            raise SystemExit("--region must be X,Y,W,H (e.g. 100,100,800,600)")
        try:
            x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            raise SystemExit("--region values must be integers")
        fps = args.fps if args.fps is not None else float(os.environ.get("CAPTURE_FPS", "15"))
        output_path = args.video
        runner.run_region(
            x, y, w, h, fps,
            output_path=output_path,
            frames_dir=frames_dir if not output_path else None,
        )
        return

    interval = args.interval
    if interval is None:
        interval = float(os.environ.get("CAPTURE_INTERVAL_SEC", "1"))

    runner.run(
        window_title=args.window,
        interval_sec=interval,
        frames_dir=frames_dir,
        texts_dir=texts_dir,
    )


if __name__ == "__main__":
    main()
