"""Run only this kit's reviewed PowerShell download/check pipeline.

The child is born inside a non-inheritable kill-on-close Windows job.  Closing
the worker therefore kills its own download/CLI descendants, without touching
the separately running Microsoft Defender service.  No uncontained fallback
is attempted when Windows cannot create that job hierarchy.
"""
from __future__ import annotations

import codecs
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import threading
import time
from typing import Callable


_LINE_LIMIT = 1500
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_REPARSE = 0x400


def _progress_line(value: str) -> str:
    value = _ANSI.sub("", value)
    value = "".join(char for char in value if char == "\t" or ord(char) >= 32)
    value = _URL.sub("[download URL]", value).strip()
    return value[:_LINE_LIMIT - 3] + "..." if len(value) > _LINE_LIMIT else value


def _validated_script(app_root: Path) -> tuple[Path, Path]:
    root = Path(os.path.abspath(os.fspath(app_root)))
    scripts = root / "scripts"
    # Inspect the lexical path before resolve(), so an ancestor junction cannot
    # silently redirect the supposedly local, reviewed script.
    for entry in reversed((scripts, *scripts.parents)):
        info = entry.lstat()
        if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & _REPARSE:
            raise RuntimeError("Checked model setup refuses a linked application folder.")
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("The checked model application folder is not a directory.")
    script = scripts / "Get-CheckedModels.ps1"
    info = script.lstat()
    if script.is_symlink() or getattr(info, "st_file_attributes", 0) & _REPARSE or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("Get-CheckedModels.ps1 must be a normal local file.")
    resolved_root = root.resolve(strict=True)
    resolved_script = script.resolve(strict=True)
    if resolved_script.parent != resolved_root / "scripts":
        raise RuntimeError("The checked model script must stay inside the application folder.")
    return resolved_root, resolved_script


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID), ("bInheritHandle", wintypes.BOOL)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)), ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", wintypes.LPVOID)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE), ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class _BasicJobLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicJobLimits), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    prototypes = {
        "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
        "CreatePipe": ([ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(_SecurityAttributes), wintypes.DWORD], wintypes.BOOL),
        "SetHandleInformation": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "InitializeProcThreadAttributeList": ([wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "UpdateProcThreadAttribute": ([wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID], wintypes.BOOL),
        "DeleteProcThreadAttributeList": ([wintypes.LPVOID], None),
        "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo)], wintypes.BOOL),
        "GetSystemDirectoryW": ([wintypes.LPWSTR, wintypes.UINT], wintypes.UINT),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in prototypes.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _winerror(message: str) -> RuntimeError:
    code = ctypes.get_last_error()
    return RuntimeError(f"{message} (Windows error {code}). Checked model setup was not started without containment.")


class _ContainedPowerShell:
    """Own the only job handle; inherited handles are limited to NUL and stdout."""
    def __init__(self, root: Path, script: Path):
        import msvcrt

        self.kernel = kernel = _kernel_api()
        self.job = self.process = None
        self.stdout = None
        read_handle = wintypes.HANDLE()
        write_handle = wintypes.HANDLE()
        null_handle = None
        attributes = None
        attributes_ready = False
        process = _ProcessInfo()
        try:
            # NULL SECURITY_ATTRIBUTES makes this handle non-inheritable.  The
            # child never receives a handle that would keep its own job alive.
            self.job = kernel.CreateJobObjectW(None, None)
            if not self.job:
                raise _winerror("Could not create the checked setup process job")
            limits = _ExtendedJobLimits()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise _winerror("Could not enable checked setup process cleanup")

            security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
            if not kernel.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle), ctypes.byref(security), 0):
                raise _winerror("Could not create the checked setup output pipe")
            if not kernel.SetHandleInformation(read_handle, 1, 0):
                raise _winerror("Could not protect the checked setup output handle")
            null_handle = kernel.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(security), 3, 0, None)
            if null_handle == ctypes.c_void_p(-1).value or not null_handle:
                null_handle = None
                raise _winerror("Could not open checked setup's null input")

            size = ctypes.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if not size.value:
                raise _winerror("Windows does not provide checked setup process containment")
            attributes = ctypes.create_string_buffer(size.value)
            if not kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
                raise _winerror("Could not initialize checked setup containment attributes")
            attributes_ready = True
            jobs = (wintypes.HANDLE * 1)(self.job)
            handles = (wintypes.HANDLE * 2)(null_handle, write_handle.value)
            # JOB_LIST assigns before execution; unlike create-suspended then
            # assign, there is no deliberately uncontained suspended child.
            if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x0002000D, jobs, ctypes.sizeof(jobs), None, None):
                raise _winerror("Could not assign the checked setup creation-time job")
            if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020002, handles, ctypes.sizeof(handles), None, None):
                raise _winerror("Could not restrict checked setup handle inheritance")

            directory = ctypes.create_unicode_buffer(32768)
            length = kernel.GetSystemDirectoryW(directory, len(directory))
            if not length or length >= len(directory):
                raise _winerror("Could not locate Windows PowerShell")
            powershell = Path(directory.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            if not powershell.is_file():
                raise RuntimeError("Windows PowerShell 5.1 was not found in the Windows system folder.")
            self.argv = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(self.argv))
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x00000101  # USESTDHANDLES | USESHOWWINDOW
            startup.StartupInfo.wShowWindow = 0  # SW_HIDE
            startup.StartupInfo.hStdInput = null_handle
            startup.StartupInfo.hStdOutput = write_handle
            startup.StartupInfo.hStdError = write_handle
            startup.lpAttributeList = ctypes.cast(attributes, wintypes.LPVOID)
            if not kernel.CreateProcessW(str(powershell), command, None, None, True,
                                         0x08080000, None, str(root), ctypes.byref(startup), ctypes.byref(process)):
                raise _winerror("Could not start contained checked model setup")
            self.process = process.hProcess
            if process.hThread:
                kernel.CloseHandle(process.hThread)
                process.hThread = None
            fd = msvcrt.open_osfhandle(read_handle.value, os.O_RDONLY | os.O_BINARY)
            read_handle.value = None  # fd owns the handle now
            self.stdout = os.fdopen(fd, "rb", buffering=0)
        except BaseException:
            self.close_job()
            if process.hThread:
                kernel.CloseHandle(process.hThread)
            if self.process:
                kernel.WaitForSingleObject(self.process, 2000)
                kernel.CloseHandle(self.process)
                self.process = None
            raise
        finally:
            if attributes_ready:
                kernel.DeleteProcThreadAttributeList(attributes)
            for handle in (read_handle.value, write_handle.value, null_handle):
                if handle:
                    kernel.CloseHandle(handle)

    def poll(self) -> int | None:
        result = self.kernel.WaitForSingleObject(self.process, 0)
        if result == 0x102:  # WAIT_TIMEOUT
            return None
        if result != 0:
            raise _winerror("Could not read checked setup process state")
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)):
            raise _winerror("Could not read checked setup exit code")
        return int(code.value)

    def close_job(self) -> None:
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None

    def close(self) -> None:
        self.close_job()
        if self.process:
            self.kernel.WaitForSingleObject(self.process, 2000)
            self.kernel.CloseHandle(self.process)
            self.process = None


def _output_reader(stream, lines: queue.Queue, stopped: threading.Event, ended: threading.Event) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pending = ""
    discarding = False

    def post(line):
        line = _progress_line(line)
        if not line:
            return
        while not stopped.is_set():
            try:
                lines.put(line, timeout=0.1)
                return
            except queue.Full:
                continue

    try:
        while not stopped.is_set():
            chunk = stream.read(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            for fragment in text.splitlines(keepends=True):
                end = fragment.endswith(("\n", "\r"))
                if not discarding:
                    pending += fragment.rstrip("\r\n")
                    if end or len(pending) > 8192:
                        post(pending[:8192])
                        pending = ""
                        discarding = not end
                elif end:
                    discarding = False
        if pending and not stopped.is_set():
            post(pending + decoder.decode(b"", final=True))
    except (OSError, ValueError) as exc:
        if not stopped.is_set():
            post("Checked setup output stream closed: " + str(exc))
    finally:
        try:
            stream.close()
        except OSError:
            pass
        ended.set()


def run_checked_powershell(app_root: Path, emit: Callable[[str], None], cancel_event: threading.Event) -> None:
    """Run Get-CheckedModels.ps1, streaming bounded/redacted progress strings.

    Raises RuntimeError for cancellation, nonzero exit, invalid local paths,
    unsupported Windows containment, or a process/output failure.  The only
    child command is the fixed local PowerShell script with its default mode.
    """
    if cancel_event.is_set():
        raise RuntimeError("Checked model setup was cancelled.")
    if os.name != "nt":
        raise RuntimeError("Checked model setup requires Windows 10 or Windows 11.")
    try:
        root, script = _validated_script(app_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("The local checked model script is missing or inaccessible.") from exc
    if cancel_event.is_set():
        raise RuntimeError("Checked model setup was cancelled.")
    process = _ContainedPowerShell(root, script)
    lines = queue.Queue(maxsize=128)
    stopped = threading.Event()
    ended = threading.Event()
    reader = threading.Thread(target=_output_reader, args=(process.stdout, lines, stopped, ended), daemon=True,
                              name="checked-model-output")
    reader.start()
    exit_code = None
    exit_time = None
    try:
        emit("Checking and downloading the fixed model set. Please wait...")
        while True:
            if cancel_event.is_set():
                raise RuntimeError("Checked model setup was cancelled. Its download process was stopped.")
            try:
                emit(lines.get(timeout=0.1))
            except queue.Empty:
                pass
            if exit_code is None:
                exit_code = process.poll()
                if exit_code is not None:
                    exit_time = time.monotonic()
                    process.close_job()  # No CLI descendant outlives its pipeline.
            if exit_code is not None and ended.is_set() and lines.empty():
                break
            if exit_time is not None and time.monotonic() - exit_time > 5:
                raise RuntimeError("Checked model setup stopped, but its output stream did not close normally.")
        if exit_code:
            raise RuntimeError(f"Checked model setup failed (exit code {exit_code}). Read the model-check status above and retry after resolving it.")
        emit("Checked model file pipeline completed. The app will now import and test the installed models.")
    finally:
        stopped.set()
        process.close()
        reader.join(timeout=2)
