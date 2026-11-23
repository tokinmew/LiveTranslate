"""Bind a small per-user Windows setup to one existing portable release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


def read_package(portable, version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid release version")
    records = {}
    with portable.open("rb") as source:
        pin = hashlib.file_digest(source, "sha256").hexdigest()
        with zipfile.ZipFile(source) as archive:
            for f in archive.infolist():
                name = f.filename.removeprefix("LiveTranslate/")
                if f.orig_filename != f.filename or name == f.filename or any(not x or x in (".","..") or x.endswith((" ",".")) or
                        bool(re.search(r'[<>:"\\|?*\x00-\x1f]', x)) or
                        bool(re.match(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)",x))
                        for x in name.split("/")):
                    raise ValueError("Invalid release member " + f.filename)
                if name.casefold() in records:
                    raise ValueError("Duplicate release member")
                with archive.open(f) as stream:
                    records[name.casefold()] = [name, f.file_size, hashlib.file_digest(stream,"sha256").hexdigest()]
    layout = tuple(map(int, version.split("."))) >= (0, 6, 8)
    if not {"livetranslate.exe", "scripts/start.cmd" if layout else "start.cmd", "backend/worker.py"}.issubset(records):
        raise ValueError("Incomplete portable ZIP")
    if layout and {name for name in records if "/" not in name} != {"livetranslate.exe"}:
        raise ValueError("Only the application may be at the root of the portable release.")
    manifest = json.dumps(list(records.values()), ensure_ascii=True, separators=(",",":")).encode("ascii")
    return pin, manifest


def render(pin, manifest, version, launcher_pin=""):
    here = Path(__file__).resolve().parent
    script = (here/"Setup.ps1").read_text("ascii").replace("__MANIFEST_SHA256__",hashlib.sha256(manifest).hexdigest())
    script = script.replace("__ARCHIVE_SHA256__",pin).replace("__VERSION__",version)
    script = script.replace("__LAUNCHER_SHA256__", launcher_pin)
    integration = (here/"desktop-setup"/"DesktopIntegration.ps1").read_text("utf-8-sig") if launcher_pin else ""
    legacy_files = json.loads((here/"legacy-root-0.6.7.json").read_text("ascii")) if tuple(map(int,version.split("."))) >= (0,6,8) else {}
    legacy = "\n".join(f"    '{name.replace(chr(39), chr(39)*2)}' = '{digest}'" for name,digest in legacy_files.items())
    script = script.replace("# __LEGACY_ROOT_HASHES__",legacy).replace("# __DESKTOP_INTEGRATION__",integration)
    return script.replace("\n","\r\n").encode("utf-8-sig")


def build(portable, output, version):
    pin, manifest = read_package(portable, version)
    here = Path(__file__).resolve().parent
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output,"x",zipfile.ZIP_DEFLATED,compresslevel=9) as kit:
        kit.writestr("Setup.ps1",render(pin, manifest, version))
        kit.writestr("files.json",manifest)
        kit.writestr("Install LiveTranslate.cmd",
            '@echo off\r\nsetlocal DisableDelayedExpansion\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"\r\nexit /b %errorlevel%\r\n')
        kit.writestr("READ-ME.txt",(here/"READ-ME.txt").read_bytes())
    print(f"{output}: {output.stat().st_size:,} bytes; portable SHA-256 {pin}")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--portable",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--version",default="0.6.8")
    args = p.parse_args()
    build(args.portable,args.output,args.version)
