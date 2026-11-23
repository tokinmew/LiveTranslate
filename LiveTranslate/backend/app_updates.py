"""Check and prepare signed updates published to the official GitHub repository."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PRODUCT = "LiveTranslate"
OFFICIAL_REPOSITORY = "https://github.com/tokinmew/LiveTranslate"
MAX_MANIFEST = 64 * 1024
MAX_PACKAGE = 8 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_FILES = 160
HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2,3}\Z")
SOURCE = re.compile(r"(?:backend/[A-Za-z][A-Za-z0-9_]*\.py|ui/[A-Za-z][A-Za-z0-9_]*\.cs|README\.md|VALIDATION\.md|START-HERE\.txt)\Z")
DEVICE = re.compile(r"(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])\Z")


def _version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Expected a three- or four-part application version.")
    parts = tuple(int(p) for p in value.split("."))
    if max(parts) > 65534:
        raise ValueError("Application version is out of range.")
    return parts + (0,) * (4 - len(parts))


def _sha(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("Invalid SHA-256 digest in update information.")
    return value.lower()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate field in update information.")
        result[key] = value
    return result


def _json(content):
    value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: _invalid_json())
    if not isinstance(value, dict):
        raise ValueError("Expected an update object.")
    return value


def _invalid_json():
    raise ValueError("Invalid JSON number in update information.")


def _read(location, limit):
    from github_releases import Asset
    if not isinstance(location, Asset):
        raise ValueError("Updates must be downloaded from official GitHub release assets.")
    return location.read(limit)


def _manifest(*, allow_unpublished=False):
    from github_releases import NoStableRelease, release
    from release_signature import verify_official_manifest
    try:
        tag_version, content, package = release(OFFICIAL_REPOSITORY, MAX_MANIFEST, MAX_PACKAGE)
    except NoStableRelease:
        if allow_unpublished:
            return None, None
        raise
    manifest = _json(content)
    # Always verify against the pinned project identity. An alternate repository
    # cannot bypass signature verification by supplying its own owner or name.
    verify_official_manifest("tokinmew/livetranslate", manifest)
    if type(manifest.get("schema")) is not int or manifest["schema"] != 1 or manifest.get("product") != PRODUCT:
        raise ValueError("This feed does not describe LiveTranslate releases.")
    version = manifest.get("version")
    _version(version)
    filename = "LiveTranslate-" + version + ".json"
    if manifest.get("package") != filename:
        raise ValueError("Unexpected package filename in release manifest.")
    size = manifest.get("size")
    if type(size) is not int or not 1 <= size <= MAX_PACKAGE:
        raise ValueError("Invalid update package size.")
    if tag_version != version or package.size != size:
        raise ValueError("GitHub release tag or asset size differs from the update manifest.")
    if package.digest and not hmac.compare_digest(package.digest, _sha(manifest.get("sha256"))):
        raise ValueError("GitHub release asset digest differs from the update manifest.")
    return {"version": version, "size": size, "sha256": _sha(manifest.get("sha256"))}, package


def check_update(installed):
    current = _version(installed)
    manifest, _ = _manifest(allow_unpublished=True)
    if manifest is None:
        return {"ok": True, "available": False, "status": "unpublished"}
    return {"ok": True, "available": _version(manifest["version"]) > current, **manifest}


def _check_package(raw, manifest):
    if len(raw) != manifest["size"] or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), manifest["sha256"]):
        raise ValueError("The downloaded package did not match the release manifest.")
    package = _json(raw)
    if package.get("version") != manifest["version"]:
        raise ValueError("The downloaded package has the wrong version.")
    records = package.get("files")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_FILES:
        raise ValueError("Invalid number of files in update.")
    files = {}
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid update file record.")
        name = record.get("path")
        if not isinstance(name, str) or len(name) > 120 or not SOURCE.fullmatch(name):
            raise ValueError("Update attempted to replace a file outside the application source.")
        key = name.casefold()
        if key in seen or DEVICE.fullmatch(Path(name).stem):
            raise ValueError("Update contains a duplicate or reserved Windows filename.")
        seen.add(key)
        value = record.get("text")
        if not isinstance(value, str):
            raise ValueError("Invalid update file content.")
        data = value.encode("utf-8")
        if len(data) > MAX_FILE or b"\0" in data:
            raise ValueError("Unexpected size or binary data in a source update.")
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), _sha(record.get("sha256"))):
            raise ValueError("Update file verification failed for " + name)
        if name.endswith(".py"):
            compile(data, name, "exec", dont_inherit=True)
        files[name] = data
    if "ui/Program.cs" not in files:
        raise ValueError("Update is missing its versioned dashboard source.")
    return files


def _file_version(path):
    if os.name != "nt":
        raise OSError("Windows is required to prepare a LiveTranslate update.")
    lib = ctypes.WinDLL("version", use_last_error=True, winmode=0x800)
    lib.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    lib.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    lib.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    lib.GetFileVersionInfoW.restype = wintypes.BOOL
    lib.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    lib.VerQueryValueW.restype = wintypes.BOOL
    size = lib.GetFileVersionInfoSizeW(str(path), None)
    if not 52 <= size <= 1024 * 1024:
        raise ValueError("Missing Windows file version on " + path.name)
    buf = ctypes.create_string_buffer(size)
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if (not lib.GetFileVersionInfoW(str(path), 0, size, buf)
            or not lib.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length))
            or not ptr.value or length.value < 52):
        raise ValueError("Unreadable Windows file version on " + path.name)
    values = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if values[0] != 0xFEEF04BD:
        raise ValueError("Invalid Windows executable version information.")
    return values[2] >> 16, values[2] & 65535, values[3] >> 16, values[3] & 65535


def _reparse(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _defender():
    platform = Path(os.environ["ProgramData"]) / "Microsoft/Windows Defender/Platform"
    candidates = []
    if platform.is_dir():
        for entry in platform.iterdir():
            match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.(\d+)-\d+", entry.name)
            if match and (entry / "MpCmdRun.exe").is_file():
                candidates.append((tuple(map(int, match.groups())), entry / "MpCmdRun.exe"))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    path = Path(os.environ["ProgramFiles"]) / "Windows Defender/MpCmdRun.exe"
    if not path.is_file():
        raise ValueError("Microsoft Defender is unavailable to scan the update.")
    return path


def _build_and_scan(root, stage, files, version):
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise ValueError("The Windows x64 .NET Framework compiler is unavailable.")
    ui = root / "ui"
    icon = ui / "LiveTranslate.ico"
    if _reparse(ui) or _reparse(icon):
        raise ValueError("Unexpected link in the dashboard source directory.")
    sources = {}
    for path in ui.glob("*.cs"):
        if _reparse(path) or not path.is_file():
            raise ValueError("Unexpected dashboard source file.")
        sources[path.name.casefold()] = path
    for name in files:
        if name.startswith("ui/"):
            sources[Path(name).name.casefold()] = stage / name
    exe = stage / "LiveTranslate.exe"
    args = [str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001",
            "/win32icon:" + str(icon), "/out:" + str(exe)]
    args.extend("/reference:" + name + ".dll" for name in
                ("System", "System.Core", "System.Drawing", "System.Windows.Forms", "System.Web.Extensions"))
    args.extend(str(sources[key]) for key in sorted(sources))
    # Keep the compiler's working directory free of installed third-party DLLs.
    compiler_result = subprocess.run(args, cwd=stage, capture_output=True, timeout=90,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
    if compiler_result.returncode:
        detail = (compiler_result.stdout + compiler_result.stderr).decode("utf-8", "replace")[:600].strip()
        raise ValueError("Dashboard compilation failed. " + detail)
    if _file_version(exe) != _version(version):
        raise ValueError("Compiled dashboard version does not match the release manifest.")
    scan = subprocess.run([str(_defender()), "-Scan", "-ScanType", "3", "-File", str(stage), "-DisableRemediation"],
                          cwd=stage, capture_output=True, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    report = (scan.stdout + scan.stderr).decode(errors="replace")
    if scan.returncode or not re.search(r"(?im)^Scanning\s+\"?" + re.escape(str(stage)) +
                                        r"\"?\s+found no threats[.!]?\s*$", report):
        raise ValueError("Microsoft Defender did not confirm that the staged update is clean.")


def prepare_update(root, installed, expected_version, expected_sha256):
    root = Path(root).resolve(strict=True)
    current = _version(installed)
    manifest, location = _manifest()
    if (manifest["version"] != expected_version
            or not hmac.compare_digest(manifest["sha256"], _sha(expected_sha256))):
        raise ValueError("The release changed after checking. Check again before installing.")
    if _version(expected_version) <= current:
        raise ValueError("Only a newer version can be installed.")
    exe = root / "LiveTranslate.exe"
    if _reparse(exe):
        raise ValueError("Unexpected link in the installed dashboard.")
    with exe.open("rb") as existing:
        baseline_hash = hashlib.file_digest(existing, "sha256").hexdigest()
    if _file_version(exe) != current:
        raise ValueError("The current installation changed. Open its dashboard and check again.")
    package = _read(location, manifest["size"])
    files = _check_package(package, manifest)
    # The three documentation names are part of the 0.6.x signed wire format.
    # The journal and its backups use real paths, so rollback never needs to
    # guess which layout was active when the update was prepared.
    if (root / "docs").is_dir() and (root / "scripts" / "Prepare-Offline.ps1").is_file():
        files = {("docs/" + name if name in {"README.md", "VALIDATION.md", "START-HERE.txt"} else name): data
                 for name, data in files.items()}
    work = root / ".livetranslate-update"
    work.mkdir(exist_ok=True)
    if _reparse(work) or not work.is_dir():
        raise ValueError("Unexpected link in the update staging folder.")
    stage = Path(tempfile.mkdtemp(dir=work, prefix="stage-"))
    published = False
    try:
        for name, data in files.items():
            target = stage / name
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
        _build_and_scan(root, stage, files, expected_version)
        if _file_version(exe) != current:
            raise ValueError("The installation changed during preparation. Check again.")
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        hashes["LiveTranslate.exe"] = hashlib.sha256((stage / "LiveTranslate.exe").read_bytes()).hexdigest()
        from update_install import publish_stage
        stage_id = publish_stage(root, stage, hashes, base_hash=baseline_hash)
        published = True
        return {"ok": True, "version": expected_version, "stage": stage_id}
    finally:
        if not published and stage.exists() and not _reparse(stage):
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare"))
    parser.add_argument("--installed", required=True)
    parser.add_argument("--version")
    parser.add_argument("--sha256")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        if args.command == "check":
            result = check_update(args.installed)
        else:
            result = prepare_update(args.root, args.installed, args.version, args.sha256)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc) or type(exc).__name__}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
