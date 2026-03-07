"""GUI: Window Capture & Multiplier Detection."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src import capture, runner


class CaptureApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Multiplier Detection")
        self.root.geometry("450x220")
        self.root.resizable(False, False)

        self.stop_event = threading.Event()
        self.capture_thread: threading.Thread | None = None

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
        self.output_label = ttk.Label(f3, text="Excel Output:")
        self.output_label.pack(side=tk.LEFT, padx=(0, 8))
        self.output_var = tk.StringVar(value="detections.xlsx")
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

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var).pack(pady=8)
        
        self._on_detect_mode_change()

    def _on_detect_mode_change(self):
        if self.detect_mode_var.get():
            self.output_label.config(text="Excel Output:")
            if self.output_var.get() == "output.mp4":
                self.output_var.set("detections.xlsx")
        else:
            self.output_label.config(text="Video Output:")
            if self.output_var.get() == "detections.xlsx":
                self.output_var.set("output.mp4")

    def _on_browse(self):
        is_detect = self.detect_mode_var.get()
        ext = ".xlsx" if is_detect else ".mp4"
        ftypes = [("Excel files", "*.xlsx"), ("All files", "*.*")] if is_detect else [("MP4 video", "*.mp4"), ("All files", "*.*")]
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
        default_out = "detections.xlsx" if detect_mode else "output.mp4"
        output = self.output_var.get().strip() or default_out
        
        if not (self.window_var.get() or "").strip():
            self.root.after(0, lambda: messagebox.showerror("Error", "Enter or select a window title"))
            self.root.after(0, self._capture_done)
            return
                
        self.stop_event.clear()
        try:
            if detect_mode:
                runner.run_detection(
                    (self.window_var.get() or "").strip(), fps,
                    output_path=output,
                    stop_event=self.stop_event
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
