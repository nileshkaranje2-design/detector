"""Window listing and region capture using pygetwindow + mss, plus native win32 for windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

import pygetwindow
import mss
from PIL import Image

# Define ctypes structures and functions for Win32 capture
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

def list_windows() -> list[tuple[str, str]]:
    """Return list of (window title, short description) for all visible windows."""
    result = []
    for w in pygetwindow.getAllWindows():
        title = w.title or "(no title)"
        if title.strip():
            result.append((title, f"{title[:60]}"))
    return result

def get_window(title_substring: str) -> pygetwindow.Window | None:
    """
    Find pygetwindow.Window whose title contains title_substring (case-insensitive).
    Prefer the foreground (active) window if it matches; otherwise use the first match.
    """
    lower = title_substring.lower()

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
