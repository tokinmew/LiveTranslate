import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from scipy import ndimage
except ImportError:
    Image = None

from scene_text import Candidate, _clean_line, confirmed_scene_row, textured_rows


class SceneRecognitionTests(unittest.TestCase):
    def word(self, text, confidence):
        return text, f"5\t1\t1\t1\t1\t1\t1\t2\t30\t10\t{confidence}\t{text}"

    def test_uncertain_short_guesses_from_scenery_stay_silent(self):
        self.assertEqual(("", ""), confirmed_scene_row(self.word("오그", 40.2)))
        self.assertEqual(None, confirmed_scene_row(None))

    def test_confident_compact_foreign_sign_remains_eligible(self):
        sign = self.word("門", 94)
        self.assertEqual(sign, confirmed_scene_row(sign))


@unittest.skipUnless(Image is not None, "Optional numerical image runtime is unavailable")
class ScenePixelsTests(unittest.TestCase):
    def texture(self):
        y, x = np.mgrid[0:240, 0:440]
        values = (78 + 20*np.sin(x/24) + 14*np.cos(y/25) + 12*np.sin((x-y)/41))
        return Image.fromarray(values.astype(np.uint8))

    def test_flat_document_uses_regular_layout_analysis(self):
        guard = Mock(side_effect=AssertionError("No helper needed for a page"))
        self.assertIsNone(textured_rows(Image.new("L", (100, 100), 250), guard))

    def test_smooth_scenery_has_no_text_and_skips_english_ocr(self):
        guard = Mock(side_effect=AssertionError("No text candidates require a second read"))
        self.assertEqual([], textured_rows(self.texture(), guard))

    def test_rows_of_filled_scenery_shapes_are_not_glyphs(self):
        image = self.texture()
        draw = ImageDraw.Draw(image)
        for x in (42, 101, 155, 218):
            draw.polygon(((x+17, 80), (x, 111), (x+35, 111)), fill=215)
        pixels = np.asarray(image, dtype=np.int16)
        box = 40, 78, 256, 114
        ink = pixels[78:114, 40:256] == 215
        candidate = Candidate(box, ink, ink.sum(), True, 128)
        self.assertIsNone(_clean_line([candidate], pixels, []))

    def test_identified_english_ink_is_excluded_before_cleanup(self):
        font_path = Path(os.environ.get("SystemRoot", "")) / "Fonts" / "segoeui.ttf"
        if not font_path.is_file():
            self.skipTest("The Windows screen font is unavailable")
        image = self.texture()
        font = ImageFont.truetype(str(font_path), 24)
        draw = ImageDraw.Draw(image)
        draw.text((12, 45), "Press to continue", font=font, fill=248, stroke_width=1, stroke_fill=14)
        label = draw.textbbox((12, 45), "Press to continue", font=font, stroke_width=1)
        self.assertTrue(textured_rows(image, lambda _: []))
        self.assertEqual([], textured_rows(image, lambda _: [SimpleNamespace(box=label)]))
