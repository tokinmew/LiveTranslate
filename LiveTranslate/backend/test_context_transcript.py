import unittest
from types import SimpleNamespace

from context_transcript import _separate, context_transcript


def word(text, start, end, probability=.85):
    return SimpleNamespace(word=text, start=start, end=end, probability=probability)


class ContextTranscriptTests(unittest.TestCase):
    def test_prefix_is_removed_and_confidence_uses_only_heard_source(self):
        words = [word("你好", .10, .52, .99), word("天氣", .55, 1.30, .63)]
        text, p = _separate(words, "zh", .73, True)
        self.assertEqual(text, "天氣")
        self.assertAlmostEqual(p, .63)

    def test_trailing_context_stays_out_of_source(self):
        words = [word("네", .15, .60), word(" 안녕하세요", 1.1, 1.7)]
        self.assertEqual(_separate(words, "ko", .80, False)[0], "네")

    def test_uncertain_alignment_and_marker_echo_do_not_create_foreign_captions(self):
        self.assertIsNone(_separate([word("你好", .10, .52)], "zh", .73, True))
        self.assertIsNone(_separate([word("你好你好", .10, 1.2)], "zh", .73, True))
        self.assertIsNone(_separate([word("你好", .10, .52), word("你好", .62, 1.3)], "zh", .73, True))
        self.assertIsNone(_separate([word("你好", .10, .52), word("Go", .72, 1.1)], "zh", .73, True))

    def test_unknown_language_or_cancellation_never_opens_the_decoder(self):
        self.assertIsNone(context_transcript(None, [], "en"))
        self.assertIsNone(context_transcript(None, [0] * 2000, "ja", cancelled=lambda:True))


if __name__ == "__main__":
    unittest.main()
