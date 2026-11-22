"""Regression coverage for one installation shared across four selectable sources."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from language_routes import with_source_options
from test_worker import FakeAudio, FakeScreen, FakeText
from worker import Worker


class CombinedSetupTests(unittest.TestCase):
    def test_all_four_retries_only_the_checked_pipeline_without_engine_downloaders(self):
        events = []
        with tempfile.TemporaryDirectory() as directory, \
                patch("worker.AudioEngine", FakeAudio), patch("worker.TextEngine", FakeText), \
                patch("worker.ScreenEngine", FakeScreen), patch.object(Worker, "_jobs", lambda self: None):
            worker = Worker(Path(directory) / "data", events.append)
            self.addCleanup(worker.close)
            with patch.object(worker.checked_setup, "install", side_effect=[RuntimeError("scan interrupted"), None]) as checked:
                with self.assertRaisesRegex(RuntimeError, "No alternative downloader"):
                    worker.execute({"command": "install_all_profiles", "id": 5})
                worker.execute({"command": "install_all_profiles", "id": 6})
            self.assertEqual(2, checked.call_count)
            self.assertEqual([], worker.text.trace)
            self.assertEqual([], worker.screen.trace)
            self.assertEqual([], worker.audio.trace)
            self.assertEqual(6, events[-1]["id"])
            self.assertEqual("checked_four_language_set", events[-1]["download_policy"]["mode"])

    def test_text_code_is_preserved_when_engines_use_different_language_codes(self):
        packs = [{"code": code, "name": code} for code in ["zt", "pb", "xx", "fr"]]
        routes = with_source_options(packs)
        self.assertEqual([("zt", "zh", "chi_tra"), ("pb", "pt", "por"), ("xx", "", ""),
                          ("fr", "fr", "fra")],
                         [(r["code"], r["speech_language"], r["ocr_language"]) for r in routes])
