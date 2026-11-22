"""Verify the official GitHub stable feed with the release key pinned in this app."""
import base64
import binascii
import ctypes
from ctypes import wintypes
import re


OFFICIAL = "tokinmew/livetranslate"
PUBLIC_BLOB = "BgIAAACkAABSU0ExAAwAAAEAAQBlT5WR0AV0aceP9KArlDGPE39kwyBuOmSA58G+aD7keDY+QJki9i8MYq7oVgolxxNWA6cL2MNmVtIMkscKIG/QnZg/r92KdSVyz5lWZq6AvZcHvulbc8FbJ3gCcX0q0zaTq+/QOy0REogVF6izijU4t2p8OtcqP64m9Ebk78U8orMql4XLxwsOGz4Rz8SuvKWKTBOoUTYoyeeQJLazryd955I72mmrV0hPXNfgSo/P7db9IkwESg5xM+PBkEVMDz4bjmAHU7wW+ogD65xX5whVTf7InJqtEju2nNvnjU4iCnzybYSyswGZl5hhDYIqTUi4fHD3VbfbDKxK+XOz/O+hwzRLSP97Gm/yitlBon77CHjiehQ+So3gEEm9ClpURRAdHBQdm6UD7JKL0HKf5kQIvyJ8Wd/NnMWTGsEDgzlXaEny0FD2YzG5kHb5RCKdFQPxNZVcuXrihUgO2mMnDXssGmzo+peItLZcT9C4ynh7vfcjcDl6pWiUkJImp+TXEss="


def verify_official_manifest(repo, manifest):
    if repo.casefold() != OFFICIAL:
        return
    version = manifest.get("version")
    size = manifest.get("size")
    digest = manifest.get("sha256")
    if (manifest.get("product") != "LiveTranslate" or type(manifest.get("schema")) is not int
            or manifest["schema"] != 1 or not isinstance(version, str)
            or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version)
            or manifest.get("package") != f"LiveTranslate-{version}.json"
            or type(size) is not int or not 0 < size <= 8 * 1024**2
            or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)):
        raise ValueError("Invalid official LiveTranslate release identity.")
    encoded = manifest.get("release_signature")
    if not isinstance(encoded,str) or len(encoded) != 512:
        raise ValueError("Missing or invalid official LiveTranslate release signature.")
    try:
        signature = base64.b64decode(encoded,validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid release signature encoding.") from exc
    fields = ["LiveTranslate", OFFICIAL, "stable", "1", version, manifest["package"], str(size), digest]
    _verify_windows("\n".join(fields).encode("ascii"), signature)


def _verify_windows(data, signature):
    crypto = ctypes.WinDLL("advapi32", use_last_error=True)
    handle = ctypes.c_size_t
    ptr = ctypes.POINTER(handle)
    dword = wintypes.DWORD
    buf = ctypes.c_void_p
    wide = wintypes.LPCWSTR
    def call(name, types, *args):
        fn = getattr(crypto,name)
        fn.argtypes, fn.restype = types, wintypes.BOOL
        if not fn(*args):
            raise ValueError("Windows could not verify the official LiveTranslate release signature.")
    provider, key, hashed = handle(), handle(), handle()
    public = base64.b64decode(PUBLIC_BLOB,validate=True)
    try:
        call("CryptAcquireContextW",[ptr,wide,wide,dword,dword],ctypes.byref(provider),None,None,24,0xF0000000)
        call("CryptImportKey",[handle,buf,dword,handle,dword,ptr],provider,public,len(public),0,0,ctypes.byref(key))
        call("CryptCreateHash",[handle,dword,handle,dword,ptr],provider,0x800C,0,0,ctypes.byref(hashed))
        call("CryptHashData",[handle,buf,dword,dword],hashed,data,len(data),0)
        # CryptoAPI expects RSA signature octets in little-endian order.
        call("CryptVerifySignatureW",[handle,buf,dword,handle,wide,dword],hashed,signature[::-1],len(signature),key,None,0)
    finally:
        if hashed.value:
            crypto.CryptDestroyHash(hashed)
        if key.value:
            crypto.CryptDestroyKey(key)
        if provider.value:
            crypto.CryptReleaseContext(provider,0)
