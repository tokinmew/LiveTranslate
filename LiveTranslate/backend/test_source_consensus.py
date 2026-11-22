import unittest
from unittest.mock import Mock

from speech_decode import _alternative_words


class SourceConsensusTests(unittest.TestCase):
    @staticmethod
    def view(lang, text, score=.97):
        return dict(language=lang, text=text, tags=["<|Speech|>"], probs={lang:score})

    def test_independent_genuine_audio_confirms_a_word_correction(self):
        model=Mock()
        model.transcribe_formatted.return_value=self.view("zh","走。")
        model.transcribe_trimmed.return_value=self.view("zh","走")
        self.assertEqual("走。",_alternative_words(model,(),"zh","奏","走",lambda:False))

    def test_unconfirmed_single_character_and_wrong_script_are_preserved(self):
        model=Mock()
        model.transcribe_formatted.return_value=self.view("zh","英語 answer")
        self.assertEqual("可以",_alternative_words(model,(),"zh","可以","英",lambda:False))
        model.transcribe_trimmed.assert_not_called()

    def test_a_new_syllable_requires_other_paired_acoustic_evidence(self):
        model=Mock()
        model.transcribe_formatted.return_value=self.view("ko","조금 작아요?")
        model.transcribe_trimmed.return_value=self.view("ko","조 작아요")
        model.transcribe_repeated.return_value=self.view("ko","조금 조 작아요")
        self.assertEqual("조금 작아요?",_alternative_words(model,(),"ko","조 작아요","저 작아요",lambda:False))
        model.transcribe_repeated.return_value=self.view("ko","조 작아요 조 작아요")
        self.assertEqual("조 작아요",_alternative_words(model,(),"ko","조 작아요","저 작아요",lambda:False))
