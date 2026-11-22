import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from ocr_guard import Word
from screen_engine import ScreenEngine
from screen_geometry import positioned_segments
from screen_lines import accepted_regions


class ExplicitScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = ScreenEngine(Path(self.temp.name))
        self.frame = Image.new("L", (600, 90), 245)
        self.frame.info["desktop_map"] = (-200, -100, .5, .5)
        self.region = dict(left=-200, top=-100, width=300, height=45)

    def test_mixed_same_row_keeps_only_foreign_words_and_source_bounds(self):
        row = [Word(text, (12+idx*62,20,70+idx*62,44), 97, ('1',))
               for idx,text in enumerate(("Press","here","Veuillez","ouvrir","la","porte."))]
        accepted = accepted_regions(self.frame, row, "fr", lambda text, _: text == "Veuillez ouvrir la porte.")
        self.assertEqual(1,len(accepted))
        self.assertEqual([(("fr","Veuillez ouvrir la porte."),(-132,-90,-10,-78))],
                         list(positioned_segments(*accepted[0], "fr")))

    def test_shared_latin_reader_reuses_unchanged_frame_and_reports_provenance(self):
        words = [Word("Merci", (10,10,60,30), 100, ("0",)), Word("beaucoup.", (65,10,150,30), 100, ("0",)),
                 Word("Continue", (10,40,100,60), 100, ("1",))]
        self.engine.accepts_source_line = lambda line,source: line=="Merci beaucoup." and source=="fr"
        with patch.object(self.engine.windows, "packs", return_value={"eng": "en-US", "deu":"de-DE"}), \
                patch.object(self.engine, "external_languages", return_value=[]), \
                patch.object(self.engine, "_native_engine", return_value=None), \
                patch.object(self.engine, "_capture", return_value=self.frame), \
                patch.object(self.engine.windows, "read", return_value=words) as read:
            self.assertEqual("Windows OCR (Latin fallback)", self.engine.ocr_sources()["fra"])
            self.assertEqual("Windows OCR", self.engine.ocr_sources()["deu"])
            self.assertNotIn("rus", self.engine.ocr_sources())
            for _ in range(2):
                result = self.engine.recognize(self.region, "fra", source="fr")
                self.assertEqual("Merci beaucoup.", result)
                self.assertEqual("fr", result.verified_source)
                self.assertEqual(1,len(result.regions))
            read.assert_called_once_with(self.frame, "en-US", None)

    def test_mismatched_packs_and_english_cannot_capture(self):
        self.engine.accepts_source_line = lambda *args: True
        with patch.object(self.engine, "_capture", side_effect=AssertionError("capture should not start")):
            for language,source in [("eng","en"),("eng","fr"),("deu","fr"),("fra+eng","fr")]:
                with self.assertRaises(ValueError):
                    self.engine.recognize(self.region, language, source=source)

    def test_independent_english_read_vetoes_visual_cyrillic_false_positive(self):
        words = [Word("ОРЕN", (10,10,60,30), 100, ("0",))]
        guard = Mock()
        guard.detect.return_value = [Word("open", (10,10,60,30))]
        self.assertEqual([], accepted_regions(self.frame, words, "ru", lambda *_: True, guard))


if __name__ == "__main__":
    unittest.main()
