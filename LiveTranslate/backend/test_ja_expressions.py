import unittest

from ja_expressions import expression_reply
from spoken_lexicon import lexical_reply


class ExpressionTests(unittest.TestCase):
    def test_exact_expression_and_formatting(self):
        self.assertEqual(expression_reply("「お先にどうぞ！」", "ja"), "Please go ahead!")
        self.assertEqual(lexical_reply("あっという間に", "ja"), "In an instant.")

    def test_whole_utterance_only_and_existing_replies_first(self):
        self.assertIsNone(expression_reply("お先にどうぞと言いました", "ja"))
        self.assertEqual(lexical_reply("お先にどうぞ", "ja", {"お先にどうぞ": "After you."}), "After you.")

    def test_language_and_ambiguous_readings(self):
        for source, lang in (("After you", "ja"), ("お先にどうぞ", "zh"), ("はし", "ja"),
                             ("かえる", "ja"), ("行ってきます ATM", "ja")):
            self.assertIsNone(expression_reply(source, lang))


if __name__ == "__main__":
    unittest.main()
