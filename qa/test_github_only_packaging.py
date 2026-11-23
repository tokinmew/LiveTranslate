"""Check that new installers cannot reintroduce a bundled update channel."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


portable = module("portable_builder", "tools/build_portable.py")
installer = module("installer_builder", "installer/build_kit.py")


class GithubOnlyPackaging(unittest.TestCase):
    def test_portable_drops_old_feed_but_retains_runtime_and_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            sources = {
                "LiveTranslate.exe": b"fixture executable",
                "ocr-tools/EnglishOcr.exe": b"fixture OCR helper",
                "scripts/Prepare-Offline.ps1": b"fixture setup",
                "scripts/Start.cmd": b"fixture launcher",
                "config/model-sources.json": b"{}",
                "config/requirements.txt": b"fixture dependency",
                "docs/README.md": b"fixture guide",
                "docs/START-HERE.txt": b"fixture start",
                "docs/VALIDATION.md": b"fixture validation",
                "backend/worker.py": b"# fixture worker",
                "ui/Program.cs": b'[assembly: AssemblyFileVersion("0.6.10.0")]',
            }
            for name, content in sources.items():
                path = app / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            base = root / "base.zip"
            with zipfile.ZipFile(base, "w") as archive:
                archive.writestr("LiveTranslate/runtime/python.exe", b"retained runtime")
                archive.writestr("LiveTranslate/data/model.bin", b"retained model")
                archive.writestr("LiveTranslate/updates/feed/latest.json", b"stale local release")
                archive.writestr("LiveTranslate/updates/feed/LiveTranslate-0.6.9.json", b"old package")
            expected = hashlib.sha256(base.read_bytes()).hexdigest()
            output = root / "portable.zip"
            with patch.object(portable, "BASE_SHA256", expected):
                portable.build(app, base, output)
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any(name.startswith("LiveTranslate/updates/") for name in archive.namelist()))
                self.assertEqual(archive.read("LiveTranslate/runtime/python.exe"), b"retained runtime")
                self.assertEqual(archive.read("LiveTranslate/data/model.bin"), b"retained model")
            _, manifest = installer.read_package(output, "0.6.10")
            self.assertNotIn(b"updates/feed/", manifest)

    def test_installer_rejects_new_portable_with_a_local_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "portable.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("LiveTranslate/LiveTranslate.exe", b"fixture executable")
                archive.writestr("LiveTranslate/scripts/start.cmd", b"fixture launcher")
                archive.writestr("LiveTranslate/backend/worker.py", b"# fixture worker")
                archive.writestr("LiveTranslate/updates/feed/latest.json", b"stale local release")
            with self.assertRaisesRegex(ValueError, "must not bundle a local update feed"):
                installer.read_package(archive_path, "0.6.10")

    def test_offline_recovery_builder_cannot_package_new_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "latest.json").write_text(json.dumps({"version": "0.6.10"}), encoding="utf8")
            result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tools/build_small_update.py"),
                                     str(root), str(root / "offline.zip")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"must be published to public GitHub Releases", result.stderr)
            self.assertFalse((root / "offline.zip").exists())


if __name__ == "__main__":
    unittest.main()
