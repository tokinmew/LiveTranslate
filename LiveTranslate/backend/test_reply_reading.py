"""Regression fixtures for custom reply readings, independent of the fixed phrasebook."""
import unittest
from unittest.mock import patch

from reply_reading import pronunciation


class ReplyReadingTests(unittest.TestCase):
    def test_mandarin_word_context_and_tones(self):
        for target, source, expected in (
            ("zh", "你好，我要去银行。", "nǐ hǎo, wǒ yào qù yín háng."),
            ("zt", "請問，銀行在哪裡？", "qǐng wèn, yín háng zài nǎ lǐ?"),
            ("zh", "我想喝水。", "wǒ xiǎng hē shuǐ."),
            ("zt", "我可以加入你們嗎？", "wǒ kě yǐ jiā rù nǐ men ma?"),
        ):
            with self.subTest(source=source):
                guide = pronunciation(source, target)
                self.assertEqual(guide["pronunciation"], expected)
                self.assertEqual(guide["pronunciation_scheme"], "Mandarin pinyin")

    def test_japanese_inflection_particles_and_script(self):
        for source, expected in (
            ("少しゆっくり話してください。", "sukoshi yukkuri hanashite kudasai."),
            ("会えて嬉しいです。", "aete ureshii desu."),
            ("私は日本語を話せません。", "watashi wa nihongo o hanasemasen."),
            ("銀行へ行きます。", "ginkou e ikimasu."),
            ("今日は良い天気です。", "kyou wa yoi tenki desu."),
            ("チケット", "chiketto"),
        ):
            with self.subTest(source=source):
                self.assertEqual(pronunciation(source, "ja")["pronunciation"], expected)

    def test_korean_sound_changes(self):
        for source, expected in (
            ("감사합니다.", "gamsahamnida."), ("같이 놀아요.", "gachi norayo."),
            ("신라 국물 연락 읽어요.", "silla gungmul yeollak ilgeoyo."),
            ("괜찮아요?", "gwaenchanayo?"), ("많이 좋아요.", "mani joayo."),
        ):
            with self.subTest(source=source):
                self.assertEqual(pronunciation(source, "ko")["pronunciation"], expected)

    def test_incomplete_or_ambiguous_readings_never_leak_source_script(self):
        for target, text in (("zh","行"), ("zt","銀行𠮷"), ("ja","今日は"), ("ja","ありがとう𠮷"),
                             ("ko","漢字 혼합"), ("ru","привет"), ("ko"," "), ("ja","123"),
                             ("ja","カ" * 4001)):
            with self.subTest(target=target, text=text[:20]):
                guide = pronunciation(text, target)
                self.assertEqual(guide["pronunciation"], "")
                self.assertTrue(guide["pronunciation_note"])

    def test_non_target_words_and_digits_are_identified_as_unconverted(self):
        result = pronunciation("我叫 Tokin。", "zh")
        self.assertEqual(result["pronunciation"], "wǒ jiào Tokin.")
        self.assertIn("remain as written", result["pronunciation_note"])

    def test_missing_data_preserves_reply_path(self):
        with patch("reply_reading._chinese_dictionary", side_effect=ImportError("missing data")):
            self.assertEqual(pronunciation("喝水", "zh")["pronunciation"], "")


if __name__ == "__main__":
    unittest.main()
