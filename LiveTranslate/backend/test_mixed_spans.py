"""Deterministic tests of pause routing and model-call budgets at 16 kHz."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from mixed_spans import partition
from speech_decode import _SCRIPTS, speech_captions


def audio(lengths, gap=4800):
    pieces = []
    for samples in lengths:
        if pieces:
            pieces.append(np.zeros(gap, dtype=np.float32))
        pieces.append(np.full(samples, 0.18, dtype=np.float32))
    return np.concatenate(pieces)


def evidence(language, text, probability=0.95, tag="<|Speech|>"):
    return {"language": language, "text": text, "probs": {language: probability}, "tags": [tag]}


EN = evidence("en", "on the right")
JA = evidence("ja", "\u53f3\u3078")
KO = evidence("ko", "\uc624\ub978\ucabd")
ZH = evidence("zh", "\u53f3\u908a")


class PauseRouting(unittest.TestCase):
    def setUp(self):
        self.signal = audio([5600, 5600, 5600])
        self.model = Mock()
        self.recognize = self.model.sensevoice.transcribe_trimmed
        self.vad = Mock(side_effect=lambda samples: [{"start": 17, "end": len(samples) - 23}])
        self.stopped = False

    def route(self, samples=None):
        return partition(self.model, self.signal if samples is None else samples, self.vad,
                         lambda: self.stopped, _SCRIPTS)

    def test_short_continuous_noisy_and_stutter_inputs_do_no_additional_inference(self):
        for samples in [audio([5000]), audio([80000]), np.zeros(32000, np.float32),
                        audio([5500, 5500], gap=2800), audio([1900, 8700]), audio([5600] * 7),
                        np.random.default_rng(104).normal(0, 0.01, 32000).astype(np.float32)]:
            with self.subTest(length=len(samples)):
                self.assertEqual(self.route(samples), [{"start": 17, "end": len(samples) - 23}])
                self.recognize.assert_not_called()

    def test_english_only_and_same_language_keep_original_vad_boundaries(self):
        for rows in ([EN] * 3, [JA] * 3, [KO] * 3, [ZH] * 3, [JA, KO, ZH]):
            with self.subTest(languages=[r["language"] for r in rows]):
                self.recognize.side_effect = rows
                self.vad.reset_mock()
                self.assertEqual(self.route(), [{"start": 17, "end": len(self.signal) - 23}])
                self.vad.assert_called_once_with(self.signal)

    def test_unreliable_or_contradictory_result_falls_back_immediately(self):
        for observation in [evidence("en", "go \u53f3"), evidence("ko", "\uc624\ub978 go"),
                            evidence("zh", "\u53f3\u3078"), evidence("en", "I"),
                            evidence("fr", "bonjour"), evidence("ja", "\u53f3", 0.5),
                            evidence("en", "yes", tag="<|Music|>")]:
            self.recognize.reset_mock()
            self.recognize.side_effect = [observation]
            self.assertEqual(len(self.route()), 1)
            self.assertEqual(self.recognize.call_count, 1)

    def test_confirmed_change_keeps_absolute_sample_offsets_and_groups_adjacent_language(self):
        self.recognize.side_effect = [JA, JA, EN]
        self.assertEqual(self.route(), [{"start": 17, "end": 18400 - 23},
                                        {"start": 18400 + 17, "end": len(self.signal) - 23}])
        self.assertEqual(self.vad.call_count, 2)
        self.assertEqual(self.recognize.call_count, 3)

    def test_five_candidate_pauses_allow_at_most_six_extra_model_calls(self):
        self.recognize.side_effect = [EN] * 6
        self.assertEqual(len(self.route(audio([5600] * 6))), 1)
        self.assertEqual(self.recognize.call_count, 6)

    def test_a_single_surviving_side_remains_partitioned(self):
        self.recognize.side_effect = [EN, JA]
        self.vad.side_effect = [[], [{"start": 2, "end": 3000}]]
        out = self.route(audio([5600, 5600]))
        self.assertEqual(1, len(out))
        self.assertTrue(out[0]["partitioned"])
        self.assertGreater(out[0]["start"], 5600)

    def test_missing_recognizer_keeps_original_segmentation(self):
        self.model = SimpleNamespace()
        self.assertEqual(self.route(), [{"start": 17, "end": len(self.signal) - 23}])

    def test_capture_already_stopped_does_no_work(self):
        self.stopped = True
        self.assertEqual(self.route(), [])
        self.vad.assert_not_called()
        self.recognize.assert_not_called()

    def test_stop_during_first_extra_model_call_stops_entire_caption_pipeline(self):
        def stop(samples, selection):
            self.stopped = True
            return EN
        self.recognize.side_effect = stop
        self.assertEqual(list(speech_captions(self.model, self.signal, cancelled=lambda: self.stopped)), [])
        self.recognize.assert_called_once()
        self.model.transcribe.assert_not_called()

    def test_stop_during_vad_discards_partial_output_and_skips_remaining_work(self):
        def stop(samples):
            self.stopped = True
            return [{"start": 0, "end": len(samples)}]
        self.vad.side_effect = stop
        for rows in ([EN, JA, EN], [EN] * 3):
            self.vad.reset_mock()
            self.stopped = False
            self.recognize.side_effect = rows
            self.assertEqual(self.route(), [])
            self.assertEqual(self.vad.call_count, 1)
