"""GitHub-only updater regressions for installations with legacy local feeds."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate/backend"))
import app_updates as updates
import github_releases as gh
import release_signature


class GitHubOnlyInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app with spaces"
        self.root.mkdir()
        (self.root / "data").mkdir()
        (self.root / "LiveTranslate.exe").write_bytes(b"original dashboard")
        (self.root / "data" / "settings.json").write_bytes(b"retained settings")
        (self.root / "data" / "model.bin").write_bytes(b"retained model")
        (self.root / "data" / "app-update-source.txt").write_text(str(self.root / "updates/feed/latest.json"))
        local = self.root / "updates" / "feed"
        local.mkdir(parents=True)
        (local / "latest.json").write_bytes(b"legacy or corrupt local snapshot")
        self.before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        source = "// synthetic dashboard source"
        self.raw = json.dumps({"version": "0.6.10", "files": [
            {"path": "ui/Program.cs", "text": source, "sha256": sha256(source.encode()).hexdigest()}
        ]}).encode()
        self.manifest = {"schema": 1, "product": "LiveTranslate", "version": "0.6.10",
                         "package": "LiveTranslate-0.6.10.json", "size": len(self.raw),
                         "sha256": sha256(self.raw).hexdigest()}
        self.asset = gh.Asset("repos/tokinmew/LiveTranslate/releases/assets/22", len(self.raw), self.manifest["sha256"])
        release = patch.object(gh, "release", return_value=("0.6.10", json.dumps(self.manifest).encode(), self.asset))
        self.release = release.start()
        self.addCleanup(release.stop)
        verify = patch.object(release_signature, "verify_official_manifest")
        self.verify = verify.start()
        self.addCleanup(verify.stop)
        modules = patch.dict(sys.modules, installed_feed=None, installed_feed_seed=None)
        modules.start()
        self.addCleanup(modules.stop)

    def assert_original_files_untouched(self):
        for path, content in self.before.items():
            self.assertEqual(content, (self.root / path).read_bytes(), str(path))

    def test_stale_preferences_and_cache_do_not_override_or_modify_published_result(self):
        result = updates.check_update("0.6.9")
        self.assertTrue(result["available"])
        self.assertEqual("0.6.10", result["version"])
        self.release.assert_called_once_with(updates.OFFICIAL_REPOSITORY, updates.MAX_MANIFEST, updates.MAX_PACKAGE)
        self.verify.assert_called_once_with("tokinmew/livetranslate", self.manifest)
        self.assert_original_files_untouched()
        self.assertEqual(set(self.before), {path.relative_to(self.root) for path in self.root.rglob("*") if path.is_file()})

    def test_online_current_check_neither_prefetches_nor_initializes_local_snapshot(self):
        with patch.object(gh, "public_read", side_effect=AssertionError("Unnecessary package download")):
            result = updates.check_update("0.6.10")
        self.assertFalse(result["available"])
        self.assertEqual("0.6.10", result["version"])
        self.assert_original_files_untouched()

    def test_unreachable_github_never_reports_local_version_as_current(self):
        for failure in (gh.SourceUnavailable("GitHub unavailable"), URLError("offline"), ValueError("bad signature")):
            with self.subTest(failure=failure):
                self.release.side_effect = failure
                with self.assertRaises(type(failure)):
                    updates.check_update("0.6.9")
        self.assert_original_files_untouched()

    def test_local_manifest_and_arbitrary_streams_cannot_be_read_as_update_assets(self):
        for value in (self.root / "updates/feed/latest.json", str(self.root),
                      "https://example.com/latest.json", "http://127.0.0.1:8080/latest.json", io.BytesIO(b"local")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "GitHub release assets"):
                updates._read(value, 4096)

    def prepare(self, builder):
        with patch.object(gh, "public_read", return_value=self.raw), \
                patch.object(updates, "_file_version", return_value=updates._version("0.6.9")), \
                patch.object(updates, "_build_and_scan", side_effect=builder):
            return updates.prepare_update(self.root, "0.6.9", "0.6.10", self.manifest["sha256"])

    def test_prepare_stages_verified_github_bytes_without_cache_or_model_settings_changes(self):
        def build(root, stage, files, version):
            self.assertEqual("0.6.10", version)
            self.assertEqual(files["ui/Program.cs"], (stage / "ui/Program.cs").read_bytes())
            (stage / "LiveTranslate.exe").write_bytes(b"synthetic compiled dashboard")
        result = self.prepare(build)
        self.assertEqual("0.6.10", result["version"])
        candidate = self.root / ".livetranslate-update" / ("candidate-" + result["stage"])
        receipt = json.loads((candidate / "stage-receipt.json").read_bytes())
        self.assertEqual(sha256(b"original dashboard").hexdigest(), receipt["base"])
        self.assertEqual(sha256(b"synthetic compiled dashboard").hexdigest(), receipt["files"]["LiveTranslate.exe"])
        self.assert_original_files_untouched()

    def test_compile_or_defender_failure_publishes_no_candidate(self):
        for failure in (ValueError("Dashboard compilation failed"), ValueError("Defender did not confirm clean")):
            with self.subTest(failure=failure), self.assertRaises(type(failure)):
                self.prepare(Mock(side_effect=failure))
            self.assertFalse(list((self.root / ".livetranslate-update").glob("candidate-*")))
            self.assertFalse(list((self.root / ".livetranslate-update").glob("stage-*")))
        self.assert_original_files_untouched()

    def test_changed_release_and_downgrade_are_refused_before_staging(self):
        for version, digest, message in (("0.6.11", self.manifest["sha256"], "changed"),
                                         ("0.6.10", "0" * 64, "changed")):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, message):
                updates.prepare_update(self.root, "0.6.9", version, digest)
        with self.assertRaisesRegex(ValueError, "newer"):
            updates.prepare_update(self.root, "0.6.10", "0.6.10", self.manifest["sha256"])
        self.assertFalse((self.root / ".livetranslate-update").exists())
        self.assert_original_files_untouched()


class GitHubOnlyCommandTests(unittest.TestCase):
    def test_removed_source_and_fallback_arguments_are_rejected(self):
        for option in (("--feed", "C:/latest.json"), ("--feed", "https://github.com/other/repo"),
                       ("--feed", "https://example.com/latest.json"), ("--serve-local",),
                       ("--automatic",), ("--bundled",)):
            with self.subTest(option=option), patch.object(sys, "argv", ["app_updates.py", "check", "--installed", "0.6.9", *option]), \
                    patch.object(updates, "_manifest") as request, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    updates.main()
                self.assertEqual(2, stopped.exception.code)
                request.assert_not_called()

    def test_check_command_requires_no_source_and_dispatches_fixed_channel(self):
        result = {"ok": True, "available": False, "version": "0.6.10"}
        output = io.StringIO()
        with patch.object(sys, "argv", ["app_updates.py", "check", "--installed", "0.6.10"]), \
                patch.object(updates, "check_update", return_value=result) as request, redirect_stdout(output):
            self.assertEqual(0, updates.main())
        request.assert_called_once_with("0.6.10")
        self.assertEqual(result, json.loads(output.getvalue()))

    def test_failed_check_returns_error_without_local_success_status(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["app_updates.py", "check", "--installed", "0.6.9"]), \
                patch.object(updates, "check_update", side_effect=gh.SourceUnavailable("GitHub unavailable")), redirect_stdout(output):
            self.assertEqual(1, updates.main())
        self.assertEqual({"ok": False, "error": "GitHub unavailable"}, json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
