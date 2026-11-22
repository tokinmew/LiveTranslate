"""Synthetic audio/decoder routing checks. No device, network or speech model is opened."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from audio_engine import AudioEngine
from multilingual_speech import BASE_SPEECH_LANGUAGES, SPOKEN_LANGUAGES
from speech_decode import speech_captions
from speech_memory import SpeechCaptionMemory


def segment(text, start=0., end=.12, confidence=-.23):
    return SimpleNamespace(text=text, start=start, end=end, avg_logprob=confidence,
                           compression_ratio=1.1, no_speech_prob=.02)


def detection(language, probability=.96, rival="en", competitor=.02):
    return SimpleNamespace(language=language, language_probability=probability,
                           all_language_probs=[(language, probability), (rival, competitor)])


def decoder(info, original, english):
    model = Mock(sensevoice=None, dialogue_model=None)
    model.transcribe.side_effect = [(iter([segment(original)]), info), (iter([segment(english)]), info)]
    return model


class MultilingualSpeechTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.sin(np.arange(1920, dtype=np.float32)*.08) * .0005
        spans = patch("speech_decode._speech_spans", side_effect=lambda audio: [{"start": 0, "end": len(audio)}])
        spans.start()
        self.addCleanup(spans.stop)

    def test_120ms_foreign_sources_translate_directly_without_a_text_pack(self):
        for language, original, english in (
            ("fr", "Merci.", "Thank you."), ("de", "Danke.", "Thank you."),
            ("es", "Gracias.", "Thanks."), ("pt", "Obrigado.", "Thank you."),
            ("it", "Grazie.", "Thanks."), ("nl", "Bedankt.", "Thanks."),
            ("tr", "Merhaba.", "Hello."), ("pl", "Dziękuję.", "Thank you."),
            ("sv", "Tack.", "Thank you."), ("tl", "Salamat.", "Thanks."),
            ("haw", "Mahalo.", "Thank you."), ("la", "Gratias tibi ago.", "Thank you."),
            ("mi", "Kia ora.", "Hello."), ("jw", "Matur nuwun.", "Thank you."),
            ("su", "Hatur nuhun.", "Thanks."), ("sw", "Asante sana.", "Thank you very much."),
            ("vi", "Xin chào.", "Hello."), ("nn", "Takk.", "Thanks."),
            ("vi", "Vâng.", "Yes."), ("hi", "नहीं।", "No."),
            ("id", "Tidak.", "No."), ("tl", "Opo.", "Yes."),
            ("br", "Trugarez.", "Thank you."), ("ln", "Mbote.", "Hello."),
            ("oc", "Mercés plan.", "Thank you very much."),
            ("ru", "Спасибо.", "Thank you."), ("el", "Γεια.", "Hello."),
            ("ar", "مرحبا.", "Hello."), ("he", "תודה.", "Thank you."),
            ("hi", "नमस्ते।", "Hello."), ("bn", "ধন্যবাদ।", "Thanks."),
            ("ta", "வணக்கம்.", "Hello."), ("am", "ሰላም", "Hello."),
            ("km", "សួស្តី", "Hello."), ("ka", "მადლობა", "Thank you."),
            ("hy", "Բարև։", "Hello."), ("my", "မင်္ဂလာပါ", "Hello."),
            ("gu", "આભાર", "Thanks."), ("te", "ధన్యవాదాలు", "Thanks."),
            ("uk", "Дякую.", "Thanks."), ("fa", "سلام.", "Hello."),
            ("ur", "شکریہ", "Thanks."), ("pa", "ਧੰਨਵਾਦ", "Thanks."),
            ("th", "สวัสดี", "Hello."), ("bo", "བཀྲ་ཤིས།", "Good luck."),
            ("yue", "唔該。", "Thanks.")):
            with self.subTest(language=language):
                model = decoder(detection(language), original, english)
                tr = Mock(side_effect=AssertionError("unexpected text pack"))
                captions = list(speech_captions(model, self.audio, "auto", tr))
                self.assertEqual([{"language": language, "original": original, "text": english}], captions)
                source, translate = model.transcribe.call_args_list
                self.assertEqual(("transcribe", None), (source.kwargs["task"], source.kwargs["language"]))
                self.assertEqual(("translate", language), (translate.kwargs["task"], translate.kwargs["language"]))
                self.assertTrue(source.kwargs["without_timestamps"])
                np.testing.assert_array_equal(source.args[0], translate.args[0])

    def test_english_uncertainty_profile_mismatch_skip_lazy_decoder(self):
        for info, selected in ((detection("en"), "fr"), (detection("en"), "auto"),
                               (detection("fr"), "de"), (detection("fr", .49, "en", .45), "fr"),
                               (detection("fr", .51, "es", .46), "auto")):
            with self.subTest(info=info, selected=selected):
                def forbidden():
                    raise AssertionError("uncertain speech decoded")
                    yield
                model = Mock(sensevoice=None, dialogue_model=None)
                model.transcribe.return_value = forbidden(), info
                self.assertEqual([], list(speech_captions(model, self.audio, selected)))
                self.assertEqual(1, model.transcribe.call_count)

    def test_foreign_detection_with_english_or_wrong_script_never_translates(self):
        for lang, text in (("es", "No."), ("fr", "Good morning."), ("de", "Please open the door."),
                           ("es", "Open Settings"), ("ru", "Hello"), ("ar", "1234"),
                           ("he", "مرحبا"), ("fr", "No way"), ("es", "Gracias. Open Settings."),
                           ("hi", "Please open Settings. नमस्ते।"), ("vi", "Xin chào. Open the menu."),
                           ("id", "Terima kasih. Hello."), ("tl", "Salamat. Open Settings.")):
            with self.subTest(lang=lang, text=text):
                model = decoder(detection(lang), text, "Forbidden.")
                self.assertEqual([], list(speech_captions(model, self.audio, lang)))
                self.assertEqual(1, model.transcribe.call_count)

    def test_mixed_english_timestamps_excluded_and_repeats_use_first_wording(self):
        info = detection("es")
        model = Mock(sensevoice=None, dialogue_model=None)
        audio = np.linspace(.001, .1, 48000, dtype=np.float32)
        segments = [segment("Necesito abrir la puerta.", 0., .75), segment("Open Settings", .75, 3.)]
        model.transcribe.side_effect = [(segments, info), ([segment("I need to open the door.")], info),
                                       (segments, info)]
        memory = SpeechCaptionMemory(None)
        first = list(speech_captions(model, audio, "es", memory))
        self.assertEqual(["I need to open the door."], [row["text"] for row in first])
        memory.accept(first[0])
        self.assertEqual(first, list(speech_captions(model, audio, "es", memory)))
        self.assertEqual(3, model.transcribe.call_count)
        self.assertEqual(12000, len(model.transcribe.call_args_list[1].args[0]))

    def test_direct_translation_rejects_copy_low_quality_and_non_english_script(self):
        for text, confidence in (("Gracias!", -.3), ("Hola.", -.3), ("Спасибо.", -.3), ("Thanks.", -1.5)):
            with self.subTest(text=text):
                info = detection("es")
                model = Mock(sensevoice=None, dialogue_model=None)
                model.transcribe.side_effect = [([segment("Gracias.")], info),
                                                ([segment(text, confidence=confidence)], info)]
                self.assertEqual([], list(speech_captions(model, self.audio, "es")))

    def test_stop_during_direct_decode_discards_completed_caption(self):
        info = detection("fr")
        stopped = False
        def stop_after_decoding():
            nonlocal stopped
            stopped = True
            yield segment("Thank you.")
        model = Mock(sensevoice=None, dialogue_model=None)
        model.transcribe.side_effect = [([segment("Merci.")], info), (stop_after_decoding(), info)]
        self.assertEqual([], list(speech_captions(model, self.audio, "fr", cancelled=lambda: stopped)))

    def test_model_choices_exclude_english_and_gate_cantonese_before_input_opens(self):
        self.assertEqual(98, len(BASE_SPEECH_LANGUAGES))
        self.assertEqual({"yue"}, SPOKEN_LANGUAGES - BASE_SPEECH_LANGUAGES)
        self.assertNotIn("en", SPOKEN_LANGUAGES)
        with TemporaryDirectory() as temp:
            engine = AudioEngine(Path(temp), Mock())
            with patch.object(engine, "installed_models", return_value=["base"]):
                for code in ("yue", "en", "xyz"):
                    with self.subTest(code=code), self.assertRaises(ValueError):
                        engine.start(-1, "base", code)
            self.assertIsNone(engine._thread)


if __name__ == "__main__":
    unittest.main()
