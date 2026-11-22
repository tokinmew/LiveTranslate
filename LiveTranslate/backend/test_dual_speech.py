import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from speech_decode import _independent_transcript, _question_ending, _repeated_phrase


class IndependentSpeechTests(unittest.TestCase):
    def test_two_target_languages_disagree_require_identical_tripled_native_source(self):
        recognizer = Mock()
        model = SimpleNamespace(sensevoice=recognizer)
        first = SimpleNamespace(language="ko", language_probability=.9)
        view = dict(language="zh", tags=["<|Speech|>"], probs={"zh": .995}, text="天气")
        recognizer.transcribe.return_value = view
        recognizer.transcribe_trimmed.return_value = view
        recognizer.transcribe_repeated.return_value = dict(view, text="天气天气天气")
        self.assertEqual(("zh", "天气"), _independent_transcript(model, (), first, "auto"))
        recognizer.transcribe_repeated.return_value = dict(view, text="好天气")
        self.assertIsNone(_independent_transcript(model, (), first, "zh"))
        recognizer.transcribe_repeated.return_value = dict(view, text="天气天气天气")
        self.assertIsNone(_independent_transcript(model, (), first, "ko"))

    def test_question_marks_follow_the_heard_ending(self):
        self.assertEqual("창문을 열까요?", _question_ending("창문을 열까요", "창문을 열까요?"))
        self.assertEqual("창문을 닫았어요", _question_ending("창문을 닫았어요", "창문을 열까요?"))

    def test_original_english_veto_precedes_secondary_decode(self):
        model = SimpleNamespace(sensevoice=Mock())
        self.assertIsNone(_independent_transcript(model, (), SimpleNamespace(language="en"), "ja"))
        model.sensevoice.transcribe.assert_not_called()

    def test_unrelated_speech_and_english_in_native_sentence_stay_in_segmented_path(self):
        model = SimpleNamespace(sensevoice=Mock())
        first = SimpleNamespace(language="ja", language_probability=.91)
        for event, source in [("<|Music|>","明日"),("<|Speech|>","明日 Open Settings")]:
            model.sensevoice.transcribe.return_value = dict(language="ja",tags=[event],probs={"ja":.99},text=source)
            self.assertIsNone(_independent_transcript(model, (), first, "auto"))

    def test_confirmed_source_is_applicable_only_to_selected_profile(self):
        model = SimpleNamespace(sensevoice=Mock())
        first = SimpleNamespace(language="ja", language_probability=.93)
        model.sensevoice.transcribe.return_value = dict(language="ja",tags=["<|Speech|>"],probs={"ja":.99},text="明日")
        self.assertIsNone(_independent_transcript(model, (), first, "ko"))
        self.assertEqual(("ja","明日"),_independent_transcript(model, (), first, "auto"))

    def test_repeated_audio_yields_one_whole_source_phrase(self):
        self.assertEqual("오늘 와요",_repeated_phrase("오늘 와요. 오늘 와요! 오늘 와요"))
        self.assertEqual("谢谢",_repeated_phrase("谢谢谢谢谢谢"))
        self.assertFalse(_repeated_phrase("今日は明日"))
