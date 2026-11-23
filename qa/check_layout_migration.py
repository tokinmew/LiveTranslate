"""Exercise migration, retries, shortcut adaptation and uninstall in temporary fixtures."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-setup", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    app = repo / "LiveTranslate"
    csc = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    ps = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    args.scratch.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=args.scratch, prefix="m68-") as directory:
        tmp = Path(directory).resolve()
        runner = tmp / "test.exe"
        source = tmp / "Probe.cs"
        source.write_text('class Probe { static int Main(string[] a) { if (a.Length == 2) ManagedLayout.Retarget(a[0],a[1]); '
                          'else LayoutMigration.Organize(a[0]); return 0; } }', encoding="utf-8")
        subprocess.run([str(csc), "/nologo", "/target:exe", "/platform:x64", "/r:System.Windows.Forms.dll",
                        "/out:" + str(runner), str(source), *[str(app / "ui" / file) for file in
                        ("LayoutMigration.cs","ManagedLayout.cs","LayoutFiles.cs")]], check=True)
        base = tmp / "managed"
        root = base / "app"
        support = root / ".lt-setup"
        support.mkdir(parents=True)
        (base / ".managed").write_text("LiveTranslate Windows per-user install v1")
        with zipfile.ZipFile(args.legacy_setup) as z:
            for name in ("Setup.ps1","files.json"):
                (support / name).write_bytes(z.read(name))
        before = (support / "Setup.ps1").read_bytes()
        (root / "README.md").write_bytes(b"My older root readme")
        (root / "docs").mkdir()
        (root / "docs/README.md").write_bytes(b"My handwritten docs content")
        (root / "custom.txt").write_bytes(b"unrelated")
        (root / "setup.lock").touch()
        (root / "LiveTranslate.exe").touch()  # payload is not launched in this test
        (root / "ui").mkdir()
        (root / "ui/LayoutMigration.cs").write_text("owned")
        (root / "data").mkdir()
        (root / "data/test-model").write_text("keep")
        started = [subprocess.Popen([str(runner),str(root) + os.sep]) for _ in range(3)]
        assert all(p.wait(timeout=30) == 0 for p in started)
        assert set(p.name for p in root.iterdir() if p.is_file()) == {"custom.txt","LiveTranslate.exe"}
        assert (root / "docs/README.md").read_bytes() == (app / "docs/README.md").read_bytes()
        assert (root / "quality/scan.ps1").read_bytes() == (app / "quality/scan.ps1").read_bytes()
        assert (support / "Setup.ps1").read_bytes() != before
        backup = root / "migration-backup/0.6.8"
        assert (backup / "managed/Setup.ps1").read_bytes() == before
        assert (backup / "docs/README.md").read_bytes() == b"My handwritten docs content"
        assert (backup / "previous-root/README.md").read_bytes() == b"My older root readme"
        assert (root / "data/test-model").read_text() == "keep"
        assert (root / "custom.txt").read_bytes() == b"unrelated"
        print("PASS trailing-slash managed migration, three concurrent starts, old lock, exact resources and user content retention.")

        # Simulate interruption just before archiving the remaining legacy file.
        (root / ".livetranslate-update/layout-0.6.8.txt").unlink()
        (root / "Start.cmd").write_bytes(b"previous launcher")
        subprocess.run([str(runner), str(root)], check=True)
        assert (backup / "previous-root/Start.cmd").read_bytes() == b"previous launcher"
        assert len(list((backup / "managed").iterdir())) == 1
        print("PASS interrupted migration resumes without overwriting its original backup.")
        menu = tmp / "Start Menu"
        menu.mkdir()
        env = {k:v for k,v in os.environ.items() if k.upper() != "PSMODULEPATH"}
        env.update(LT_TEST_ROOT=str(root), LT_TEST_MENU=str(menu), LT_TEST_RUNNER=str(runner))
        test = r"""
$ErrorActionPreference='Stop'
$app=$env:LT_TEST_ROOT; $menu=$env:LT_TEST_MENU
$file=Join-Path $menu 'LiveTranslate.lnk'
$shell=New-Object -ComObject WScript.Shell
try {
  $shortcut=$shell.CreateShortcut($file)
  $shortcut.TargetPath=Join-Path $app 'Start.cmd'; $shortcut.Save()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut)
  & $env:LT_TEST_RUNNER $app $menu
  if ($LASTEXITCODE) {throw 'Shortcut migration failed'}
  $shortcut=$shell.CreateShortcut($file)
  if ($shortcut.TargetPath -ine (Join-Path $app 'LiveTranslate.exe')) {throw 'Did not retarget old launcher'}
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut)
} finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) }
. (Join-Path $app '.lt-setup/Setup.ps1')
Uninstall-Portable ([IO.Path]::GetDirectoryName($app)) $menu $false
if (Test-Path -LiteralPath $file) {throw 'Launch shortcut survived uninstall'}
"""
        subprocess.run([str(ps), "-NoProfile", "-NonInteractive","-ExecutionPolicy","RemoteSigned","-Command",test],
                       check=True, env=env, cwd=tmp)
        assert not (root / "docs/README.md").exists() and not (root / "scripts/Prepare-Offline.ps1").exists()
        assert not (root / "ui/LayoutMigration.cs").exists()
        assert (backup / "previous-root/README.md").exists() and (root / "data/test-model").exists()
        assert (root / "custom.txt").exists()
        print("PASS migrated .lnk and original managed uninstall remove organized app files while retaining unrelated data and archived originals.")


if __name__ == "__main__":
    main()
