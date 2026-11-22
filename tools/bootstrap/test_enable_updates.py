"""Offline bootstrap checks for the Windows update ZIP layout."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import enable_updates as updater


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.contents = b"entry_point = None\n"
        records = [
            {"path": name, "text": self.contents.decode(), "sha256": updater.sha(self.contents)}
            for name in sorted(updater.HELPERS)
        ]
        self.package = json.dumps({"version": updater.VERSION, "files": records}).encode()
        self.manifest = {
            "schema": 1, "product": "LiveTranslate", "version": updater.VERSION,
            "package": updater.PACKAGE, "size": len(self.package), "sha256": updater.sha(self.package)
        }
        self.pin = patch.object(updater, "PACKAGE_SHA256", self.manifest["sha256"])
        self.pin.start()
        self.addCleanup(self.pin.stop)
        (self.folder / "latest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.folder / updater.PACKAGE).write_bytes(self.package)

    def test_only_two_pinned_helpers_are_extracted(self):
        _, payload, components = updater.seed_inputs(self.folder)
        self.assertEqual(self.package, payload)
        self.assertEqual({path: self.contents for path in updater.HELPERS}, components)

    def test_same_length_changed_package_rejected(self):
        (self.folder / updater.PACKAGE).write_bytes(self.package[:-1] + b" ")
        with self.assertRaisesRegex(ValueError, "changed"):
            updater.seed_inputs(self.folder)

    def test_external_manifest_cannot_choose_different_package(self):
        self.manifest["package"] = "../elsewhere.json"
        (self.folder / "latest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest"):
            updater.seed_inputs(self.folder)

    def test_existing_configured_or_newer_feed_is_preserved(self):
        releases = self.folder / "LiveTranslate/Releases"
        releases.mkdir(parents=True)
        old = releases / "latest.json"
        old.write_bytes(b"newer release")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder)}):
            updater.seed_personal_feed(b"new manifest", self.package)
        self.assertEqual(old.read_bytes(), b"newer release")
        self.assertFalse((releases / updater.PACKAGE).exists())

    @unittest.skipUnless(os.name == "nt", "Windows no-replace rename semantics")
    def test_preexisting_conflicting_package_never_overwritten(self):
        releases = self.folder / "LiveTranslate/Releases"
        releases.mkdir(parents=True)
        other = releases / updater.PACKAGE
        other.write_bytes(b"different contents")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder)}):
            with self.assertRaisesRegex(ValueError, "different release"):
                updater.seed_personal_feed(b"new manifest", self.package)
        self.assertEqual(other.read_bytes(), b"different contents")
        self.assertFalse((releases / "latest.json").exists())


if __name__ == "__main__":
    unittest.main()
