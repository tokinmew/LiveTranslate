"""Archive recovery packages for releases through 0.6.9; newer updates require GitHub."""
from pathlib import Path
import hashlib
import json
import re
import sys
import tempfile
import zipfile

here = Path(__file__).resolve().parent
feed = Path(sys.argv[1])
dest = Path(sys.argv[2])
base = here/"bootstrap"
manifest = (feed/"latest.json").read_bytes()
meta = json.loads(manifest)
version = meta["version"]
if tuple(map(int, version.split("."))) >= (0, 6, 10):
    raise ValueError("LiveTranslate 0.6.10 and later updates must be published to public GitHub Releases and installed in the app.")
match = re.fullmatch(r"0\.6\.([1-9][0-9]*)", version)
if not match:
    raise ValueError("This bootstrap only supports the 0.6.x product line.")
name = f"LiveTranslate-{version}.json"
if (meta.get("schema") != 1 or meta.get("product") != "LiveTranslate" or meta.get("package") != name
        or type(meta.get("size")) is not int or not 0 < meta["size"] <= 8 * 1024**2):
    raise ValueError("Invalid update manifest.")
with (feed/name).open("rb") as source:
    package = source.read(meta["size"] + 1)
if len(package) != meta["size"] or hashlib.sha256(package).hexdigest() != meta["sha256"]:
    raise ValueError("The package length or digest differs from the manifest.")


def render(filename, replacements):
    text = (base / filename).read_text("utf8")
    for token, value in replacements.items():
        if text.count(token) != 1:
            raise ValueError("Unexpected template marker in " + filename + ": " + token)
        text = text.replace(token, value)
    return text


script = render("enable_updates.py", {"__LIVETRANSLATE_RELEASE_VERSION__": version,
                                     "__LIVETRANSLATE_BUNDLED_PACKAGE_SHA256__": meta["sha256"]})
cmd = render("Enable updates.cmd", {"__LIVETRANSLATE_MAX_PATCH__": match.group(1),
                                  "__LIVETRANSLATE_RELEASE_VERSION__": version})
notice = rf"""LiveTranslate {version} for an existing Windows installation

Close the app. Extract this ZIP, open Enable updates.cmd, and select the
folder containing your installed LiveTranslate.exe. For the standard Windows
installation, this is %LOCALAPPDATA%\Programs\LiveTranslate\app.
The installer verifies the release, compiles the interface, scans the update
with Microsoft Defender, keeps existing models and settings, and reopens
your dashboard. Allow time for the scan on slower computers.

For a fresh installation, open LiveTranslate-{version}-Setup.exe instead.
For later updates, use Settings > Updates in LiveTranslate.
"""
if dest.exists():
    raise FileExistsError(dest)
with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
    built = Path(tmp) / dest.name
    with zipfile.ZipFile(built,"w",zipfile.ZIP_DEFLATED,compresslevel=8) as out:
        out.writestr("Enable updates.cmd", cmd.replace("\n","\r\n"))
        out.writestr("enable_updates.py", script)
        out.writestr("latest.json",manifest)
        out.writestr(name,package)
        out.writestr("START-HERE.txt",notice)
    with zipfile.ZipFile(built) as out:
        if out.testzip() is not None:
            raise ValueError("Update ZIP failed verification.")
    built.rename(dest)
print(dest, dest.stat().st_size)
