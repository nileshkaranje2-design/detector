"""GUI: Window Capture & Multiplier Detection."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from src import capture, predictor, runner

PREVIEW_MAX_WIDTH = 400  # cap so a wide capture still fits its half of the split preview/response row

# How often the main thread drains work handed over by the capture thread.
# The capture thread never touches Tk directly - Tkinter is not thread-safe,
# and posting root.after() from a worker on every captured frame is what let
# detection updates pile up behind preview rendering and arrive late. Instead
# the worker parks results in the _pending_* slots below and this pump applies
# them on the UI thread.
UI_PUMP_MS = 50


class CaptureApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Multiplier Detection")
        self.root.geometry("900x760")
        self.root.minsize(650, 500)
        self.root.resizable(True, True)

        # One Event per capture run, created in _on_start(). It must not be
        # shared and reused: a restart used to clear the same Event the
        # previous run was still watching, wiping a stop it hadn't noticed yet
        # and leaving two capture loops running at once - each with its own
        # last_detected, both appending to the same file, which produced
        # duplicate rounds and made "Last detected" jump backwards.
        self.stop_event: threading.Event | None = None
        self.capture_thread: threading.Thread | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None

        # Handover from the capture thread to the UI thread (see UI_PUMP_MS).
        # Detection updates are queued in full - they're rare and each one
        # matters. Preview frames are coalesced down to the newest one only:
        # they arrive every capture cycle, and letting them queue was what
        # pushed "Last detected" behind the capture loop.
        self._handover_lock = threading.Lock()
        self._pending_updates: deque[dict] = deque()
        self._pending_frame: Image.Image | None = None
        # (finished, error) once the capture loop exits; None while it runs.
        self._pending_done: tuple[bool, str | None] | None = None
        # ISO timestamp of the newest round shown, so a slow prediction landing
        # after a newer round can't repaint an older round's multiplier.
        self._shown_detection_ts: str | None = None

        # Every round known to this session, oldest first: rounds loaded from a
        # file plus rounds detected live. Shown in the detections list, and used
        # to seed the context handed to the predictor when capture starts.
        self._history: list[tuple[str, float]] = []

        # Window
        self._f1w = ttk.Frame(self.root, padding=8)
        self._f1w.pack(fill=tk.X)
        ttk.Label(self._f1w, text="Window:").pack(side=tk.LEFT, padx=(0, 8))
        self.window_var = tk.StringVar(value="Chrome")
        self.window_combo = ttk.Combobox(self._f1w, textvariable=self.window_var, width=35)
        self.window_combo.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(self._f1w, text="Refresh list", command=self._refresh_windows).pack(side=tk.LEFT)
        self._refresh_windows()

        # Output
        f3 = ttk.Frame(self.root, padding=8)
        f3.pack(fill=tk.X)
        self.output_label = ttk.Label(f3, text="Text Output:")
        self.output_label.pack(side=tk.LEFT, padx=(0, 8))
        self.output_var = tk.StringVar(value="detections.txt")
        self.output_entry = ttk.Entry(f3, textvariable=self.output_var, width=30)
        self.output_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.browse_btn = ttk.Button(f3, text="Browse", command=self._on_browse)
        self.browse_btn.pack(side=tk.LEFT)

        # Mode
        fm = ttk.Frame(self.root, padding=8)
        fm.pack(fill=tk.X)
        self.detect_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            fm, 
            text="Option: Detect Multiplier Mode (Logs to Excel)", 
            variable=self.detect_mode_var,
            command=self._on_detect_mode_change
        ).pack(side=tk.LEFT)

        # Buttons
        f4 = ttk.Frame(self.root, padding=8)
        f4.pack(fill=tk.X)
        self.start_btn = ttk.Button(f4, text="Start capture", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(f4, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

        # Live detection status
        f5 = ttk.Frame(self.root, padding=8)
        f5.pack(fill=tk.X)
        self.detected_var = tk.StringVar(value="Last detected: —")
        ttk.Label(f5, textvariable=self.detected_var).pack(anchor=tk.W)
        self.prediction_var = tk.StringVar(value="Next prediction: —")
        ttk.Label(f5, textvariable=self.prediction_var).pack(anchor=tk.W)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var).pack(pady=8)

        # Captured frame preview (left) and model response (right), side by
        # side so the two panes use horizontal space instead of stacking.
        f6 = ttk.Frame(self.root, padding=8)
        f6.pack(fill=tk.BOTH, expand=True)

        f_preview = ttk.Frame(f6)
        f_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        ttk.Label(f_preview, text="Captured frame:").pack(anchor=tk.W)
        self.preview_label = ttk.Label(f_preview, text="(no frame yet)", relief=tk.SUNKEN)
        self.preview_label.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # Right-hand column: the round-by-round detection list above the model's
        # response. A paned window rather than a fixed split so either half can
        # be given the space - the list matters while capturing, the response
        # matters when reading a prediction.
        right_pane = ttk.PanedWindow(f6, orient=tk.VERTICAL)
        right_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        f_detections = ttk.Frame(right_pane)
        right_pane.add(f_detections, weight=3)
        det_header = ttk.Frame(f_detections)
        det_header.pack(fill=tk.X)
        self.detections_title_var = tk.StringVar(value="Detections (0):")
        ttk.Label(det_header, textvariable=self.detections_title_var).pack(side=tk.LEFT)
        ttk.Button(det_header, text="Clear", width=6, command=self._on_clear_detections).pack(side=tk.RIGHT)
        ttk.Button(det_header, text="Load file", width=9, command=self._on_load_detections).pack(side=tk.RIGHT, padx=(0, 4))

        det_body = ttk.Frame(f_detections)
        det_body.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        det_scroll = ttk.Scrollbar(det_body, orient=tk.VERTICAL)
        self.detections_list = tk.Listbox(
            det_body, height=8, activestyle="none", yscrollcommand=det_scroll.set
        )
        det_scroll.config(command=self.detections_list.yview)
        det_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.detections_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        f_response = ttk.Frame(right_pane)
        right_pane.add(f_response, weight=2)
        ttk.Label(f_response, text="Model response:").pack(anchor=tk.W)
        # An explicit height: tk.Text asks for 24 lines by default, which - now
        # that the detections list sits above it - demanded more vertical space
        # than the window has and pushed the model/prompt rows off the bottom.
        # Both panes grow from here via the paned window.
        self.response_text = tk.Text(f_response, wrap=tk.WORD, height=6, state=tk.DISABLED)
        self.response_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # Model
        f_model = ttk.Frame(self.root, padding=8)
        f_model.pack(fill=tk.X)
        ttk.Label(f_model, text="Model:").pack(side=tk.LEFT, padx=(0, 8))
        self.model_var = tk.StringVar(value=predictor.DEFAULT_MODEL)
        self.model_combo = ttk.Combobox(
            f_model, textvariable=self.model_var, values=predictor.MODEL_OPTIONS, width=20
        )
        self.model_combo.pack(side=tk.LEFT)
        ttk.Button(
            f_model, text="Set API Key", command=self._on_set_api_key
        ).pack(side=tk.LEFT, padx=(12, 4))
        self.api_key_status_var = tk.StringVar()
        ttk.Label(f_model, textvariable=self.api_key_status_var).pack(side=tk.LEFT)
        self._update_api_key_status()

        # Prediction prompt (editable)
        f_prompt = ttk.Frame(self.root, padding=8)
        f_prompt.pack(fill=tk.X)
        prompt_header = ttk.Frame(f_prompt)
        prompt_header.pack(fill=tk.X)
        ttk.Label(prompt_header, text="Prediction prompt:").pack(side=tk.LEFT)
        ttk.Button(
            prompt_header, text="Reset to default", command=self._on_reset_prompt
        ).pack(side=tk.RIGHT)
        self.prompt_text = tk.Text(f_prompt, height=6, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.X, pady=(4, 0))
        self.prompt_text.insert("1.0", predictor.DEFAULT_SYSTEM_PROMPT)

        self._on_detect_mode_change()
        self._autoload_detections()
        self.root.after(UI_PUMP_MS, self._pump_ui)

    def _pump_ui(self):
        """Apply work handed over by the capture thread. Runs on the UI thread."""
        with self._handover_lock:
            updates = list(self._pending_updates)
            self._pending_updates.clear()
            frame = self._pending_frame
            self._pending_frame = None
            done = self._pending_done
            self._pending_done = None

        # Detection updates first: the label must never wait on preview
        # rendering, which is by far the slower of the two.
        for update in updates:
            self._apply_detection_update(update)
        if frame is not None:
            self._apply_frame_update(frame)
        if done is not None:
            self._capture_done(done[1])

        self.root.after(UI_PUMP_MS, self._pump_ui)

    @staticmethod
    def _format_row(timestamp: str, value: float) -> str:
        """
        One detections-list line. Rounds from today show just the clock time;
        older ones carry their date too, since the list now mixes live rounds
        with history loaded from earlier sessions and a bare time is ambiguous
        across days.
        """
        try:
            when = datetime.fromisoformat(timestamp)
        except ValueError:
            return f"{timestamp}   {value}x"
        if when.date() == datetime.now().date():
            return f"{when.strftime('%H:%M:%S')}   {value}x"
        return f"{when.strftime('%Y-%m-%d %H:%M:%S')}   {value}x"

    def _add_history_rows(self, rows: list[tuple[str, float]]) -> int:
        """
        Append rounds to the history and the on-screen list, skipping any
        already held. Returns how many were actually added.

        The de-duplication matters because the output file is auto-loaded at
        startup and can also be picked again with "Load file"; without it the
        same rounds would be counted twice and sent to the model twice.
        Timestamps carry microseconds, so a genuine collision isn't realistic.
        """
        known = set(self._history)
        added = 0
        for timestamp, value in rows:
            if (timestamp, value) in known:
                continue
            known.add((timestamp, value))
            self._history.append((timestamp, value))
            self.detections_list.insert(tk.END, self._format_row(timestamp, value))
            added += 1
        if added:
            self.detections_list.see(tk.END)
        self.detections_title_var.set(f"Detections ({len(self._history)}):")
        return added

    def _autoload_detections(self):
        """
        Load the output file's existing rounds at startup, so a new session
        continues from the history already on disk instead of from nothing -
        the same file capture is about to append to.
        """
        if not self.detect_mode_var.get():
            return
        path = self.output_var.get().strip()
        if not path or not os.path.isfile(path):
            return
        try:
            rows = runner.load_detections(path)
        except OSError as e:
            # Never let a bad output file stop the app from opening.
            print(f"Could not auto-load {path}: {e}")
            return
        if not rows:
            return
        added = self._add_history_rows(rows)
        self.status_var.set(
            f"Loaded {added} previous round(s) from {os.path.basename(path)} - "
            "included in the context sent to the model."
        )

    def _on_load_detections(self):
        path = filedialog.askopenfilename(
            title="Load detections",
            filetypes=[("Detection logs", "*.txt *.log"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            rows = runner.load_detections(path)
        except OSError as e:
            messagebox.showerror("Error", f"Could not read {path}:\n{e}")
            return
        if not rows:
            messagebox.showwarning(
                "Nothing loaded",
                "No detection lines were found in that file.\n\n"
                "Expected lines like:\n"
                "2026-09-14T11:05:00 - Detected Multiplier: 1.86x",
            )
            return
        added = self._add_history_rows(rows)
        skipped = len(rows) - added
        self.status_var.set(
            f"Loaded {added} round(s) from {os.path.basename(path)}"
            + (f" ({skipped} already listed)" if skipped else "")
            + " - included in the context sent to the model."
        )

    def _on_clear_detections(self):
        self._history.clear()
        self.detections_list.delete(0, tk.END)
        self.detections_title_var.set("Detections (0):")

    def _on_reset_prompt(self):
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", predictor.DEFAULT_SYSTEM_PROMPT)

    def _update_api_key_status(self):
        self.api_key_status_var.set("API key: set" if predictor.has_api_key() else "API key: not set")

    def _on_set_api_key(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Set OpenAI API Key")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="OpenAI API key:").pack(anchor=tk.W)
        key_var = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        entry = ttk.Entry(frame, textvariable=key_var, width=50, show="*")
        entry.pack(fill=tk.X, pady=(4, 4))
        entry.focus_set()

        show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Show key", variable=show_var,
            command=lambda: entry.config(show="" if show_var.get() else "*"),
        ).pack(anchor=tk.W)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))

        def _save():
            predictor.set_api_key(key_var.get())
            self._update_api_key_status()
            dialog.destroy()

        def _clear():
            predictor.set_api_key("")
            self._update_api_key_status()
            dialog.destroy()

        ttk.Button(btn_row, text="Save", command=_save).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Clear", command=_clear).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

        dialog.bind("<Return>", lambda _e: _save())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def _on_detect_mode_change(self):
        if self.detect_mode_var.get():
            self.output_label.config(text="Text Output:")
            if self.output_var.get() == "output.mp4":
                self.output_var.set("detections.txt")
        else:
            self.output_label.config(text="Video Output:")
            if self.output_var.get() == "detections.txt":
                self.output_var.set("output.mp4")

    def _on_browse(self):
        is_detect = self.detect_mode_var.get()
        ext = ".txt" if is_detect else ".mp4"
        ftypes = [("Text files", "*.txt"), ("All files", "*.*")] if is_detect else [("MP4 video", "*.mp4"), ("All files", "*.*")]
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=ftypes,
        )
        if path:
            self.output_var.set(path)
            # Capture appends to this file, so show what's already in it - the
            # same reasoning as the startup auto-load.
            self._autoload_detections()

    def _refresh_windows(self):
        titles = [t[0] for t in capture.list_windows() if t[0].strip()]
        self.window_combo["values"] = titles[:100]
        if titles and not self.window_var.get():
            self.window_var.set(titles[0][:60])

    def _run_capture(self, settings: dict):
        """Capture loop body. Runs on a worker thread, so it must not touch Tk:
        every widget value it needs is read on the UI thread in _on_start() and
        handed over via settings."""
        fps = 15.0
        stop_event = settings["stop_event"]
        error: str | None = None
        try:
            if settings["detect_mode"]:
                runner.run_detection(
                    settings["window"], fps,
                    output_path=settings["output"],
                    stop_event=stop_event,
                    on_update=self._on_detection_update,
                    on_frame=self._on_frame_update,
                    system_prompt=settings["prompt"] or None,
                    model=settings["model"] or None,
                    initial_history=settings["history"],
                )
            else:
                runner.run_window_capture(
                    settings["window"], fps,
                    output_path=settings["output"], stop_event=stop_event,
                )
        except Exception as e:
            error = str(e)
        finally:
            with self._handover_lock:
                self._pending_done = (True, error)

    def _on_start(self):
        window = (self.window_var.get() or "").strip()
        if not window:
            messagebox.showwarning("Warning", "Enter or select a window title")
            return
        # Refuse to start a second loop while the previous one is still winding
        # down - two concurrent loops log the same rounds twice.
        if self.capture_thread is not None and self.capture_thread.is_alive():
            messagebox.showwarning(
                "Still stopping",
                "The previous capture hasn't finished stopping yet.\n"
                "Wait a moment and press Start capture again.",
            )
            return
        detect_mode = self.detect_mode_var.get()
        settings = {
            "window": window,
            "detect_mode": detect_mode,
            "output": self.output_var.get().strip()
                      or ("detections.txt" if detect_mode else "output.mp4"),
            "prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "model": (self.model_var.get() or "").strip(),
            # Snapshot, so the worker isn't reading a list the UI thread mutates
            # as new rounds come in.
            "history": list(self._history),
            # Fresh per run - never shared with a previous, still-exiting loop.
            "stop_event": threading.Event(),
        }
        self.stop_event = settings["stop_event"]
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Capturing... (Close app to exit)")
        self.capture_thread = threading.Thread(
            target=self._run_capture, args=(settings,), daemon=True
        )
        self.capture_thread.start()

    def _on_stop(self):
        if self.stop_event is not None:
            self.stop_event.set()
        self.status_var.set("Stopping... (capture runs in thread; close app to exit)")

    def _on_detection_update(self, update: dict):
        """Called from the capture thread - park the update, don't touch Tk."""
        with self._handover_lock:
            self._pending_updates.append(update)

    def _apply_detection_update(self, update: dict):
        timestamp = update["timestamp"]
        is_prediction = update.get("kind") == "prediction"

        # A prediction is the (slow, network-bound) answer for one specific
        # round. If a newer round has already been shown by the time it lands,
        # its multiplier is stale - drop it rather than repainting an older
        # value over the label.
        if is_prediction and self._shown_detection_ts is not None and timestamp < self._shown_detection_ts:
            return

        if not is_prediction:
            time_str = datetime.fromisoformat(timestamp).strftime("%H:%M:%S")
            self.detected_var.set(f"Last detected: {update['detected']}x at {time_str}")
            self._shown_detection_ts = timestamp
            self._add_history_rows([(timestamp, update["detected"])])
            # This round's prediction hasn't come back yet.
            self.prediction_var.set("Next prediction: …")
            return

        predicted = update.get("predicted_multiplier")
        error = update.get("error")
        if predicted is not None:
            confidence = update.get("confidence") or "?"
            self.prediction_var.set(f"Next prediction: {predicted}x (confidence: {confidence})")
        elif error:
            # Say why there's no prediction rather than showing a bare dash -
            # a billing or key problem is otherwise indistinguishable from the
            # model simply having nothing to say.
            self.prediction_var.set(f"Next prediction: unavailable ({error})")
        else:
            self.prediction_var.set("Next prediction: —")

        if error:
            self._set_response_text(update.get("error_detail") or error)
            return

        reasoning = update.get("reasoning")
        if reasoning:
            self._set_response_text(reasoning)

    def _set_response_text(self, text: str):
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert("1.0", text)
        self.response_text.config(state=tk.DISABLED)

    def _on_frame_update(self, img: Image.Image):
        """Called from the capture thread every cycle. Downscale here - the
        capture thread can absorb it, the UI thread can't - and keep only the
        newest frame, since any older pending one is about to be replaced."""
        # This runs on the capture thread, so anything raised here would kill
        # the capture loop outright - the preview is cosmetic and must never
        # be able to take detection down with it.
        try:
            w, h = img.size
            if w > PREVIEW_MAX_WIDTH:
                scale = PREVIEW_MAX_WIDTH / w
                img = img.resize((PREVIEW_MAX_WIDTH, max(1, int(h * scale))))
        except Exception as e:
            print(f"Preview scaling failed (ignored): {e}")
            return
        with self._handover_lock:
            self._pending_frame = img

    def _apply_frame_update(self, img: Image.Image):
        self._preview_photo = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self._preview_photo, text="")

    def _capture_done(self, error: str | None = None):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Ready")
        if error:
            messagebox.showerror("Error", error)

    def run(self):
        self.root.mainloop()


def main():
    app = CaptureApp()
    app.run()


if __name__ == "__main__":
    main()
