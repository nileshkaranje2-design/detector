"""GUI: region picker + continuous capture."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src import capture, runner


def pick_region() -> tuple[int, int, int, int] | None:
    """Show fullscreen overlay; user drags to select region. Returns (x, y, w, h) or None if cancelled."""

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.configure(bg="black")
    root.attributes("-alpha", 0.3)

    result: tuple[int, int, int, int] | None = None
    start_x = start_y = None
    rect_id = None

    canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)

    def on_press(e):
        nonlocal start_x, start_y, rect_id
        start_x, start_y = e.x, e.y
        if rect_id is not None:
            canvas.delete(rect_id)
        rect_id = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="white", width=2)

    def on_drag(e):
        nonlocal rect_id
        if rect_id is not None and start_x is not None:
            canvas.coords(rect_id, start_x, start_y, e.x, e.y)

    def on_release(e):
        nonlocal result
        if start_x is not None and start_y is not None:
            x1, x2 = min(start_x, e.x), max(start_x, e.x)
            y1, y2 = min(start_y, e.y), max(start_y, e.y)
            w, h = max(1, x2 - x1), max(1, y2 - y1)
            result = (x1, y1, w, h)
        root.quit()
        root.destroy()

    def on_escape(_):
        root.quit()
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    return result


class CaptureApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Region / Window Capture")
        self.root.geometry("500x340")
        self.root.resizable(False, False)

        self.region: tuple[int, int, int, int] | None = None
        self.stop_event = threading.Event()
        self.capture_thread: threading.Thread | None = None

        # Source: Region or Window
        f0 = ttk.Frame(self.root, padding=8)
        f0.pack(fill=tk.X)
        ttk.Label(f0, text="Capture source:").pack(side=tk.LEFT, padx=(0, 8))
        self.source_var = tk.StringVar(value="region")
        ttk.Radiobutton(f0, text="Region", variable=self.source_var, value="region", command=self._on_source_change).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(f0, text="Window", variable=self.source_var, value="window", command=self._on_source_change).pack(side=tk.LEFT)

        # Region (when source = region)
        self._f1 = ttk.Frame(self.root, padding=8)
        self._f1.pack(fill=tk.X)
        ttk.Button(self._f1, text="Select region", command=self._on_select_region).pack(side=tk.LEFT, padx=(0, 8))
        self.region_label = ttk.Label(self._f1, text="No region selected")
        self.region_label.pack(side=tk.LEFT)

        # Window (when source = window)
        self._f1w = ttk.Frame(self.root, padding=8)
        ttk.Label(self._f1w, text="Window:").pack(side=tk.LEFT, padx=(0, 8))
        self.window_var = tk.StringVar(value="Chrome")
        self.window_combo = ttk.Combobox(self._f1w, textvariable=self.window_var, width=42)
        self.window_combo.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(self._f1w, text="Refresh list", command=self._refresh_windows).pack(side=tk.LEFT)
        self._refresh_windows()

        # FPS
        f2 = ttk.Frame(self.root, padding=8)
        f2.pack(fill=tk.X)
        ttk.Label(f2, text="FPS:").pack(side=tk.LEFT, padx=(0, 8))
        self.fps_var = tk.StringVar(value="15")
        ttk.Spinbox(f2, from_=5, to=60, width=6, textvariable=self.fps_var).pack(side=tk.LEFT)

        # Output
        f3 = ttk.Frame(self.root, padding=8)
        f3.pack(fill=tk.X)
        self.output_label = ttk.Label(f3, text="Output:")
        self.output_label.pack(side=tk.LEFT, padx=(0, 8))
        self.output_var = tk.StringVar(value="output.mp4")
        self.output_entry = ttk.Entry(f3, textvariable=self.output_var, width=30)
        self.output_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.browse_btn = ttk.Button(f3, text="Browse", command=self._on_browse)
        self.browse_btn.pack(side=tk.LEFT)
        
        # Mode
        fm = ttk.Frame(self.root, padding=8)
        fm.pack(fill=tk.X)
        self.detect_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fm, 
            text="Detect Multiplier Mode (No Video, OCR via Terminal Logging)", 
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

        self._on_source_change()

    def _on_source_change(self):
        is_region = self.source_var.get() == "region"
        if is_region:
            self._f1w.pack_forget()
            self._f1.pack(fill=tk.X)
        else:
            self._f1.pack_forget()
            self._f1w.pack(fill=tk.X)

    def _on_detect_mode_change(self):
        if self.detect_mode_var.get():
            self.output_entry.config(state=tk.DISABLED)
            self.browse_btn.config(state=tk.DISABLED)
        else:
            self.output_entry.config(state=tk.NORMAL)
            self.browse_btn.config(state=tk.NORMAL)

    def _refresh_windows(self):
        titles = [t[0] for t in capture.list_windows() if t[0].strip()]
        self.window_combo["values"] = titles[:100]
        if titles and not self.window_var.get():
            self.window_var.set(titles[0][:60])

    def _on_select_region(self):
        self.root.attributes("-topmost", False)
        self.root.iconify()
        self.root.after(100, self._do_pick)

    def _do_pick(self):
        r = pick_region()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        if r:
            self.region = r
            self.region_label.config(text=f"x={r[0]}, y={r[1]}, {r[2]}x{r[3]}")

    def _on_browse(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if path:
            self.output_var.set(path)

    def _run_capture(self):
        fps = float(self.fps_var.get() or "15")
        output = self.output_var.get().strip() or "output.mp4"
        detect_mode = self.detect_mode_var.get()
        
        if self.source_var.get() == "region":
            if not self.region:
                self.root.after(0, lambda: messagebox.showerror("Error", "Select a region first"))
                self.root.after(0, self._capture_done)
                return
            if detect_mode:
                self.root.after(0, lambda: messagebox.showerror("Error", "Detection Mode requires choosing a Window source, not Region"))
                self.root.after(0, self._capture_done)
                return
        else:
            if not (self.window_var.get() or "").strip():
                self.root.after(0, lambda: messagebox.showerror("Error", "Enter or select a window title"))
                self.root.after(0, self._capture_done)
                return
                
        self.stop_event.clear()
        try:
            if detect_mode:
                runner.run_detection(
                    (self.window_var.get() or "").strip(), fps,
                    stop_event=self.stop_event
                )
            else:
                if self.source_var.get() == "region":
                    x, y, w, h = self.region
                    runner.run_region(x, y, w, h, fps, output_path=output, stop_event=self.stop_event)
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
        if self.source_var.get() == "region":
            if not self.region:
                messagebox.showwarning("Warning", "Select a region first")
                return
        else:
            if not (self.window_var.get() or "").strip():
                messagebox.showwarning("Warning", "Enter or select a window title")
                return
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Capturing... (Ctrl+C in terminal to stop)")
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
