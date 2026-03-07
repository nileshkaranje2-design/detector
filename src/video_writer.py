"""Write captured frames to MP4 video file."""

from __future__ import annotations

import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class VideoWriter:
    """Write PIL Images to an MP4 or AVI file using OpenCV."""

    def __init__(self, width: int, height: int, fps: float, output_path: str) -> None:
        if not HAS_CV2:
            raise ImportError("opencv-python is required for video output. Install with: pip install opencv-python")
        path_lower = output_path.lower()
        # Force a video backend (CAP_FFMPEG or CAP_MSMF); otherwise OpenCV may use CV_IMAGES and fail with filename_pattern.empty
        self._writer = None
        if path_lower.endswith(".mp4"):
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            for cap in (getattr(cv2, "CAP_FFMPEG", None), getattr(cv2, "CAP_MSMF", None)):
                if cap is not None:
                    w = cv2.VideoWriter(output_path, cap, fourcc, fps, (width, height))
                    if w.isOpened():
                        self._writer = w
                        break
        if self._writer is None:
            # Fallback: AVI + MJPG with explicit backend to avoid CV_IMAGES dispatch
            avi_path = output_path.rsplit(".", 1)[0] + ".avi" if "." in output_path else output_path + ".avi"
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            for cap in (getattr(cv2, "CAP_FFMPEG", None), getattr(cv2, "CAP_MSMF", None)):
                if cap is not None:
                    w = cv2.VideoWriter(avi_path, cap, fourcc, fps, (width, height))
                    if w.isOpened():
                        self._writer = w
                        break
            if self._writer is None:
                self._writer = cv2.VideoWriter(avi_path, fourcc, fps, (width, height))
            if not self._writer.isOpened():
                raise RuntimeError(f"VideoWriter could not open {avi_path}. Try installing opencv-python-headless or use a .avi path.")
            self._output_path = avi_path
        else:
            self._output_path = output_path
        self._width = width
        self._height = height

    @property
    def output_path(self) -> str:
        """Path to the file actually being written (may be .avi if MP4 was unavailable)."""
        return self._output_path

    def write_frame(self, image: Image.Image) -> None:
        """Convert PIL Image (RGB) to BGR and write one frame."""
        arr = np.array(image)
        if arr.shape[:2] != (self._height, self._width):
            image = image.resize((self._width, self._height), Image.Resampling.LANCZOS)
            arr = np.array(image)
        bgr = arr[:, :, ::-1].copy()  # RGB -> BGR
        self._writer.write(bgr)

    def release(self) -> None:
        """Close the video file."""
        self._writer.release()
