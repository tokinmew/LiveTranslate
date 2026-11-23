"""Build a portable Windows release from the organized app and verified offline assets."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import zipfile


BASE_SHA256 = "314614291ddc0ed893dc8ce008b97482f3630ed603c1fa126fb98da130d4ed78"
PREFIX = "LiveTranslate/"
SOURCE_PATTERNS = (
    "LiveTranslate.exe", "backend/*.py", "backend/*.gz", "ui/*.cs", "ui/*.ico",
    "scripts/*.cmd", "scripts/*.ps1", "config/*.json", "config/*.txt", "docs/*.md",
    "docs/*.txt", "ocr-tools/*.exe", "ocr-tools/*.cs", "ocr-tools/*.cmd",
    "fixture-tools/*.cs", "fixture-tools/audio/*.txt", "fixture-tools/audio/*.json",
    "quality/*.ps1", "quality/*.py", "quality/*.json", "quality/*.txt",
    "dialogue/*.py", "dialogue/*.json", "dialogue/*.md", "dialogue/*.txt",
)


def digest_stream(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def add_stream(target, info, stream):
    digest = hashlib.sha256()
    with target.open(info, "w") as out:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def build(app, base, output):
    if output.exists():
        raise FileExistsError(output)
    sources = {path.relative_to(app).as_posix(): path
               for pattern in SOURCE_PATTERNS for path in app.glob(pattern) if path.is_file()}
    required = {"LiveTranslate.exe", "ocr-tools/EnglishOcr.exe", "scripts/Prepare-Offline.ps1",
                "scripts/Start.cmd", "config/model-sources.json", "config/requirements.txt",
                "docs/README.md", "docs/START-HERE.txt", "docs/VALIDATION.md", "backend/worker.py"}
    missing = required.difference(sources)
    if missing:
        raise ValueError("Build the organized app first. Missing: " + ", ".join(sorted(missing)))
    output.parent.mkdir(parents=True, exist_ok=True)
    with base.open("rb") as baseline, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        if digest_stream(baseline) != BASE_SHA256:
            raise ValueError("Expected the verified LiveTranslate 0.6.7 Windows portable ZIP.")
        baseline.seek(0)
        made = Path(temp) / "portable.zip"
        expected = {}
        with zipfile.ZipFile(baseline) as previous, zipfile.ZipFile(made,"x",zipfile.ZIP_DEFLATED,compresslevel=6) as target:
            for info in previous.infolist():
                name = info.filename.removeprefix(PREFIX)
                if "/" not in name:
                    if name != "LiveTranslate.exe" and not any(folder + "/" + name in sources for folder in ("docs","scripts","config")):
                        raise ValueError("No organized source for previous root file " + name)
                    continue
                if name in sources or name.split("/")[0] in {"backend","ui","ocr-tools"}:
                    continue
                with previous.open(info) as stream:
                    expected[info.filename] = add_stream(target, info, stream)
            for name, path in sorted(sources.items()):
                info = zipfile.ZipInfo.from_file(path, PREFIX + name)
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as stream:
                    expected[info.filename] = add_stream(target, info, stream)
        with zipfile.ZipFile(made) as check:
            if len(expected) != len(check.infolist()) or set(check.namelist()) != set(expected):
                raise ValueError("Completed archive inventory differs.")
            for name, digest in expected.items():
                with check.open(name) as stream:
                    if digest_stream(stream) != digest:
                        raise ValueError("Mismatch for " + name)
        made.rename(output)
    print(f"Verified {len(expected)} files, one application at the root, {output.stat().st_size:,} bytes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for parameter in ("app","base","output"):
        parser.add_argument("--" + parameter, required=True, type=Path)
    args = parser.parse_args()
    build(args.app,args.base,args.output)
