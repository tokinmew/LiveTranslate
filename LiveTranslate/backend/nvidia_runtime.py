"""Map only the reviewed NVIDIA cuBLAS pair inside this worker process."""
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import threading


_CUBLAS = (
    ('cublasLt64_12.dll', 531812352, '0d59d264782cec2782b9ac72483e53c9ba485a9d3a1e19b34071a17b8152102e'),
    ('cublas64_12.dll',   104883712, '01d8172b25d8e2d2cb6a276e76e719f5908c6124f484c8c8ca310fbe7b6634f3'),
)
_libraries = {}
_library_lock = threading.Lock()
_SYSTEM32_ONLY = 0x00000800


def _win32():
    kernel = ctypes.WinDLL('kernel32', winmode=_SYSTEM32_ONLY, use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    kernel.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _locked_reader(path, kernel):
    """Deny writes/deletion between identity verification and mapping the DLL."""
    import msvcrt
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(fd, 'rb')


def _module_path(kernel, handle):
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError('Cannot resolve loaded CUDA library path.')
    return Path(buffer.value).resolve()


def _load_cublas(directory):
    if os.name != 'nt':
        raise OSError('The checked NVIDIA package requires 64-bit Windows.')
    directory = Path(directory).resolve(strict=True)
    with _library_lock:
        if directory in _libraries:
            return
        kernel = _win32()
        paths = []
        with ExitStack() as locks:
            for name, length, digest in _CUBLAS:
                path = directory / name
                if path.is_symlink() or path.resolve() != path:
                    raise OSError('Unverified GPU library path.')
                stream = locks.enter_context(_locked_reader(path, kernel))
                if os.fstat(stream.fileno()).st_size != length or hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise OSError('The NVIDIA library failed its identity check: ' + name)
                existing = kernel.GetModuleHandleW(name)
                if existing and _module_path(kernel, existing) != path:
                    raise OSError('Another copy of the NVIDIA library is already loaded: ' + name)
                paths.append(path)
            # Load by exact path. Dependencies may resolve from already mapped
            # modules or Windows System32. There is no global search-path change.
            handles = []
            for path in paths:
                dll = ctypes.WinDLL(str(path), winmode=_SYSTEM32_ONLY)
                if _module_path(kernel, dll._handle) != path:
                    raise OSError('Windows mapped an unexpected NVIDIA library.')
                handles.append(dll)
            _libraries[directory] = handles
