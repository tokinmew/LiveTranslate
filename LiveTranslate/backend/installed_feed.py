"""Maintain the installed copy of the last authenticated local release."""
import base64
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import zlib

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_updates import MAX_MANIFEST, _json, _version
from release_signature import OFFICIAL, verify_official_manifest
from update_install import _atomic_bytes, _folder, _plain
import installed_feed_seed as seed


@dataclass
class Snapshot:
    raw: bytes
    info: dict
    package: bytes


def _identity(raw):
    info = _json(raw)
    verify_official_manifest(OFFICIAL, info)
    _version(info["version"])
    return info


def _read(path, limit):
    _plain(path)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release file is larger than expected: " + path.name)
    return data


def _validate_package(info, package):
    if len(package) != info["size"] or hashlib.sha256(package).hexdigest() != info["sha256"]:
        raise ValueError("The package differs from its signed release manifest: " + info["package"])


def _verified(path, require_local=False):
    raw = _read(path, MAX_MANIFEST)
    info = _identity(raw)
    package_path = path.with_name(info["package"])
    if require_local and not _local_file(package_path):
        raise ValueError("The release package is unavailable as a local disk file.")
    package = _read(package_path, info["size"])
    _validate_package(info, package)
    return Snapshot(raw, info, package)


def _baseline():
    info = _identity(seed.MANIFEST)
    package = zlib.decompress(base64.b64decode(seed.PACKAGE, validate=True))
    _validate_package(info, package)
    return Snapshot(seed.MANIFEST, info, package)


def _local_file(value):
    """Import only ordinary absolute disk paths. Never open a UNC, mapped share or cloud placeholder."""
    candidate = Path(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None
    if os.name == "nt":
        if (len(candidate.drive) != 2 or not candidate.drive[0].isascii() or
                not candidate.drive[0].isalpha() or candidate.drive[1] != ":" or
                any(os.path.isreserved(part) for part in candidate.parts[1:])):
            return None
        get_drive = ctypes.windll.kernel32.GetDriveTypeW
        if get_drive(ctypes.c_wchar_p(candidate.anchor)) not in (2, 3, 6):
            return None
    for item in (*reversed(candidate.parents), candidate):
        if not _plain(item, directory=item != candidate, missing=True):
            return None
        # FILE_ATTRIBUTE_OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS.
        if getattr(item.lstat(), "st_file_attributes", 0) & 0x441000:
            return None
    return candidate


def _sources(root):
    preference = root / "data" / "app-update-source.txt"
    try:
        if _local_file(preference):
            value = _read(preference, 8192).decode("utf-8-sig").strip()
            if value:
                yield value, True
    except (OSError, ValueError):
        pass
    base = os.environ.get("LOCALAPPDATA")
    if base:
        yield str(Path(base) / "LiveTranslate" / "Releases" / "latest.json"), False


@contextmanager
def _feed_lock(directory):
    # Use the same filename and native lock as tools/publish_update.py.
    path = directory / ".publish.lock"
    _plain(path, missing=True)
    with path.open("a+b") as stream:
        if os.fstat(stream.fileno()).st_nlink != 1:
            raise ValueError("The installed release lock must be a regular, unshared file.")
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        yield


def _store(manifest, snapshot):
    target = manifest.with_name(snapshot.info["package"])
    if _plain(target, missing=True):
        _validate_package(snapshot.info, _read(target, snapshot.info["size"]))
    else:
        _atomic_bytes(target, snapshot.package)
    _atomic_bytes(manifest, snapshot.raw)


def _newer(current, candidate):
    if current is None:
        return candidate
    if current.info["version"] == candidate.info["version"] and current.info["sha256"] != candidate.info["sha256"]:
        raise ValueError("Two signed snapshots supply different packages for the same release version.")
    return candidate if _version(candidate.info["version"]) > _version(current.info["version"]) else current


def _record_managed_files(root, snapshot):
    version = snapshot.info["version"]
    if version not in ("0.6.8", "0.6.9"):
        return
    support = root / ".lt-setup"
    try:
        if not _plain(support, directory=True, missing=True) or not _plain(support / "files.json", missing=True):
            return
        destination = support / f"feed-{version}.json"
        content = (json.dumps({"manifest_sha256": hashlib.sha256(snapshot.raw).hexdigest(),
                               "package_sha256": snapshot.info["sha256"]}) + "\n").encode("ascii")
        if _plain(destination, missing=True) and _read(destination, 4096) == content:
            return
        _atomic_bytes(destination, content)
    except (OSError, ValueError):
        # If uninstall metadata cannot be written, uninstall conservatively retains these files.
        pass


def _maintain(root, supplied=None):
    root = Path(root).absolute()
    _plain(root, directory=True)
    directory = _folder(_folder(root / "updates") / "feed")
    manifest = directory / "latest.json"
    with _feed_lock(directory):
        current = None
        if _plain(manifest, missing=True):
            # Surface any corruption in the installed snapshot. Never mask it with an older baseline.
            current = _verified(manifest)
        best = _newer(current, supplied) if supplied is not None else current
        migrate = None
        for value, preference in _sources(root):
            try:
                path = _local_file(value)
                if not path or path.name.casefold() != "latest.json" or path == manifest:
                    continue
                foreign = _verified(path, require_local=True)
            except (OSError, ValueError):
                # User-selected custom/unsigned feeds are valid independent settings.
                # They do not qualify to seed the official installed snapshot.
                continue
            best = _newer(best, foreign)
            version = foreign.info["version"]
            if (preference and version in ("0.6.8", "0.6.9") and
                    path.parent.name.casefold() == f"livetranslate-{version}-local-update-feed"):
                migrate = value
        if best is None or _version(best.info["version"]) < _version("0.6.8"):
            best = _newer(best, _baseline())
        if best is not current:
            _store(manifest, best)
        _record_managed_files(root, best)
        result = {"ok": True, "manifest": str(manifest), "version": best.info["version"],
                  "sha256": best.info["sha256"]}
        if migrate:
            result["migrate_source"] = migrate
        return result


def installed_snapshot(root):
    return _maintain(root)


def cache_official_snapshot(root, raw_manifest, package):
    """Remember already-downloaded release bytes only after independent verification."""
    if not isinstance(raw_manifest, bytes) or len(raw_manifest) > MAX_MANIFEST:
        raise ValueError("Invalid official release manifest size.")
    info = _identity(raw_manifest)
    if not isinstance(package, bytes):
        raise ValueError("Expected the downloaded release package bytes.")
    _validate_package(info, package)
    return _maintain(root, Snapshot(raw_manifest, info, package))


if __name__ == "__main__":
    try:
        print(json.dumps(installed_snapshot(Path(__file__).absolute().parents[1])))
    except (OSError, ValueError, zlib.error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
