"""Download the GUI's own models on request, then exercise the installed engines."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from audio_engine import AudioEngine
from profiles import PROFILES
from screen_engine import ScreenEngine
from text_engine import TextEngine


def log(message):
    print(message, flush=True)


def install_models(data):
    """Keep completed downloads and continue with independent assets after errors."""
    text = TextEngine(data)
    screen = ScreenEngine(data)
    audio = AudioEngine(data, lambda event: log(event.get("message", "")))
    downloads = []

    def collect(kind, language, present, install):
        record = {"kind": kind, "language": language}
        try:
            if present:
                record["status"] = "already installed"
            else:
                log(f"Downloading {kind} / {language}")
                install(language)
                record["status"] = "downloaded"
        except Exception as exc:
            record.update(status="failed", reason=str(exc))
        log(f"  {kind} / {language}: {record['status']} {record.get('reason', '')}".rstrip())
        downloads.append(record)

    text_codes = {pack["code"] for pack in text.installed()}
    catalog_error = None
    if not text.index_path.is_file() and any(p.text_language not in text_codes for p in PROFILES):
        try:
            log("Getting the text model catalog")
            text.catalog()
        except Exception as exc:
            catalog_error = str(exc)
    for profile in PROFILES:
        code = profile.text_language
        if code not in text_codes and catalog_error:
            downloads.append({"kind": "text", "language": code, "status": "failed", "reason": catalog_error})
            log(f"  Text / {code} could not download: {catalog_error}")
        else:
            collect("text", code, code in text_codes, text.install)
    ocr_codes = set(screen.local_languages())
    for profile in PROFILES:
        for code in profile.ocr_languages:
            collect("OCR", code, code in ocr_codes, screen.install_ocr_language)
    collect("speech", "base", "base" in audio.installed_models(), audio.download_model)
    return downloads


def check_models(data):
    from speech_checks import check_speech
    from visual_checks import check_ocr, check_screen_translation, check_text
    rows = []
    for kind, check in (("text", check_text), ("OCR", check_ocr), ("speech", check_speech)):
        log(f"Testing installed {kind} models")
        try:
            result = check(data)
            if not result:
                raise ValueError("No check results were returned.")
            rows.extend(result)
            if kind == "OCR":
                log("Testing screen-to-English translation from the OCR output")
                rows.extend(check_screen_translation(data, result))
        except Exception as exc:
            rows.append({"kind": kind, "language": "all", "status": "failed", "reason": str(exc)})
    return rows


def result_status(checks, downloads):
    states = Counter(row["status"] for row in checks)
    if not checks or states["failed"]:
        return "failed", 1
    if states["missing"] or any(row["status"] == "failed" for row in downloads):
        return "incomplete", 2
    if states["skipped"] or any(state != "passed" for state in states):
        return "partially tested", 3
    return "passed", 0


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8",
                                     suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(text)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def report_text(report):
    lines = ["Live Translate model test", report["started_utc"], "Overall result: " + report["status"],
             "", "Machine recognition and translation were checked using sample inputs.",
             "Compare the English output with each expected meaning. These are short functional checks."]
    if report["downloads"]:
        lines.extend(["", "Model downloads"])
    for row in report["downloads"]:
        lines.append(f"  {row['kind']} / {row['language']}: {row['status']}")
        if row.get("reason"):
            lines.append("    " + row["reason"])
    for row in report["checks"]:
        lines.extend(["", f"{row['kind']} / {row['language']}: {row['status']}"])
        for key, value in row.items():
            if key in ("kind", "language", "status") or value is None or value == "":
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"  {key.replace('_', ' ')}: {value}")
    return "\n".join(lines) + "\n"


@contextmanager
def model_lock(data):
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".model-test.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError("Another model check is using this app folder. Wait for it to finish.") from exc
        # Closing this handle releases the lock, including after an interrupted run.
        yield


def run(args):
    # Both CLI entry points report CJK source text, including with stdout piped.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    downloads = []
    start = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.download:
        try:
            downloads = install_models(args.data_dir)
        except Exception as exc:
            downloads.append({"kind": "setup", "language": "all", "status": "failed", "reason": str(exc)})
    os.environ["HF_HUB_OFFLINE"] = "1"
    checks = check_models(args.data_dir)
    status, code = result_status(checks, downloads)
    report = {"started_utc": start, "status": status, "downloads": downloads, "checks": checks}
    text = report_text(report)
    atomic_write(args.results_dir / "report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    atomic_write(args.results_dir / "report.txt", text)
    log(text)
    log("Saved model test results to " + str(args.results_dir / "report.txt"))
    return code


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download any missing app models first")
    parser.add_argument("--data-dir", type=Path, default=root / "data")
    parser.add_argument("--results-dir", type=Path, default=root / "model-test-results")
    args = parser.parse_args()
    try:
        with model_lock(args.data_dir):
            return run(args)
    except BlockingIOError as exc:
        log(str(exc))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
