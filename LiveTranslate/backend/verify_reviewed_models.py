"""Import the reviewed text archives, then run the app's real offline model checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import zipfile

from check_models import model_lock, run
from text_engine import TextEngine, _safe_members


def file_digest(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def existing_pack_matches(folder, archive_path):
    """A prior installation is reusable only if it exactly matches the scanned ZIP."""
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_members(archive)
        roots = [PurePosixPath(m.filename).parent for m in members
                 if PurePosixPath(m.filename).name == "metadata.json"]
        if len(roots) != 1:
            return False
        names = set()
        for item in members:
            if item.is_dir():
                continue
            relative = PurePosixPath(item.filename).relative_to(roots[0]).as_posix()
            names.add(relative)
            local = folder / relative
            if not local.is_file() or not local.resolve().is_relative_to(folder.resolve()):
                return False
            if local.stat().st_size != item.file_size:
                return False
            with local.open("rb") as candidate, archive.open(item) as expected:
                if file_digest(candidate) != file_digest(expected):
                    return False
        return names == {p.relative_to(folder).as_posix()
                         for p in folder.rglob("*") if p.is_file()}


def import_archives(root, data, results):
    manifest = json.loads((root / "config" / "model-sources.json").read_text(encoding="utf-8-sig"))
    report = json.loads((results / "model-file-checks.json").read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict) or report.get("status") != "verified":
        raise RuntimeError("Model file checks are incomplete. Run scripts/Download and test models.cmd first.")
    rows = report.get("files", [])
    verified = {(r["kind"], r["name"]) for r in rows if r.get("status") == "verified"}
    expected = {(r["kind"], r["name"]) for r in manifest["files"]}
    if (len(manifest["files"]) != 13 or len(expected) != 13 or
            verified != expected or len(rows) != len(expected)):
        raise RuntimeError("Model file checks are incomplete. Run scripts/Download and test models.cmd first.")
    engine = TextEngine(data)
    for entry in manifest["files"]:
        kind = entry["kind"]
        name = entry["name"]
        if Path(name).name != name:
            raise ValueError("Invalid filename in model manifest.")
        if kind == "ocr":
            path = data / "tessdata" / name
        elif kind == "speech":
            path = data / "speech" / "base" / name
        else:
            path = data / "reviewed-packs" / name
        # Bind the copy about to be used to the bytes in the current scan log.
        passed = next(r for r in rows if r["kind"] == kind and r["name"] == name)
        with path.open("rb") as stream:
            sha = file_digest(stream)
        if sha != passed["sha256"].lower() or (entry.get("sha256") and sha != entry["sha256"].lower()):
            raise ValueError(f"{name} changed after its verification. Run the file checks again.")
        if kind == "text":
            code = entry["language"]
            target = engine.pack_dir / (code + "_en")
            if target.exists():
                if not existing_pack_matches(target, path):
                    raise ValueError(f"The installed {code} files differ from the verified archive. "
                                     "Use a fresh app folder to preserve both copies.")
            else:
                engine.import_pack(path, expected_code=code)
            if engine._packs()[code][0].resolve() != target.resolve():
                raise ValueError(f"Multiple {code} packs conflict. Use a fresh app folder.")


def main():
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    results = root / "model-test-results"
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        with model_lock(data):
            import_archives(root, data, results)
            return run(argparse.Namespace(data_dir=data, results_dir=results, download=False))
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
        print("Model import or verification stopped: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
