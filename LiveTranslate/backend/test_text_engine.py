import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from text_engine import TextEngine, _token_chunks, _sentence_parts, _short_script_language


class CharacterTokenizer:
    def encode(self, text, out_type=str):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


class Result:
    def __init__(self, tokens):
        self.hypotheses = [tokens]


class EchoTranslator:
    def __init__(self):
        self.calls = []
        self.model_is_loaded = True

    def unload_model(self):
        self.model_is_loaded = False

    def load_model(self):
        self.model_is_loaded = True

    def translate_batch(self, tokens, **kwargs):
        self.calls.append((tokens, kwargs))
        return [Result(x) for x in tokens]


class TextTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.engine = TextEngine(self.root / "data")

    def tearDown(self):
        self.scratch.cleanup()

    def pack(self, extra=None, target="en", tokenizer=True, code="es", config=True, vocabulary="json"):
        path = self.root / "test.argosmodel"
        contents = {
            "translate-es_en/metadata.json": json.dumps({"from_code": code, "from_name": "Spanish", "to_code": target}),
            "translate-es_en/model/model.bin": b"placeholder",
        }
        if config:
            contents["translate-es_en/model/config.json"] = b"{}"
        if vocabulary:
            contents["translate-es_en/model/shared_vocabulary." + vocabulary] = b"[]"
        if tokenizer:
            contents["translate-es_en/sentencepiece.model"] = b"placeholder"
        contents.update(extra or {})
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in contents.items():
                archive.writestr(name, value)
        return path

    def test_import_is_offline_and_lists_installed(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network used")):
            self.assertEqual(self.engine.import_pack(self.pack()), "es")
            self.assertEqual(self.engine.installed()[0]["name"], "Spanish")

    def test_rejects_traversal_without_writing(self):
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.engine.import_pack(self.pack({"../escaped.txt": "bad"}))
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertEqual(self.engine.installed(), [])

    def test_rejects_windows_alternate_stream(self):
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.engine.import_pack(self.pack({"translate-es_en/model/a:stream": "bad"}))

    def test_rejects_non_english_direction(self):
        with self.assertRaisesRegex(ValueError, "English"):
            self.engine.import_pack(self.pack(target="fr"))

    def test_rejects_unsupported_tokenizer(self):
        with self.assertRaisesRegex(ValueError, "SentencePiece"):
            self.engine.import_pack(self.pack(tokenizer=False))

    def test_does_not_overwrite_installed_pack(self):
        path = self.pack()
        self.engine.import_pack(path)
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.engine.import_pack(path)

    def test_installed_language_does_not_trigger_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network used")):
            self.assertEqual(self.engine.translate("Hello", "en")["text"], "")
            with self.assertRaisesRegex(ValueError, "pack is installed"):
                self.engine.translate("Hola", "es")

    def test_long_cjk_chunking_loses_no_characters(self):
        text = "日本語の長い文章" * 90
        chunks = _token_chunks(text, CharacterTokenizer(), maximum=17)
        self.assertEqual("".join("".join(x) for x in chunks), text)
        self.assertTrue(all(len(x) <= 17 for x in chunks))

    def test_word_chunking_loses_no_characters(self):
        text = "uno dos tres cuatro " * 40
        chunks = _token_chunks(text, CharacterTokenizer(), maximum=17)
        self.assertEqual("".join("".join(x) for x in chunks), text)

    def test_translation_preserves_paragraph_separators_and_disables_truncation(self):
        translator = EchoTranslator()
        self.engine._loaded["es"] = translator, CharacterTokenizer(), ""
        result = self.engine.translate("Hola.\n\nMundo!", "es")
        self.assertEqual(result, {"text": "Hola.\n\nMundo!", "language": "es"})
        self.assertEqual(translator.calls[0][1]["max_input_length"], 0)

    def test_short_japanese_labels_use_validated_decoder_length(self):
        for code, penalty in (("ja", 0.6), ("ko", 0.2), ("zh", 0.2), ("zt", 0.2)):
            translator = EchoTranslator()
            self.engine._loaded[code] = translator, CharacterTokenizer(), ""
            self.engine.translate("日本語翻訳", code)
            self.assertEqual(penalty, translator.calls[0][1]["length_penalty"])

    def test_auto_detection_is_not_forced_to_installed_languages(self):
        with patch.object(self.engine, "_detect", return_value="ja"):
            with self.assertRaisesRegex(ValueError, "ja"):
                self.engine.translate("日本語です", "auto")

    def test_switches_reuse_native_instances_and_park_inactive_weights(self):
        factories = []
        for code in ("ko", "ja"):
            self.engine.import_pack(self.pack(code=code))
        def construct(*args, **kwargs):
            translator = EchoTranslator()
            factories.append(translator)
            return translator
        modules = {"ctranslate2": types.SimpleNamespace(Translator=construct),
                   "sentencepiece": types.SimpleNamespace(SentencePieceProcessor=lambda **kwargs: CharacterTokenizer())}
        with patch.dict("sys.modules", modules):
            ko = self.engine._load("ko")[0]
            ja = self.engine._load("ja")[0]
            self.assertFalse(ko.model_is_loaded)
            self.assertTrue(ja.model_is_loaded)
            for _ in range(5):
                self.assertIs(ko, self.engine._load("ko")[0])
                self.assertFalse(ja.model_is_loaded)
                self.assertIs(ja, self.engine._load("ja")[0])
                self.assertFalse(ko.model_is_loaded)
        self.assertEqual([ko, ja], factories)

    def test_accepts_legacy_japanese_txt_pack_without_config(self):
        self.engine.import_pack(self.pack(code="ja", config=False, vocabulary="txt"))
        self.assertEqual(self.engine.installed()[0]["code"], "ja")
        self.assertEqual(self.engine.installed()[0]["name"], "Japanese")

    def test_tokenizer_bytes_are_read_from_a_unicode_installation(self):
        engine = TextEngine(self.root / "図書館 & 한글" / "data")
        engine.import_pack(self.pack(code="ja"))
        def open_tokenizer(*, model_proto):
            self.assertEqual(b"placeholder", model_proto)
            return CharacterTokenizer()
        modules = {"ctranslate2": types.SimpleNamespace(Translator=lambda *args, **kwargs: EchoTranslator()),
                   "sentencepiece": types.SimpleNamespace(SentencePieceProcessor=open_tokenizer)}
        with patch.dict("sys.modules", modules):
            self.assertEqual("図書館", engine.translate("図書館", "ja")["text"])

    def test_accepts_korean_and_both_distinct_chinese_pack_codes(self):
        for code in ("ko", "zh", "zt"):
            self.engine.import_pack(self.pack(code=code, config=False))
        self.assertEqual({x["code"] for x in self.engine.installed()}, {"ko", "zh", "zt"})

    def test_rejects_missing_vocabulary(self):
        with self.assertRaisesRegex(ValueError, "vocabulary"):
            self.engine.import_pack(self.pack(vocabulary=None))

    def test_cjk_sentence_punctuation_is_recognized(self):
        self.assertEqual(_sentence_parts("\u65e5\u672c\u8a9e\u3002\u6b21\u3002"),
                         ["\u65e5\u672c\u8a9e\u3002", "\u6b21\u3002"])

    def chinese_converters(self, simplified=False, traditional=False):
        class Converter:
            def __init__(self, changed):
                self.changed = changed
            def convert(self, text):
                return text + "changed" if self.changed else text
        self.engine._chinese_converters = Converter(simplified), Converter(traditional)

    def test_chinese_simplified_evidence_selects_zh_only(self):
        self.chinese_converters(simplified=True)
        self.assertEqual(self.engine._chinese_script("sample"), "zh")

    def test_chinese_traditional_evidence_selects_zt_only(self):
        self.chinese_converters(traditional=True)
        self.assertEqual(self.engine._chinese_script("sample"), "zt")

    def test_common_chinese_needs_manual_script_selection(self):
        self.chinese_converters()
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.engine._chinese_script("sample")

    def test_mixed_chinese_needs_manual_script_selection(self):
        self.chinese_converters(simplified=True, traditional=True)
        with self.assertRaisesRegex(ValueError, "mixed"):
            self.engine._chinese_script("sample")

    def test_detector_preserves_other_language_results(self):
        class Identifier:
            def classify(self, text):
                return "en", 0.99
        self.engine._identifier = Identifier()
        with patch.object(self.engine, "_chinese_script", side_effect=AssertionError("wrong routing")):
            self.assertEqual(self.engine._detect("English text"), "en")

    def test_detector_uses_py3langid_modern_model_file_api(self):
        calls = []
        class Identifier:
            @classmethod
            def from_model_file(cls, path, norm_probs=False):
                calls.append((path, norm_probs))
                return cls()
            def classify(self, text):
                return "en", 0.99
        package = types.ModuleType("py3langid")
        module = types.ModuleType("py3langid.langid")
        module.MODEL_FILE = "bundled-model"
        module.LanguageIdentifier = Identifier
        with patch.dict("sys.modules", {"py3langid": package, "py3langid.langid": module}):
            self.assertEqual(self.engine._detect("This is an English sentence."), "en")
        self.assertEqual(calls, [("bundled-model", True)])

    def test_short_kana_routes_to_japanese_without_detector(self):
        text = "\u30ab\u30e1\u30e9"
        self.assertEqual(_short_script_language(text), "ja")
        self.assertEqual(self.engine._detect(text), "ja")
        self.assertIsNone(self.engine._identifier)

    def test_short_hangul_routes_to_korean_without_detector(self):
        text = "\ub3c4\uc11c\uad00"
        self.assertEqual(_short_script_language(text), "ko")
        self.assertEqual(self.engine._detect(text), "ko")
        self.assertIsNone(self.engine._identifier)

    def test_mixed_and_han_only_do_not_override_detector(self):
        for text in ("\u30ab\u30e1\u30e9 camera", "\u30ab\u30e1\u30e9 \ub3c4\uc11c\uad00", "\u4e2d\u6587", "English"):
            self.assertIsNone(_short_script_language(text))

    def test_manual_source_is_not_overridden_by_script_detection(self):
        translator = EchoTranslator()
        self.engine._loaded["zh"] = translator, CharacterTokenizer(), ""
        with patch.object(self.engine, "_detect", side_effect=AssertionError("Manual source overridden")):
            result = self.engine.translate("\u30ab\u30e1\u30e9", "zh")
        self.assertEqual(result["language"], "zh")

    def test_detector_routes_chinese_only_after_classification(self):
        class Identifier:
            def classify(self, text):
                return "zh", 0.99
        self.engine._identifier = Identifier()
        self.chinese_converters(traditional=True)
        self.assertEqual(self.engine._detect("sample"), "zt")

    def test_automatic_simplified_never_uses_installed_traditional_pack(self):
        translator = EchoTranslator()
        self.engine._loaded["zt"] = translator, CharacterTokenizer(), ""
        with patch.object(self.engine, "_detect", return_value="zh"):
            with self.assertRaisesRegex(ValueError, "No zh"):
                self.engine.translate("sample", "auto")
        self.assertEqual(translator.calls, [])

    def test_catalog_only_selects_direct_english_routes(self):
        rows = [{"from_code": "es", "from_name": "Spanish", "to_code": "en", "links": ["https://example.org/es"]},
                {"from_code": "en", "to_code": "es", "links": ["https://example.org/en"]}]
        with patch("text_engine._bounded_read", return_value=json.dumps(rows).encode()):
            result = self.engine.catalog()
        self.assertEqual([p["code"] for p in result], ["es"])


if __name__ == "__main__":
    unittest.main()
