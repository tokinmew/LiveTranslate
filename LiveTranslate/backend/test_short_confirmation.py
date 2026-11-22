"""Regression checks for reconsidering short words after acoustic detection."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from speech_decode import _speech_spans, speech_captions


def language(code, **probabilities):
    return SimpleNamespace(language=code, language_probability=probabilities[code],
                           all_language_probs=list(probabilities.items()))


def segment(text, score=-.35):
    return SimpleNamespace(text=text, start=0.0, end=.6, compression_ratio=1.1,
                           no_speech_prob=.12, avg_logprob=score)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.clip = (.2 * np.sin(np.arange(4800, dtype=np.float32) * .08))
        spans = patch("speech_decode._speech_spans", return_value=[{"start": 0, "end": len(self.clip)}])
        spans.start()
        self.addCleanup(spans.stop)
        self.model = Mock()

    def test_named_profile_can_confirm_borderline_native_language_on_a_second_unconstrained_view(self):
        self.model.transcribe.side_effect = [
            ([], language("ko", ko=.35, en=.04, ja=.15)),
            ([segment("네")], language("ko", ko=.33, en=.04, ja=.11))]
        out = list(speech_captions(self.model, self.clip, "ko", lambda *_: {"text": "Yes."}))
        self.assertEqual(["Yes."], [row["text"] for row in out])
        self.assertEqual([None, None], [c.kwargs["language"] for c in self.model.transcribe.call_args_list])

    def test_second_window_cannot_turn_an_english_winner_into_a_caption(self):
        self.model.transcribe.return_value = ([], language("en", en=.39, ko=.36))
        self.assertEqual([], list(speech_captions(self.model, self.clip, "ko")))
        self.assertEqual(1, self.model.transcribe.call_count)

    def test_a_timestamped_reading_can_restore_agreeing_marginal_word(self):
        ko = language("ko", ko=.83, en=.02)
        self.model.transcribe.side_effect = [([segment("그 날씨가", -1.16)], ko), ([segment("날씨가")], ko)]
        out = list(speech_captions(self.model, self.clip, "auto", lambda *_: {"text": "The weather"}))
        self.assertEqual(["The weather"], [r["text"] for r in out])
        self.assertFalse(self.model.transcribe.call_args.kwargs["without_timestamps"])

    def test_conflicting_native_word_is_silent_even_with_a_better_second_score(self):
        ko = language("ko", ko=.83, en=.02)
        self.model.transcribe.side_effect = [([segment("주소", -1.17)], ko), ([segment("과일")], ko)]
        self.assertEqual([], list(speech_captions(self.model, self.clip, "auto")))

    def test_menu_like_output_is_checked_against_audio(self):
        ko = language("ko", ko=.91, en=.02)
        self.model.transcribe.side_effect = [([segment("비가 와")], ko), ([segment("It's raining.")], ko)]
        out = list(speech_captions(self.model, self.clip, "auto", lambda *_: {"text": "Contact Us"}))
        self.assertEqual(["It's raining."], [r["text"] for r in out])


class IdleVoiceDetectorTests(unittest.TestCase):
    def test_second_vad_view_maps_only_real_sample_offsets(self):
        clip = np.ones(9600, np.float32)
        lead = 3840
        second = [{"start": 0, "end": 128}, {"start": lead - 128, "end": lead + 1200},
                  {"start": lead + 8400, "end": lead + 12000}]
        with patch("faster_whisper.vad.get_speech_timestamps", side_effect=[[], second]) as detector:
            self.assertEqual([{"start": 0, "end": 1200}, {"start": 8400, "end": 9600}], _speech_spans(clip))
            self.assertEqual(2, detector.call_count)
            np.testing.assert_array_equal(clip, detector.call_args.args[0][lead:lead + len(clip)])

    def test_a_voiced_first_pass_does_not_retry_or_shift_its_range(self):
        spans = [{"start": 200, "end": 9600}]
        with patch("faster_whisper.vad.get_speech_timestamps", return_value=spans) as detector:
            self.assertEqual(spans, _speech_spans(np.ones(9600, np.float32)))
            self.assertEqual(1, detector.call_count)
