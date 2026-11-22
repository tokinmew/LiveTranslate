import unittest
from unittest.mock import Mock, patch

from chinese_label import _label_crop, confirm_label
from screen_geometry import physical_box


def result(text, confidence):
    return text, f"5\t1\t1\t1\t1\t1\t5\t5\t70\t35\t{confidence}\t{text}"


class CompactChineseLabelTests(unittest.TestCase):
    def test_two_segmentation_modes_must_independently_agree_above_threshold(self):
        crop = object()
        weak = result("设重", 48)
        for line, single in ((result("设置", 96), result("设重", 97)),
                             (result("设置", 65), result("设置", 97)),
                             (result("设置", 97), result("设置", 67)),
                             (result("设A", 97), result("设A", 98)),
                             (result("设", 98), result("设", 98))):
            with patch("chinese_label._label_crop", return_value=crop):
                self.assertIsNone(confirm_label(object(), weak, "chi_sim", Mock(side_effect=[line, single])))

    def test_auto_preserves_supported_script_and_abstains_on_an_ambiguous_tie(self):
        crop = object()
        def read(_, code, mode, timeout):
            return result("設置" if code == "chi_tra" else "设置", 96)
        with patch("chinese_label._label_crop", return_value=crop):
            self.assertEqual((crop, result("设置", 96)), confirm_label(object(), result("设重", 48), "chi_tra+chi_sim", read))
            self.assertIsNone(confirm_label(object(), result("重", 47), "chi_sim+chi_tra", read))

    def test_confident_english_and_foreign_words_do_not_trigger_extra_reads(self):
        for primary in (result("ID卡", 72), result("設定", 95), result("안내室", 83), result("Settings", 90)):
            self.assertIsNone(confirm_label(object(), primary, "chi_sim", Mock(side_effect=AssertionError("extra OCR"))))

    def test_panel_crop_carries_physical_pixels_and_rejects_multiple_rows(self):
        from PIL import Image, ImageDraw
        for background, ink in ((25,235), (235,25)):
            panel = Image.new("L", (320, 120), background)
            panel.info["desktop_map"] = (-700, 20, .5, .5)
            draw = ImageDraw.Draw(panel)
            for x in (42, 74):
                draw.rectangle((x, 26, x+24, 53), outline=ink, width=2)
                draw.line((x, 40, x+24, 40), fill=ink, width=2)
            crop = _label_crop(panel)
            self.assertEqual((-679,33,-650,47), physical_box(crop, crop.info["content_box"]))
            self.assertGreater(crop.getpixel((0,0)),190)
            draw.rectangle((42, 65, 98, 72), outline=ink, width=2)
            self.assertIsNone(_label_crop(panel))
