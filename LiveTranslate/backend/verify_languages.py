r"""Real-model acceptance checks; translation inference is never mocked.

Run with the application's Python after Setup.cmd. Default: installed local
packs only, network blocked during checks. --download explicitly fetches any
missing packs from the official index before the offline acceptance checks.

Examples from the app folder:
  runtime\python.exe backend\verify_languages.py
  runtime\python.exe backend\verify_languages.py --download
  runtime\python.exe backend\verify_languages.py --import-pack path\ja.argosmodel

Exit 0: all real models produced plausible English and routing matched these
examples. Exit 1: a runtime/model/routing check failed. Exit 2: packs absent.
Human review of the printed translations is required to evaluate quality.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

from text_engine import TextEngine


CASES = {
    "zt": "\u6211\u60f3\u5b78\u7fd2\u5982\u4f55\u4f7f\u7528\u9019\u500b\u7a0b\u5f0f\uff0c\u8acb\u5c07\u9019\u6bb5\u6587\u5b57\u7ffb\u8b6f\u6210\u82f1\u6587\u3002",
    "zh": "\u6211\u60f3\u5b66\u4e60\u5982\u4f55\u4f7f\u7528\u8fd9\u4e2a\u7a0b\u5e8f\uff0c\u8bf7\u5c06\u8fd9\u6bb5\u6587\u5b57\u7ffb\u8bd1\u6210\u82f1\u6587\u3002",
    "ko": "\uc774 \ud504\ub85c\uadf8\ub7a8\uc744 \uc0ac\uc6a9\ud558\ub294 \ubc29\ubc95\uc744 \ubc30\uc6b0\uace0 \uc2f6\uc2b5\ub2c8\ub2e4. \uc774 \ubb38\uc7a5\uc744 \uc601\uc5b4\ub85c \ubc88\uc5ed\ud574 \uc8fc\uc138\uc694.",
    "ja": "\u3053\u306e\u30d7\u30ed\u30b0\u30e9\u30e0\u306e\u4f7f\u3044\u65b9\u3092\u5b66\u3073\u305f\u3044\u3067\u3059\u3002\u3053\u306e\u6587\u7ae0\u3092\u82f1\u8a9e\u306b\u7ffb\u8a33\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--download", action="store_true", help="Explicitly download missing language packs")
    parser.add_argument("--import-pack", action="append", default=[], help="Import an existing .argosmodel; repeat as needed")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    engine = TextEngine(args.data_dir)
    for path in args.import_pack:
        engine.import_pack(path)
    installed = {row["code"] for row in engine.installed()}
    if args.download:
        engine.catalog()
        for code in CASES:
            if code not in installed:
                print("Downloading " + code + " -> English...", file=sys.stderr, flush=True)
                engine.install(code)
        installed = {row["code"] for row in engine.installed()}
    missing = sorted(set(CASES) - installed)
    if missing:
        print(json.dumps({"status": "not_run", "reason": "Missing real language packs", "missing": missing,
                          "action": "Install/import all four packs, or explicitly run with --download."}))
        return 2
    versions = {}
    for name in ("ctranslate2", "sentencepiece", "numpy", "py3langid", "opencc-python-reimplemented"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    report = {"status": "passed", "versions": versions, "cases": [],
              "quality_review": "Human review of English output is required."}
    with patch("urllib.request.urlopen", side_effect=AssertionError("Offline check attempted network access")), \
         patch("socket.create_connection", side_effect=AssertionError("Offline check attempted network access")):
        for code, text in CASES.items():
            row = {"source": code, "input": text}
            try:
                folder, meta = engine._packs()[code]
                row["pack"] = {"version": meta.get("package_version"), "tokenizer": "SentencePiece",
                               "has_config_json": (folder / "model" / "config.json").is_file(),
                               "model_files": sorted(p.name for p in (folder / "model").iterdir() if p.is_file())}
                result = engine.translate(text, code)
                detected = engine._detect(text)
                row.update(output=result["text"], detected=detected)
                row["passed"] = (detected == code and result["text"] != text
                                 and len(re.findall(r"[A-Za-z]", result["text"])) >= 10
                                 and not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]", result["text"]))
            except Exception as exc:
                row.update(passed=False, error=str(exc))
            report["cases"].append(row)
        english = "This English text must stay unchanged."
        report["english_passthrough"] = "passed" if engine.translate(english, "en")["text"] == english else "failed"
    if not all(x["passed"] for x in report["cases"]) or report["english_passthrough"] != "passed":
        report["status"] = "failed"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
