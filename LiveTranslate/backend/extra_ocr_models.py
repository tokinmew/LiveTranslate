"""Reviewed app-local German, Italian and Spanish OCR data.

The source is the same official Tesseract fast release pinned by the starter
language installer. Nothing is installed into Windows language packs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import os
import subprocess
import tempfile
import urllib.request

from checked_model_setup import _plain_directory, _plain_file

COMMIT = "65727574dfcd264acbb0c3e07860e4e9e9b22185"
# SHA-256 verified against downloaded bytes and Git blob identities published in
# https://api.github.com/repos/tesseract-ocr/tessdata_fast/git/trees/<COMMIT>
MODELS = (
    ("deu", 1525436, "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d", "97ed7b2b60f2771c07040660ef0f6daf596dc7bf"),
    ("ita", 2701314, "b8f89e1e785118dac4d51ae042c029a64edb5c3ee42ef73027a6d412748d8827", "edbffbe0e51892b240630b5eeabededa7e7c9c4f"),
    ("spa", 2294433, "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464", "72e901f13ca52cfe34cf239a368b9ed3c0ddaf26"),
)
SCAN_SHA256 = "91e74a878f18d40334c9026a58492abdc3e690d72699bef7a7ca475412c04bd9"


def _verified(path, model):
    _, size, sha256, blob = model
    if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
        return False
    payload = path.read_bytes()
    return (hashlib.sha256(payload).hexdigest() == sha256 and
            hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0" + payload).hexdigest() == blob)


def _scan(root, path):
    scan = _plain_file(root, "quality/scan.ps1")
    if hashlib.sha256(scan.read_bytes()).hexdigest() != SCAN_SHA256:
        raise ValueError("The reviewed model scanner is missing or changed. Restore the original application package.")
    shell = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(scan), "-File", str(path)], cwd=root,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=180)
    if result.returncode:
        raise ValueError("Windows Defender did not approve an OCR model. No replacement was installed.")


def install(root, offline=False):
    """Verify/install all three models, returning zero only after identity/scan checks."""
    root = Path(root).absolute()
    target = root / "data/tessdata"
    staging = root / ".lt-setup/extra-ocr"
    _plain_directory(root, target)
    _plain_directory(root, staging)
    for model in MODELS:
        path = target / (model[0] + ".traineddata")
        if path.exists():
            _plain_file(root, str(path.relative_to(root)))
    pending = [model for model in MODELS if not _verified(target / (model[0] + ".traineddata"), model)]
    if not pending:
        print("German, Italian and Spanish OCR files are verified.", flush=True)
        return 0
    if offline:
        raise ValueError("German, Italian and Spanish OCR files are not all installed. Run this setup online once.")
    target.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reviewed-", dir=staging) as folder:
        stage = Path(folder)
        for model in pending:
            code, size, _, _ = model
            path = stage / (code + ".traineddata")
            url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/" + COMMIT + "/" + path.name
            print("Downloading reviewed " + code + " OCR data...", flush=True)
            with urllib.request.urlopen(url, timeout=30) as response, path.open("xb") as output:
                total = 0
                while True:
                    block = response.read(min(65536, size + 1 - total))
                    if not block:
                        break
                    total += len(block)
                    if total > size:
                        raise ValueError("The " + code + " OCR download exceeded its reviewed size.")
                    output.write(block)
            if not _verified(path, model):
                raise ValueError("The " + code + " OCR download failed identity verification. No replacement was installed.")
            _scan(root, path)
        # Verify the entire pending set before replacing any existing model.
        for model in pending:
            path = stage / (model[0] + ".traineddata")
            _plain_directory(root, target)
            destination = target / path.name
            if destination.exists():
                _plain_file(root, str(destination.relative_to(root)))
            os.replace(path, destination)
    print("German, Italian and Spanish OCR files are ready in this application.", flush=True)
    return 0
