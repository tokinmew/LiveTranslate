import random
import string
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from foreign_text import PRIORITY, foreign_segments, script
from screen_engine import ScreenCaptureUnavailable
from text_engine import TextEngine, _decode_target, _japanese_sentence
from test_worker import FakeAudio, FakeScreen, FakeText
from worker import Worker


class ForeignScriptTests(unittest.TestCase):
    def test_no_cjk_means_no_route(self):
        examples = [
            "Hello, let's go!\nPress F1 to open Settings.",
            "Ｆｕｌｌｗｉｄｔｈ Ｅｎｇｌｉｓｈ ９９％",
            "Français Ελληνικά Русский العربية हिन्दी ไทย",
            "ni hao / konnichiwa / annyeong",
            "©2026—⚙️ １２３４５ ＆ 100% \u3000 ー ・ 々",
            "https://example.test/東京?search=日本語",
            "⟪Cancel⟫\r\n(OK)\rOther",
        ]
        for source in sorted(PRIORITY | {"auto", "en"}):
            for text in examples:
                with self.subTest(source=source, text=text):
                    self.assertEqual([], foreign_segments(text, source))

    def test_thousands_of_latin_only_variations(self):
        generator = random.Random(401)
        characters = string.printable + "üÀÉœ－’Ｆｅ—Ⓜ³¾ "
        for _ in range(1200):
            value = "".join(generator.choices(characters, k=generator.randrange(1, 95)))
            self.assertEqual([], foreign_segments(value, generator.choice(("ja", "zh", "zt", "ko", "auto"))))

    def test_cjk_variants_and_shared_han(self):
        cases = [
            ("こんにちは", "ja"), ("カタカナ", "ja"), ("ﾊﾝｶｸ", "ja"),
            ("한", "ko"), ("안녕하세요", "ko"), ("ㄱㅁ", "ko"),
            ("ㄅㄆㄇ", "zt"), ("臺灣", "han"), ("𠮷野家", "han"), ("入口", "han"),
        ]
        for phrase, route in cases:
            self.assertEqual([(route, phrase)], foreign_segments(phrase, "auto"))
        for source in PRIORITY:
            self.assertEqual([(source, "入口")], foreign_segments("入口", source))
        self.assertEqual([], foreign_segments("안녕하세요", "ja"))
        self.assertEqual([], foreign_segments("カタカナ", "ko"))
        self.assertEqual("", script("⚙"))

    def test_bilingual_ui_and_inline_names(self):
        self.assertEqual([("ja", "東京駅でWi-Fiを使えます。")],
                         foreign_segments("HOME | 東京駅でWi-Fiを使えます。 English translation.\nSettings", "ja"))
        self.assertEqual([("zh", "你好")], foreign_segments("Hello你好", "zh"))
        self.assertEqual([("zh", "你好")], foreign_segments("你好Hello", "zh"))
        self.assertEqual([], foreign_segments("S日ttings", "auto"))
        self.assertEqual([("ja", "東京")], foreign_segments("a" * 49000 + "!東京", "ja"))
        self.assertEqual([("zh", "日期")], foreign_segments("DATE 日期 / Date", "zh"))
        self.assertEqual([("ja", "iPhoneを使用")], foreign_segments("iPhoneを使用", "ja"))
        self.assertEqual([("ko", "USB-C 는 사용 가능합니다")],
                         foreign_segments("USB-C 는 사용 가능합니다", "ko"))
        self.assertEqual([("ko", "기차는 New York 에 갑니다.")],
                         foreign_segments("기차는 New York 에 갑니다.", "ko"))
        self.assertEqual([("ja", "山田"), ("ja", "東京へ")],
                         foreign_segments("山田 this is already in English 東京へ", "ja"))

    def test_independent_languages_on_same_screen(self):
        self.assertEqual([("ja", "日本に行く。"), ("ko", "서울에 갑니다."), ("han", "再見")],
                         foreign_segments("English. 日本に行く。\t서울에 갑니다.\nStatus\n再見", "auto"))
        self.assertEqual([("ja", "ホタル"), ("ko", "안녕")], foreign_segments("ホタル 안녕", "auto"))


class ForeignRoutingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, fake in (("TextEngine", FakeText), ("AudioEngine", FakeAudio), ("ScreenEngine", FakeScreen)):
            p = patch("worker." + name, fake)
            p.start()
            self.addCleanup(p.stop)
        job = patch.object(Worker, "_jobs", lambda _: None)
        job.start()
        self.addCleanup(job.stop)
        self.events = []
        self.app = Worker(Path(directory.name), self.events.append)
        self.addCleanup(self.app.close)
        self.app.text.translate = Mock(side_effect=lambda t, s: {"text": "translated " + t, "language": s})
        self.app.text.caption_han_language = Mock(return_value="zt")

    def test_all_profiles_ignore_typed_english_before_inference(self):
        for source in PRIORITY | {"auto", "en"}:
            self.app.execute({"command": "translate", "text": "Already in English", "source": source, "id": 8})
            self.assertEqual("", self.events[-1]["text"])
            self.assertTrue(self.events[-1]["ignored"])
            self.assertEqual(8, self.events[-1]["id"])
        self.app.text.translate.assert_not_called()
        self.app.text.caption_han_language.assert_not_called()

    def test_typed_language_routing_keeps_order_and_filters_english(self):
        self.app.execute({"command": "translate", "source": "auto",
                          "text": "Menu\nこんにちは\nEnglish subtitle\n再見\n안녕\nまたね"})
        self.assertEqual({"ja", "zt", "ko"}, {call.args[1] for call in self.app.text.translate.call_args_list})
        self.assertEqual("mul", self.events[-1]["language"])
        self.assertEqual(["translated こんにちは", "translated 再見", "translated 안녕", "translated またね"],
                         self.events[-1]["text"].splitlines())
        self.app.text.caption_han_language.assert_called_once_with("再見")

    def _one_shot(self, value, **extra):
        with patch.object(self.app.screen, "recognize", return_value=value, create=True) as recognize:
            self.app.dispatch(dict(command="read_screen_once", source="ja", session_id="read1",
                                   region={"left":0, "top":0, "width":90, "height":90}, **extra))
            self.app.execute(self.app.jobs.get_nowait())
            self.app.screen_once_thread.join(2)
        self.assertFalse(self.app.screen_once_thread.is_alive())
        return next(event for event in self.events if event["type"] == "screen_once"), recognize

    def test_read_once_english_returns_empty_without_translation(self):
        e, _ = self._one_shot("Reading an English subtitle")
        self.assertTrue(e["ignored"])
        self.assertEqual((e["original"], e["text"]), ("", ""))
        self.assertEqual("read1", e["session_id"])
        self.app.text.translate.assert_not_called()

    def test_read_once_masks_window_handles_and_filters_mixed_source(self):
        e, mock = self._one_shot("Close\nこんにちは\nGood morning", exclude_windows=[22, 11, 22])
        self.assertEqual((22,11), mock.call_args.kwargs["exclude_windows"])
        self.assertEqual("こんにちは", e["original"])
        self.app.text.translate.assert_called_once_with("こんにちは", "ja")

    def test_partial_auto_install_keeps_other_foreign_lines(self):
        self.app.text.codes = {"ja"}
        request = self.app._screen_request({"source":"auto","region":{"left":0,"top":0,"width":170,"height":90}}, "screen")
        orig, result = self.app.translate_screen_text("안녕\nこんにちは\nSettings", "auto", request)
        self.assertEqual("こんにちは", orig)
        self.assertEqual("translated こんにちは", result["text"])
        self.app.text.translate.assert_called_once_with("こんにちは", "ja")

    def test_transient_display_failures_are_retryable_but_model_errors_are_not(self):
        for issue, expected in ((ScreenCaptureUnavailable("Display unplugged"), True),
                                (RuntimeError("Model error"), False)):
            done = threading.Event()
            def send(e):
                self.events.append(e)
                if e.get("state") == "error":
                    done.set()
            self.app.send = send
            with patch.object(self.app.screen, "recognize", side_effect=issue, create=True):
                self.app.dispatch({"command":"start_screen","source":"ja","session_id":"display",
                                   "region":{"left":0,"top":0,"width":90,"height":90}})
                self.app.execute(self.app.jobs.get_nowait())
                self.assertTrue(done.wait(2))
            last = [e for e in self.events if e.get("state") == "error"][-1]
            self.assertEqual(expected, last["retryable"])

    def test_defaults_and_invalid_window_exclusions(self):
        for handles in (None, [False], [0], [-1], [2**64], "123", list(range(1,19))):
            with self.assertRaisesRegex(ValueError, "exclusions"):
                self.app._screen_request({"source":"ja", "exclude_windows":handles,
                                          "region":{"left":0,"top":0,"width":200,"height":100}}, "screen")

    def test_imported_language_skips_english_and_uncertain_input(self):
        with tempfile.TemporaryDirectory() as d:
            engine = TextEngine(Path(d))
            with patch.object(engine, "_detect", side_effect=["en", "de", ValueError("uncertain"), "fr"]), \
                 patch.object(engine, "translate", return_value={"text":"Good evening", "language":"fr"}) as translate:
                r = engine.translate_imported("already English\nguten Abend\nOK\nbonsoir", "fr")
                self.assertEqual("Good evening", r["text"])
                translate.assert_called_once_with("bonsoir", "fr")

    def test_ambiguous_han_does_not_stop_auto_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TextEngine(Path(directory))
            with patch.object(engine, "_detect", side_effect=ValueError("uncertain")), \
                 patch.object(engine, "_chinese_script", side_effect=ValueError("ambiguous")):
                self.assertEqual("zh", engine.caption_han_language("入口"))

    def test_mandarin_speech_normalizes_whisper_script_for_available_pack(self):
        self.app.text.codes = {"zh", "zt"}
        self.app.text.convert_chinese = Mock(return_value="这是一个语音识别测试")
        r = self.app.audio.translate_source("這是一個語音識別測試", "zh")
        self.assertEqual("zh", r["language"])
        self.app.text.translate.assert_called_once_with("这是一个语音识别测试", "zh")
        self.app.text.codes = {"zt"}
        self.app.text.convert_chinese.return_value = "這是一個語音識別測試"
        r = self.app.audio.translate_source("这是一个语音识别测试", "zh")
        self.assertEqual("zt", r["language"])
        self.app.text.codes.clear()
        self.assertIsNone(self.app.audio.translate_source("日本語です", "ja"))
        self.assertTrue(self.app.audio.translate_source("Only English", "ja")["ignored"])

    def test_chinese_target_only_english_word_boundaries(self):
        pieces = ["▁Where", "'", "s", "▁the", "▁library", "?"]
        tokenizer = Mock()
        tokenizer.decode.return_value = "▁Where's the▁library?"
        tokenizer.unk_id.return_value = 0
        tokenizer.piece_to_id.side_effect = lambda p: 0 if p in {"▁Where", "▁library"} else 3
        self.assertEqual("Where's the library?", _decode_target(tokenizer, pieces).strip())
        tokenizer.decode.return_value = "Where is the library?"
        self.assertEqual("Where is the library?", _decode_target(tokenizer, pieces))

    def test_unpunctuated_japanese_subtitles_and_complete_labels(self):
        self.assertEqual("日本語を英語に翻訳します。", _japanese_sentence("日本語を英語に翻訳します"))
        self.assertEqual("駅はどこですか？", _japanese_sentence("駅はどこですか"))
        self.assertEqual("電車が来ます！", _japanese_sentence("電車が来ます！"))
        self.assertEqual("日本語翻訳", _japanese_sentence("日本語翻訳"))

    def test_source_script_echo_is_not_an_english_caption(self):
        self.app.text.translate.side_effect = lambda t, s: {"text":t, "language":s}
        self.app.execute({"command":"translate", "text":"日本語の字幕", "source":"ja"})
        self.assertTrue(self.events[-1]["ignored"])


if __name__ == "__main__":
    unittest.main()
