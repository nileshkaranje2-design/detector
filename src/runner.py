"""Main loop: capture -> timestamp -> save frame + OCR text."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from typing import Callable

from . import capture
from . import ocr
from . import predictor
from . import video_writer

# How long the multiplier must be absent from the screen before the next
# sighting counts as a new round rather than a repeat of the current one.
ROUND_RESET_SEC = 3.0


# Date and time each round is written with, e.g. "2026-09-14 11:05:00".
# Readable in the log rather than ISO-with-microseconds, and still accepted by
# datetime.fromisoformat() so the GUI can parse it back.
DETECTION_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Matches the lines written below, e.g.
#   2026-09-14 11:05:00 - Detected Multiplier: 1.86x
# The separator is [T ] and the fractional part optional so that logs written
# before the switch to DETECTION_TIME_FORMAT (ISO, "2026-09-14T11:05:00.324034")
# still load - these files are appended to across many sessions.
_DETECTION_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*-\s*"
    r"Detected Multiplier:\s*(?P<value>\d+(?:\.\d+)?)\s*x?\s*$",
    re.IGNORECASE,
)


def _parse_multiplier(value: str) -> float | None:
    """Parse a multiplier string like '3.02x' into a float."""
    try:
        return float(value.rstrip("xX"))
    except ValueError:
        return None


def load_detections(path: str) -> list[tuple[str, float]]:
    """
    Read a detections file written by run_detection() back into
    (timestamp, multiplier) pairs, oldest first.

    Unparseable lines are skipped rather than raising: these files are appended
    to across many runs and may hold blank lines or notes, and a single bad
    line shouldn't cost the user the rest of their history.
    """
    rows: list[tuple[str, float]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            match = _DETECTION_LINE_RE.match(line.strip())
            if not match:
                continue
            try:
                rows.append((match.group("ts"), float(match.group("value"))))
            except ValueError:
                continue
    return rows


def _log_prediction_result(path: str, timestamp: str, prediction: dict, actual: float) -> None:
    """Append a line comparing a previously-made prediction to the actual outcome."""
    predicted = prediction.get("predicted_multiplier")
    confidence = prediction.get("confidence")
    error = abs(predicted - actual) if isinstance(predicted, (int, float)) else None
    line = (
        f"{timestamp}\tpredicted={predicted}x\tconfidence={confidence}\t"
        f"actual={actual}x\terror={error}\n"
    )
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"Failed to save prediction result to {path}: {e}")


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
    output_path: str = "detections.txt",
    predictions_path: str = "predictions.txt",
    stop_event: threading.Event | None = None,
    on_update: "Callable[[dict], None] | None" = None,
    on_frame: "Callable[[object], None] | None" = None,
    system_prompt: str | None = None,
    model: str | None = None,
    initial_history: "list[tuple[str, float]] | None" = None,
) -> None:
    """
    Run continuous detection from a window (by title substring) at target FPS.
    Applies OCR to detect the multiplier below 'FLEW AWAY!' and logs it to a text file.
    After each detection, asks the predictor to estimate the next round's multiplier and
    logs predicted-vs-actual to predictions_path once the next round lands.
    Does NOT save video or frames.

    system_prompt, if given, overrides the predictor's default system prompt
    (e.g. edited by the user in the GUI's prompt box).
    model, if given, overrides the predictor's default model
    (e.g. chosen by the user in the GUI's model dropdown).

    If on_update is given, it's called after each new detection with a dict:
    {"timestamp": <ISO str>, "detected": <float>,
     "predicted_multiplier": <float | None>, "confidence": <str | None>,
     "reasoning": <str | None>}. reasoning/predicted_multiplier/confidence are
    None on the immediate "detected" call and filled in once the background
    prediction finishes (see _predict_async).

    If on_frame is given, it's called with the raw captured PIL Image every
    cycle (before OCR), regardless of whether a multiplier was detected.
    """
    frame_interval = 1.0 / fps
    last_detected = None
    # initial_history seeds the context sent to the predictor with rounds from
    # an earlier session (see load_detections), so a fresh run doesn't have to
    # rebuild a usable sample from zero. Kept as two parallel lists because
    # predict_next() zips them and requires equal lengths.
    history: list[float] = [value for _, value in (initial_history or [])]
    history_timestamps: list[str] = [ts for ts, _ in (initial_history or [])]
    pending_prediction: dict | None = None
    # predict_next() is a live, synchronous LLM API call that can take several
    # seconds. It's run on a background thread (below) so it never stalls the
    # capture loop; this lock just protects pending_prediction and
    # prediction_request_id, which both that thread and the loop below read/write.
    prediction_lock = threading.Lock()
    # Bumped every time a new round's prediction is requested. If a round's
    # multiplier lands while an older prediction request is still pending, the
    # old request is left running (the API call can't be aborted mid-flight)
    # but its result is treated as cancelled: it's discarded on arrival so only
    # the newest round's prediction is ever shown/logged.
    prediction_request_id = 0

    def _predict_async(
        history_snapshot: list[float],
        timestamps_snapshot: list[str],
        timestamp: str,
        actual_value: float,
        request_id: int,
    ) -> None:
        nonlocal pending_prediction
        result = predictor.predict_next(
            history_snapshot, timestamps=timestamps_snapshot, system_prompt=system_prompt, model=model
        ) or {}
        # A result carrying "error" is a failure report, not a prediction: it
        # must reach the GUI so the user can see why there's no estimate, but
        # it must not be logged as a prediction to score against the outcome.
        error = result.get("error")
        prediction = None if error else (result or None)
        with prediction_lock:
            if request_id != prediction_request_id:
                print(f"Prediction for {timestamp} superseded by a newer round; discarding.")
                return
            pending_prediction = prediction
        if prediction is not None:
            print(
                f"Predicted next multiplier: {prediction.get('predicted_multiplier')}x "
                f"(confidence: {prediction.get('confidence')})"
            )
        if on_update:
            on_update({
                # kind="prediction" tells the GUI this update only carries the
                # prediction fields. It still names its round via timestamp, so
                # a reply that arrives after a newer round can be discarded
                # rather than repainting that older round's multiplier.
                "kind": "prediction",
                "timestamp": timestamp,
                "detected": actual_value,
                "predicted_multiplier": (prediction or {}).get("predicted_multiplier"),
                "confidence": (prediction or {}).get("confidence"),
                "reasoning": (prediction or {}).get("reasoning"),
                "error": error,
                "error_detail": result.get("error_detail"),
            })

    # We maintain a small memory so we don't log the same 'FLEW AWAY' multiple
    # times for the same round. It's cleared once the multiplier has been gone
    # from the screen for ROUND_RESET_SEC, which marks the round boundary.
    last_multiplier_seen_at: float | None = None

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

            if on_frame:
                on_frame(img)

            # Locate and OCR just the multiplier text below "FLEW AWAY!"
            multiplier = ocr.detect_multiplier(img)
            
            if multiplier:
                last_multiplier_seen_at = time.monotonic()
                if multiplier != last_detected:
                    timestamp = datetime.now().strftime(DETECTION_TIME_FORMAT)
                    log_line = f"{timestamp} - Detected Multiplier: {multiplier}\n"
                    print(log_line.strip())
                    try:
                        with open(output_path, "a", encoding="utf-8") as f:
                            f.write(log_line)
                    except Exception as e:
                        print(f"Failed to save to {output_path}: {e}")

                    actual_value = _parse_multiplier(multiplier)
                    if actual_value is not None:
                        with prediction_lock:
                            prediction_to_log = pending_prediction
                            pending_prediction = None
                        if prediction_to_log is not None:
                            _log_prediction_result(predictions_path, timestamp, prediction_to_log, actual_value)
                        history.append(actual_value)
                        history_timestamps.append(timestamp)

                        # Allocate the new request id *before* announcing this
                        # round, so any still-pending older prediction is
                        # already marked cancelled. Doing it after left a window
                        # in which an older reply passed the id check and
                        # repainted the previous round over this one.
                        with prediction_lock:
                            prediction_request_id += 1
                            request_id = prediction_request_id

                        # Fire the detection update immediately, before kicking
                        # off the (slow, network-bound) prediction - the GUI's
                        # "Last detected" label shouldn't wait on that just
                        # because it shares an update dict with "Next prediction".
                        if on_update:
                            on_update({
                                "kind": "detection",
                                "timestamp": timestamp,
                                "detected": actual_value,
                                "predicted_multiplier": None,
                                "confidence": None,
                            })

                        # Run the prediction on a background thread so a slow
                        # (or hung) API call never stalls frame capture/OCR.
                        threading.Thread(
                            target=_predict_async,
                            args=(list(history), list(history_timestamps), timestamp, actual_value, request_id),
                            daemon=True,
                        ).start()

                    last_detected = multiplier
            else:
                # Measure the gap in wall-clock time, not frames. fps here is
                # the *target* rate; the loop is OCR-bound and runs well below
                # it, so a frame count against fps was really waiting tens of
                # seconds - long enough that last_detected often survived into
                # the next round and silently swallowed a repeated multiplier,
                # leaving the GUI showing the previous round.
                if (
                    last_multiplier_seen_at is not None
                    and time.monotonic() - last_multiplier_seen_at > ROUND_RESET_SEC
                ):
                    last_detected = None
                    last_multiplier_seen_at = None

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        print("Detection stopped.")
