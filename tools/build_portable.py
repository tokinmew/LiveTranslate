"""Build a portable Windows release from the organized app and verified offline assets."""
import argparse
import copy
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "publisher"))
from github_publish import check_signature, load_feed, parse


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


def release_version(app):
    source = (app / "ui/Program.cs").read_text("utf-8-sig")
    match = re.search(r'\bAssemblyFileVersion\("(\d+\.\d+\.\d+)\.0"\)', source)
    if not match:
        raise ValueError("The dashboard is missing its Windows release version.")
    return match[1]


def release_feed(app, directory):
    version_text = release_version(app)
    if directory is None:
        if tuple(map(int, version_text.split("."))) != (0, 6, 9):
            return {}, []
        raise ValueError("The official signed local update feed is required for this release.")
    version, assets = load_feed(directory)
    if version != version_text:
        raise ValueError("The signed local feed and dashboard versions differ.")
    manifest = parse(assets["latest.json"])
    check_signature(manifest)
    records = parse(assets[manifest["package"]])["files"]
    published_paths = {path.relative_to(app).as_posix() for pattern in ("ui/*.cs", "backend/*.py") for path in app.glob(pattern)}
    published_paths.update(("README.md", "VALIDATION.md", "START-HERE.txt"))
    if {record["path"] for record in records} != published_paths:
        raise ValueError("The signed feed must cover the full dashboard and backend for this release.")
    return assets, records


def build(app, base, output, feed=None):
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
    assets, records = release_feed(app, feed)
    github_only = tuple(map(int, release_version(app).split("."))) >= (0, 6, 10)
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
                if github_only and name.startswith("updates/"):
                    continue
                if "/" not in name:
                    if name != "LiveTranslate.exe" and not any(folder + "/" + name in sources for folder in ("docs","scripts","config")):
                        raise ValueError("No organized source for previous root file " + name)
                    continue
                if name in sources or name.split("/")[0] in {"backend","ui","ocr-tools"}:
                    continue
                output_info = copy.copy(info)
                # A few model blocks shrink with ordinary Deflate. Already compressed
                # model streams otherwise retain their original storage method.
                if info.compress_type == zipfile.ZIP_STORED and info.file_size:
                    with previous.open(info) as stream:
                        sample = stream.read(65536)
                    if len(zlib.compress(sample,9)) < len(sample) * 0.985:
                        output_info.compress_type = zipfile.ZIP_DEFLATED
                        output_info.compress_level = 9
                with previous.open(info) as stream:
                    expected[info.filename] = add_stream(target, output_info, stream)
            for name, path in sorted(sources.items()):
                info = zipfile.ZipInfo.from_file(path, PREFIX + name)
                # The desktop installer compresses this section as a single native
                # Windows stream, sharing the signed feed's repeated source bytes.
                info.compress_type = zipfile.ZIP_STORED if assets and not github_only else zipfile.ZIP_DEFLATED
                with path.open("rb") as stream:
                    expected[info.filename] = add_stream(target, info, stream)
            for name, data in (assets.items() if not github_only else ()):
                member = PREFIX + "updates/feed/" + name
                target.writestr(member, data, compress_type=zipfile.ZIP_STORED)
                expected[member] = hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(made) as check:
            if len(expected) != len(check.infolist()) or set(check.namelist()) != set(expected):
                raise ValueError("Completed archive inventory differs.")
            for name, digest in expected.items():
                with check.open(name) as stream:
                    if digest_stream(stream) != digest:
                        raise ValueError("Mismatch for " + name)
            for record in records:
                logical = record["path"]
                physical = logical if "/" in logical else "docs/" + logical
                source = check.read(PREFIX + physical).decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
                if source != record["text"]:
                    raise ValueError("Packaged application does not match its signed full feed: " + logical)
        made.rename(output)
    print(f"Verified {len(expected)} files, one application at the root, {output.stat().st_size:,} bytes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for parameter in ("app","base","output"):
        parser.add_argument("--" + parameter, required=True, type=Path)
    parser.add_argument("--feed", type=Path, help="Directory containing the official signed manifest and cumulative release package")
    args = parser.parse_args()
    build(args.app,args.base,args.output,args.feed)
