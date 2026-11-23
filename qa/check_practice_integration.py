"""Exercise the actual worker stdio protocol and Windows exclusion of practice text."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading


def check_window_filter(backend):
    sys.path.insert(0, str(backend))
    from screen_engine import ScreenEngine
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user.CreateWindowExW.restype = wintypes.HWND
    user.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
    user.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user.DestroyWindow.argtypes = [wintypes.HWND]
    # Both fixture windows are outside the virtual desktop and cannot take focus.
    left = user.GetSystemMetrics(76) - 2000
    handles = []
    try:
        for offset in (0, 500):
            window = user.CreateWindowExW(0x08000080, "STATIC", "Synthetic window", 0x90000000,
                                          left + offset, 0, 100, 80, None, None, None, None)
            if not window:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(window)
        dashboard, reply = handles
        before = ScreenEngine._visible_bounds([dashboard], include_source_windows=False)
        assert len(before) == 1, before
        assert user.SetPropW(reply, "LiveTranslate.ReplyPractice", 1)
        for include in (True, False):
            marked = ScreenEngine._visible_bounds([dashboard], include_source_windows=include)
            assert len(set(marked) - set(before)) == 1, marked
        user.RemovePropW(reply, "LiveTranslate.ReplyPractice")
        assert before == ScreenEngine._visible_bounds([dashboard], include_source_windows=False)
    finally:
        for window in handles:
            user.DestroyWindow(window)


def exercise(backend, temp):
    copied = temp / "app" / "backend"
    shutil.copytree(backend, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    launch = "import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[1]+'/worker.py',run_name='__main__')"
    proc = subprocess.Popen([sys.executable, "-I", "-B", "-X", "utf8", "-c", launch, str(copied)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
    events = queue.Queue()
    def read():
        for line in proc.stdout:
            events.put(json.loads(line))
        events.put(None)
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    count = 0
    def request(command, **args):
        nonlocal count
        count += 1
        proc.stdin.write(json.dumps(dict(args, command=command, id=count)) + "\n")
        proc.stdin.flush()
        result = events.get(timeout=60)
        assert result is not None and result.get("id") == count, result
        return result
    try:
        phrases = ("Hello!", "Thank you", "Please say that again.", "I don’t understand",
                   "Can you speak more slowly?")
        for target, hello in (("ja", "こんにちは"), ("ko", "안녕하세요"), ("zt", "你好"), ("zh", "你好")):
            for phrase in phrases:
                result = request("practice_reply", text=phrase, target=target)
                assert result["type"] == "practice_reply" and result["target"] == target, result
                assert result["method"] == "phrasebook" and result["text"], result
                assert result["pronunciation"] and result["pronunciation_scheme"], result
                assert result["pronunciation_note"].startswith("Approximate sound:"), result
                if phrase == "Hello!":
                    assert hello in result["text"], result
        missing = request("practice_reply", text="Where is the station?", target="ja")
        assert missing["type"] == "error" and "pack" in missing["message"], missing
        retry = request("practice_reply", text="Please say that again.", target="ja")
        assert retry["method"] == "phrasebook" and retry["pronunciation"], retry
        inbound = request("translate", source="auto", text="Where is the library?")
        assert inbound["type"] == "result" and not inbound["text"], inbound
        proc.stdin.close()
        assert proc.wait(timeout=15) == 0
        thread.join(5)
        assert events.get_nowait() is None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    backend = (args.app / "backend").resolve()
    check_window_filter(backend)
    print("Windows excludes a newly opened practice panel from both kinds of screen scan.")
    with tempfile.TemporaryDirectory(prefix="lt-practice-") as temp:
        count = exercise(backend, Path(temp))
        print("Fresh-install worker stdio:", count, "responses verified.")
