"""Combine the verified per-user installer and portable archive into one download."""
import hashlib
from pathlib import Path
import sys
import zipfile


def build(kit, portable, output):
    with portable.open("rb") as data:
        pin = hashlib.file_digest(data, "sha256").hexdigest()
    with zipfile.ZipFile(kit) as small:
        assert pin in small.read("Setup.ps1").decode("utf8").lower()
        assert set(small.namelist()) == {"Setup.ps1","files.json","Install LiveTranslate.cmd","READ-ME.txt"}
        with zipfile.ZipFile(output,"x",zipfile.ZIP_DEFLATED) as bundle:
            for name in small.namelist():
                bundle.writestr(name,small.read(name))
            bundle.write(portable,portable.name,compress_type=zipfile.ZIP_STORED)
    with zipfile.ZipFile(output) as check:
        assert check.testzip() is None
        with check.open(portable.name) as data:
            assert hashlib.file_digest(data,"sha256").hexdigest() == pin
    assert output.stat().st_size < 512*1024**2
    print(output,output.stat().st_size,"bytes; all members verified")


if __name__ == "__main__":
    build(*(Path(arg) for arg in sys.argv[1:]))
