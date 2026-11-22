import unittest
from speech_fidelity import preserve_clock_precision


class SpeechTimeTests(unittest.TestCase):
    def test_preserves_unspecified_time_in_all_three_languages(self):
        cases = [
            ("ko", "두 시에 문을 엽니다.", "We open at 2 p.m.", "We open at 2."),
            ("ja", "三時ですか？", "Three a.m.?", "Three?"),
            ("zh", "八點半可以嗎？", "Can we meet at 8:30pm?", "Can we meet at 8:30?"),
            ("zh", "从九点到十一点。", "From 9 a.m. to 11 a.m.", "From 9 to 11."),
        ]
        for language, source, english, expected in cases:
            with self.subTest(language=language, english=english):
                self.assertEqual(preserve_clock_precision(source, english, language), expected)

    def test_keeps_expressed_dayparts_and_unrelated_phrases(self):
        cases = [
            ("ko", "저녁 일곱 시에 봐요.", "See you at 7pm."),
            ("ja", "午後二時です。", "It's two p.m."),
            ("zh", "晚上九点见。", "See you at 9 p.m."),
            ("zh", "十九点出发。", "Leave at 7 p.m."),
            ("ja", "18時に開きます。", "It opens at 6 p.m."),
            ("ko", "십육 시에 만나요.", "Meet me at 4 p.m."),
            ("zh", "打开文件。", "Open the 10 PM file."),
            ("ja", "三時です。", "It's 3 o'clock."),
        ]
        for language, source, english in cases:
            with self.subTest(language=language, english=english):
                self.assertEqual(preserve_clock_precision(source, english, language), english)
