"""Profile mappings and readiness require no model downloads or native imports."""
import unittest

from profiles import get_profile, profile_status, screen_languages, speech_language


class ProfileTests(unittest.TestCase):
    def test_script_specific_chinese_text_has_shared_speech_language(self):
        self.assertEqual("zt", get_profile("zt").text_language)
        self.assertEqual("chi_tra", get_profile("zt").ocr_language)
        self.assertEqual("chi_sim", get_profile("zh").ocr_language)
        self.assertEqual("zh", speech_language("zt"))
        self.assertEqual("zh", speech_language("zh"))

    def test_manual_profiles_choose_matching_ocr(self):
        self.assertEqual(("ko", "kor"), screen_languages("ko", "auto"))
        self.assertEqual(("ja", "jpn"), screen_languages("ja", "auto"))
        self.assertEqual(("zt", "chi_tra"), screen_languages("zt", "auto"))
        self.assertEqual(("ko", "kor"), screen_languages("ko", ""))
        self.assertEqual(("ko", "eng"), screen_languages("ko", "eng"))

    def test_japanese_vertical_keeps_same_text_translator(self):
        self.assertEqual(("ja", "jpn_vert"), screen_languages("ja", vertical=True))
        self.assertEqual(("ja", "jpn_vert"), screen_languages("ja", "jpn_vert"))
        self.assertEqual(("jpn", "jpn_vert"), get_profile("ja").ocr_languages)

    def test_other_languages_keep_advanced_ocr_choice(self):
        self.assertEqual(("auto", "spa+eng"), screen_languages("auto", "spa+eng"))
        self.assertEqual("auto", speech_language("auto"))
        self.assertEqual("es", speech_language("es"))

    def test_unsupported_vertical_layout_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "Japanese"):
            screen_languages("ko", vertical=True)

    def test_japanese_readiness_requires_both_layouts(self):
        status = {row["code"]: row for row in profile_status(["ja"], ["jpn"], ["base"], True)}
        self.assertTrue(status["ja"]["text_ready"])
        self.assertFalse(status["ja"]["ocr_ready"])
        self.assertFalse(status["ja"]["assets_ready"])

    def test_downloaded_assets_do_not_claim_ocr_engine_installed(self):
        japanese = next(row for row in profile_status(["ja"], ["jpn", "jpn_vert"], ["base"], False) if row["code"] == "ja")
        self.assertTrue(japanese["assets_ready"])
        self.assertFalse(japanese["ocr_engine_ready"])
        self.assertFalse(japanese["screen_ready"])


if __name__ == "__main__":
    unittest.main()
