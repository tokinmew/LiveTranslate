"""Stream the prepacked models and compress the portable ZIP's source section with Windows."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import zipfile


def compress(data):
    api = ctypes.WinDLL("cabinet.dll", use_last_error=True, winmode=0x800)
    pointer = ctypes.c_void_p
    size = ctypes.c_size_t
    api.CreateCompressor.argtypes = (wintypes.DWORD, pointer, ctypes.POINTER(pointer))
    api.SetCompressorInformation.argtypes = (pointer, ctypes.c_int, pointer, size)
    api.Compress.argtypes = (pointer, pointer, size, pointer, size, ctypes.POINTER(size))
    api.CloseCompressor.argtypes = (pointer,)
    handle = pointer()
    if not api.CreateCompressor(5, None, ctypes.byref(handle)):  # COMPRESS_ALGORITHM_LZMS
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        block = wintypes.DWORD(32 << 20)
        if not api.SetCompressorInformation(handle, 1, ctypes.byref(block), ctypes.sizeof(block)):
            raise ctypes.WinError(ctypes.get_last_error())
        needed = size()
        api.Compress(handle, data, len(data), None, 0, ctypes.byref(needed))
        if ctypes.get_last_error() != 122 or not needed.value:
            raise ctypes.WinError(ctypes.get_last_error())
        output = ctypes.create_string_buffer(needed.value)
        if not api.Compress(handle, data, len(data), output, len(output), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return output.raw[:needed.value]
    finally:
        api.CloseCompressor(handle)


def split(portable, output):
    with portable.open("rb") as src:
        with zipfile.ZipFile(src) as archive:
            split_at = archive.getinfo("LiveTranslate/LiveTranslate.exe").header_offset
        suffix_size = portable.stat().st_size - split_at
        if not 0 < suffix_size <= 64 << 20:
            raise ValueError("Expected the portable source section to follow its offline payload.")
        src.seek(0)
        remaining = split_at
        with (output / "Portable.prefix").open("xb") as prefix:
            while remaining:
                chunk = src.read(min(remaining, 1 << 20))
                if not chunk:
                    raise ValueError("The portable file changed while reading.")
                prefix.write(chunk)
                remaining -= len(chunk)
        tail = src.read()
        if len(tail) != suffix_size:
            raise ValueError("The portable file changed while reading.")
        (output / "Portable.suffix").write_bytes(compress(tail))
        return len(tail)


if __name__ == "__main__":
    print(split(Path(sys.argv[1]), Path(sys.argv[2])))
