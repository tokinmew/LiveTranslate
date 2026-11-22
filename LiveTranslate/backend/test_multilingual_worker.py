"""Exercise the public capture/translation commands without opening devices."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worker import Worker
from test_worker import FakeAudio, FakeScreen


class MultilingualWorkerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, replacement in (("AudioEngine", FakeAudio), ("ScreenEngine", FakeScreen)):
            p = patch("worker." + name, replacement)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(Worker, "_jobs", lambda self: None)
        p.start()
        self.addCleanup(p.stop)
        self.worker = Worker(Path(self.temp.name), self.events.append)
        self.addCleanup(self.worker.close)

    def run_capture(self, **options):
        self.worker.dispatch(options)
        self.worker.execute(self.worker.jobs.get_nowait())
        if self.worker.screen_once_thread:
            self.worker.screen_once_thread.join(3)

    def test_independent_readiness_and_local_speech_route(self):
        self.worker.execute({"command": "status", "id": 1})
        rows = {row["code"]: row for row in self.events[-1]["profiles"]}
        self.assertGreaterEqual(len(rows), 200)
        self.assertNotIn("en", rows)
        self.assertTrue(rows["fr"]["speech_ready"])
        self.assertFalse(rows["fr"]["text_ready"])
        self.assertFalse(rows["fr"]["screen_ready"])
        self.run_capture(command="start_audio", profile="fr", device_id=-2, session_id="pc")
        self.assertEqual((-2, "base", "fr"), self.worker.audio.starts[0][:3])

    def test_missing_assets_reject_screen_before_capture(self):
        with patch.object(self.worker.screen, "recognize", create=True) as recognize, \
             patch.object(self.worker.screen, "languages", return_value=["fra"]) as langs:
            with self.assertRaisesRegex(ValueError, "text translation files"):
                self.worker._screen_request({"source": "fr"}, "screen_once")
            langs.return_value = []
            with self.assertRaisesRegex(ValueError, "recognition files"):
                self.worker._screen_request({"source": "fr"}, "screen_once")
            recognize.assert_not_called()

    def test_explicit_french_once_skips_english_and_returns_only_positioned_foreign_text(self):
        class Frame(str):
            pass
        phrase = "La bibliothèque ouvre le dimanche."
        frame = Frame("Settings\n" + phrase)
        frame.regions = [("Settings", [(0, 8, (0, 0, 55, 20))]), (phrase, [(0, len(phrase), (4, 30, 120, 52))])]
        with patch.object(self.worker.screen, "languages", return_value=["fra"]), \
             patch.object(self.worker.screen, "recognize", create=True, return_value=frame) as capture, \
             patch.object(self.worker.text, "installed", return_value=[{"code": "fr"}]), \
             patch.object(self.worker.text, "_recent_language_scores", return_value=("fr", .99, .005, .002)), \
             patch.object(self.worker.text, "translate", return_value={"text": "The library opens on Sundays.", "language": "fr"}) as translate:
            self.run_capture(command="read_screen_once", source="fr", id=8, session_id="french")
            capture.assert_called_once()
            self.assertEqual("fr", capture.call_args.kwargs["source"])
            translate.assert_called_once_with(phrase, "fr")
        reply = next(e for e in self.events if e["type"] == "screen_once")
        self.assertEqual((8, "french", "The library opens on Sundays.", phrase), (reply["id"], reply["session_id"], reply["text"], reply["original"]))
        self.assertEqual((4, 30, 116, 22), tuple(reply["regions"][0][k] for k in ("left", "top", "width", "height")))

    def test_nllb_only_handles_selected_paste_and_auto_ignores_english(self):
        phrase = "Le train entre en gare."
        with patch("worker.model_files_present", return_value=True), \
             patch.object(self.worker.text, "_recent_language_scores", return_value=("fr", .99, .005, .002)), \
             patch.object(self.worker, "_quality_translation", return_value={"text": "The train is arriving.", "language": "fr"}) as quality:
            for source in ("auto", "fr"):
                self.worker.execute({"command": "translate", "source": source, "text": "Settings\n" + phrase, "id": 4})
                self.assertEqual(("fr", "The train is arriving.", 4), tuple(self.events[-1][k] for k in ("language", "text", "id")))
            self.assertEqual([([phrase], "fr", None)] * 2, [c.args for c in quality.call_args_list])
