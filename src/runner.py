"""Main loop: capture -> timestamp -> save frame + OCR text."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

from . import capture
from . import ocr
from . import video_writer


def run(
    window_title: str,
    interval_sec: float,
    frames_dir: str,
    texts_dir: str,
) -> None:
    """
    Run real-time capture loop: find window by title, then repeatedly
    capture -> timestamp -> save frame + OCR text -> sleep(interval_sec).
    """
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(texts_dir, exist_ok=True)

    try:
        while True:
            window = capture.get_window(window_title)
            if window is None:
                time.sleep(interval_sec)
                continue

            now = datetime.now()
            ts = now.strftime("%Y-%m-%d_%H-%M-%S")

            img = capture.capture_true_window(window)
            if img is None:
                time.sleep(interval_sec)
                continue
                
            frame_path = os.path.join(frames_dir, f"frame_{ts}.png")
            img.save(frame_path)

            text = ocr.image_to_text(img)
            text_path = os.path.join(texts_dir, f"text_{ts}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(f"# {now.isoformat()}\n\n")
                f.write(text)

            print(f"{now.isoformat()}  frame={frame_path}  text={text_path}")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\nStopped.")


def run_region(
    x: int,
    y: int,
    width: int,
    height: int,
    fps: float,
    *,
    output_path: str | None = None,
    frames_dir: str | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """
    Run continuous capture from region (x, y, width, height) at target FPS.
    Write to video file if output_path is set, else save frames to frames_dir.
    """
    frame_interval = 1.0 / fps
    writer: video_writer.VideoWriter | None = None

    if output_path:
        writer = video_writer.VideoWriter(width, height, fps, output_path)
    elif frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
    else:
        raise ValueError("Either output_path or frames_dir must be provided")

    try:
        next_frame_time = time.perf_counter()
        frame_count = 0
        while True:
            if stop_event and stop_event.is_set():
                break
            now = time.perf_counter()
            if now < next_frame_time:
                sleep_time = next_frame_time - now
                if stop_event:
                    end = time.perf_counter() + sleep_time
                    while time.perf_counter() < end:
                        if stop_event.is_set():
                            break
                        stop_event.wait(timeout=0.05)
                    if stop_event.is_set():
                        break
                else:
                    time.sleep(sleep_time)
            next_frame_time += frame_interval

            img = capture.capture_rect(x, y, width, height)

            if writer:
                writer.write_frame(img)
            else:
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                frame_path = os.path.join(frames_dir, f"frame_{ts}.png")
                img.save(frame_path)
                print(f"{datetime.now().isoformat()}  frame={frame_path}")

            frame_count += 1
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if writer:
            writer.release()
            print(f"Saved {frame_count} frames to {writer.output_path}")


def run_window_capture(
    window_title: str,
    fps: float,
    *,
    output_path: str | None = None,
    frames_dir: str | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """
    Run continuous capture from a window (by title substring) at target FPS.
    Write to video file if output_path is set, else save frames to frames_dir.
    """
    if not output_path and not frames_dir:
        raise ValueError("Either output_path or frames_dir must be provided")
    frame_interval = 1.0 / fps
    writer: video_writer.VideoWriter | None = None

    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)

    try:
        next_frame_time = time.perf_counter()
        frame_count = 0
        while True:
            if stop_event and stop_event.is_set():
                break
            now = time.perf_counter()
            if now < next_frame_time:
                sleep_time = next_frame_time - now
                if stop_event:
                    end = time.perf_counter() + sleep_time
                    while time.perf_counter() < end:
                        if stop_event.is_set():
                            break
                        stop_event.wait(timeout=0.05)
                    if stop_event.is_set():
                        break
                else:
                    time.sleep(sleep_time)
            next_frame_time += frame_interval

            window = capture.get_window(window_title)
            if window is None:
                continue
            img = capture.capture_true_window(window)
            if img is None:
                continue
                
            w, h = img.size[0], img.size[1]

            if output_path:
                if writer is None:
                    writer = video_writer.VideoWriter(w, h, fps, output_path)
                writer.write_frame(img)
            else:
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                frame_path = os.path.join(frames_dir, f"frame_{ts}.png")
                img.save(frame_path)
                print(f"{datetime.now().isoformat()}  frame={frame_path}")

            frame_count += 1
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if writer:
            writer.release()
            print(f"Saved {frame_count} frames to {writer.output_path}")


def run_detection(
    window_title: str,
    fps: float,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """
    Run continuous detection from a window (by title substring) at target FPS.
    Applies OCR to detect the multiplier below 'FLEW AWAY!' and logs it to a file.
    Does NOT save video or frames.
    """
    frame_interval = 1.0 / fps
    log_path = "detections.log"
    last_detected = None
    
    # We maintain a small memory so we don't log the same 'FLEW AWAY' multiple times for the same round
    # We clear it if we go a few frames without seeing any multiplier.
    empty_frames_count = 0

    print(f"Starting detection on window containing '{window_title}'...")
    try:
        next_frame_time = time.perf_counter()
        while True:
            if stop_event and stop_event.is_set():
                break
            now = time.perf_counter()
            if now < next_frame_time:
                sleep_time = next_frame_time - now
                if stop_event:
                    end = time.perf_counter() + sleep_time
                    while time.perf_counter() < end:
                        if stop_event.is_set():
                            break
                        stop_event.wait(timeout=0.05)
                    if stop_event.is_set():
                        break
                else:
                    time.sleep(sleep_time)
            next_frame_time += frame_interval

            window = capture.get_window(window_title)
            if window is None:
                continue
            
            # Use true window capture
            img = capture.capture_true_window(window)
            if img is None:
                continue
                
            # Perform OCR on the image
            text = ocr.image_to_text(img)
            multiplier = ocr.detect_multiplier(text)
            
            if multiplier:
                empty_frames_count = 0
                if multiplier != last_detected:
                    timestamp = datetime.now().isoformat()
                    log_line = f"{timestamp} - Detected Multiplier: {multiplier}\n"
                    print(log_line.strip())
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(log_line)
                    last_detected = multiplier
            else:
                empty_frames_count += 1
                if empty_frames_count > fps * 3:  # 3 seconds without multiplier
                    last_detected = None

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        print("Detection stopped.")
