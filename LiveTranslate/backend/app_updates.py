"""Check and prepare a LiveTranslate source update from a configured feed."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


PRODUCT = "LiveTranslate"
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("The update server redirected the request. Configure its final HTTPS manifest URL.")


def _feed_location(feed):
    if not isinstance(feed, str) or not feed or any(ord(ch) < 32 for ch in feed):
        raise ValueError("Choose an HTTPS manifest URL or an absolute path to a local manifest.")
    if Path(feed).is_absolute() and not feed.startswith("//"):
        if os.name == "nt" and feed.replace("/", "\\").startswith(("\\\\.\\", "\\\\?\\")):
            raise ValueError("Use a regular local file or a shared folder for the update feed.")
        path = Path(feed)
        if path.is_dir():
            path = path / "latest.json"
        if not path.is_file() or _reparse(path):
            raise ValueError("The local update manifest does not exist.")
        return path.resolve(strict=True)
    parts = urllib.parse.urlsplit(feed)
    # Relative package names are appended to this exact directory. Query strings,
    # credentials and encoded separators would make that authority ambiguous.
    loopback = parts.scheme.lower() == "http" and parts.hostname == "127.0.0.1"
    if ((parts.scheme.lower() != "https" and not loopback) or not parts.hostname or not parts.netloc
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or "\\" in feed
            or not parts.path.startswith("/") or parts.path.endswith("/")
            or not parts.path.lower().endswith(".json")):
        raise ValueError("Choose an HTTPS manifest, a local file, or an explicit 127.0.0.1 release server.")
    port = parts.port
    if port == 0 or (loopback and parts.netloc not in
                     {"127.0.0.1", "127.0.0.1:" + str(port)}):
        raise ValueError("Invalid release-server port or loopback address.")
    for segment in parts.path.split("/")[1:]:
        decoded = urllib.parse.unquote(segment)
        if (not segment or decoded in (".", "..") or "/" in decoded or "\\" in decoded
                or "%" in decoded or any(ord(ch) < 32 for ch in decoded)):
            raise ValueError("Invalid directory in update URL.")
    return parts.geturl()


def _read(location, limit):
    if isinstance(location, Path):
        if not location.is_file() or _reparse(location):
            raise ValueError("The configured release file is missing or is a link.")
        with location.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Update file exceeds the expected size.")
        return data
    request = urllib.request.Request(location, headers={"User-Agent": "LiveTranslate-Updater/1",
                                                        "Accept-Encoding": "identity"})
    handlers = [_NoRedirect()]
    if urllib.parse.urlsplit(location).scheme == "http":
        if urllib.parse.urlsplit(location).hostname != "127.0.0.1":
            raise ValueError("Plain HTTP is only allowed for a loopback update server.")
        # Never send a local release request to a system-configured proxy.
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    deadline = time.monotonic() + 90
    output = bytearray()
    with opener.open(request, timeout=12) as response:
        if response.status != 200 or response.geturl() != location:
            raise ValueError("The update server did not return the requested file.")
        encoding = response.headers.get("Content-Encoding", "identity").lower()
        if encoding != "identity":
            raise ValueError("Unexpected encoding from update server.")
        declared = response.headers.get("Content-Length")
        if declared is not None and not 0 <= int(declared) <= limit:
            raise ValueError("Update file exceeds the expected size.")
        while len(output) <= limit:
            if time.monotonic() > deadline:
                raise TimeoutError("The update download took too long.")
            # read1 returns as data arrives, so a slow streaming peer cannot
            # postpone the total deadline by dribbling bytes into one read.
            chunk = response.read1(min(65536, limit + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        if len(output) > limit or (declared is not None and int(declared) != len(output)):
            raise ValueError("The update download was incomplete or exceeded its limit.")
    return bytes(output)


@contextmanager
def _active_feed(feed, serve_local):
    """Host a designated local feed only for this operation's lifetime."""
    if not serve_local:
        yield feed
        return
    manifest = _feed_location(feed)
    if not isinstance(manifest, Path) or manifest.name.casefold() != "latest.json":
        raise ValueError("The managed local server needs a local latest.json manifest.")
    server = Path(__file__).resolve().with_name("release_server.py")
    if not server.is_file() or _reparse(server):
        raise ValueError("The built-in release server is missing from this installation.")
    args = [sys.executable, "-I", "-B", "-X", "utf8", str(server), "--root", str(manifest.parent),
            "--bind", "127.0.0.1", "--port", "0", "--parent-pipe", "--quiet"]
    # Keeping stdin open is a lease: if this updater process dies, the OS
    # closes the pipe and the child shuts itself down even without a finally.
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
        response = queue.Queue(maxsize=1)

        def read_ready():
            try:
                response.put(child.stdout.readline(1025))
            except (OSError, ValueError):
                response.put(b"")

        try:
            threading.Thread(target=read_ready, name="release-server-ready", daemon=True).start()
            try:
                line = response.get(timeout=10)
            except queue.Empty:
                raise ValueError("The local release server did not start in time.") from None
            if not line.endswith(b"\n") or len(line) > 1024:
                raise ValueError("The local release server did not return a listening address.")
            record = _json(line)
            url = record.get("url")
            if (record.get("ready") is not True or not isinstance(url, str)
                    or not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}/latest\.json", url)):
                raise ValueError("The local release server returned an invalid listening address.")
            yield _feed_location(url)
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)


def _manifest(feed):
    location = _feed_location(feed)
    manifest = _json(_read(location, MAX_MANIFEST))
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
    if isinstance(location, Path):
        package = location.parent / filename
        if package.resolve().parent != location.parent:
            raise ValueError("Update package is outside the selected feed folder.")
    else:
        package = location.rsplit("/", 1)[0] + "/" + filename
    return {"version": version, "size": size, "sha256": _sha(manifest.get("sha256"))}, package


def check_update(feed, installed):
    current = _version(installed)
    manifest, _ = _manifest(feed)
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


def prepare_update(root, feed, installed, expected_version, expected_sha256):
    root = Path(root).resolve(strict=True)
    current = _version(installed)
    manifest, location = _manifest(feed)
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
    files = _check_package(_read(location, manifest["size"]), manifest)
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
    parser.add_argument("--feed", required=True)
    parser.add_argument("--installed", required=True)
    parser.add_argument("--version")
    parser.add_argument("--sha256")
    parser.add_argument("--serve-local", action="store_true",
                        help="start the bundled loopback release server for a local latest.json feed")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        with _active_feed(args.feed, args.serve_local) as feed:
            if args.command == "check":
                result = check_update(feed, args.installed)
            else:
                result = prepare_update(args.root, feed, args.installed, args.version, args.sha256)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc) or type(exc).__name__}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
