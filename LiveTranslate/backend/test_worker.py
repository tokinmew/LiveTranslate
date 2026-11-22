"""Test capture cancellation and protocol behavior without models or devices."""
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from worker import Worker


class FakeText:
    def __init__(self, root):
        self.codes = {"ja"}
        self.trace = []
    def installed(self): return [{"code": code, "name": code} for code in sorted(self.codes)]
    def install(self, code):
        self.trace.append("text:" + code)
        self.codes.add(code)
    def translate(self, text, source): return {"text": "English result", "language": source}


class FakeAudio:
    def __init__(self, root, send):
        self.starts = []
        self.stops = 0
        self.models = ["base"]
        self.running = False
        self.trace = []
    def stop(self): self.stops += 1
    def start(self, *args, **kwargs): self.starts.append(args)
    def installed_models(self): return self.models[:]
    def download_model(self, model):
        self.trace.append("speech:" + model)
        self.models.append(model)
    def devices(self): return []


class FakeScreen:
    def __init__(self, root):
        self.codes = {"jpn"}
        self.trace = []
    def languages(self): return sorted(self.codes)
    def local_languages(self): return sorted(self.codes)
    def engine_ready(self): return True
    def resolve_engine(self, executable=""): return executable
    def auto_language(self, executable=""): return "+".join(code for code in ("chi_tra", "chi_sim", "kor", "jpn", "eng") if code in self.codes)
    def install_ocr_language(self, code):
        self.trace.append("ocr:" + code)
        self.codes.add(code)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [patch("worker.TextEngine", FakeText), patch("worker.AudioEngine", FakeAudio),
                        patch("worker.ScreenEngine", FakeScreen), patch.object(Worker, "_jobs", lambda self: None)]
        for item in self.patches: item.start()
        self.worker = Worker(Path(self.directory.name), self.events.append)

    def tearDown(self):
        self.worker.close()
        for item in reversed(self.patches): item.stop()
        self.directory.cleanup()

    def test_startup_does_not_capture(self):
        self.assertEqual([], self.worker.audio.starts)
        self.assertIsNone(self.worker.screen_thread)

    def test_optional_speech_translator_receives_only_foreign_segments(self):
        from unittest.mock import Mock
        engine = Mock()
        engine.name = "nllb"
        engine.translate_many.return_value = ["Where is the station?"]
        with patch("speech_translation.load_local_model", return_value=engine) as load:
            self.assertTrue(self.worker._translate_speech_source("Hello there", "ja")["ignored"])
            load.assert_not_called()
            answer = self.worker._translate_speech_source("駅はどこですか？", "ja")
            self.assertEqual(answer["text"], "Where is the station?")
            self.assertEqual(answer["engine"], "nllb")
            self.worker._translate_speech_source("駅はどこですか？", "ja")
            load.assert_called_once()

    def test_optional_speech_translator_normalizes_mixed_mandarin_scripts(self):
        from unittest.mock import Mock
        from text_engine import TextEngine
        self.worker.text = TextEngine(Path(self.directory.name))
        engine = Mock()
        engine.name = "nllb"
        engine.translate_many.return_value = ["Where is the station?"]
        with patch("speech_translation.load_local_model", return_value=engine):
            answer = self.worker._translate_speech_source("車站在哪里？", "zh")
        self.assertEqual(answer["text"], "Where is the station?")
        engine.translate_many.assert_called_once_with([("zh", "车站在哪里？")])

    def test_recognized_source_echo_allows_local_speech_translation_retry(self):
        with patch.object(self.worker.text, "translate", return_value={"text":"こんにちは","language":"ja"}):
            self.assertIsNone(self.worker._translate_speech_source("こんにちは", "ja"))
            self.assertTrue(self.worker._translate_speech_source("Nice to meet you", "ja")["ignored"])

    def test_speech_model_inference_leaves_screen_text_available(self):
        from unittest.mock import Mock
        started, release = threading.Event(), threading.Event()

        def translate(_phrases):
            started.set()
            release.wait(2)
            return ["Where is the station?"]

        translator = Mock()
        translator.translate_many.side_effect = translate
        translator.name = "nllb"
        self.worker.speech_translation_checked = True
        self.worker.speech_translator = translator
        job = threading.Thread(target=self.worker._translate_speech_source, args=("駅はどこですか", "ja"))
        job.start()
        try:
            self.assertTrue(started.wait(1))
            acquired = self.worker.text_lock.acquire(timeout=0.2)
            if acquired:
                self.worker.text_lock.release()
            self.assertTrue(acquired, "Screen text waited for the independent speech model.")
        finally:
            release.set()
            job.join(2)
        self.assertFalse(job.is_alive())

    def test_damaged_optional_model_uses_standard_translator_and_warns_once(self):
        with patch("speech_translation.load_local_model", side_effect=ValueError("File failed verification.")):
            first = self.worker._translate_speech_source("駅はどこですか", "ja")
            second = self.worker._translate_speech_source("電車に乗ります", "ja")
        self.assertEqual("English result", first["text"])
        self.assertEqual("English result", second["text"])
        self.assertEqual(1, sum("repair" in event.get("message", "") for event in self.events))

    def test_one_optional_inference_failure_does_not_end_listening(self):
        from unittest.mock import Mock
        engine = Mock(name="optional")
        engine.name = "nllb"
        engine.translate_many.side_effect = [RuntimeError("synthetic inference failure"), ["Here is the station."]]
        with patch("speech_translation.load_local_model", return_value=engine):
            self.assertTrue(self.worker._translate_speech_source("Already English", "ja")["ignored"])
            self.assertEqual("English result", self.worker._translate_speech_source("駅に着きました。", "ja")["text"])
            self.assertEqual("Here is the station.", self.worker._translate_speech_source("ここが駅です。", "ja")["text"])
        self.assertEqual(2, engine.translate_many.call_count)

    def test_standard_inference_failure_releases_approved_speech_to_decoder(self):
        with patch.object(self.worker, "_quality_translation", return_value=None), \
                patch.object(self.worker.text, "translate", side_effect=ValueError("synthetic bad input")):
            self.assertIsNone(self.worker._translate_speech_source("駅まで歩きます。", "ja"))
            self.assertTrue(self.worker._translate_speech_source("English only", "ja")["ignored"])

    def test_stop_cancels_audio_start_waiting_in_queue(self):
        self.worker.dispatch({"command": "start_audio", "device_id": 4})
        pending = self.worker.jobs.get_nowait()
        self.worker.dispatch({"command": "stop_audio", "id": 5})
        self.worker.execute(pending)
        self.assertEqual([], self.worker.audio.starts)
        self.assertEqual(5, self.events[-1]["id"])

    def test_new_audio_start_after_stop_is_allowed(self):
        self.worker.dispatch({"command": "stop_audio"})
        self.worker.dispatch({"command": "start_audio", "device_id": 4})
        self.worker.execute(self.worker.jobs.get_nowait())
        self.assertEqual(4, self.worker.audio.starts[0][0])

    def test_stop_cancels_pending_screen_start(self):
        self.worker.dispatch({"command": "start_screen"})
        pending = self.worker.jobs.get_nowait()
        self.worker.dispatch({"command": "stop_screen"})
        with patch.object(self.worker, "start_screen") as capture:
            self.worker.execute(pending)
            capture.assert_not_called()

    def test_shutdown_clears_queued_capture(self):
        self.worker.dispatch({"command": "start_audio", "device_id": 4})
        self.worker.dispatch({"command": "shutdown"})
        self.assertTrue(self.worker.closing.is_set())
        self.assertTrue(self.worker.jobs.empty())

    def test_protocol_preserves_request_id_and_language(self):
        self.worker.execute({"command": "translate", "id": 17, "text": "こんにちは", "source": "ja"})
        self.assertEqual({"type": "result", "id": 17, "kind": "text", "text": "English result", "language": "ja"}, self.events[-1])

    def test_empty_translation_rejected(self):
        with self.assertRaises(ValueError):
            self.worker.execute({"command": "translate", "text": "  "})

    def test_traditional_chinese_audio_uses_whisper_chinese(self):
        self.worker.dispatch({"command": "start_audio", "device_id": 4, "language": "zt"})
        self.worker.execute(self.worker.jobs.get_nowait())
        self.assertEqual("zh", self.worker.audio.starts[0][2])

    def test_vertical_screen_profile_reaches_native_ocr_without_cli(self):
        seen = []
        def recognize(region, language, executable):
            seen.append((language, executable))
            self.worker.screen_stop.set()
            return ""
        with patch.object(self.worker.screen, "recognize", side_effect=recognize, create=True):
            self.worker.start_screen({"source": "ja", "vertical": True,
                                      "region": {"left": 0, "top": 0, "width": 100, "height": 100}})
            self.worker.screen_thread.join(timeout=2)
        self.assertEqual([("jpn_vert", "")], seen)

    def test_start_commands_preserve_session_and_supersede_queued_starts(self):
        for number in range(20):
            self.worker.dispatch({"command": "start_audio", "device_id": number, "session_id": str(number)})
        self.assertEqual(1, self.worker.jobs.qsize())
        pending = self.worker.jobs.get_nowait()
        self.assertEqual("19", pending["session_id"])
        self.worker.execute(pending)
        self.assertEqual(19, self.worker.audio.starts[0][0])
        self.assertEqual("starting", [event for event in self.events if event.get("session_id") == "19"][0]["state"])

    def test_one_shot_reads_exactly_once_without_starting_watch(self):
        self.worker.dispatch({"command": "read_screen_once", "id": 101, "session_id": "once",
                              "source": "ja", "region": {"left": 0, "top": 0, "width": 100, "height": 100}})
        with patch.object(self.worker.screen, "recognize", return_value="日本語の字幕", create=True) as recognize:
            self.worker.execute(self.worker.jobs.get_nowait())
            self.worker.screen_once_thread.join(timeout=2)
        recognize.assert_called_once()
        self.assertIsNone(self.worker.screen_thread)
        result = next(event for event in self.events if event["type"] == "screen_once")
        self.assertEqual((101, "once", "日本語の字幕", "English result"),
                         (result["id"], result["session_id"], result["original"], result["text"]))
        self.assertEqual("stopped", [event for event in self.events if event["type"] == "capture_state"][-1]["state"])

    def test_cancelled_one_shot_cannot_publish_or_translate_stale_image(self):
        entered, release = threading.Event(), threading.Event()
        def recognize(*args):
            entered.set()
            release.wait(2)
            return "Old image"
        with patch.object(self.worker.screen, "recognize", side_effect=recognize, create=True), \
             patch.object(self.worker.text, "translate", wraps=self.worker.text.translate) as translate:
            self.worker.dispatch({"command": "read_screen_once", "session_id": "old", "source": "ja",
                                  "region": {"left": 0, "top": 0, "width": 100, "height": 100}})
            self.worker.execute(self.worker.jobs.get_nowait())
            self.assertTrue(entered.wait(1))
            self.worker.dispatch({"command": "cancel_read_screen_once"})
            release.set()
            self.worker.screen_once_thread.join(timeout=2)
        translate.assert_not_called()
        self.assertFalse(any(event["type"] == "screen_once" for event in self.events))

    def test_screen_restart_during_old_ocr_publishes_only_new_session(self):
        self.worker.text.codes.add("ko")
        self.worker.screen.codes.add("kor")
        entered, release, new_result = threading.Event(), threading.Event(), threading.Event()
        calls = []
        old_send = self.worker.send
        def send(event):
            old_send(event)
            if event.get("type") == "screen" and event.get("session_id") == "new":
                new_result.set()
        self.worker.send = send
        def recognize(region, language, executable):
            calls.append(language)
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            return "일본어를 번역해요" if language == "kor" else "日本語を翻訳します"
        region = {"left": 0, "top": 0, "width": 100, "height": 100}
        with patch.object(self.worker.screen, "recognize", side_effect=recognize, create=True):
            self.worker.dispatch({"command": "start_screen", "session_id": "old", "source": "ja", "region": region})
            self.worker.execute(self.worker.jobs.get_nowait())
            self.assertTrue(entered.wait(1))
            self.worker.dispatch({"command": "stop_screen"})
            self.worker.dispatch({"command": "start_screen", "session_id": "new", "source": "ko", "region": region})
            self.worker.execute(self.worker.jobs.get_nowait())
            release.set()
            self.assertTrue(new_result.wait(2))
            self.worker.dispatch({"command": "stop_screen"})
        self.assertEqual(["jpn", "kor"], calls)
        self.assertFalse(any(event["type"] == "screen" and event.get("session_id") == "old" for event in self.events))

    def test_off_during_slow_screen_preparation_prevents_capture(self):
        entered, release = threading.Event(), threading.Event()
        def auto_language(executable):
            entered.set()
            release.wait(2)
            return "jpn"
        self.worker.dispatch({"command": "start_screen", "session_id": "pending", "source": "auto", "ocr_language": "auto",
                              "region": {"left": 0, "top": 0, "width": 100, "height": 100}})
        pending = self.worker.jobs.get_nowait()
        with patch.object(self.worker.screen, "auto_language", side_effect=auto_language), \
             patch.object(self.worker.screen, "recognize", side_effect=AssertionError("No capture"), create=True):
            preparation = threading.Thread(target=self.worker.execute, args=(pending,))
            preparation.start()
            self.assertTrue(entered.wait(1))
            began = time.monotonic()
            self.worker.dispatch({"command": "stop_screen"})
            self.assertLess(time.monotonic() - began, 0.5)
            release.set()
            preparation.join(timeout=2)
        self.assertIsNone(self.worker.screen_thread)

    def test_one_shot_invalid_rectangle_never_captures(self):
        self.worker.dispatch({"command": "read_screen_once", "session_id": "bad", "source": "ja",
                              "region": {"left": 0, "top": 0, "width": 0, "height": 100}})
        with self.assertRaises(ValueError):
            self.worker.execute(self.worker.jobs.get_nowait())
        self.assertIsNone(self.worker.screen_once_thread)

    def test_watch_skips_translation_for_duplicate_text_and_resets_after_blank(self):
        done = threading.Event()
        old_send = self.worker.send
        def send(event):
            old_send(event)
            if len([value for value in self.events if value["type"] == "screen"]) == 2 and event["type"] == "screen":
                self.worker.dispatch({"command": "stop_screen"})
                done.set()
        self.worker.send = send
        original_request = self.worker._screen_request
        def fast_request(item, channel):
            request = original_request(item, channel)
            request.interval = 0.01
            return request
        with patch.object(self.worker, "_screen_request", side_effect=fast_request), \
             patch.object(self.worker.screen, "recognize", side_effect=["駅はどこですか", "駅はどこですか\nSettings", "", "駅はどこですか"], create=True), \
             patch.object(self.worker.text, "translate", wraps=self.worker.text.translate) as translate:
            self.worker.dispatch({"command": "start_screen", "session_id": "dedup", "source": "ja",
                                  "region": {"left": 0, "top": 0, "width": 100, "height": 100}})
            self.worker.execute(self.worker.jobs.get_nowait())
            self.assertTrue(done.wait(2))
        self.assertEqual(1, translate.call_count)
        self.assertEqual(1, sum(e["type"] == "screen_clear" for e in self.events))

    def test_single_profile_requires_explicit_all_four_without_downloading(self):
        with patch.object(self.worker.checked_setup, "install") as checked:
            with self.assertRaisesRegex(ValueError, "Install all four"):
                self.worker.execute({"command": "install_profile", "id": 71, "language": "ja"})
        checked.assert_not_called()
        self.assertEqual([], self.worker.text.trace)
        self.assertEqual([], self.worker.screen.trace)
        self.assertEqual([], self.worker.audio.trace)

    def test_failed_checked_setup_refreshes_assets_and_can_retry(self):
        with patch.object(self.worker.checked_setup, "install", side_effect=[RuntimeError("scan interrupted"), None]) as checked:
            with self.assertRaisesRegex(RuntimeError, "No alternative downloader"):
                self.worker.execute({"command": "install_all_profiles", "id": 71})
            self.assertEqual("status", self.events[-1]["type"])
            self.assertIn("profiles", self.events[-1])
            self.worker.execute({"command": "install_all_profiles", "id": 72})
        self.assertEqual(2, checked.call_count)
        self.assertEqual("ok", self.events[-1]["type"])
        self.assertEqual(72, self.events[-1]["id"])
        self.assertEqual([], self.worker.text.trace)
        self.assertEqual([], self.worker.screen.trace)
        self.assertEqual([], self.worker.audio.trace)

    def test_all_four_rejects_active_audio_before_downloads(self):
        self.worker.audio.running = True
        with patch.object(self.worker.checked_setup, "install") as checked:
            with self.assertRaisesRegex(RuntimeError, "Turn listening Off"):
                self.worker.execute({"command": "install_all_profiles"})
        checked.assert_not_called()
        self.assertEqual([], self.worker.text.trace)
        self.assertEqual([], self.worker.screen.trace)


if __name__ == "__main__":
    unittest.main()
