"""Select Windows playback and microphone endpoints for WASAPI loopback capture."""
from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass
from functools import lru_cache
import os
import uuid


DEFAULT_PLAYBACK = -2
DEFAULT_PLAYBACK_AND_MIC = -3


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str


@dataclass(frozen=True)
class Route:
    info: dict
    source: str

    @property
    def key(self):
        return self.source, int(self.info["index"])


class _Guid(ct.Structure):
    _fields_ = [("bytes", ct.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _PropertyKey(ct.Structure):
    _fields_ = [("guid", _Guid), ("index", ct.c_uint32)]


class _Variant(ct.Structure):
    # PROPVARIANT's largest union entry also contains a count and pointer.
    _fields_ = [("vt", ct.c_ushort), ("reserved", ct.c_ushort * 3),
                ("pointer", ct.c_void_p), ("tail", ct.c_void_p)]


def _method(pointer, slot, output, *args):
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(output, ct.c_void_p, *args)(table[slot])


@lru_cache(maxsize=1)
def _com_api():
    # Use WinDLL so HRESULT failures from the optional defaults are returned
    # normally. Signatures here are local, with no process-wide COM settings.
    ole = ct.WinDLL("ole32")
    hr = ct.c_long
    p = ct.c_void_p
    pp = ct.POINTER(p)
    guidp = ct.POINTER(_Guid)
    ole.CoInitializeEx.argtypes = (p, ct.c_uint32)
    ole.CoInitializeEx.restype = hr
    ole.CoCreateInstance.argtypes = (guidp, p, ct.c_uint32, guidp, pp)
    ole.CoCreateInstance.restype = hr
    ole.CoTaskMemFree.argtypes = (p,)
    ole.CoTaskMemFree.restype = None
    ole.PropVariantClear.argtypes = (ct.POINTER(_Variant),)
    ole.PropVariantClear.restype = hr
    ole.CoUninitialize.argtypes = ()
    ole.CoUninitialize.restype = None
    return ole


def windows_default_routes(include_mic=False):
    """Read the endpoint IDs and friendly names for the media and calls roles.

    PortAudio exposes a default render device but omits the separate Windows
    communications role. IMMDeviceEnumerator exposes both. No stream opens.
    """
    if os.name != "nt":
        return ()
    ole = _com_api()
    hr = ct.c_long
    p = ct.c_void_p
    pp = ct.POINTER(p)
    init = ole.CoInitializeEx(None, 0)
    if init < 0 and init != -2147417850:  # RPC_E_CHANGED_MODE: already initialized.
        return ()
    enumerator = p()
    try:
        clsid = _Guid.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
        iid = _Guid.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
        if ole.CoCreateInstance(ct.byref(clsid), None, 1, ct.byref(iid), ct.byref(enumerator)) < 0:
            return ()
        key = _PropertyKey(_Guid.parse("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
        result = []
        # A missing role is represented by None so a changed set of defaults
        # can be noticed while capture is active.
        for flow, role in ([(0, 1), (0, 2), (1, 1)] if include_mic else [(0, 1), (0, 2)]):
            device, store, identity = p(), p(), p()
            value = _Variant()
            endpoint = None
            try:
                get_default = _method(enumerator, 4, hr, ct.c_int, ct.c_int, pp)
                if get_default(enumerator, flow, role, ct.byref(device)) >= 0:
                    get_id = _method(device, 5, hr, pp)
                    open_properties = _method(device, 4, hr, ct.c_uint32, pp)
                    if (get_id(device, ct.byref(identity)) >= 0
                            and open_properties(device, 0, ct.byref(store)) >= 0):
                        get_value = _method(store, 5, hr, ct.POINTER(_PropertyKey), ct.POINTER(_Variant))
                        if get_value(store, ct.byref(key), ct.byref(value)) >= 0 and value.vt == 31 and value.pointer:
                            endpoint = Endpoint(ct.wstring_at(identity), ct.wstring_at(value.pointer))
            finally:
                ole.PropVariantClear(ct.byref(value))
                if identity:
                    ole.CoTaskMemFree(identity)
                for obj in (store, device):
                    if obj:
                        _method(obj, 2, ct.c_ulong)(obj)
            result.append(endpoint)
        return tuple(result)
    finally:
        if enumerator:
            _method(enumerator, 2, ct.c_ulong)(enumerator)
        if init >= 0:
            ole.CoUninitialize()


def _plain_name(name):
    return " ".join(str(name).casefold().removesuffix(" [loopback]").split())


def input_devices(audio, api_index):
    return [info for i in range(audio.get_device_count())
            if (info := audio.get_device_info_by_index(i)).get("hostApi") == api_index
            and int(info.get("maxInputChannels", 0)) > 0]


def capture_routes(audio, requested, defaults=()):
    """Map Core Audio endpoint identities to PortAudio inputs without ever
    substituting a microphone for an output. An ambiguous name is skipped.
    """
    if requested not in (DEFAULT_PLAYBACK, DEFAULT_PLAYBACK_AND_MIC):
        if requested < 0:
            raise ValueError("Choose a listed playback output or microphone.")
        info = dict(audio.get_device_info_by_index(requested))
        info.setdefault("index", requested)
        if int(info.get("maxInputChannels", 0)) < 1:
            raise ValueError("The selected recording endpoint is unavailable. Refresh audio sources.")
        return [Route(info, "pc" if info.get("isLoopbackDevice") else "microphone")]

    loopbacks = list(audio.get_loopback_device_info_generator())
    selected = []
    endpoint_ids = set()
    for pos, endpoint in enumerate((tuple(defaults) + (None, None))[:2]):
        if endpoint and endpoint.id in endpoint_ids:
            continue
        matches = [x for x in loopbacks if endpoint and _plain_name(x["name"]) == _plain_name(endpoint.name)]
        if len(matches) == 1:
            info = matches[0]
        elif pos == 0:
            try:
                info = audio.get_default_wasapi_loopback()
            except (LookupError, OSError, ValueError):
                info = None
            if (endpoint and info and
                    (len(matches) > 1 or _plain_name(endpoint.name) != _plain_name(info["name"]))):
                info = None
        else:
            info = None
        if info and info.get("isLoopbackDevice") and int(info.get("maxInputChannels", 0)) > 0:
            if not any(route.info["index"] == info["index"] for route in selected):
                selected.append(Route(info, "pc"))
            if endpoint:
                endpoint_ids.add(endpoint.id)
    if not selected:
        raise RuntimeError("Windows has no available default playback loopback. Choose a listed computer output or reconnect your headset.")
    if requested == DEFAULT_PLAYBACK_AND_MIC:
        try:
            mic = audio.get_default_wasapi_device(d_in=True)
        except (LookupError, OSError, ValueError) as exc:
            raise RuntimeError("No default Windows microphone is available. Choose Computer audio to hear playback alone.") from exc
        if mic.get("isLoopbackDevice") or int(mic.get("maxInputChannels", 0)) < 1:
            raise RuntimeError("Windows did not provide a microphone input. Choose Computer audio to hear playback alone.")
        selected.append(Route(mic, "microphone"))
    return selected
