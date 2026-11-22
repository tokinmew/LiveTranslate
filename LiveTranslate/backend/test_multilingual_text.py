"""Regression coverage for profile capabilities, English rejection and model routing."""
from collections import OrderedDict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from language_catalog import NLLB_TAGS, canonical_code
from language_routes import ocr_code, speech_code
from multilingual_text import model_files_present, resolve_line, standalone_translation
from profiles import profile_status
from speech_translation import NllbTranslator
from text_engine import TextEngine


class MultilingualTextTests(unittest.TestCase):
    def test_tags_are_unique_and_english_is_destination_only(self):
        self.assertEqual(201, len(set(NLLB_TAGS.values())))
        self.assertNotIn('eng_Latn', NLLB_TAGS.values())
        self.assertEqual('zho_Hant', NLLB_TAGS[canonical_code('zh_HK')])
        self.assertEqual('kas_Deva', NLLB_TAGS[canonical_code('ks-deva')])
        self.assertEqual('jw', speech_code('jv'))
        self.assertEqual('fra', ocr_code('fr-CA'))
        self.assertEqual('', speech_code('ks-deva'))

    def test_readiness_requires_installed_assets_for_each_mode(self):
        rows = {r['code']: r for r in profile_status(['fr'], ['fra'], ['base'], True)}
        self.assertEqual(204, len(rows))
        self.assertTrue(rows['fr']['screen_ready'])
        self.assertTrue(rows['de']['speech_ready'])
        self.assertFalse(rows['de']['text_ready'])
        self.assertFalse(rows['haw']['text_supported'])
        self.assertFalse(rows['yue']['speech_ready'])
        rows = {r['code']: r for r in profile_status([], [], ['large-v3'], False, True)}
        self.assertTrue(rows['yue']['speech_ready'])
        self.assertEqual('NLLB', rows['ks-deva']['text_model'])
        self.assertFalse(rows['ks-deva']['screen_ready'])

    def test_missing_or_partial_model_does_not_advertise_text_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(model_files_present(tmp))
            part = Path(tmp) / 'nllb-600m-int8'
            part.mkdir()
            (part / 'model.bin').write_bytes(b'partial')
            self.assertFalse(model_files_present(tmp))

    def test_nonenglish_dominance_resolves_confusion_among_related_languages(self):
        rank = lambda text: ('es', .32, .24, .00001)
        self.assertEqual('es', resolve_line('una puerta grande', 'es', rank, lambda: ['es']))
        self.assertIsNone(resolve_line('una puerta grande', 'fr', rank, lambda: ['es','fr']))
        # Remaining English candidates preclude emitting an ambiguous caption.
        self.assertIsNone(resolve_line('found some treasure', 'es', lambda t: ('es', .5, .4, .1), lambda: ['es']))

    def test_unlisted_latin_detector_classes_need_positive_foreign_evidence(self):
        rank = lambda text: ('it', .60, .28, .00001)
        self.assertEqual('scn', resolve_line('chidda casa era granni', 'scn', rank, lambda: ['it']))
        self.assertIsNone(resolve_line('Texas', 'scn', rank, lambda: ['it']))
        self.assertIsNone(resolve_line('Continue', 'scn', rank, lambda: ['it']))

    def test_mixed_rows_keep_order_skip_english_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = TextEngine(Path(tmp))
            quality = Mock(side_effect=lambda lines, lang: {'text': {'fr':'Hello','ta':'Open the door'}[lang]})
            result = engine.translate_multilingual('Bonjour\nContinue\nகதவைத் திற\nBonjour', 'auto',
                                                  quality, Mock(side_effect=AssertionError()))
            self.assertEqual({'language': 'mul', 'text': 'Hello\nOpen the door\nHello'}, result)
            self.assertEqual(2, quality.call_count)

    def test_explicit_script_and_unambiguous_short_phrases_need_no_id_model(self):
        forbidden = Mock(side_effect=AssertionError('ID model loaded unnecessarily'))
        for source, text in [('ar','افتح الباب'),('hi','दरवाजा खोलो'),('th','สวัสดี'),('vi','xin chào')]:
            self.assertEqual(source, resolve_line(text, source, forbidden, forbidden))
        for text in ['Is the display ready?', 'Options', '© 2026', 'https://example.invalid']:
            self.assertIsNone(resolve_line(text, 'vi', forbidden, forbidden))

    def test_missing_shared_model_offers_install_and_english_stays_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = TextEngine(Path(tmp))
            quality = Mock(return_value=None)
            omit = Mock(side_effect=AssertionError())
            self.assertTrue(engine.translate_multilingual('Turn on subtitles', 'de', quality, omit)['ignored'])
            quality.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'multilingual quality model'):
                engine.translate_multilingual('Vielen Dank', 'de', quality, omit)

    def test_standalone_greetings_preserve_meaning_without_rewriting_sentences(self):
        for code, phrase, expected in [('fr','Bonjour!', 'Hello.'), ('fr','Merci beaucoup.', 'Thank you very much.'),
                                       ('es','Buenos días.', 'Good morning.'), ('vi','Xin chào', 'Hello.')]:
            self.assertEqual(expected, standalone_translation(phrase, code))
        self.assertIsNone(standalone_translation('Bonjour, madame.', 'fr'))
        self.assertIsNone(standalone_translation('Bonsoir', 'de'))

    def test_long_nllb_input_is_batched_without_truncating_the_tail(self):
        class Tokenizer:
            def encode(self, text, out_type=str): return list(text)
            def decode(self, tokens): return ''.join(tokens)
        class Model:
            def __init__(self): self.calls = 0
            def translate_batch(self, values, **kwargs):
                self.calls += 1
                return [Mock(hypotheses=[['eng_Latn', *v[1:-1]]]) for v in values]
        engine = NllbTranslator.__new__(NllbTranslator)
        engine._recent, engine.tokens, engine.model = OrderedDict(), Tokenizer(), Model()
        source = ('木' * 401) + '尾'
        results = engine.translate_many([('zh', source), ('zh', source)])
        self.assertEqual(source, results[0].replace(' ', ''))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results, engine.translate_many([('zh', source), ('zh', source)]))
        self.assertEqual(1, engine.model.calls)


if __name__ == '__main__':
    unittest.main()

