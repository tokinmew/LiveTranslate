"""Windows tests for the authenticated, per-install offline release snapshot."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate" / "backend"))
import installed_feed as feed


@unittest.skipUnless(os.name == "nt", "Official signature verification uses Windows CryptoAPI.")
class InstalledFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "app with spaces"
        self.root.mkdir()
        env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "local")})
        env.start()
        self.addCleanup(env.stop)
        self.manifest = self.root / "updates" / "feed" / "latest.json"
        self.seed = feed._baseline()

    def export(self, where):
        where.mkdir(parents=True, exist_ok=True)
        manifest = where / "latest.json"
        manifest.write_bytes(self.seed.raw)
        (where / self.seed.info["package"]).write_bytes(self.seed.package)
        return manifest

    def save_pref(self, value):
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        (data / "app-update-source.txt").write_text(str(value), "utf-8")

    def test_baseline_is_authentic_and_stable(self):
        result = feed.installed_snapshot(self.root)
        self.assertEqual(result, {"ok": True, "manifest": str(self.manifest), "version": "0.6.8",
                                  "sha256": self.seed.info["sha256"]})
        self.assertEqual(self.manifest.read_bytes(), self.seed.raw)
        package = self.manifest.with_name(self.seed.info["package"])
        self.assertEqual(package.read_bytes(), self.seed.package)
        stat = self.manifest.stat()
        self.assertEqual(feed.installed_snapshot(self.root), result)
        self.assertEqual(stat.st_mtime_ns, self.manifest.stat().st_mtime_ns)
        self.assertFalse((self.root / ".lt-setup").exists())

    def test_specific_extracted_feed_migrates_but_custom_path_is_preserved(self):
        stock = self.export(self.base / "LiveTranslate-0.6.8-Local-Update-Feed")
        self.save_pref(stock)
        self.assertEqual(feed.installed_snapshot(self.root)["migrate_source"], str(stock))
        custom = self.export(self.base / "custom")
        self.save_pref(custom)
        self.assertNotIn("migrate_source", feed.installed_snapshot(self.root))
        self.assertEqual((self.root / "data" / "app-update-source.txt").read_text(), str(custom))

    def test_existing_invalid_signed_data_is_reported_and_preserved(self):
        manifest = self.export(self.manifest.parent)
        parsed = json.loads(manifest.read_bytes())
        signature = parsed["release_signature"]
        parsed["release_signature"] = ("B" if signature[0] == "A" else "A") + signature[1:]
        changed = json.dumps(parsed).encode()
        manifest.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "release signature"):
            feed.installed_snapshot(self.root)
        self.assertEqual(manifest.read_bytes(), changed)
        manifest.write_bytes(self.seed.raw)
        self.manifest.with_name(self.seed.info["package"]).write_bytes(b"partial")
        with self.assertRaisesRegex(ValueError, "differs from"):
            feed.installed_snapshot(self.root)
        self.assertEqual(self.manifest.with_name(self.seed.info["package"]).read_bytes(), b"partial")

    def test_partial_write_retries_without_publishing_an_incomplete_pair(self):
        real = feed._atomic_bytes

        def interrupt(path, data):
            if path == self.manifest:
                raise OSError("interrupted before commit")
            real(path, data)

        with patch.object(feed, "_atomic_bytes", interrupt), self.assertRaises(OSError):
            feed.installed_snapshot(self.root)
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.manifest.with_name(self.seed.info["package"]).read_bytes(), self.seed.package)
        self.assertEqual(feed.installed_snapshot(self.root)["version"], "0.6.8")

    def test_concurrent_readers_complete_under_one_lock(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(feed.installed_snapshot, [self.root] * 3))
        self.assertEqual(results, [results[0]] * 3)
        self.assertEqual(self.manifest.read_bytes(), self.seed.raw)
        self.assertEqual((self.manifest.parent / ".publish.lock").read_bytes(), b"0")

    def test_unc_urls_and_nonlocal_drive_selections_are_never_opened(self):
        for preference in ("https://github.com/tokinmew/LiveTranslate", "//server/updates/latest.json",
                           "relative/latest.json", "//?/C:/updates/latest.json", "C:/../latest.json"):
            with self.subTest(preference=preference):
                self.assertIsNone(feed._local_file(preference))
        self.save_pref("//server/updates/latest.json")
        self.assertNotIn("migrate_source", feed.installed_snapshot(self.root))

    def test_nonstock_optional_feed_is_ignored(self):
        stock = self.export(self.base / "LiveTranslate-0.6.8-Local-Update-Feed")
        stock.with_name(self.seed.info["package"]).write_bytes(b"bad")
        self.save_pref(stock)
        result = feed.installed_snapshot(self.root)
        self.assertNotIn("migrate_source", result)
        self.assertEqual(self.manifest.with_name(self.seed.info["package"]).read_bytes(), self.seed.package)

    def test_authenticated_newer_version_beats_source_and_baseline(self):
        # Stand in for a future verified identity to exercise ordering independently of signing.
        manifest = self.export(self.manifest.parent)
        current = self.seed.info.copy()
        current.update(version="0.6.9", package="LiveTranslate-0.6.9.json")
        blob = json.dumps(current).encode()
        manifest.write_bytes(blob)
        manifest.with_name(current["package"]).write_bytes(self.seed.package)
        stock = self.export(self.base / "custom")
        self.save_pref(stock)
        actual = feed._identity
        with patch.object(feed, "_identity", lambda raw: current if raw == blob else actual(raw)):
            self.assertEqual(feed.installed_snapshot(self.root)["version"], "0.6.9")
        self.assertEqual(manifest.read_bytes(), blob)

    def test_signed_older_existing_snapshot_promotes_newer_local_import(self):
        current = self.seed.info.copy()
        current.update(version="0.6.9", package="LiveTranslate-0.6.9.json")
        blob = json.dumps(current).encode()
        local = Path(os.environ["LOCALAPPDATA"]) / "LiveTranslate" / "Releases"
        local.mkdir(parents=True)
        (local / "latest.json").write_bytes(blob)
        (local / current["package"]).write_bytes(self.seed.package)
        self.export(self.manifest.parent)
        actual = feed._identity
        with patch.object(feed, "_identity", lambda raw: current if raw == blob else actual(raw)):
            result = feed.installed_snapshot(self.root)
        self.assertEqual(result["version"], "0.6.9")
        self.assertNotIn("migrate_source", result)
        self.assertEqual(self.manifest.read_bytes(), blob)

    def test_own_installation_receipt_matches_installed_files(self):
        support = self.root / ".lt-setup"
        support.mkdir()
        (support / "files.json").write_bytes(b"{}")
        feed.installed_snapshot(self.root)
        receipt = json.loads((support / "feed-0.6.8.json").read_bytes())
        self.assertEqual(receipt, {"manifest_sha256": hashlib.sha256(self.seed.raw).hexdigest(),
                                   "package_sha256": self.seed.info["sha256"]})

    def test_download_cache_validates_before_touching_installation(self):
        with self.assertRaisesRegex(ValueError, "differs from"):
            feed.cache_official_snapshot(self.root, self.seed.raw, b"incomplete")
        self.assertFalse(self.manifest.exists())
        result = feed.cache_official_snapshot(self.root, self.seed.raw, self.seed.package)
        self.assertEqual(result["sha256"], self.seed.info["sha256"])
        self.assertEqual(self.manifest.read_bytes(), self.seed.raw)


if __name__ == "__main__":
    unittest.main()
