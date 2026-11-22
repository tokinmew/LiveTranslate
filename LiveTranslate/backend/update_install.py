"""Install a verified incremental LiveTranslate release and recover interrupted writes."""
import argparse
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

_STATE = ".livetranslate-update"
_JOURNAL = "transaction.json"
_EXE = "LiveTranslate.exe"
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[a-f0-9]{32}\Z")
_PATH = re.compile(r"(?:backend/[A-Za-z0-9_]{1,80}\.py|ui/[A-Za-z0-9_]{1,80}\.cs|README\.md|VALIDATION\.md|START-HERE\.txt|LiveTranslate\.exe)\Z", re.ASCII)
_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1,10)), *(f"lpt{i}" for i in range(1,10))}
_MAX_TOTAL = 64 * 1024 * 1024


def _plain(path, directory=False, missing=False):
    """Reject junctions, symlinks and special files below the installation."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        if missing:
            return False
        raise
    if (getattr(st, "st_file_attributes", 0) & 0x400 or
            not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))):
        raise ValueError("Unexpected file type at " + str(path))
    return True


def _folder(path):
    if not _plain(path, directory=True, missing=True):
        path.mkdir(exist_ok=True)
        _plain(path, directory=True)
    return path


def _file(root, rel, missing=False):
    if not isinstance(rel, str) or not _PATH.fullmatch(rel) or Path(rel).stem.lower() in _DEVICES:
        raise ValueError("Unsupported application update path.")
    p = root / rel
    _plain(p.parent, directory=True)
    _plain(p, missing=missing)
    return p


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _atomic_bytes(path, data):
    _plain(path, missing=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _write_json(path, value):
    _atomic_bytes(path, json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def _read_json(path):
    _plain(path)
    if path.stat().st_size > 128 * 1024:
        raise ValueError("The update receipt is too large.")
    return json.loads(path.read_text("utf8"))


def _replace_copy(source, destination, expected):
    """Keep backups reusable until the journal says the entire install is complete."""
    _plain(source)
    _plain(destination, missing=True)
    fd, name = tempfile.mkstemp(prefix=".lt-write-", dir=destination.parent)
    try:
        h = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, source.open("rb") as src:
            while data := src.read(256 * 1024):
                out.write(data)
                h.update(data)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != expected:
            raise ValueError("Update file failed its SHA-256 check: " + source.name)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def _validate_files(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 256 or _EXE not in files:
        raise ValueError("Invalid update inventory.")
    seen = set()
    for rel, digest in files.items():
        if (not isinstance(rel, str) or not _PATH.fullmatch(rel) or Path(rel).stem.lower() in _DEVICES or
                rel.casefold() in seen or not isinstance(digest, str) or not _HASH.fullmatch(digest)):
            raise ValueError("Invalid update inventory entry.")
        seen.add(rel.casefold())


def publish_stage(root, stage, files, base_hash=None):
    root = Path(root).resolve(strict=True)
    state = _folder(root / _STATE)
    stage = Path(stage).absolute()
    if stage.parent != state or not re.fullmatch(r"stage-[A-Za-z0-9_-]{1,80}", stage.name):
        raise ValueError("Unexpected staging directory.")
    _plain(stage, directory=True)
    _validate_files(files)
    size = 0
    for rel, expected in files.items():
        path = _file(stage, rel)
        size += path.stat().st_size
        if size > _MAX_TOTAL or _digest(path) != expected:
            raise ValueError("Prepared release failed verification.")
    token = uuid.uuid4().hex
    current = _digest(_file(root,_EXE))
    if base_hash is not None and current != base_hash:
        raise RuntimeError("The installed version changed during preparation. Check for updates again.")
    receipt = {"id": token, "base": current, "files": dict(files)}
    _write_json(stage / "stage-receipt.json", receipt)
    stage.rename(state / ("candidate-" + token))
    _prune_old_candidates(state)
    return token


def _receipt(state, token):
    if not isinstance(token,str) or not _ID.fullmatch(token):
        raise ValueError("Invalid update selection.")
    staged = state / ("candidate-" + token)
    _plain(staged, directory=True)
    receipt = _read_json(staged / "stage-receipt.json")
    if receipt.get("id") != token or not _HASH.fullmatch(str(receipt.get("base",""))):
        raise ValueError("Invalid update receipt.")
    _validate_files(receipt.get("files"))
    return staged, receipt


@contextlib.contextmanager
def _writer(state):
    lock_path = state / "install.lock"
    _plain(lock_path, missing=True)
    with lock_path.open("a+b") as fh:
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError("Another LiveTranslate update is already running.") from exc
        yield  # Closing the file releases the native lock, including after a crash.


def _prune_old_candidates(state):
    # Prepared downloads can outlive a closed update window. A writer or
    # recovery journal takes precedence, and recent prepared updates stay valid.
    try:
        with _writer(state):
            if (state / _JOURNAL).exists():
                return
            cutoff = time.time() - 7 * 86400
            for path in state.iterdir():
                if (re.fullmatch(r"candidate-[a-f0-9]{32}", path.name) and
                        _plain(path, directory=True) and path.stat().st_mtime < cutoff):
                    shutil.rmtree(path)
    except (OSError, ValueError):
        pass


def _win():
    return ctypes.WinDLL("kernel32", use_last_error=True)


@contextlib.contextmanager
def _run_gate(root):
    """Windows forms hold a shared handle while running. Take exclusive access."""
    if os.name != "nt":
        yield
        return
    path = root / _STATE / "run.lock"
    _plain(path, missing=True)
    api = _win()
    api.CreateFileW.argtypes = (wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
    api.CreateFileW.restype = wintypes.HANDLE
    handle = api.CreateFileW(str(path), 0x80000000, 0, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Close the other LiveTranslate window, then try again.")
    try:
        yield
    finally:
        api.CloseHandle(wintypes.HANDLE(handle))


def _process_image(api, handle):
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    if not api.QueryFullProcessImageNameW(wintypes.HANDLE(handle),0,buf,ctypes.byref(size)):
        return None
    return os.path.normcase(os.path.realpath(buf.value))


@contextlib.contextmanager
def _parent(root, pid):
    if not pid:
        yield None
        return
    if os.name != "nt" or pid <= 0 or pid > 0xffffffff:
        raise ValueError("Invalid dashboard process.")
    api = _win()
    api.OpenProcess.restype = wintypes.HANDLE
    handle = api.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        raise OSError("The dashboard closed before the update could start.")
    try:
        if _process_image(api,handle) != os.path.normcase(os.path.realpath(root / _EXE)):
            raise OSError("The selected dashboard is from a different installation.")
        yield handle
    finally:
        api.CloseHandle(wintypes.HANDLE(handle))


def _wait_exit(handle):
    if handle and _win().WaitForSingleObject(wintypes.HANDLE(handle), 45000) != 0:
        raise TimeoutError("The dashboard did not close in time.")


def _check_running(root, parent, workers=False):
    """Older dashboards predate run.lock; check only matching app/runtime processes."""
    if os.name != "nt":
        return
    class Entry(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("usage",wintypes.DWORD),("pid",wintypes.DWORD),
                    ("heap",ctypes.c_size_t),("mod",wintypes.DWORD),("threads",wintypes.DWORD),
                    ("ppid",wintypes.DWORD),("priority",wintypes.LONG),("flags",wintypes.DWORD),
                    ("name",wintypes.WCHAR * 260)]
    api = _win()
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.OpenProcess.restype = wintypes.HANDLE
    h = api.CreateToolhelp32Snapshot(2,0)
    if h == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    snap = wintypes.HANDLE(h)
    targets = {_EXE.casefold():os.path.normcase(os.path.realpath(root / _EXE))}
    if workers and parent:
        targets["python.exe"] = os.path.normcase(os.path.realpath(root / "runtime/python.exe"))
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = api.Process32FirstW(snap,ctypes.byref(entry))
        while more:
            exe = entry.name.casefold()
            # The dashboard launches its worker directly. Its verified process
            # handle remains open throughout apply, protecting its PID identity.
            # The update server can use the same interpreter independently.
            own = entry.pid == os.getpid() or entry.pid == parent
            relevant = exe != "python.exe" or entry.ppid == parent
            if exe in targets and not own and relevant:
                proc = api.OpenProcess(0x1000,False,entry.pid)
                if proc:
                    try:
                        if _process_image(api, proc) == targets[exe]:
                            raise BlockingIOError("Another LiveTranslate window or local worker is using this installation.")
                    finally:
                        api.CloseHandle(wintypes.HANDLE(proc))
            more = api.Process32NextW(snap,ctypes.byref(entry))
    finally:
        api.CloseHandle(snap)


def _idle_install(root, parent, timeout=10):
    end = time.monotonic() + timeout
    while True:
        try:
            _check_running(root, parent, workers=True)
            return
        except BlockingIOError:
            if time.monotonic() >= end:
                raise
            time.sleep(.2)


def _mark(state, token, phase, originals=None):
    _write_json(state / _JOURNAL, {"id":token,"phase":phase,"originals":originals or {}})


def _backup(root, state, token, files):
    directory = state / ("backup-" + token)
    _folder(directory)
    originals = {}
    for rel in files:
        dest = _file(root, rel, missing=True)
        if dest.exists():
            original_hash = _digest(dest)
            _folder((directory / rel).parent)
            _replace_copy(dest, directory / rel, original_hash)
            originals[rel] = original_hash
        else:
            originals[rel] = None
    return originals


def _commit_file(root, staged, rel, expected):
    _replace_copy(_file(staged,rel), _file(root,rel,missing=True), expected)


def _roll_back(root, state, token, originals):
    backup = state / ("backup-" + token)
    _plain(backup,directory=True)
    if not isinstance(originals,dict) or _EXE not in originals:
        raise ValueError("Original update backups are incomplete.")
    # Validate every stored original before restoring any destination.
    for rel, digest in originals.items():
        _file(root,rel,missing=True)
        if digest is not None and (not isinstance(digest,str) or not _HASH.fullmatch(digest) or
                                   _digest(_file(backup,rel)) != digest):
            raise ValueError("Original update backups failed verification.")
    # Restore the executable last, so the recovery-capable dashboard stays usable.
    for rel in sorted(originals,key=lambda s: s == _EXE):
        dest = _file(root,rel,missing=True)
        digest = originals[rel]
        if digest is None:
            dest.unlink(missing_ok=True)
        elif not dest.exists() or _digest(dest) != digest:
            _replace_copy(_file(backup,rel), dest, digest)


def _forget(state, token, keep_stage=False):
    (state / _JOURNAL).unlink(missing_ok=True)
    # Only remove entries created under this updater's private directory.
    for name in (["backup-" + token] if keep_stage else ["backup-" + token,"candidate-" + token]):
        target = state / name
        if _plain(target,directory=True,missing=True):
            try:
                shutil.rmtree(target)
            except OSError:
                pass  # Locks on obsolete staging files do not invalidate a completed install.


def _note(state, message):
    try:
        _atomic_bytes(state / "last-result.txt", (message + "\n").encode("utf8"))
    except OSError:
        pass


def _relaunch(root):
    subprocess.Popen([str(root/_EXE)], cwd=root, close_fds=True,
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def apply_stage(root, token, parent=0, restart=False, on_ready=None):
    root = Path(root).resolve(strict=True)
    state = _folder(root / _STATE)
    with _writer(state), _parent(root,parent) as handle:
        if (state / _JOURNAL).exists():
            raise RuntimeError("Finish recovery of the previous update first.")
        staged, receipt = _receipt(state, token)
        if _digest(_file(root,_EXE)) != receipt["base"]:
            raise RuntimeError("The installed version changed. Check for updates again.")
        _check_running(root,parent)
        total = 0
        for rel, digest in receipt["files"].items():
            src = _file(staged,rel)
            total += src.stat().st_size
            if total > _MAX_TOTAL or _digest(src) != digest:
                raise ValueError("Prepared update contents changed.")
        helper = Path(__file__).resolve(strict=True)
        _replace_copy(helper, state / "recovery.py", _digest(helper))
        _mark(state,token,"waiting")
        try:
            if on_ready:
                on_ready()
            _wait_exit(handle)
            _idle_install(root,parent)
            with _run_gate(root):
                if _digest(_file(root,_EXE)) != receipt["base"]:
                    raise RuntimeError("The installation changed after preparing this update.")
                originals = _backup(root,state,token,receipt["files"])
                _mark(state,token,"prepared",originals)
                try:
                    for rel in sorted(receipt["files"],key=lambda s: s != _EXE):
                        _commit_file(root,staged,rel,receipt["files"][rel])
                    _mark(state,token,"committed")
                except Exception:
                    _roll_back(root,state,token,originals)
                    _forget(state,token,keep_stage=True)
                    raise
                _forget(state,token)
        except Exception as exc:
            marker = state / _JOURNAL
            if marker.exists() and _read_json(marker).get("phase") == "waiting":
                _forget(state,token,keep_stage=True)
            _note(state,"Update did not finish. " + str(exc))
            raise
        _note(state,"The application update finished successfully.")
    if restart:
        _relaunch(root)


def recover(root, parent=0, restart=False):
    root = Path(root).resolve(strict=True)
    state = root / _STATE
    if not _plain(state,directory=True,missing=True) or not _plain(state / _JOURNAL,missing=True):
        return False
    with _writer(state), _parent(root,parent) as handle:
        if not (state / _JOURNAL).exists():
            return False
        journal = _read_json(state / _JOURNAL)
        token = journal.get("id")
        if not isinstance(token,str) or not _ID.fullmatch(token) or journal.get("phase") not in {"waiting","prepared","committed"}:
            raise ValueError("The interrupted update journal is invalid.")
        _wait_exit(handle)
        _idle_install(root,parent)
        with _run_gate(root):
            if journal["phase"] == "prepared":
                _roll_back(root,state,token,journal["originals"])
            _forget(state,token,keep_stage=journal["phase"] != "committed")
        _note(state, "The interrupted update was recovered.")
    if restart:
        _relaunch(root)
    return True


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=["apply","recover"])
    parser.add_argument("--stage")
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--parent",type=int,default=0)
    parser.add_argument("--no-restart",action="store_true")
    args = parser.parse_args()
    ready = False
    def announce():
        nonlocal ready
        print("READY",flush=True)
        ready = True
    try:
        if args.action == "apply":
            apply_stage(args.root,args.stage,args.parent,not args.no_restart,announce)
        else:
            recover(args.root,args.parent,not args.no_restart)
        return 0
    except Exception as exc:
        # GUI may have already closed the readiness pipe. A hidden helper still
        # needs to give the user an actionable failure message after that point.
        message = str(exc)
        try:
            print("ERROR " + message.replace("\n"," "),flush=True)
        except OSError:
            pass
        if os.name == "nt" and not args.no_restart and (ready or args.action == "recover") and not (
                args.action == "recover" and isinstance(exc,BlockingIOError)):
            state = args.root / _STATE
            retry = "Run Start.cmd again to recover the interrupted update." if (state / _JOURNAL).exists() else "Run Start.cmd to reopen LiveTranslate."
            _win_message(message + "\n\n" + retry)
        return 1


def _win_message(message):
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "LiveTranslate update", 0x10)
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
