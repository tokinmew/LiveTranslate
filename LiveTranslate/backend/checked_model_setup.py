"""GUI bridge to the reviewed downloader and its offline archive importer.

This module never chooses a download URL. Only the packaged, checked
scripts/Get-CheckedModels.ps1 and config/model-sources.json can supply the model files.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import threading


CHECKED_TEXT_CODES = frozenset({"zt", "zh", "ko", "ja"})
CHECKED_OCR_CODES = frozenset({"chi_tra", "chi_sim", "kor", "jpn", "jpn_vert"})
POLICY_MESSAGE = (
    "This checked edition downloads the full reviewed four-language set: "
    "Traditional Chinese, Simplified Chinese, Korean, Japanese, their OCR files, "
    "and one shared base speech model. No alternative download source is used."
)


def _redirected(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _plain_directory(root: Path, directory: Path):
    if not directory.absolute().is_relative_to(root.absolute()) or _redirected(root):
        raise RuntimeError("Checked model folders must stay inside a normal application folder.")
    current = directory
    while current != root:
        if _redirected(current):
            raise RuntimeError("Checked model folders must not be links or junctions.")
        current = current.parent


def _plain_file(root: Path, relative: str) -> Path:
    """Reject redirected package inputs before starting a download or import."""
    candidate = root / relative
    try:
        if not candidate.is_file() or _redirected(candidate):
            raise ValueError("missing or linked file")
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError("path left application folder")
        current = candidate
        while current != root:
            if _redirected(current):
                raise ValueError("redirected package path")
            current = current.parent
        return candidate
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"The checked model installer needs the original {relative}. "
            "Extract the complete checked edition into a normal writable folder."
        ) from exc


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _report_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    if path.stat().st_size > 2 * 1024 * 1024:
        raise RuntimeError("The model verification report is unexpectedly large.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_report(report_path: Path, manifest, before: str | None, started: datetime):
    if _redirected(report_path) or not report_path.is_file():
        raise RuntimeError("The checked downloader did not produce a model verification report.")
    if before is not None and _report_digest(report_path) == before:
        raise RuntimeError("The model verification report did not change. No files were imported.")
    report = _read_json(report_path)
    if not isinstance(report, dict) or report.get("status") != "verified":
        raise RuntimeError("The model verification report is incomplete. No files were imported.")
    try:
        report_started = datetime.fromisoformat(str(report["started"]).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(report["finished"]).replace("Z", "+00:00"))
        if report_started.tzinfo is None or finished.tzinfo is None:
            raise ValueError("UTC timestamps required")
        if report_started < started - timedelta(seconds=2) or finished < report_started:
            raise ValueError("stale timestamps")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("The model report does not describe this setup attempt. No files were imported.") from exc
    rows = report.get("files")
    expected = {(item["kind"], item["name"]) for item in manifest["files"]}
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or len(rows) != 13 or len(expected) != 13
            or {(row.get("kind"), row.get("name")) for row in rows if row.get("status") == "verified"} != expected):
        raise RuntimeError("Not all 13 reviewed files passed their identity and Defender checks. No files were imported.")
    return report


class CheckedModelSetup:
    def __init__(self, app_root: Path, data_dir: Path, emit, cancel_event: threading.Event,
                 process_runner=None, importer=None, lock_factory=None):
        self.app_root = Path(app_root).absolute()
        self.data_dir = Path(data_dir).absolute()
        self.emit = emit
        self.cancel_event = cancel_event
        self._runner = process_runner
        self._importer = importer
        self._lock_factory = lock_factory
        self._local_guard = threading.Lock()

    def install(self):
        if not self._local_guard.acquire(blocking=False):
            raise RuntimeError("Checked model setup is already running. Wait for it to finish.")
        try:
            self._install()
        finally:
            self._local_guard.release()

    def _install(self):
        root = self.app_root
        if self.data_dir.resolve() != (root / "data").resolve():
            raise RuntimeError("Checked models must be installed into this application's own data folder.")
        if self.cancel_event.is_set():
            raise RuntimeError("Model setup was cancelled.")
        _plain_directory(root, self.data_dir)
        _plain_file(root, "scripts/Get-CheckedModels.ps1")
        manifest_path = _plain_file(root, "config/model-sources.json")
        _plain_file(root, "backend/verify_reviewed_models.py")
        _plain_file(root, "backend/check_models.py")
        manifest = _read_json(manifest_path)
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if (not isinstance(files, list) or not all(isinstance(item, dict) for item in files)
                or len(files) != 13
                or Counter(item.get("kind") for item in files) != {"text": 4, "ocr": 5, "speech": 4}):
            raise RuntimeError("The reviewed model manifest must contain four text archives, five OCR files, and four speech files.")

        # Imports here load only local Python glue. Neither call loads model
        # weights; the installer must finish verification first.
        importer = self._importer
        if importer is None:
            importer = importlib.import_module("verify_reviewed_models").import_archives
        lock_factory = self._lock_factory
        if lock_factory is None:
            lock_factory = importlib.import_module("check_models").model_lock
        runner = self._runner
        if runner is None:
            runner = importlib.import_module("checked_process").run_checked_powershell

        results = root / "model-test-results"
        _plain_directory(root, results)
        results.mkdir(parents=True, exist_ok=True)
        report_path = results / "model-file-checks.json"
        self.emit(POLICY_MESSAGE)
        with lock_factory(self.data_dir):
            before = _report_digest(report_path)
            started = datetime.now(timezone.utc)
            self.emit("Checking pinned identities and scanning model files with Microsoft Defender...")
            runner(root, self.emit, self.cancel_event)
            if self.cancel_event.is_set():
                raise RuntimeError("Model setup was cancelled before import.")
            _verified_report(report_path, manifest, before, started)
            self.emit("All 13 files passed verification. Importing the verified local text archives...")
            # The importer hashes each input again against the current scan
            # report and preserves any conflicting existing installed pack.
            os.environ["HF_HUB_OFFLINE"] = "1"
            importer(root, self.data_dir, results)
            if self.cancel_event.is_set():
                raise RuntimeError("Model setup was cancelled. Verified files were kept for retry.")
            self.emit("All four reviewed language profiles are installed. Capture remains off until you enable it.")

