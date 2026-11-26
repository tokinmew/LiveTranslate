"""Measured endpoint activity and speech decisions; no hardware/model/downloads."""
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from audio_diagnostics import SignalMonitor
from audio_engine import AudioEngine, _Session
from audio_devices import Route
from speech_decode import speech_captions


def info(language, probability=.98):
    return SimpleNamespace(language=language, language_probability=probability,
                           all_language_probs=[(language, probability), ("en", .01)])


def segment(text):
    return SimpleNamespace(text=text, start=0.0, end=.4, avg_logprob=-.2,
                           compression_ratio=1.0, no_speech_prob=.01)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.monitor = SignalMonitor()
        self.monitor.register("pc", 7, 2, 48000)

    def test_absent_packets_never_fabricate_signal_and_emission_is_bounded(self):
        row = self.monitor.snapshots(0)[0]
        self.assertFalse(row["activity"])
        self.assertFalse(row["samples_received"])
        self.assertEqual((-120, -120, 0), (row["rms_dbfs"], row["peak_dbfs"], row["level"]))
        self.assertEqual([], self.monitor.snapshots(.2))
        self.assertEqual(1, len(self.monitor.snapshots(.5)))
        self.assertIn("No audio samples", row["message"])

    def test_strongest_channel_is_measured_without_averaging_away_center_speech(self):
        self.monitor.register("pc", 7, 8, 48000)
        pcm = np.zeros((480, 8), dtype="<i2")
        pcm[:, 2] = 8192
        self.monitor.observe("pc", 7, pcm.tobytes(), 8, now=1)
        row = self.monitor.snapshots(1)[0]
        self.assertTrue(row["activity"])
        self.assertTrue(row["samples_received"])
        self.assertAlmostEqual(-12, row["rms_dbfs"], delta=.1)
        self.assertEqual((7, 8, 48000), (row["endpoint"], row["channels"], row["sample_rate"]))

    def test_silent_packets_are_distinguished_from_no_packets(self):
        self.monitor.observe("pc", 7, bytes(960 * 2 * 2), 2, now=2)
        row = self.monitor.snapshots(2)[0]
        self.assertTrue(row["samples_received"])
        self.assertFalse(row["activity"])
        self.assertIn("sending silence", row["message"])

    def test_idle_loopback_does_not_leave_old_loud_level_on_screen(self):
        self.monitor.observe("pc", 7, struct.pack("<h", 16000) * 960, 2, now=2)
        self.assertGreater(self.monitor.snapshots(2)[0]["level"], 0)
        row = self.monitor.snapshots(4)[0]
        self.assertEqual(0, row["level"])
        self.assertFalse(row["samples_received"])

    def test_real_fullscale_sample_reports_clipping_with_finite_numbers(self):
        self.monitor.observe("pc", 7, struct.pack("<h", -32768) * 960, 2, now=2)
        row = self.monitor.snapshots(2)[0]
        self.assertTrue(row["clipping"])
        self.assertEqual((0.0, 100), (row["peak_dbfs"], row["level"]))

    def test_odd_fragment_is_ignored_and_reroute_drops_previous_endpoint(self):
        self.monitor.observe("pc", 7, b"x", 2, now=2)
        self.assertFalse(self.monitor.snapshots(2)[0]["samples_received"])
        self.monitor.reset()
        self.monitor.register("microphone", 1, 1, 16000)
        self.assertEqual([1], [r["endpoint"] for r in self.monitor.snapshots(2)])

    def test_old_session_diagnostic_cannot_overwrite_new_input(self):
        events = []
        with tempfile.TemporaryDirectory() as folder:
            engine = AudioEngine(Path(folder), events.append)
            old = _Session(0, 7, "base", "auto", 5, 1, "old")
            engine._generation = 1
            engine._session_event(old, {"type": "audio_diagnostic", "level": 99})
            self.assertEqual([], events)

    def test_old_endpoint_callback_cannot_publish_signal_after_routing_changes(self):
        session = _Session(0, 7, "base", "auto", 5, 1, "route")
        audio = Mock()
        audio.open.return_value = object()
        pa = SimpleNamespace(paInt16=8, paComplete=1, paContinue=0)
        route = Route({"index": 7, "maxInputChannels": 2, "defaultSampleRate": 48000}, "pc")
        AudioEngine._open_device(session, pa, audio, route)
        callback = audio.open.call_args.kwargs["stream_callback"]
        session.route_epoch += 1
        self.assertEqual((None, 1), callback(struct.pack("<h", 16000) * 960, 480, {}, 0))
        self.assertFalse(session.signals.snapshots()[0]["samples_received"])


class SpeechDecisionTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.sin(np.arange(6400, dtype=np.float32) * .08) * .1
        self.spans = patch("speech_decode._speech_spans", return_value=[{"start": 0, "end": len(self.audio)}])
        self.spans.start()
        self.addCleanup(self.spans.stop)

    def test_silence_and_no_voice_activity_have_distinct_explanations(self):
        diagnostics = {}
        self.assertEqual([], list(speech_captions(object(), np.zeros(6400, np.float32), diagnostics=diagnostics)))
        self.assertEqual("no_speech", diagnostics["decision"])
        self.assertIn("silence", diagnostics["message"])
        with patch("speech_decode._speech_spans", return_value=[]):
            self.assertEqual([], list(speech_captions(SimpleNamespace(sensevoice=None), self.audio, diagnostics=diagnostics)))
        self.assertIn("voice detector", diagnostics["message"])

    def test_english_is_explained_without_eagerly_decoding_untrusted_words(self):
        def forbidden():
            raise AssertionError("English rejected generator should remain lazy")
            yield
        model = SimpleNamespace(sensevoice=None, dialogue_model=None,
                                transcribe=Mock(return_value=(forbidden(), info("en"))))
        diagnostics = {}
        self.assertEqual([], list(speech_captions(model, self.audio, diagnostics=diagnostics)))
        self.assertEqual("english_filtered", diagnostics["decision"])
        self.assertEqual("en", diagnostics["language"])
        self.assertEqual("", diagnostics["recognized"])

    def test_explicit_source_mismatch_is_not_reported_as_silence(self):
        model = SimpleNamespace(sensevoice=None, dialogue_model=None,
                                transcribe=Mock(return_value=(iter(()), info("de"))))
        diagnostics = {}
        self.assertEqual([], list(speech_captions(model, self.audio, "es", diagnostics=diagnostics)))
        self.assertEqual("language_mismatch", diagnostics["decision"])
        self.assertEqual("de", diagnostics["language"])

    def test_accepted_words_and_language_are_exposed_separately_from_caption(self):
        model = SimpleNamespace(sensevoice=None, dialogue_model=None,
            transcribe=Mock(side_effect=[([segment("今日は駅に行きます。")], info("ja")),
                                        ([segment("I will go to the station today.")], info("ja"))]))
        diagnostics = {}
        captions = list(speech_captions(model, self.audio, diagnostics=diagnostics))
        self.assertEqual(1, len(captions))
        self.assertEqual("accepted", diagnostics["decision"])
        self.assertEqual("ja", diagnostics["language"])
        self.assertEqual("今日は駅に行きます。", diagnostics["recognized"])

    def test_decoded_but_rejected_words_are_diagnostic_only_and_bounded(self):
        source = segment("Home " * 300)
        model = SimpleNamespace(sensevoice=None, dialogue_model=None,
                                transcribe=Mock(return_value=([source], info("ja"))))
        diagnostics = {}
        self.assertEqual([], list(speech_captions(model, self.audio, diagnostics=diagnostics)))
        self.assertEqual("source_unconfirmed", diagnostics["decision"])
        self.assertTrue(diagnostics["recognized"].startswith("Home "))
        self.assertLessEqual(len(diagnostics["recognized"]), 240)


if __name__ == "__main__":
    unittest.main()
