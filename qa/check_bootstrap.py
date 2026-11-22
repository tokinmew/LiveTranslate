"""Run the released small-update bootstrap on a disposable copy; suppress GUI capture."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import zipfile


def guarded_entry(script, dest):
    # Only replace launching the dashboard, which would watch the actual
    # display. All installer child processes and native scans run as shipped.
    original = subprocess.Popen
    launched = []
    def launch(args, *a, **kw):
        if isinstance(args, list) and args == [str(dest / "LiveTranslate.exe")]:
            launched.append(args)
            return None
        return original(args, *a, **kw)
    subprocess.Popen = launch
    sys.argv = [str(script),str(dest)]
    runpy.run_path(str(script),run_name="__main__")
    assert len(launched) == 1


def test(small_zip, old_zip, runtime_folder):
    with tempfile.TemporaryDirectory(prefix="LiveTranslate-bootstrap-") as base:
        base = Path(base)
        dest = base/"Existing portable"
        patch = base/"Update"
        patch.mkdir()
        with zipfile.ZipFile(small_zip) as kit:
            kit.extractall(patch)
        with zipfile.ZipFile(old_zip) as original:
            names = ["LiveTranslate.exe","Start.cmd"]
            names.extend(n.removeprefix("LiveTranslate/") for n in original.namelist()
                         if n.startswith(("LiveTranslate/ui/", "LiveTranslate/backend/")))
            for name in names:
                dest.joinpath(name).parent.mkdir(parents=True,exist_ok=True)
                (dest/name).write_bytes(original.read("LiveTranslate/"+name))
        runtime = dest/"runtime"
        runtime.mkdir()
        for f in runtime_folder.iterdir():
            if f.is_file():
                shutil.copyfile(f,runtime/f.name)
        data = dest/"data"
        data.mkdir()
        (data/"user-prefs.json").write_text('{"chosen":"ja"}')
        env = dict(os.environ,LOCALAPPDATA=str(base/"Private profile"),TEMP=str(base),TMP=str(base))
        subprocess.run([str(runtime/"python.exe"),"-I","-B","-X","utf8",__file__,"--entry",
                        str(patch/"enable_updates.py"),str(dest)],cwd=dest,env=env,check=True)
        assert (data/"user-prefs.json").read_text() == '{"chosen":"ja"}'
        assert (Path(env["LOCALAPPDATA"])/"LiveTranslate/Releases/latest.json").read_bytes() == (patch/"latest.json").read_bytes()
        manifest = json.loads((patch/"latest.json").read_bytes())
        for row in json.loads((patch/manifest["package"]).read_bytes())["files"]:
            assert hashlib.sha256((dest/row["path"]).read_bytes()).hexdigest() == row["sha256"]
        print("Final small ZIP migrated shipped 0.6.1 and preserved user prefs. All code files and feed matched.")

if __name__ == "__main__":
    if sys.argv[1:2] == ["--entry"]:
        guarded_entry(Path(sys.argv[2]),Path(sys.argv[3]))
    else:
        work = Path(__file__).resolve().parents[2]
        outputs = work.parent / "outputs"
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--update", type=Path, default=outputs/"LiveTranslate-0.6.6-Existing-Install-Update.zip")
        parser.add_argument("--original", type=Path, default=outputs/"LiveTranslate-0.6.1-Windows-Test.zip")
        parser.add_argument("--runtime", type=Path, default=work/"captions-v04/qa-installed/LiveTranslate/runtime")
        args = parser.parse_args()
        test(args.update, args.original, args.runtime)
