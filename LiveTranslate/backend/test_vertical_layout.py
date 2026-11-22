"""A vertical caption needs ordered source glyph agreement from two layouts."""
import unittest
from unittest.mock import Mock

from ocr_guard import join_vertical_glyphs
from vertical_layout import Column, _accepted_source, read_columns


def token(text, confidence=95):
    return f'5\t1\t1\t1\t1\t1\t2\t2\t110\t20\t{confidence}\t{text}'


class VerticalLayoutTests(unittest.TestCase):
    def test_order_correspondence_and_confidence(self):
        vertical = ('新幹線 の 切符',token('新幹線の切符'))
        self.assertEqual('新幹線の切符',_accepted_source(vertical,'新幹線の切符'))
        self.assertEqual('',_accepted_source(vertical,'切符の新幹線'))
        self.assertEqual('',_accepted_source(('新幹線',token('新幹線',25)),'新幹線'))
        self.assertEqual('',_accepted_source(vertical,'Train ticket'))

    def test_cjk_punctuation_and_vowel_marks_do_not_become_words(self):
        self.assertEqual('ミルクティー。',join_vertical_glyphs('ミル ク ティ ー 。'))
        self.assertEqual('USB です。',join_vertical_glyphs('USB で す 。'))

    def test_stacked_english_is_removed_before_horizontal_screen_ocr(self):
        frame, column, reflowed = Mock(), Mock(), Mock()
        box = (25,10,65,165)
        read = Mock(return_value=('OPTIONS',''))
        masked, lines, partial = read_columns(frame,[Column(box,column,reflowed,245)],'jpn+kor',read,Mock())
        self.assertEqual([],lines)
        self.assertFalse(partial)
        masked.paste.assert_called_once_with(245,box)
        self.assertEqual(1,read.call_count)

    def test_timeout_flags_partial_column_for_retry(self):
        frame = Mock()
        column = Column((0,0,30,150), Mock(), Mock(), 250)
        _, lines, partial = read_columns(frame, [column], 'jpn+kor', Mock(return_value=None), Mock())
        self.assertTrue(partial)
        self.assertEqual([], lines)


if __name__ == '__main__':
    unittest.main()
