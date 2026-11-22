import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from korean_dialogue import _break, _known_clause, accurate_turn


class KoreanDialogueTests(unittest.TestCase):
    def test_english_and_short_speech_cannot_start_second_model(self):
        small = SimpleNamespace(sensevoice=Mock(), dialogue_model=Mock())
        for lang, duration in (("en",48000),("ja",48000),("ko",15000)):
            audio = np.zeros(duration, np.float32)
            first=SimpleNamespace(language=lang,language_probability=.99)
            self.assertIsNone(accurate_turn(small,audio,audio,"auto",first,lambda:False,None))
        small.sensevoice.transcribe_trimmed.assert_not_called()
        small.dialogue_model.transcribe.assert_not_called()

    def test_every_utterance_still_needs_unforced_positive_korean_speech(self):
        small=SimpleNamespace(sensevoice=Mock(), dialogue_model=Mock())
        audio = np.zeros(48000, np.float32)
        for lang,tag in (("en","<|Speech|>"),("ko","<|Music|>")):
            small.sensevoice.transcribe_trimmed.return_value = dict(language=lang,probs={lang:.99}, tags=[tag],text="audio")
            first=SimpleNamespace(language="ko",language_probability=.91)
            self.assertIsNone(accurate_turn(small,audio,audio,"ko",first,lambda:False,None))
        small.dialogue_model.transcribe.assert_not_called()

    def test_partial_pause_and_end_silence_do_not_create_clauses(self):
        voice=np.ones(8000,np.float32)*.1
        self.assertEqual(0,_break(np.r_[voice,np.zeros(8000)]))
        self.assertEqual(0,_break(np.r_[voice,np.zeros(1300),voice]))
        self.assertTrue(8000 < _break(np.r_[voice,np.zeros(3200),voice]) < 11200)

    def test_known_clause_matches_complete_source_words_only(self):
        replies={"예":"Yes.","알아요":"I know."}
        self.assertEqual("Yes. I know.",_known_clause("예 알아요.",replies))
        self.assertEqual("",_known_clause("예 알아요 아마도",replies))

    def test_counted_units_need_two_models_and_both_ctc_views(self):
        text = "한 번에 몇 병까지 살 수 있나요"
        generic = "한 번에 몇 개까지 살 수 있나요?"
        evidence = dict(language="ko",probs={"ko":.99},tags=["<|Speech|>"],text=text)
        small=Mock()
        small.sensevoice.transcribe_trimmed.return_value = evidence
        small.sensevoice.transcribe.return_value = evidence
        small.sensevoice.transcribe_formatted.return_value = evidence
        small.sensevoice._trim.side_effect = lambda a:a
        confident=SimpleNamespace(text=text,compression_ratio=1,avg_logprob=-.1,no_speech_prob=.03)
        small.transcribe.return_value = ([confident],None)
        first=SimpleNamespace(language="ko",language_probability=.99)
        audio=np.ones(35000,np.float32)*.1
        with patch("korean_dialogue._native",return_value=generic), patch("korean_dialogue._english",return_value="How many can you buy?"):
            r=accurate_turn(small,audio,audio,"auto",first,lambda:False,None)
            self.assertEqual("How many bottles can you buy?",r["text"])
            small.sensevoice.transcribe.return_value=dict(evidence,text=generic)
            r=accurate_turn(small,audio,audio,"auto",first,lambda:False,None)
            self.assertEqual("How many can you buy?",r["text"])
