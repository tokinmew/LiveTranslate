"""Bounded, opt-in capture of one application client area, without desktop fallback.

PrintWindow can block inside the target application. Execute it in a disposable
child process so a hung game never strands the OCR thread or its GDI objects.
Pixels travel through an anonymous pipe and are never saved to disk.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import subprocess
import sys

HEADER = struct.Struct("<8siiii")
MAGIC = b"LTCAP01\0"
MAX_PIXELS = 40_000_000


def validate_target(region):
    if set(region) != {"window", "process"}:
        raise ValueError("Choose an application window again.")
    handle, process = region["window"], region["process"]
    if (isinstance(handle, bool) or not isinstance(handle, int) or not 0 < handle < 2**63
            or isinstance(process, bool) or not isinstance(process, int) or not 0 < process < 2**32):
        raise ValueError("The application window identifier is invalid.")
    return dict(window=handle, process=process)


def capture_application(region, timeout=2.0):
    """Return (RGB pixels, physical client rectangle), or an actionable error."""
    from PIL import Image
    target = validate_target(region)
    if os.name != "nt":
        raise RuntimeError("Application capture is available on Windows only.")
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
               str(target["window"]), str(target["process"])]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError("The selected application did not provide a frame. Keep its window open and rendering, then retry.") from None
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()[:400]
        raise RuntimeError(detail or "The selected application could not be captured.")
    if len(result.stdout) < HEADER.size:
        raise RuntimeError("The selected application returned an incomplete frame.")
    marker, left, top, width, height = HEADER.unpack_from(result.stdout)
    if (marker != MAGIC or width < 5 or height < 5 or width * height > MAX_PIXELS
            or len(result.stdout) != HEADER.size + width * height * 4):
        raise RuntimeError("The selected application returned an invalid frame.")
    image = Image.frombytes("RGB", (width, height), result.stdout[HEADER.size:], "raw", "BGRX")
    # GPU/protected windows sometimes report success but supply a solid surface.
    # Never substitute the desktop: that would silently OCR unrelated content.
    if all(low == high for low, high in image.getextrema()):
        raise RuntimeError("The selected application returned a blank frame. Keep VRChat rendering in a window; use Preview captured view to check it.")
    return image, dict(left=left, top=top, width=width, height=height)


def _enable_physical_pixels(user):
    # This helper is a fresh Python process. Match the UI/MSS physical-pixel
    # contract before looking up any geometry or obtaining a device context.
    try:
        aware = user.SetProcessDpiAwarenessContext
        aware.argtypes = [ctypes.c_void_p]
        aware.restype = wintypes.BOOL
        if aware(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    user.SetProcessDPIAware()


def _native_capture(handle, process):
    user = ctypes.WinDLL("user32", use_last_error=True)
    _enable_physical_pixels(user)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    hwnd = wintypes.HWND(handle)
    pid = wintypes.DWORD()
    if not user.IsWindow(hwnd) or not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or pid.value != process:
        raise RuntimeError("The selected application has closed. Choose its new window again.")
    if user.IsIconic(hwnd):
        raise RuntimeError("The selected application is minimized. Restore its window; LiveTranslate can stay behind it.")
    rect, origin = wintypes.RECT(), wintypes.POINT()
    if not user.GetClientRect(hwnd, ctypes.byref(rect)) or not user.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("Windows could not locate the selected application window.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 5 or height < 5 or width * height > MAX_PIXELS:
        raise RuntimeError("The selected application has no usable client area.")
    # BITMAPINFOHEADER, top-down 32-bit uncompressed DIB.
    info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
    dc = user.GetDC(hwnd)
    memory = bitmap = old = None
    try:
        memory = gdi.CreateCompatibleDC(dc)
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, info, 0, ctypes.byref(bits), None, 0)
        if not dc or not memory or not bitmap or not bits:
            raise RuntimeError("Windows could not allocate an application capture frame.")
        old = gdi.SelectObject(memory, bitmap)
        # PW_CLIENTONLY | PW_RENDERFULLCONTENT. No foreground/desktop copying.
        if not user.PrintWindow(hwnd, memory, 3):
            raise RuntimeError("This application does not provide window frames. Try windowed VRChat or select a visible display area.")
        if not user.IsWindow(hwnd) or user.IsIconic(hwnd):
            raise RuntimeError("The selected application changed while reading. Restore it and retry.")
        after = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(after))
        if after.value != process:
            raise RuntimeError("The selected application changed. Choose its window again.")
        after_rect, after_origin = wintypes.RECT(), wintypes.POINT()
        if (not user.GetClientRect(hwnd, ctypes.byref(after_rect)) or not user.ClientToScreen(hwnd, ctypes.byref(after_origin))
                or (after_rect.right - after_rect.left, after_rect.bottom - after_rect.top, after_origin.x, after_origin.y)
                != (width, height, origin.x, origin.y)):
            raise RuntimeError("The selected application moved or resized while reading. Retry the capture.")
        return HEADER.pack(MAGIC, origin.x, origin.y, width, height) + ctypes.string_at(bits, width * height * 4)
    finally:
        if old and memory:
            gdi.SelectObject(memory, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(hwnd, dc)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("Choose an application window first.")
        sys.stdout.buffer.write(_native_capture(int(sys.argv[1]), int(sys.argv[2])))
    except Exception as exc:
        sys.stderr.buffer.write(str(exc).encode("utf-8", "replace"))
        sys.exit(1)
