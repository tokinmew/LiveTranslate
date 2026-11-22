"""Install the built-in updater into an existing prepared LiveTranslate installation."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


VERSION = "0.6.3"
PACKAGE = "LiveTranslate-0.6.3.json"
PACKAGE_SHA256 = "__LIVETRANSLATE_BUNDLED_PACKAGE_SHA256__"
MAX_PACKAGE = 8 * 1024 * 1024
HELPERS = {"backend/app_updates.py", "backend/update_install.py"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bounded_read(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Unexpected file size for " + path.name)
    return data


def seed_inputs(directory):
    manifest_blob = bounded_read(directory / "latest.json", 64 * 1024)
    manifest = json.loads(manifest_blob.decode("utf-8-sig"))
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1 or
            manifest.get("product") != "LiveTranslate" or manifest.get("version") != VERSION or
            manifest.get("package") != PACKAGE or manifest.get("sha256") != PACKAGE_SHA256 or
            type(manifest.get("size")) is not int or not 0 < manifest["size"] <= MAX_PACKAGE):
        raise ValueError("The starter release manifest does not match this installer. Extract the complete update ZIP.")
    payload = bounded_read(directory / PACKAGE, manifest["size"])
    if len(payload) != manifest["size"] or sha(payload) != PACKAGE_SHA256:
        raise ValueError("The update package is incomplete or has changed. Extract the complete update ZIP.")
    release = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(release, dict) or release.get("version") != VERSION or not isinstance(release.get("files"), list):
        raise ValueError("The update package is not a LiveTranslate 0.6.3 release.")
    helpers = {}
    for entry in release["files"]:
        if not isinstance(entry, dict) or entry.get("path") not in HELPERS:
            continue
        name = entry["path"]
        if name in helpers or not isinstance(entry.get("text"), str):
            raise ValueError("Duplicate or invalid updater component.")
        content = entry["text"].encode("utf-8")
        if sha(content) != entry.get("sha256"):
            raise ValueError("Updater component failed verification: " + name)
        helpers[name] = content
    if set(helpers) != HELPERS:
        raise ValueError("The update package is missing its installer components.")
    return manifest_blob, payload, helpers


def installed_version(exe):
    library = ctypes.WinDLL("version", use_last_error=True)
    size_of = library.GetFileVersionInfoSizeW
    size_of.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    size_of.restype = wintypes.DWORD
    get_info = library.GetFileVersionInfoW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    get_info.restype = wintypes.BOOL
    query = library.VerQueryValueW
    query.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                      ctypes.POINTER(wintypes.UINT)]
    query.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = size_of(str(exe), ctypes.byref(unused))
    if size < 52 or size > 16 * 1024 * 1024:
        raise ValueError("The installed dashboard has no readable Windows version.")
    buffer = ctypes.create_string_buffer(size)
    anchor, count = ctypes.c_void_p(), wintypes.UINT()
    if (not get_info(str(exe), 0, size, buffer) or
            not query(buffer, "\\", ctypes.byref(anchor), ctypes.byref(count)) or count.value < 52 or not anchor.value):
        raise ValueError("Could not read the installed dashboard version.")
    fields = ctypes.cast(anchor, ctypes.POINTER(wintypes.DWORD))
    if fields[0] != 0xFEEF04BD:
        raise ValueError("The installed dashboard version record is invalid.")
    major, minor = divmod(fields[2], 65536)
    build, patch = divmod(fields[3], 65536)
    if (major, minor, build, patch) not in {(0, 6, n, 0) for n in (1, 2, 3)}:
        raise ValueError("Select an existing LiveTranslate 0.6.1 or 0.6.2 installation.")
    return f"{major}.{minor}.{build}"


def install_file_if_absent(destination, data):
    # The updater is Windows-only. os.rename on the same Windows volume
    # fails if a concurrent writer has already published the destination.
    fd, name = tempfile.mkstemp(prefix=".bootstrap-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.rename(name, destination)
        except FileExistsError:
            return False
        return True
    finally:
        Path(name).unlink(missing_ok=True)


def seed_personal_feed(manifest, payload):
    releases = Path(os.environ["LOCALAPPDATA"]) / "LiveTranslate" / "Releases"
    releases.mkdir(parents=True, exist_ok=True)
    latest = releases / "latest.json"
    if os.path.lexists(latest):
        return  # Preserve the user's newer release or independently configured feed.
    package = releases / PACKAGE
    if not install_file_if_absent(package, payload):
        if sha(bounded_read(package, MAX_PACKAGE)) != PACKAGE_SHA256:
            raise ValueError("A different release with this filename already exists in " + str(releases))
    install_file_if_absent(latest, manifest)


def transaction(python, helper, root, operation, stage=None):
    args = [str(python), "-I", "-B", "-X", "utf8", str(helper), operation,
            "--root", str(root), "--parent", "0", "--no-restart"]
    if stage is not None:
        args.extend(["--stage", stage])
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        raise RuntimeError("The " + operation + " step failed. Close LiveTranslate and try again; see the message above.")


def main():
    if os.name != "nt" or len(sys.argv) != 2:
        raise ValueError("On Windows, extract the complete update and run Enable updates.cmd.")
    root = Path(sys.argv[1]).resolve(strict=True)
    exe, python = root / "LiveTranslate.exe", root / "runtime/python.exe"
    for path in (exe, python, root / "Start.cmd", root / "ui/Program.cs", root / "backend/worker.py"):
        if not path.is_file():
            raise ValueError("Select the existing prepared LiveTranslate app folder.")
    if not os.path.samefile(sys.executable, python):
        raise ValueError("Run Enable updates.cmd to use this installation's bundled runtime.")
    installed_version(exe)
    manifest, payload, helpers = seed_inputs(Path(__file__).resolve().parent)
    with tempfile.TemporaryDirectory(prefix="LiveTranslate-bootstrap-") as tempdir:
        temp = Path(tempdir)
        for path, contents in helpers.items():
            (temp / Path(path).name).write_bytes(contents)
        feed = temp / "latest.json"
        feed.write_bytes(manifest)
        (temp / PACKAGE).write_bytes(payload)
        sys.path.insert(0, str(temp))
        from app_updates import prepare_update
        helper = temp / "update_install.py"
        transaction(python, helper, root, "recover")
        installed = installed_version(exe)
        if installed != VERSION:
            print(f"Preparing the in-place update from {installed} to {VERSION}.", flush=True)
            ready = prepare_update(root, str(feed), installed, VERSION, PACKAGE_SHA256)
            if ready.get("ok") is not True or ready.get("version") != VERSION or not isinstance(ready.get("stage"), str):
                raise ValueError("The release could not be staged.")
            transaction(python, helper, root, "apply", ready["stage"])
            if installed_version(exe) != VERSION:
                raise ValueError("The dashboard version after installation was unexpected.")
    try:
        seed_personal_feed(manifest, payload)
    except (OSError, ValueError, KeyError) as exc:
        print("Updated the app. The personal release folder could not be initialized: " + str(exc),
              file=sys.stderr, flush=True)
    print("The built-in updater is installed. Opening " + str(exe), flush=True)
    subprocess.Popen([str(exe)], cwd=root, close_fds=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("LiveTranslate updater: " + str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
