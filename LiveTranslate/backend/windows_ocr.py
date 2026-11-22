"""Read local Windows OCR language packs and word bounds without writing a screenshot."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import struct
import subprocess
import threading
import time

from ocr_guard import Word

# Fixed program text. The source tag and pixels travel through a binary pipe,
# never through command arguments, the clipboard or temporary image files.
_SETUP = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$ocr = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
"""
_LIST = _SETUP + r"""
foreach ($item in $ocr::AvailableRecognizerLanguages) { [Console]::WriteLine($item.LanguageTag) }
"""
_OPEN = _SETUP + r"""
$reader = [IO.BinaryReader]::new([Console]::OpenStandardInput())
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$resultType = [Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$awaitResult = $asTask.MakeGenericMethod($resultType)
$loadedTag = ''
"""
_FRAME = r"""
$tag = [Text.Encoding]::ASCII.GetString($reader.ReadBytes($reader.ReadByte()))
$w = $reader.ReadInt32()
$h = $reader.ReadInt32()
if ($w -lt 1 -or $h -lt 1 -or $w -gt $ocr::MaxImageDimension -or $h -gt $ocr::MaxImageDimension -or [long]$w*$h -gt 6000000) { exit 3 }
if ($loadedTag -ne $tag) {
    $lang = $ocr::AvailableRecognizerLanguages | Where-Object LanguageTag -eq $tag | Select-Object -First 1
    if (!$lang) { exit 2 }
    $engine = $ocr::TryCreateFromLanguage($lang)
    if (!$engine) { exit 2 }
    $loadedTag = $tag
}
$bitmap = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics,ContentType=WindowsRuntime]::new([Windows.Graphics.Imaging.BitmapPixelFormat]::Gray8,$w,$h,[Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)
$bytes = $reader.ReadBytes($w*$h)
if ($bytes.Length -ne $w*$h) { exit 3 }
$bitmap.CopyFromBuffer([System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions]::AsBuffer($bytes))
$task = $awaitResult.Invoke($null,@($engine.RecognizeAsync($bitmap)))
$result = $task.GetAwaiter().GetResult()
$lineIndex = 0
$count = 0
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        if (++$count -gt 10000) { exit 3 }
        if ($word.Text.Length -gt 256 -or $word.Text -match '[\x00-\x1f]') { continue }
        $b = $word.BoundingRect
        [Console]::WriteLine(('{0}{5}{1}{5}{2}{5}{3}{5}{4}{5}{6}' -f $lineIndex, [int][math]::Floor($b.Left), [int][math]::Floor($b.Top), [int][math]::Ceiling($b.Right), [int][math]::Ceiling($b.Bottom), [char]9, $word.Text))
    }
    $lineIndex++
}
$bitmap.Dispose()
$result = $null
$task = $null
$bytes = $null
"""
_READ = _OPEN + _FRAME
_WATCH = _OPEN + "\nwhile ($true) {\n" + _FRAME + "\n[Console]::WriteLine('END')\n}\n"
_TAG = re.compile(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*\Z")


def _command(command):
    # Use the system binary even when the working folder or PATH contains an
    # unrelated executable called powershell.exe.
    host = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return [str(host), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]


def _run(command, data, timeout):
    return subprocess.run(_command(command),
                          input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _pack_code(tag):
    from language_catalog import NLLB_TAGS, canonical_code
    from language_routes import ocr_code
    parts = tag.lower().split("-")
    if parts[0] == "zh":
        return "chi_tra" if any(part in {"hant", "tw", "hk", "mo"} for part in parts) else "chi_sim"
    source = canonical_code("-".join(parts[:2]))
    if not ocr_code(source):
        source = canonical_code(parts[0])
    script = next((p for p in parts[1:] if len(p) == 4 and p.isalpha()), "")
    model_script = NLLB_TAGS.get(source, "").partition("_")[2].lower()
    if script and model_script and script != model_script:
        return ""
    return ocr_code(source)


class WindowsWatch:
    """Keep one Windows OCR engine warm until its watcher stops."""
    def __init__(self):
        self.process = None

    def close(self):
        process, self.process = self.process, None
        if process:
            process.kill()
            process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()

    def frame(self, data):
        if self.process is None:
            self.process = subprocess.Popen(_command(_WATCH), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = self.process
        output = bytearray()
        complete = False

        def exchange():
            nonlocal complete
            try:
                process.stdin.write(data)
                process.stdin.flush()
                while len(output) < 2 * 1024 * 1024:
                    line = process.stdout.readline(2048)
                    if not line:
                        return
                    if line.rstrip(b"\r\n") == b"END":
                        complete = True
                        return
                    output.extend(line)
            except (OSError, ValueError):
                pass

        # Bound a blocked anonymous pipe as well as the native OCR operation.
        thread = threading.Thread(target=exchange, daemon=True)
        thread.start()
        thread.join(8)
        if not complete:
            self.close()
            thread.join(1)
            raise RuntimeError("The installed Windows OCR reader did not finish the frame.")
        return bytes(output)


class WindowsOCR:
    def __init__(self):
        self._packs = {}
        self._expires = 0.

    def packs(self):
        if os.name != "nt":
            return {}
        now = time.monotonic()
        if now >= self._expires:
            packs = {}
            try:
                process = _run(_LIST, b"", 5)
                if process.returncode == 0:
                    for tag in process.stdout.decode("utf-8-sig").splitlines():
                        if _TAG.fullmatch(tag):
                            code = _pack_code(tag)
                            if code:
                                packs.setdefault(code, tag)
            except (OSError, UnicodeError, subprocess.TimeoutExpired):
                pass
            self._packs = packs
            self._expires = now + (60 if packs else 10)
        return self._packs.copy()

    def read(self, image, tag, watcher=None):
        if not _TAG.fullmatch(tag):
            raise ValueError("Invalid Windows OCR language tag.")
        from PIL import Image
        ratio = min(1, 3072 / max(image.size), math.sqrt(6000000 / (image.width * image.height)))
        scaled = image if ratio == 1 else image.resize(tuple(max(1, round(n * ratio)) for n in image.size),
                                                        Image.Resampling.LANCZOS)
        bits = tag.encode("ascii")
        data = bytes([len(bits)]) + bits + struct.pack("<ii", *scaled.size) + scaled.convert("L").tobytes()
        try:
            if watcher is None:
                result = _run(_READ, data, 8)
                if result.returncode:
                    raise RuntimeError("Windows could not read the frame using its installed OCR language.")
                output = result.stdout
            else:
                output = watcher.frame(data)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("The installed Windows OCR reader did not respond.") from exc
        if len(output) > 2 * 1024 * 1024:
            raise RuntimeError("Windows could not read the frame using its installed OCR language.")
        sx, sy = image.width / scaled.width, image.height / scaled.height
        words = []
        for row in output.decode("utf-8-sig").splitlines():
            fields = row.split("\t", 5)
            if len(fields) != 6:
                continue
            line, left, top, right, bottom = map(int, fields[:5])
            if 0 <= left < right <= scaled.width and 0 <= top < bottom <= scaled.height:
                box = (math.floor(sx * left), math.floor(sy * top), math.ceil(sx * right), math.ceil(sy * bottom))
                words.append(Word(fields[5], box, 100, (str(line),)))
        return words
