"""Synthetic live-caption tests. No devices or native speech models are opened."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from audio_chunks import CapturedPhrase
from audio_devices import DEFAULT_PLAYBACK_AND_MIC
from audio_engine import AudioEngine, _Session
from speech_decode import speech_captions
from speech_memory import SpeechCaptionMemory


def caption(original, english, language="ja"):
    return {"original": original, "text": english, "language": language}


class SpeechStabilityTests(unittest.TestCase):
    def test_single_declarative_exclamation_keeps_first_wording_across_recordings(self):
        memory = SpeechCaptionMemory(None)
        original = "지금 출발해요"
        for index, source in enumerate((original, original + "!", original + "！", original + ".")):
            phrase = CapturedPhrase(bytes([index]), 16000, 1, "pc", 1, 0)
            row = caption(source, "We're leaving now." if not index else "Let's go now!", "ko")
            result, = memory.stabilize(phrase, [row], lambda: False)
            self.assertEqual("We're leaving now.", result["text"])
            self.assertEqual(source, result["original"])
        for distinct in (original + "?", original + "?!", original + "!!", "지금, 출발해요!",
                         "지금 안 출발해요!", "5분 후에 출발해요!"):
            self.assertIsNone(memory.lookup(distinct, "ko"))
        memory.accept(caption("5", "Five.", "ko"))
        self.assertIsNone(memory.lookup("5!", "ko"))

    def test_equal_words_keep_first_english_without_merging_distinct_meanings(self):
        memory = SpeechCaptionMemory(None)
        for original, english in (("今日は十時。", "It's ten today."), ("今日は十時？", "Is it ten today?"),
                                  ("今日は十一時。", "It's eleven today."), ("今日は十時じゃない。", "It isn't ten today."),
                                  ("今日は午後十時。", "It's ten PM today.")):
            self.assertEqual(english, memory.accept(caption(original, english))["text"])
        self.assertEqual("It's ten today.", memory.accept(caption(" 今日は十時 . ", "Today it's 10."))["text"])
        self.assertEqual("It's ten today.", memory.lookup("今日 は 十時", "ja"))
        memory.accept(caption("一 二", "One, two", "zh"))
        self.assertIsNone(memory.lookup("一二", "zh"))
        self.assertIsNone(memory.lookup("今日は十時", "zh"))
        memory.accept(caption("아버지가 방에", "Father in the room", "ko"))
        self.assertIsNone(memory.lookup("아버지 가방에", "ko"))

    def test_english_gate_runs_on_every_clip_and_repeats_skip_translation(self):
        import numpy as np
        original = "今日は早く帰ります。"
        samples = np.full(48000, .2, dtype=np.float32)
        model = SimpleNamespace(transcribe=Mock())
        segment = SimpleNamespace(text=original, start=0, end=3, avg_logprob=-.2,
                                  no_speech_prob=.05, compression_ratio=1.1)
        def info(language):
            return SimpleNamespace(language=language, language_probability=.98, all_language_probs=[(language,.98)])
        def forbidden():
            raise AssertionError("The English segment decoder ran.")
            yield
        model.transcribe.side_effect = [([segment],info("ja")), ([segment],info("ja")), (forbidden(),info("en"))]
        translate = Mock(side_effect=[{"text": "I'll head home early today."}, AssertionError("Translated twice")])
        memory = SpeechCaptionMemory(translate)
        with patch("mixed_spans.partition",return_value=[{"start":0,"end":len(samples)}]):
            results = [[memory.accept(item) for item in speech_captions(model,samples,"auto",memory)] for _ in range(3)]
        self.assertEqual(results[0], results[1])
        self.assertEqual("I'll head home early today.", results[0][0]["text"])
        self.assertEqual([], results[2])
        self.assertEqual((3,1), (model.transcribe.call_count,translate.call_count))

    def test_bounded_memory_and_route_restart(self):
        memory = SpeechCaptionMemory(None)
        for index in range(memory.MAX_PHRASES + 1):
            memory.accept(caption("時刻" + str(index), "Time " + str(index)))
        self.assertIsNone(memory.lookup("時刻0", "ja"))
        self.assertEqual("Time 1", memory.lookup("時刻1", "ja"))
        self.assertIsNone(SpeechCaptionMemory(None).lookup("時刻1", "ja"))

    def test_identical_digital_replay_requires_new_approval_and_matches_format(self):
        memory = SpeechCaptionMemory(None)
        original = caption("駅に行きます。", "I'm going to the station.")
        alternate = caption("車で行きます。", "I'm taking the car.")
        other_language = caption("출발합니다.", "Departing.", "ko")
        phrase = CapturedPhrase(b"fixture A",16000,1,"pc",1,0)
        emit = lambda p, items: list(memory.stabilize(p, items, lambda: False))
        self.assertEqual([original], emit(phrase, [original]))
        self.assertEqual([], emit(phrase, []))
        self.assertEqual([original], emit(phrase, [alternate,alternate]))
        self.assertEqual([other_language], emit(phrase, [other_language]))
        for p in (CapturedPhrase(b"fixture B",16000,1,"pc",1,0),
                  CapturedPhrase(b"fixture A",48000,1,"pc",1,0),
                  CapturedPhrase(b"fixture A",16000,2,"pc",1,0)):
            self.assertEqual([alternate], emit(p,[alternate]))

    def test_live_source_mirrors_partial_decodes_and_intentional_repeats(self):
        import numpy as np
        wave = (np.sin(np.arange(3200)*.08)*3200).astype("<i2").tobytes()
        rows = [
            (0,0,"pc",10,[caption("出発する。","We're leaving."), caption("今。","Now.")]),
            (.03,0,"microphone",1,[caption("違う。","Different wording."), caption("さらに。","Extra phrase."), caption("今。","Right now.")]),
            (.12,0,"microphone",1,[caption("出発する", "We depart.")]),
            (.90,0,"pc",10,[caption("到着する？", "Are we arriving?")]),
            (1,1,"pc",10,[caption("出発する", "We set off.")]),
        ]
        events = []
        with TemporaryDirectory() as root:
            engine = AudioEngine(Path(root),events.append)
            session = _Session(0, DEFAULT_PLAYBACK_AND_MIC, "base", "auto", 5, 1, "session")
            def packets():
                now = time.monotonic()
                for offset, epoch, source, endpoint, _ in rows:
                    session.route_epoch = epoch
                    payload = wave if offset != .90 else wave[:2000]
                    yield CapturedPhrase(payload,16000,1,source,endpoint,now+offset,epoch)
                session.stop.set()
                yield None
            packets = packets()
            session.chunks.next = lambda timeout: next(packets)
            with patch("audio_engine.speech_captions",side_effect=[r[-1] for r in rows]):
                engine._translate(session,object())
        self.assertEqual(["We're leaving.","Now.","We're leaving.","Are we arriving?","We set off."],
                         [e["text"] for e in events if e["type"] == "audio"])

