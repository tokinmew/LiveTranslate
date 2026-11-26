"""Logic checks only: no audio device is opened and no model is downloaded."""
from pathlib import Path
import queue
import tempfile
import unittest
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audio_engine import AudioEngine, pcm_to_mono, put_latest, validate_model
from screen_engine import ScreenEngine


class AudioControlTests(unittest.TestCase):
    def test_stereo_pcm_is_averaged_and_scaled(self):
        import struct
        # Opposite stereo samples cancel, equal samples retain amplitude.
        data = struct.pack("<hhhh", 16384, -16384, 8192, 8192)
        decoded = pcm_to_mono(data, channels=2, sample_rate=16000)
        self.assertEqual(decoded.tolist(), [0.0, 0.25])

    def test_queue_retains_latest_audio(self):
        chunks = queue.Queue(maxsize=2)
        self.assertFalse(put_latest(chunks, b"first"))
        self.assertFalse(put_latest(chunks, b"second"))
        self.assertTrue(put_latest(chunks, b"latest"))
        self.assertEqual([chunks.get_nowait(), chunks.get_nowait()], [b"second", b"latest"])

    def test_speech_translation_rejects_wrong_model(self):
        for name in ("tiny.en", "turbo", "large-v3-turbo", "../../outside"):
            with self.assertRaises(ValueError):
                validate_model(name)

    def test_missing_model_does_not_start_or_download(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), lambda event: self.fail("No event should be emitted"))
            with self.assertRaisesRegex(RuntimeError, "Download"):
                engine.start(0)
            self.assertFalse(engine.running)
            self.assertEqual(engine.installed_models(), [])

    def test_incomplete_download_is_not_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), lambda event: None)
            incomplete = Path(directory) / "speech" / "base"
            incomplete.mkdir()
            (incomplete / "model.bin").write_bytes(b"incomplete")
            self.assertNotIn("base", engine.installed_models())

    def test_empty_or_missing_vocabulary_is_not_an_installed_model(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=AudioEngine(Path(directory), lambda _:None)
            folder=engine.root / "base"
            folder.mkdir()
            for name in ("model.bin","config.json","tokenizer.json"):
                (folder/name).write_bytes(b"fixture")
            self.assertNotIn("base",engine.installed_models())
            (folder/"vocabulary.txt").write_bytes(b"")
            self.assertNotIn("base",engine.installed_models())
            (folder/"vocabulary.json").write_bytes(b'["token"]')
            self.assertIn("base",engine.installed_models())

    def test_late_result_is_suppressed_after_stop(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), events.append)
            generation = engine._generation
            engine.stop()
            engine._event(generation, {"type": "audio", "text": "late"})
            self.assertEqual(events, [])

    def test_ocr_download_rejects_path_or_url(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ScreenEngine(Path(directory))
            for code in ("../../outside", "https://example.com/model", "jpn/eng"):
                with self.assertRaises(ValueError):
                    engine.install_ocr_language(code)


class AudioLifecycleTests(unittest.TestCase):
    def test_identical_translations_keep_distinct_voices_languages_and_separate_replies(self):
        import numpy as np
        from audio_chunks import CapturedPhrase
        from audio_devices import DEFAULT_PLAYBACK_AND_MIC
        from audio_engine import _Session
        t = np.arange(2560) / 16000.0
        first = np.rint(np.sin(2 * np.pi * 210 * t) * 2000).astype("<i2") * 2
        other = np.rint(np.sin(2 * np.pi * 275 * t) * 2000).astype("<i2") * 2
        echo = np.pad(first // 2, (113, 307))
        # Two people saying "yes", a copy sent by two Windows buses, and a
        # later intentional repeat. Recordings with different languages also
        # remain separate when their English translations coincide.
        inputs = [
            (0.00, "pc", 1, first, "ja"),
            (0.03, "microphone", 2, echo, "ja"),
            (0.04, "microphone", 2, other, "ja"),
            (0.05, "pc", 3, first, "ko"),
            (0.08, "pc", 1, first, "ja"),
            (0.90, "microphone", 2, first, "ja"),
        ]
        events = []
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), events.append)
            session = _Session(0, DEFAULT_PLAYBACK_AND_MIC, "base", "auto", 3, 1, "echo")
            def capture():
                stamp = time.monotonic()
                for offset, source, index, data, lang in inputs:
                    yield CapturedPhrase(data.tobytes(), 16000, 1, source, index, stamp + offset)
                session.stop.set()
                yield None
            queue = capture()
            session.chunks.next = lambda timeout: next(queue)
            captions = [[{"text": "Yes.", "language": lang}] for *_, lang in inputs]
            with patch("audio_engine.speech_captions", side_effect=captions):
                engine._translate(session, object())
            self.assertEqual([("pc", "ja"), ("microphone", "ja"), ("pc", "ko"), ("pc", "ja"),
                              ("microphone", "ja")], [(e["source"], e["language"]) for e in events if e["type"] == "audio"])

    def test_model_load_time_does_not_count_against_pending_reply_age(self):
        from audio_chunks import CapturedPhrase
        from audio_engine import _Session
        events = []
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), events.append)
            session = _Session(0, 1, "base", "ja", 3, 1, "age")
            def input_queue():
                data = struct.pack("<h", 450) * 1600
                yield CapturedPhrase(data, 16000, 1, "pc", 1, 73.0)
                yield CapturedPhrase(data, 16000, 1, "pc", 1, 101.0)
                session.stop.set()
                yield None
            phrases = input_queue()
            session.chunks.next = lambda timeout: next(phrases)
            with patch("audio_engine.time") as clock, patch("audio_engine.speech_captions") as decode:
                # Model ready at 100; first caption starts immediately. Next
                # live phrase waits until 113, exceeding the eight-second limit.
                clock.monotonic.side_effect = [100.0, 100.05, 100.6, 113.0]
                decode.return_value = [{"text": "Hello.", "language": "ja"}]
                engine._translate(session, object())
            decode.assert_called_once()
            self.assertEqual(["audio", "status"], [e["type"] for e in events if e["type"] != "audio_diagnostic"])

    def test_first_replies_are_captured_during_model_load_and_discarded_on_stop(self):
        # A virtual loopback sends six short replies only once. They all arrive
        # before the decoder is ready, just like a call already in progress.
        for stop_while_loading in (False, True):
            with self.subTest(stop_while_loading=stop_while_loading), tempfile.TemporaryDirectory() as directory:
                loading, release, sent, closed, done = (threading.Event() for _ in range(5))
                levels = [44, 29, 10, 80, 220, 70]
                received = []
                events = []
                def load(*args):
                    loading.set()
                    release.wait(5)
                    return object()
                def open_stream(**kwargs):
                    stream = Mock()
                    def send():
                        for level in levels:
                            speech = struct.pack("<h", level) * 1313
                            silence = b"\0\0" * 14400
                            data = speech + silence
                            kwargs["stream_callback"](data, len(data) // 2, {}, 0)
                        sent.set()
                    stream.start_stream.side_effect = send
                    stream.is_active.side_effect = lambda: not closed.is_set()
                    stream.close.side_effect = closed.set
                    return stream
                def decode(model, samples, language, translate, cancelled, **kwargs):
                    received.append(round(float(max(samples)) * 32768))
                    yield {"text": str(received[-1]), "language": "ja"}
                def emit(event):
                    events.append(event)
                    if len([e for e in events if e["type"] == "audio"]) == len(levels):
                        done.set()
                audio = Mock()
                audio.get_device_info_by_index.return_value = {"index": 1, "name": "Fixture", "maxInputChannels": 1,
                                                               "defaultSampleRate": 16000, "isLoopbackDevice": True}
                audio.open.side_effect = open_stream
                pa = SimpleNamespace(PyAudio=lambda: audio, paInt16=8, paComplete=1, paContinue=0)
                engine = AudioEngine(Path(directory), emit)
                with patch.dict("sys.modules", {"pyaudiowpatch": pa}), \
                     patch.object(engine, "installed_models", return_value=["base"]), \
                     patch.object(engine, "_load_model", side_effect=load), \
                     patch("audio_engine.speech_captions", decode):
                    try:
                        engine.start(1, language="ja", chunk_seconds=3)
                        self.assertTrue(loading.wait(3))
                        self.assertTrue(sent.wait(3), "Audio callbacks must begin before model loading finishes")
                        self.assertEqual([], received)
                        if stop_while_loading:
                            engine.stop()
                            self.assertTrue(closed.wait(1))
                        release.set()
                        if not stop_while_loading:
                            self.assertTrue(done.wait(3))
                        self.assertEqual([] if stop_while_loading else levels, received)
                    finally:
                        release.set()
                        engine.close()
                        engine._thread.join(3)
                self.assertFalse(engine._thread.is_alive())
                self.assertTrue(closed.is_set())
                self.assertFalse(any(e.get("state") == "error" for e in events))

    def test_device_failure_reports_error_while_inference_is_blocked(self):
        entered, release, error, active = (threading.Event() for _ in range(4))
        active.set()
        events = []
        class Stream:
            def __init__(self, callback): self.callback = callback
            def start_stream(self): self.callback(struct.pack("<h", 8192) * 48000, 48000, {}, 0)
            def is_active(self): return active.is_set()
            def stop_stream(self): pass
            def close(self): pass
        class Audio:
            def get_device_info_by_index(self, index): return {"maxInputChannels": 1, "defaultSampleRate": 16000}
            def open(self, **kwargs): return Stream(kwargs["stream_callback"])
            def terminate(self): pass
        def decode(model, samples, language, translate, cancelled, **kwargs):
            entered.set()
            release.wait(3)
            yield {"text": "stale", "language": language}
        def emit(event):
            events.append(event)
            if event.get("state") == "error": error.set()
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), emit)
            with patch.dict("sys.modules", {"pyaudiowpatch": SimpleNamespace(PyAudio=Audio, paInt16=8, paComplete=1, paContinue=0)}), \
                 patch.object(engine, "installed_models", return_value=["base"]), \
                 patch.object(engine, "_load_model", return_value=object()), \
                 patch("audio_engine.speech_captions", decode):
                try:
                    engine.start(0, language="ja", chunk_seconds=3, session_id="unplugged")
                    self.assertTrue(entered.wait(2))
                    active.clear()
                    self.assertTrue(error.wait(0.75))
                    self.assertFalse(release.is_set())
                    self.assertEqual("unplugged", [event for event in events if event.get("state") == "error"][0]["session_id"])
                finally:
                    release.set()
                    engine.stop()
            self.assertFalse(any(event["type"] == "audio" for event in events))

    def test_off_closes_capture_during_blocked_inference_and_latest_start_survives(self):
        entered, release, new_caption = threading.Event(), threading.Event(), threading.Event()
        streams, events = [], []

        class Stream:
            def __init__(self, callback):
                self.callback, self.closed = callback, threading.Event()
            def start_stream(self):
                # A synthetic three-second mono PCM chunk, never a real device.
                self.callback(struct.pack("<h", 8192) * (16000 * 3), 48000, {}, 0)
            def is_active(self): return not self.closed.is_set()
            def stop_stream(self): pass
            def close(self): self.closed.set()

        class Audio:
            def get_device_info_by_index(self, index):
                return {"maxInputChannels": 1, "defaultSampleRate": 16000}
            def open(self, **kwargs):
                stream = Stream(kwargs["stream_callback"])
                streams.append(stream)
                return stream
            def terminate(self): pass

        calls = []
        def decode(model, samples, language, translate, cancelled, **kwargs):
            calls.append(language)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            yield {"text": "caption " + language, "language": language}

        def emit(event):
            events.append(event)
            if event.get("type") == "audio" and event.get("session_id") == "new":
                new_caption.set()

        fake_pa = SimpleNamespace(PyAudio=Audio, paInt16=8, paComplete=1, paContinue=0)
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), emit)
            with patch.dict("sys.modules", {"pyaudiowpatch": fake_pa}), \
                 patch.object(engine, "installed_models", return_value=["base"]), \
                 patch.object(engine, "_load_model", return_value=object()), \
                 patch("audio_engine.speech_captions", decode):
                try:
                    engine.start(0, language="ja", chunk_seconds=3, session_id="old")
                    self.assertTrue(entered.wait(2))
                    engine.stop()
                    self.assertTrue(streams[0].closed.wait(0.75), "Off must close the capture stream before native inference finishes")
                    self.assertFalse(release.is_set())
                    engine.start(0, language="zh", chunk_seconds=3, session_id="superseded")
                    engine.start(0, language="ko", chunk_seconds=3, session_id="new")
                    release.set()
                    self.assertTrue(new_caption.wait(2))
                    engine.stop()
                    self.assertTrue(streams[-1].closed.wait(0.75))
                finally:
                    release.set()
                    engine.stop()
            captions = [event for event in events if event["type"] == "audio"]
            self.assertEqual(["new"], [event["session_id"] for event in captions])
            self.assertEqual(["ja", "ko"], calls)
            self.assertEqual(2, len(streams))
            self.assertFalse(any(event.get("state") == "error" for event in events))

    def test_cleanup_errors_do_not_block_capture_done_or_restart(self):
        closed, complete = threading.Event(), threading.Event()
        class Stream:
            def start_stream(self): pass
            def is_active(self): return True
            def stop_stream(self): raise OSError("Stop failed")
            def close(self): closed.set()
        class Audio:
            def get_device_info_by_index(self, index): return {"maxInputChannels": 1, "defaultSampleRate": 16000}
            def open(self, **kwargs): return Stream()
            def terminate(self): raise OSError("Terminate failed")
        def emit(event):
            if event.get("state") == "stopped": complete.set()
        fake_pa = SimpleNamespace(PyAudio=Audio, paInt16=8, paComplete=1, paContinue=0)
        from audio_engine import _Session
        with tempfile.TemporaryDirectory() as directory:
            engine = AudioEngine(Path(directory), emit)
            session = _Session(0, 0, "base", "ja", 3, 1, "cleanup")
            with patch.dict("sys.modules", {"pyaudiowpatch": fake_pa}):
                pump = threading.Thread(target=engine._capture, args=(session,))
                pump.start()
                self.assertTrue(session.ready.wait(1))
                session.stop.set()
                self.assertTrue(session.capture_done.wait(0.75))
                pump.join(timeout=1)
            self.assertTrue(closed.is_set())
            self.assertTrue(complete.is_set())


if __name__ == "__main__":
    unittest.main()
