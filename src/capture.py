"""Window listing and region capture using pygetwindow + mss, plus native win32 for windows."""

from __future__ import annotations

import ctypes
import platform
import time

import pygetwindow
import mss
from PIL import Image

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

# Define ctypes structures and functions for Win32 capture (Windows only;
# on other platforms capture_true_window() falls back to mss-based capture).
if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD)
        ]

if IS_MACOS:
    # pygetwindow's macOS backend is a thin stub (no getAllWindows/getActiveWindow),
    # so list/find windows directly via Quartz's window server APIs instead.
    import Quartz

    class _MacWindow:
        """Minimal stand-in with the same attributes capture.py/runner.py rely on."""

        def __init__(self, title: str, left: int, top: int, width: int, height: int, window_id: int):
            self.title = title
            self.left = left
            self.top = top
            self.width = width
            self.height = height
            self.window_id = window_id

    def _list_mac_windows() -> list[_MacWindow]:
        info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        windows = []
        for w in info:
            if w.get("kCGWindowLayer", 0) != 0:
                continue  # skip menu bar / status items / overlays
            bounds = w.get("kCGWindowBounds") or {}
            width, height = int(bounds.get("Width", 0)), int(bounds.get("Height", 0))
            if width < 50 or height < 50:
                continue  # skip tiny/invisible windows
            owner = (w.get("kCGWindowOwnerName") or "").strip()
            name = (w.get("kCGWindowName") or "").strip()
            title = f"{owner} - {name}" if name and name != owner else owner
            if not title.strip():
                continue
            windows.append(_MacWindow(
                title,
                int(bounds.get("X", 0)),
                int(bounds.get("Y", 0)),
                width,
                height,
                int(w.get("kCGWindowNumber", 0)),
            ))
        return windows

    def _cgimage_to_pil(cg_image) -> Image.Image | None:
        width = Quartz.CGImageGetWidth(cg_image)
        height = Quartz.CGImageGetHeight(cg_image)
        if width == 0 or height == 0:
            return None
        bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)
        provider = Quartz.CGImageGetDataProvider(cg_image)
        data = bytes(Quartz.CGDataProviderCopyData(provider))
        img = Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", bytes_per_row, 1)
        return img.convert("RGB")

    def _capture_mac_window_by_id(window_id: int) -> Image.Image | None:
        """
        Capture a specific window's own content by window ID, regardless of
        stacking order (as long as it's on-screen and not minimized).

        A plain mss screen-region grab captures whatever is visually topmost
        at those screen coordinates, which silently grabs the wrong app's
        pixels whenever another window overlaps the same area - this uses
        Quartz's window-specific compositing instead, the macOS equivalent of
        Windows' PrintWindow.
        """
        cg_image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if cg_image is None:
            return None
        return _cgimage_to_pil(cg_image)

def list_windows() -> list[tuple[str, str]]:
    """Return list of (window title, short description) for all visible windows."""
    if IS_MACOS:
        return [(w.title, w.title[:60]) for w in _list_mac_windows()]

    result = []
    for w in pygetwindow.getAllWindows():
        title = w.title or "(no title)"
        if title.strip():
            result.append((title, f"{title[:60]}"))
    return result

def get_window(title_substring: str):
    """
    Find the window whose title contains title_substring (case-insensitive).
    Prefer the foreground (active) window if it matches; otherwise use the first match.
    """
    lower = title_substring.lower()

    if IS_MACOS:
        # CGWindowListCopyWindowInfo already returns windows front-to-back,
        # so the first match is effectively the most-foreground one.
        for w in _list_mac_windows():
            if lower in w.title.lower():
                return w
        return None

    # Prefer the active window
    try:
        active = pygetwindow.getActiveWindow()
        if active and lower in (active.title or "").lower():
            return active
    except Exception:
        pass

    # First matching window
    for w in pygetwindow.getAllWindows():
        if lower in (w.title or "").lower():
            return w

    return None

def get_window_region(title_substring: str) -> dict[str, int] | None:
    """
    Find window whose title contains title_substring (case-insensitive).
    Return mss-style monitor dict: {"left", "top", "width", "height"}, or None if not found.
    """
    w = get_window(title_substring)
    if w:
        return {
            "left": int(w.left),
            "top": int(w.top),
            "width": int(w.width),
            "height": int(w.height),
        }
    return None


def capture_true_window(window: pygetwindow.Window) -> Image.Image | None:
    """
    Capture a window's actual contents using PrintWindow Win32 API via ctypes.
    This captures the window even if obscured and avoids capturing the whole monitor if maximized.
    """
    if IS_MACOS:
        window_id = getattr(window, "window_id", None)
        if window_id:
            img = _capture_mac_window_by_id(window_id)
            if img is not None:
                return img
        # Fallback if the Quartz capture fails (e.g. window closed mid-capture):
        # a plain screen-region grab. This can capture the wrong app if another
        # window overlaps the same screen area.
        region = {"left": int(window.left), "top": int(window.top), "width": int(window.width), "height": int(window.height)}
        return capture_region(region)

    if not IS_WINDOWS:
        region = {"left": int(window.left), "top": int(window.top), "width": int(window.width), "height": int(window.height)}
        return capture_region(region)

    hwnd = window._hWnd
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    hwndDC = user32.GetWindowDC(hwnd)
    mfcDC  = gdi32.CreateCompatibleDC(hwndDC)
    saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, width, height)
    gdi32.SelectObject(mfcDC, saveBitMap)

    # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT (captures hardware accelerated windows too)
    result = user32.PrintWindow(hwnd, mfcDC, 3)

    if not result:
        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(hwnd, hwndDC)
        # Fallback to mss if PrintWindow fails for some reason
        region = {"left": int(window.left), "top": int(window.top), "width": int(window.width), "height": int(window.height)}
        return capture_region(region)

    bmpinfo = BITMAPINFOHEADER()
    bmpinfo.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmpinfo.biWidth = width
    bmpinfo.biHeight = -height  # top-down image
    bmpinfo.biPlanes = 1
    bmpinfo.biBitCount = 32
    bmpinfo.biCompression = 0

    buffer_len = width * height * 4
    buf = ctypes.create_string_buffer(buffer_len)

    gdi32.GetDIBits(mfcDC, saveBitMap, 0, height, buf, ctypes.cast(ctypes.pointer(bmpinfo), ctypes.c_void_p), 0)

    img = Image.frombuffer('RGBA', (width, height), buf, 'raw', 'BGRA', 0, 1)

    gdi32.DeleteObject(saveBitMap)
    gdi32.DeleteDC(mfcDC)
    user32.ReleaseDC(hwnd, hwndDC)
    
    return img.convert('RGB')


def capture_rect(x: int, y: int, width: int, height: int) -> Image.Image:
    """Capture screen region at (x, y) with given width and height."""
    region = {"left": x, "top": y, "width": width, "height": height}
    return capture_region(region)


def capture_region(region: dict[str, int]) -> Image.Image:
    """
    Capture the screen region (mss monitor dict) and return a PIL Image (RGB).
    """
    with mss.mss() as sct:
        shot = sct.grab(region)
        return Image.frombytes(
            "RGB",
            (shot.width, shot.height),
            shot.rgb,
        )
