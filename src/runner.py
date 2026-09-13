"""Main loop: capture -> timestamp -> save frame + OCR text."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Callable

from . import capture
from . import ocr
from . import predictor
from . import video_writer


def _parse_multiplier(value: str) -> float | None:
    """Parse a multiplier string like '3.02x' into a float."""
    try:
        return float(value.rstrip("xX"))
    except ValueError:
        return None


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
    history: list[float] = []
    history_timestamps: list[str] = []
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
        prediction = predictor.predict_next(
            history_snapshot, timestamps=timestamps_snapshot, system_prompt=system_prompt, model=model
        )
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
                "timestamp": timestamp,
                "detected": actual_value,
                "predicted_multiplier": (prediction or {}).get("predicted_multiplier"),
                "confidence": (prediction or {}).get("confidence"),
                "reasoning": (prediction or {}).get("reasoning"),
            })

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

            if on_frame:
                on_frame(img)

            # Locate and OCR just the multiplier text below "FLEW AWAY!"
            multiplier = ocr.detect_multiplier(img)
            
            if multiplier:
                empty_frames_count = 0
                if multiplier != last_detected:
                    timestamp = datetime.now().isoformat()
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

                        # Fire the detection update immediately, before kicking
                        # off the (slow, network-bound) prediction - the GUI's
                        # "Last detected" label shouldn't wait on that just
                        # because it shares an update dict with "Next prediction".
                        if on_update:
                            on_update({
                                "timestamp": timestamp,
                                "detected": actual_value,
                                "predicted_multiplier": None,
                                "confidence": None,
                            })

                        # Run the prediction on a background thread so a slow
                        # (or hung) API call never stalls frame capture/OCR.
                        # Allocate a new request id so any still-pending older
                        # request gets discarded as cancelled when it returns.
                        with prediction_lock:
                            prediction_request_id += 1
                            request_id = prediction_request_id
                        threading.Thread(
                            target=_predict_async,
                            args=(list(history), list(history_timestamps), timestamp, actual_value, request_id),
                            daemon=True,
                        ).start()

                    last_detected = multiplier
            else:
                empty_frames_count += 1
                if empty_frames_count > fps * 3:  # 3 seconds without multiplier
                    last_detected = None

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        print("Detection stopped.")
