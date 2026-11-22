"""Screen logic without taking screenshots or loading a native OCR library."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from screen_engine import ScreenCaptureUnavailable, ScreenEngine, _tesseract_data_path, page_segmentation_mode


class ScreenTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows native model path")
    def test_unicode_installation_can_use_relative_tessdata_without_short_names(self):
        root = Path(self.directory.name) / "音声" / "data" / "tessdata"
        with patch("screen_engine.os.path.relpath", return_value=r"data\tessdata"):
            self.assertEqual(r"data\tessdata", _tesseract_data_path(root))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = ScreenEngine(Path(self.directory.name))
        self.region = {"left": -100, "top": 0, "width": 100, "height": 200}

    def tearDown(self):
        self.directory.cleanup()

    def add_pack(self, code):
        (self.engine.root / (code + ".traineddata")).write_bytes(b"x" * 2000)

    def test_page_layout_matches_vertical_models(self):
        self.assertEqual(5, page_segmentation_mode("jpn_vert"))
        self.assertEqual(5, page_segmentation_mode("jpn_vert+eng"))
        self.assertEqual(6, page_segmentation_mode("jpn"))
        self.assertEqual(11, page_segmentation_mode("jpn", full_monitor=True))
        self.assertEqual(5, page_segmentation_mode("jpn_vert", full_monitor=True))

    def test_native_ocr_needs_no_tesseract_executable(self):
        self.add_pack("jpn_vert")
        api = MagicMock()
        api.__enter__.return_value = api
        api.GetUTF8Text.return_value = " 日本語 \n"
        api.GetTSVText.return_value = "5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t94\t日本語\n"
        factory = MagicMock(return_value=api)
        native = SimpleNamespace(PyTessBaseAPI=factory)
        image = MagicMock(size=(30, 10))
        image.tobytes.return_value = bytes(300)
        with patch.object(self.engine, "_native_engine", return_value=native), \
             patch.object(self.engine, "find_tesseract", side_effect=AssertionError("No CLI needed")), \
             patch.object(self.engine, "_capture", return_value=image), \
             patch.object(self.engine.english_guard, "detect", return_value=[]):
            self.assertEqual("", self.engine.resolve_engine())
            self.assertTrue(self.engine.engine_ready())
            self.assertEqual("日本語", self.engine.recognize(self.region, "jpn_vert"))
            self.assertEqual("日本語", self.engine.recognize(self.region, "jpn_vert"))
        factory.assert_called_once_with(path=str(self.engine.root), lang="jpn_vert", psm=5)
        api.SetImage.assert_called_once_with(image)
        api.__exit__.assert_called_once()

    def test_native_ocr_missing_pack_is_reported_before_capture(self):
        with patch.object(self.engine, "_native_engine", return_value=object()), \
             patch.object(self.engine, "find_tesseract", side_effect=RuntimeError("Not installed")), \
             patch.object(self.engine, "_capture", side_effect=AssertionError("No screen capture")):
            with self.assertRaisesRegex(RuntimeError, "jpn"):
                self.engine.recognize(self.region, "jpn")

    def test_manual_executable_remains_an_explicit_fallback(self):
        self.add_pack("jpn")
        tsv = "5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t94\t日本語\n".encode("utf-8")
        image = MagicMock(size=(30, 10))
        image.tobytes.return_value = bytes(300)
        with patch("screen_engine.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=tsv)) as run, \
             patch.object(self.engine, "_native_engine", side_effect=AssertionError("Manual CLI selected")), \
             patch.object(self.engine, "find_tesseract", return_value="C:/manual/tesseract.exe"), \
             patch.object(self.engine.english_guard, "detect", return_value=[]), \
             patch.object(self.engine, "_capture", return_value=image):
            self.assertEqual("日本語", self.engine.recognize(self.region, "jpn", "C:/manual/tesseract.exe"))
        args = run.call_args.args[0]
        self.assertEqual("C:/manual/tesseract.exe", args[0])
        self.assertEqual("6", args[args.index("--psm") + 1])
        self.assertEqual(["stdin", "stdout"], args[1:3])

    def test_absent_ocr_pack_uses_reviewed_setup(self):
        with self.assertRaisesRegex(RuntimeError, "checked model setup"):
            self.engine.install_ocr_language("chi_tra")
        self.assertEqual([], self.engine.local_languages())

    def test_retry_does_not_redownload_existing_language_file(self):
        self.add_pack("jpn")
        self.assertEqual(str(self.engine.root / "jpn.traineddata"), self.engine.install_ocr_language("jpn"))

    def test_incomplete_language_file_is_not_ready(self):
        (self.engine.root / "jpn.traineddata").write_bytes(b"truncated")
        self.assertEqual([], self.engine.local_languages())

    def test_auto_ocr_combines_only_horizontal_priority_files(self):
        for code in ("chi_tra", "chi_sim", "kor", "jpn", "jpn_vert", "eng", "spa"):
            self.add_pack(code)
        with patch.object(self.engine, "external_languages", return_value=[]):
            self.assertEqual("chi_tra+chi_sim+kor+jpn+eng", self.engine.auto_language())

    def test_auto_ocr_keeps_data_folders_separate(self):
        self.add_pack("jpn")
        with patch.object(self.engine, "external_languages", return_value=["kor", "eng"]):
            self.assertEqual("kor+eng", self.engine.auto_language())

    def test_auto_ocr_with_only_vertical_model_requires_profile_install(self):
        self.add_pack("jpn_vert")
        with patch.object(self.engine, "external_languages", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Install all four"):
                self.engine.auto_language()

    def test_auto_ocr_skips_other_installed_languages(self):
        self.add_pack("fra")
        self.add_pack("eng")
        with patch.object(self.engine, "external_languages", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Install all four"):
                self.engine.auto_language()

    def test_primary_monitor_is_resolved_each_capture_not_virtual_desktop(self):
        virtual = dict(left=-900, top=0, width=2000, height=1000)
        secondary = dict(left=-900, top=0, width=900, height=1000)
        primary = dict(left=0, top=0, width=1100, height=1000)
        self.assertEqual(primary, self.engine.primary_region([virtual, secondary, primary]))
        self.assertEqual(secondary, self.engine.primary_region([virtual, dict(secondary, is_primary=True), primary]))
        self.assertEqual({"monitor": "primary"}, self.engine.validate_region({"monitor": "primary"}))
        with self.assertRaises(ValueError):
            self.engine.validate_region({"monitor": "all"})
        self.assertEqual(dict(self.region,full_display=True),self.engine.validate_region(dict(self.region,full_display=True)))
        with self.assertRaisesRegex(ValueError, "true or false"):
            self.engine.validate_region(dict(self.region,full_display=1))
        with self.assertRaises(ScreenCaptureUnavailable):
            self.engine.primary_region([virtual])

    def test_os_capture_error_is_retryable_and_configuration_errors_are_distinct(self):
        self.add_pack("jpn")
        with patch.object(self.engine,"_capture",side_effect=OSError("temporarily unavailable")), \
                patch.object(self.engine,"_native_engine",return_value=object()):
            with self.assertRaises(ScreenCaptureUnavailable):
                self.engine.recognize(self.region,"jpn")

    def test_changed_region_forces_new_read_even_with_identical_pixels(self):
        self.add_pack("jpn")
        image=MagicMock(size=(8,8))
        image.tobytes.return_value=bytes(64)
        api=MagicMock()
        api.__enter__.return_value=api
        api.Recognize.return_value=True
        api.GetUTF8Text.return_value="English UI"
        with patch.object(self.engine,"_native_engine",return_value=SimpleNamespace(PyTessBaseAPI=MagicMock(return_value=api))), \
                patch.object(self.engine,"_capture",return_value=image), \
                patch.object(self.engine.english_guard,"detect",side_effect=AssertionError("Unnecessary second OCR")):
            self.assertEqual("",self.engine.recognize(self.region,"jpn"))
            self.assertEqual("",self.engine.recognize(self.region,"jpn"))
            self.assertEqual("",self.engine.recognize(dict(self.region,left=10),"jpn"))
        self.assertEqual(2,api.Recognize.call_count)

    def test_window_bounds_clipped_in_physical_pixels_on_negative_monitor(self):
        image = MagicMock(width=120, height=80)
        rect = dict(left=-100, top=-20, width=120, height=80)
        self.engine._mask_bounds(image, rect, [(-300, -40, -70, 2), (200, 0, 300, 30)])
        image.paste.assert_called_once_with(255, (0, 0, 30, 22))

    def test_moved_fallback_windows_are_masked_before_and_after_the_grab(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow required to test synthetic screenshot pixels')
        import sys
        calls=[]
        fake=MagicMock()
        capture=fake.mss.return_value.__enter__.return_value
        def get_bounds(handles):
            calls.append('bounds')
            return [(10,0,20,5)] if len(calls)==1 else [(30,0,40,5)]
        def grab(rect):
            calls.append('grab')
            return SimpleNamespace(size=(1200,5),rgb=bytes(1200*5*3))
        capture.grab.side_effect=grab
        with patch.dict(sys.modules,{'mss':fake,'mss.exception':SimpleNamespace(ScreenShotError=OSError)}), \
             patch.object(ScreenEngine,'_visible_bounds',side_effect=get_bounds):
            image=ScreenEngine._capture(dict(left=0,top=0,width=1200,height=5),[100])
        self.assertEqual(['bounds','grab','bounds'],calls)
        self.assertEqual([255,0,255],[image.getpixel((x,2)) for x in (15,25,35)])

    def test_explicitly_english_or_unrelated_language_never_captures(self):
        with patch.object(self.engine, "_capture", side_effect=AssertionError("unexpected capture")):
            for code in ("eng", "fra", "jpn+ara", "osd"):
                with self.assertRaisesRegex(ValueError, "source language"):
                    self.engine.recognize(self.region, code)

    def test_rectangle_validation_rejects_fractional_and_oversized_input(self):
        for region in ({"left": 0, "top": 0, "width": 5.5, "height": 10},
                       {"left": 0, "top": 0, "width": 10000, "height": 10000}):
            with self.assertRaises(ValueError):
                self.engine.validate_region(region)


if __name__ == "__main__":
    unittest.main()
