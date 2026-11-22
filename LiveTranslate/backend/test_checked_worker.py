"""All GUI network actions are explicit and use only the reviewed installer."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from test_worker import FakeAudio, FakeScreen, FakeText
from worker import Worker


class CheckedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patches = [patch("worker.AudioEngine", FakeAudio), patch("worker.TextEngine", FakeText),
                        patch("worker.ScreenEngine", FakeScreen), patch.object(Worker, "_jobs", lambda self: None)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.worker = Worker(Path(self.temp.name) / "data", self.events.append)
        self.addCleanup(self.worker.close)
        self.install = Mock()
        self.worker.checked_setup.install = self.install
        self.legacy = [patch.object(self.worker.text, "install", side_effect=AssertionError("legacy text URL")),
                       patch.object(self.worker.text, "catalog", side_effect=AssertionError("legacy catalog URL"), create=True),
                       patch.object(self.worker.audio, "download_model", side_effect=AssertionError("legacy speech URL")),
                       patch.object(self.worker.screen, "install_ocr_language", side_effect=AssertionError("legacy OCR URL"))]
        for item in self.legacy:
            item.start()
            self.addCleanup(item.stop)

    def test_only_explicit_all_four_calls_installer_once(self):
        self.worker.execute({"command": "install_all_profiles", "id": 91})
        self.install.assert_called_once_with()
        self.assertEqual(91, self.events[-1]["id"])
        self.assertEqual("ok", self.events[-1]["type"])
        self.assertEqual("checked_four_language_set", self.events[-1]["download_policy"]["mode"])

    def test_individual_buttons_do_not_silently_fetch_the_large_set(self):
        requests = [{"command": command, "language": code}
                    for command in ("install_profile", "install_language") for code in ("zt", "zh", "ko", "ja")]
        requests += [{"command": "install_ocr", "language": code} for code in ("chi_tra", "chi_sim", "kor", "jpn", "jpn_vert")]
        requests.append({"command": "download_speech", "model": "base"})
        for request in requests:
            with self.subTest(request=request), self.assertRaisesRegex(ValueError, "Install all four"):
                self.worker.execute(request)
        self.install.assert_not_called()

    def test_unsupported_downloads_fail_without_any_fallback(self):
        for request in ({"command": "install_language", "language": "fr"},
                        {"command": "install_ocr", "language": "eng"},
                        {"command": "download_speech", "model": "small"},
                        {"command": "download_speech", "model": "medium"}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.worker.execute(request)
        self.install.assert_not_called()

    def test_catalog_is_local_and_limited_to_reviewed_profiles(self):
        self.worker.execute({"command": "catalog", "id": 9})
        self.assertEqual({"zt", "zh", "ko", "ja"}, {row["code"] for row in self.events[-1]["languages"]})
        self.install.assert_not_called()

    def test_local_owner_supplied_import_is_retained_and_identified(self):
        with patch.object(self.worker.text, "import_pack", create=True) as importer:
            self.worker.execute({"command": "import_pack", "path": "local.argosmodel", "id": 7})
        importer.assert_called_once_with("local.argosmodel")
        self.assertIn("user-supplied", self.events[-1]["message"])
        self.install.assert_not_called()

    def test_installer_failure_refreshes_available_assets_but_never_claims_success(self):
        self.install.side_effect = RuntimeError("hash mismatch")
        with self.assertRaisesRegex(RuntimeError, "No alternative downloader"):
            self.worker.execute({"command": "install_all_profiles", "id": 4})
        self.assertEqual("status", self.events[-1]["type"])
        self.assertIn("installed_languages", self.events[-1])
        self.assertFalse(any(row.get("type") == "ok" for row in self.events))

    def test_active_audio_or_screen_rejects_model_changes_before_download(self):
        self.worker.audio.running = True
        with self.assertRaisesRegex(RuntimeError, "Turn listening Off"):
            self.worker.execute({"command": "install_all_profiles"})
        self.worker.audio.running = False
        self.worker.screen_current = SimpleNamespace(stop=threading.Event())
        with self.assertRaisesRegex(RuntimeError, "screen watching Off"):
            self.worker.execute({"command": "install_all_profiles"})
        self.install.assert_not_called()

    def test_shutdown_cancels_setup_and_suppresses_late_errors(self):
        self.worker.close()
        self.assertTrue(self.worker.checked_setup.cancel_event.is_set())
        self.worker._failure({"command": "install_all_profiles", "id": 1}, RuntimeError("late"))
        self.assertEqual([], self.events)


if __name__ == "__main__":
    unittest.main()

