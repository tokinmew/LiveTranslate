"""Isolate very brief/quiet speech behavior. Acoustic integration uses recorded fixtures."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from speech_decode import speech_captions


def segment(text, score=-0.3):
    return SimpleNamespace(text=text, start=0.0, end=1.0, compression_ratio=1.0,
                           no_speech_prob=0.02, avg_logprob=score)


class ShortSpeechTests(unittest.TestCase):
    def setUp(self):
        self.samples = (np.sin(np.arange(1920, dtype=np.float32) * 0.08) * 0.00045)
        spans = patch("speech_decode._speech_spans", return_value=[{"start": 0, "end": len(self.samples)}])
        self.vad = spans.start()
        self.addCleanup(spans.stop)
        self.info = SimpleNamespace(language="ko", language_probability=.94,
                                    all_language_probs=[("ko", .94), ("en", .01)])

    def test_quiet_120ms_reply_reaches_both_models_with_its_edges_intact(self):
        model = Mock()
        model.transcribe.side_effect = [
            ([segment("눈")], self.info), ([segment("Snow.")], self.info)]
        caps = list(speech_captions(model, self.samples, "auto", lambda *_: {"text": "눈"}))
        self.assertEqual([{"text": "Snow.", "original": "눈", "language": "ko"}], caps)
        boosted = self.vad.call_args.args[0]
        self.assertGreater(np.max(abs(boosted)), 0.02)
        source_call, translation_call = model.transcribe.call_args_list
        self.assertIsNone(source_call.kwargs["language"])
        self.assertTrue(source_call.kwargs["without_timestamps"])
        self.assertEqual("ko", translation_call.kwargs["language"])
        self.assertEqual("translate", translation_call.kwargs["task"])
        np.testing.assert_array_equal(source_call.args[0], translation_call.args[0])
        self.assertTrue(any(source_call.args[0] == boosted.max()))

    def test_ambiguous_english_never_enters_lazy_decoder_even_with_specific_profile(self):
        self.info.language_probability = .50
        self.info.all_language_probs = [("ko", .50), ("en", .46)]
        def forbidden():
            raise AssertionError("ambiguous speech decoded")
            yield
        model = Mock()
        model.transcribe.return_value = (forbidden(), self.info)
        translator = Mock(side_effect=AssertionError("ambiguous speech translated"))
        self.assertEqual([], list(speech_captions(model, self.samples, "ko", translator)))
        self.assertEqual(1, model.transcribe.call_count)

    def test_complete_reply_and_longer_sentence_with_same_words_remain_distinct(self):
        model = Mock()
        model.transcribe.return_value = ([segment("저기요!")], self.info)
        translate = lambda *_: {"text": "About Us"}
        out = list(speech_captions(model, self.samples, "auto", translate))
        self.assertEqual(["Excuse me."], [c["text"] for c in out])
        model.transcribe.return_value = ([segment("저기요 어디세요?")], self.info)
        out = list(speech_captions(model, self.samples, "auto", lambda *_: {"text": "Excuse me, where are you?"}))
        self.assertEqual(["Excuse me, where are you?"], [c["text"] for c in out])

    def test_valid_local_translation_avoids_a_second_decode(self):
        model = Mock()
        model.transcribe.return_value = ([segment("감사")], self.info)
        with patch("spoken_lexicon.lexical_reply", return_value=None):
            out = list(speech_captions(model, self.samples, "auto", lambda *_: {"text": "Thanks"}))
        self.assertEqual(["Thanks"], [c["text"] for c in out])
        self.assertEqual(1, model.transcribe.call_count)

    def test_trusted_acoustic_sentence_can_correct_text_translation(self):
        for score, expected in [(-.3, "Could you open the door?"), (-.95, "Open the door.")]:
            with self.subTest(score=score):
                model = Mock(sensevoice=None)
                model.transcribe.side_effect = [
                    ([segment("문을 열어 주시겠어요?")], self.info),
                    ([segment("Could you open the door?", score)], self.info)]
                translate = lambda *_: {"text": "Open the door.", "engine": "nllb"}
                with patch("spoken_lexicon.lexical_reply", return_value=None):
                    out = list(speech_captions(model, self.samples, "auto", translate))
                self.assertEqual([expected], [caption["text"] for caption in out])
                self.assertEqual(2, model.transcribe.call_count)

    def test_silence_dither_and_nonfinite_samples_are_rejected_before_inference(self):
        for value in (0.0, 1/32768, float("nan")):
            with self.subTest(value=value):
                samples = np.full(1920, value, np.float32)
                self.assertFalse(list(speech_captions(Mock(), samples)))
        self.vad.assert_not_called()


if __name__ == "__main__":
    unittest.main()
