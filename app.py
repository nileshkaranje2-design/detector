"""GUI: Window Capture & Multiplier Detection."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from src import capture, predictor, runner

PREVIEW_MAX_WIDTH = 400  # cap so a wide capture still fits its half of the split preview/response row


class CaptureApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Multiplier Detection")
        self.root.geometry("900x760")
        self.root.minsize(650, 500)
        self.root.resizable(True, True)

        self.stop_event = threading.Event()
        self.capture_thread: threading.Thread | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None

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

        f_response = ttk.Frame(f6)
        f_response.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))
        ttk.Label(f_response, text="Model response:").pack(anchor=tk.W)
        self.response_text = tk.Text(f_response, wrap=tk.WORD, state=tk.DISABLED)
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

    def _refresh_windows(self):
        titles = [t[0] for t in capture.list_windows() if t[0].strip()]
        self.window_combo["values"] = titles[:100]
        if titles and not self.window_var.get():
            self.window_var.set(titles[0][:60])

    def _run_capture(self):
        fps = 15.0
        detect_mode = self.detect_mode_var.get()
        default_out = "detections.txt" if detect_mode else "output.mp4"
        output = self.output_var.get().strip() or default_out
        
        if not (self.window_var.get() or "").strip():
            self.root.after(0, lambda: messagebox.showerror("Error", "Enter or select a window title"))
            self.root.after(0, self._capture_done)
            return
                
        self.stop_event.clear()
        try:
            if detect_mode:
                prompt = self.prompt_text.get("1.0", tk.END).strip()
                model = (self.model_var.get() or "").strip()
                runner.run_detection(
                    (self.window_var.get() or "").strip(), fps,
                    output_path=output,
                    stop_event=self.stop_event,
                    on_update=self._on_detection_update,
                    on_frame=self._on_frame_update,
                    system_prompt=prompt or None,
                    model=model or None,
                )
            else:
                runner.run_window_capture(
                    (self.window_var.get() or "").strip(), fps,
                    output_path=output, stop_event=self.stop_event,
                )
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda msg=err_msg: messagebox.showerror("Error", msg))
        finally:
            self.root.after(0, self._capture_done)

    def _on_start(self):
        if not (self.window_var.get() or "").strip():
            messagebox.showwarning("Warning", "Enter or select a window title")
            return
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Capturing... (Close app to exit)")
        self.capture_thread = threading.Thread(target=self._run_capture, daemon=True)
        self.capture_thread.start()

    def _on_stop(self):
        self.stop_event.set()
        self.status_var.set("Stopping... (capture runs in thread; close app to exit)")

    def _on_detection_update(self, update: dict):
        self.root.after(0, self._apply_detection_update, update)

    def _apply_detection_update(self, update: dict):
        time_str = datetime.fromisoformat(update["timestamp"]).strftime("%H:%M:%S")
        self.detected_var.set(f"Last detected: {update['detected']}x at {time_str}")

        predicted = update.get("predicted_multiplier")
        if predicted is not None:
            confidence = update.get("confidence") or "?"
            self.prediction_var.set(f"Next prediction: {predicted}x (confidence: {confidence})")
        else:
            self.prediction_var.set("Next prediction: —")

        reasoning = update.get("reasoning")
        if reasoning:
            self._set_response_text(reasoning)

    def _set_response_text(self, text: str):
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert("1.0", text)
        self.response_text.config(state=tk.DISABLED)

    def _on_frame_update(self, img: Image.Image):
        self.root.after(0, self._apply_frame_update, img)

    def _apply_frame_update(self, img: Image.Image):
        w, h = img.size
        if w > PREVIEW_MAX_WIDTH:
            scale = PREVIEW_MAX_WIDTH / w
            img = img.resize((PREVIEW_MAX_WIDTH, int(h * scale)))
        self._preview_photo = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self._preview_photo, text="")

    def _capture_done(self):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Ready")

    def run(self):
        self.root.mainloop()


def main():
    app = CaptureApp()
    app.run()


if __name__ == "__main__":
    main()
