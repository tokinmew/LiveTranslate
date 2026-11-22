"""Package a cumulative update for prepared Windows 0.6.x installs."""
from pathlib import Path
import hashlib
import json
import re
import sys
import zipfile

here = Path(__file__).resolve().parent
feed = Path(sys.argv[1])
dest = Path(sys.argv[2])
base = here/"bootstrap"
manifest = (feed/"latest.json").read_bytes()
meta = json.loads(manifest)
version = meta["version"]
match = re.fullmatch(r"0\.6\.([1-9][0-9]*)", version)
if not match:
    raise ValueError("This bootstrap only supports the 0.6.x product line.")
patches = tuple(range(1, int(match.group(1)) + 1))
package = (feed/meta["package"]).read_bytes()
assert len(package) == meta["size"] and hashlib.sha256(package).hexdigest() == meta["sha256"]
script = (base/"enable_updates.py").read_text("utf8").replace("0.6.3",version)
script = script.replace("for n in (1, 2, 3)", "for n in " + repr(patches))
script = script.replace("0.6.1 or 0.6.2 installation.", f"0.6.1 through {version} installation.")
assert script.count("__LIVETRANSLATE_BUNDLED_PACKAGE_SHA256__") == 1
script = script.replace("__LIVETRANSLATE_BUNDLED_PACKAGE_SHA256__",meta["sha256"])
cmd = (base/"Enable updates.cmd").read_text("utf8").replace("@(1,2,3)", "@(" + ",".join(map(str,patches)) + ")")
cmd = cmd.replace("0.6.1, 0.6.2, and 0.6.3.", f"0.6.1 through {version}.")
notice = f"""LiveTranslate {version} for an existing Windows installation

Close the app. Extract this ZIP, open Enable updates.cmd, and select the
folder that contains your existing LiveTranslate.exe and Start.cmd.
The installer verifies the release, compiles the interface, scans the update
with Microsoft Defender, keeps existing models and settings, and reopens
your dashboard. Allow time for the scan on slower computers.

Use the complete Windows Setup ZIP for a first installation. Once your copy
has the Updates page, you can use Settings > Updates with your private feed.
"""
with zipfile.ZipFile(dest,"x",zipfile.ZIP_DEFLATED,compresslevel=8) as out:
    out.writestr("Enable updates.cmd", cmd.replace("\n","\r\n"))
    out.writestr("enable_updates.py", script)
    out.writestr("latest.json",manifest)
    out.writestr(meta["package"],package)
    out.writestr("START-HERE.txt",notice)
with zipfile.ZipFile(dest) as out:
    assert out.testzip() is None
print(dest, dest.stat().st_size)
