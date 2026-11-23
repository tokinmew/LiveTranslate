"""Exercise known 0.6.8 uninstall engines against disposable files without running an installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_case(work, probe, original, custom):
    app = work / "app"
    support = app / ".lt-setup"
    support.mkdir(parents=True)
    (work / ".managed").write_text("LiveTranslate Windows per-user install v1")
    script = support / "Setup.ps1"
    script.write_bytes(original)
    state = app / ".livetranslate-update"
    state.mkdir()
    (state / "layout-0.6.8.txt").write_text("previous fingerprint")
    subprocess.run([str(probe), str(app)], check=True)
    if custom:
        assert script.read_bytes() == original
        return

    backup = app / "migration-backup/0.6.9/managed"
    assert (backup / "Setup.ps1").read_bytes() == original
    assert len(list(backup.iterdir())) == 1
    text = script.read_text(encoding="utf-8-sig")
    stock = original.decode("utf-8-sig").replace("\r\n", "\n")
    start = text.index("        if (!$erase) {\n            $support = Under $appDir '.lt-setup'\n            $feed =")
    end = text.index("        Setup-Links $menu $appDir $true", start)
    helpers = stock[stock.index("function Plain-Path("):stock.index("function Read-List")]
    # Isolate the feed-removal block from the uninstaller that the app actually patched.
    harness = work / "fixture.ps1"
    harness.write_text("param([string]$appDir)\n$ErrorActionPreference='Stop'\n$erase=$false\n"
                       + helpers + text[start:end], encoding="utf-8-sig")
    ps = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = [str(ps), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
               "-File", str(harness), str(app)]
    child_env = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    feed = app / "updates/feed"
    feed.mkdir(parents=True)
    (feed / "mine.txt").write_text("retain")
    (feed / ".publish.lock").write_bytes(b"0")
    latest = feed / "latest.json"
    for version in ("0.6.8", "0.6.9"):
        data = ("stock " + version).encode()
        metadata = ("release " + version).encode()
        latest.write_bytes(metadata)
        (feed / ("LiveTranslate-" + version + ".json")).write_bytes(data)
        (support / ("feed-" + version + ".json")).write_text(json.dumps({
            "package_sha256": digest(data), "manifest_sha256": digest(metadata)}))
    latest.write_bytes(b"my private manifest")
    subprocess.run(command, check=True, timeout=30, env=child_env)
    assert len(list(feed.iterdir())) == 5
    latest.write_bytes(b"release 0.6.9")
    subprocess.run(command, check=True, timeout=30, env=child_env)
    assert [p.name for p in feed.iterdir()] == ["mine.txt"]
    assert not list(support.glob("feed-*.json"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-engine", type=Path, action="append", required=True,
                        help="Original installed .lt-setup/Setup.ps1 from 0.6.8 or its revision 2")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    qa = repo / "qa"
    ui = repo / "LiveTranslate/ui"
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    with tempfile.TemporaryDirectory(dir=qa) as directory:
        scratch = Path(directory)
        runner = scratch / "check.exe"
        subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/r:System.Windows.Forms.dll",
                        "/out:" + str(runner), str(qa / "CheckManagedUpdate.cs"),
                        *[str(ui / name) for name in ("LayoutMigration.cs", "ManagedLayout.cs", "LayoutFiles.cs")]],
                       check=True)
        for index, engine in enumerate(args.original_engine):
            original = engine.read_bytes()
            run_case(scratch / str(index), runner, original, False)
            run_case(scratch / (str(index) + "-custom"), runner, original + b"# Custom installer", True)
    print("PASS managed update registration, retries, both release-owned feed generations and customized file retention.")


if __name__ == "__main__":
    main()
