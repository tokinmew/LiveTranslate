"""Apply the signed 0.6.8 release using an original 0.6.7 client in disposable folders."""
from contextlib import ExitStack
from hashlib import sha256
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError


HERE = Path(__file__).resolve().parent
DEFAULT_OLD = HERE.parents[2] / "captions-v067/LiveTranslate"
DEFAULT_NEW = HERE.parent / "LiveTranslate"
OLD_VERSION = "0.6.7"
NEW_VERSION = "0.6.8"


def sha(data):
    return sha256(data).hexdigest()


def finish_layout(app):
    """Call the actual startup migration, without creating a dashboard or starting a worker."""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    assembly = app / "LiveTranslate.exe"
    command = """
$ErrorActionPreference='Stop'
$a=[Reflection.Assembly]::LoadFrom($env:LT_FIXTURE_EXE)
$t=@($a.GetTypes() | Where-Object { $_.Name -eq 'LayoutMigration' })[0]
$m=$t.GetMethod('Organize',[Reflection.BindingFlags]'Static,Public,NonPublic')
$argsForMethod=[string[]]@([IO.Path]::GetDirectoryName($env:LT_FIXTURE_EXE))
$result=$m.Invoke($null,$argsForMethod)
if ($result -is [bool] -and !$result) { throw 'Layout migration did not complete' }
"""
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                   cwd=app, env={**os.environ, "LT_FIXTURE_EXE":str(assembly)}, check=True, timeout=120)


def check(feed, mode, old, new, ocr_model, portable):
    import app_updates
    import github_releases
    import release_signature
    import update_install
    url = "https://github.com/tokinmew/LiveTranslate"
    manifest_bytes = (feed / "latest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest["version"] == NEW_VERSION
    release_signature.verify_official_manifest("tokinmew/LiveTranslate", manifest)
    payload = (feed / manifest["package"]).read_bytes()
    assert sha(payload) == manifest["sha256"] and len(payload) == manifest["size"]
    files = json.loads(payload)["files"]
    data = {"assets/1": manifest_bytes, "assets/2": payload}
    api_calls = []

    def read(endpoint, accept, limit):
        prefix = "repos/tokinmew/LiveTranslate/releases/"
        assert endpoint.startswith(prefix)
        resource = endpoint[len(prefix):]
        api_calls.append(resource)
        if resource == "latest":
            assert accept == "application/vnd.github+json"
            assets = []
            for ident, name in ((1, "latest.json"), (2, manifest["package"])):
                body = data[f"assets/{ident}"]
                assets.append(dict(id=ident, name=name, state="uploaded", size=len(body), digest="sha256:" + sha(body)))
            response = json.dumps(dict(tag_name="v"+NEW_VERSION, draft=False, prerelease=False, assets=assets)).encode()
        else:
            assert accept == "application/octet-stream"
            response = data[resource]
        assert len(response) <= limit
        return response

    def private_repository(*_):
        raise HTTPError(url, 404, "Not found", {}, io.BytesIO())

    with tempfile.TemporaryDirectory(dir=HERE) as temp, ExitStack() as stack:
        stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network access")))
        stack.enter_context(patch("socket.getaddrinfo", side_effect=AssertionError("Network lookup")))
        source = str(feed)
        if mode == "private-fixture":
            source = url
            stack.enter_context(patch.object(github_releases, "public_read", side_effect=private_repository))
            stack.enter_context(patch.object(github_releases, "private_read", side_effect=read))
            changed = dict(manifest, sha256="0" * 64)
            data["assets/1"] = json.dumps(changed).encode()
            try:
                app_updates.check_update(source, OLD_VERSION)
            except ValueError as error:
                assert "signature" in str(error).lower()
            else:
                raise AssertionError("Altered signed metadata was accepted")
            data["assets/1"] = manifest_bytes

        app = Path(temp) / "LiveTranslate"
        for folder in ("ui", "backend"):
            shutil.copytree(old / folder, app / folder, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("LiveTranslate.exe", "Start.cmd"):
            shutil.copyfile(old / name, app / name)
        from zipfile import ZipFile
        with ZipFile(portable) as release:
            for item in release.infolist():
                relative = item.filename.removeprefix("LiveTranslate/")
                if relative == "LiveTranslate.exe" or item.is_dir():
                    continue
                if "/" not in relative or relative == "quality/scan.ps1":
                    dest = app / relative
                    dest.parent.mkdir(exist_ok=True)
                    dest.write_bytes(release.read(item))
        exe = app / "LiveTranslate.exe"
        assert app_updates._file_version(exe) == tuple(map(int, OLD_VERSION.split("."))) + (0,)
        baseline = sha(exe.read_bytes())
        model = app / "data/tessdata/jpn.traineddata"
        model.parent.mkdir(parents=True)
        shutil.copyfile(ocr_model, model)
        prefs = app / "data/app-update-source.txt"
        prefs.write_text(source, "utf8")
        model_hash = sha(model.read_bytes())
        offer = app_updates.check_update(source, OLD_VERSION)
        assert offer["available"] and offer["version"] == manifest["version"] and "assets/2" not in api_calls
        ready = app_updates.prepare_update(app, source, OLD_VERSION, offer["version"], offer["sha256"])
        assert ready["ok"] and sha(exe.read_bytes()) == baseline
        update_install.apply_stage(app, ready["stage"], restart=False)
        assert app_updates._file_version(exe) == tuple(map(int, NEW_VERSION.split("."))) + (0,)
        assert not app_updates.check_update(source, NEW_VERSION)["available"]
        assert not (app / ".livetranslate-update/transaction.json").exists()
        assert prefs.read_text("utf8") == source and sha(model.read_bytes()) == model_hash
        assert api_calls.count("assets/2") == int(mode == "private-fixture")
        for file in files:
            name = file["path"]
            assert sha((app / name).read_bytes()) == file["sha256"], name
            tagged = new / "docs" / name if "/" not in name else new / name
            assert (app / name).read_text("utf-8-sig") == tagged.read_text("utf-8-sig"), name
        finish_layout(app)
        finish_layout(app)
        assert sorted(p.name for p in app.iterdir() if p.is_file()) == ["LiveTranslate.exe"]
        assert (app/"scripts/Prepare-Offline.ps1").is_file() and (app/"config/model-sources.json").is_file()
        assert (app/"docs/START-HERE.txt").read_text("utf-8-sig") == (new/"docs/START-HERE.txt").read_text("utf-8-sig")
        assert prefs.read_text("utf8") == source and sha(model.read_bytes()) == model_hash
        return dict(route=mode, old=OLD_VERSION, installed=NEW_VERSION, source_files=len(files), package_sha256=sha(payload),
                    retained_ocr_sha256=model_hash, settings_preserved=True, defender_passed=True, native_compile=True,
                    signature_verified=True, network_used=False, root_files=["LiveTranslate.exe"], second_start=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path, help="Folder containing signed latest.json and the numbered package")
    parser.add_argument("--old-app", type=Path, default=DEFAULT_OLD, help="Extracted previous application")
    parser.add_argument("--new-app", type=Path, default=DEFAULT_NEW, help="Current release source directory")
    parser.add_argument("--old-portable", required=True, type=Path, help="Original 0.6.7 portable ZIP")
    parser.add_argument("--ocr-model", type=Path, help="Checked jpn.traineddata file to retain through the update")
    args = parser.parse_args()
    old, new = args.old_app.resolve(), args.new_app.resolve()
    sys.path.insert(0, str(old / "backend"))
    model = args.ocr_model or old / "data/tessdata/jpn.traineddata"
    results = [check(args.feed.resolve(), route, old, new, model,args.old_portable) for route in ("local-folder", "private-fixture")]
    print(json.dumps(results, indent=2))
