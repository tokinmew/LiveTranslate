"""Replace app files in the verified 0.6.4 portable distribution, retaining its offline models."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
import zipfile


def sha(file):
    return hashlib.file_digest(file, "sha256").hexdigest()


def build(app, base, output):
    with base.open("rb") as stream:
        if sha(stream) != "5676f48621217ce72a002bf37916a0e8f32989b2106a2800e2836d907bca4e97":
            raise ValueError("Choose the original full LiveTranslate 0.6.4 Windows ZIP.")
    if output.exists():
        raise FileExistsError(output)
    if not (app / "LiveTranslate.exe").is_file():
        raise FileNotFoundError("Run LiveTranslate/Build.cmd before packaging.")
    updated = {p.relative_to(app).as_posix():p for pattern in
               ("backend/*.py", "ui/*.cs", "ui/*.ico", "LiveTranslate.exe", "ocr-tools/EnglishOcr.exe",
                "README.md", "START-HERE.txt", "VALIDATION.md", "SOURCE-CHECKS.md")
               for p in app.glob(pattern)}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        made = Path(tmp)/"new.zip"
        expected = {}
        with zipfile.ZipFile(base) as prev, zipfile.ZipFile(made,"w",zipfile.ZIP_DEFLATED,compresslevel=8) as out:
            for info in prev.infolist():
                path = info.filename.removeprefix("LiveTranslate/")
                if path in updated:
                    continue
                with prev.open(info) as src:
                    expected[info.filename] = sha(src)
                with prev.open(info) as src, out.open(info,"w") as dest:
                    shutil.copyfileobj(src,dest,1<<20)
            for path, local in updated.items():
                with local.open("rb") as src:
                    expected["LiveTranslate/"+path]=sha(src)
                out.write(local,"LiveTranslate/"+path)
        with zipfile.ZipFile(made) as check:
            if set(check.namelist())!=expected.keys() or len(check.infolist())!=len(expected):
                raise ValueError("Completed archive inventory differs.")
            for name, digest in expected.items():
                with check.open(name) as src:
                    if sha(src)!=digest:
                        raise ValueError("Mismatch for "+name)
        made.rename(output)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("app","base","output"):
        parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    build(args.app,args.base,args.output)
