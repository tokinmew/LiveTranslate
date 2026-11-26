"""Application pixels never silently become desktop pixels; deadlines are bounded."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from PIL import Image
from screen_engine import ScreenCaptureUnavailable, ScreenEngine
from window_capture import HEADER, MAGIC, capture_application, validate_target, _enable_physical_pixels, _native_capture


class ApplicationCaptureTests(unittest.TestCase):
    def test_physical_pixel_awareness_precedes_window_geometry_and_capture(self):
        user, gdi = MagicMock(), MagicMock()
        order = []
        user.IsWindow.side_effect = lambda *args: order.append("window") or False
        with patch("window_capture.ctypes.WinDLL", side_effect=[user, gdi], create=True), \
             patch("window_capture._enable_physical_pixels", side_effect=lambda *args: order.append("dpi")):
            with self.assertRaisesRegex(RuntimeError, "has closed"):
                _native_capture(12, 34)
        self.assertEqual(["dpi", "window"], order)

    def test_physical_pixel_awareness_uses_per_monitor_context_with_legacy_fallback(self):
        user = MagicMock()
        user.SetProcessDpiAwarenessContext.return_value = True
        _enable_physical_pixels(user)
        user.SetProcessDPIAware.assert_not_called()
        self.assertEqual(-4 & ((1 << (8 * __import__('ctypes').sizeof(__import__('ctypes').c_void_p))) - 1),
                         user.SetProcessDpiAwarenessContext.call_args.args[0].value)
        user.SetProcessDpiAwarenessContext.return_value = False
        _enable_physical_pixels(user)
        user.SetProcessDPIAware.assert_called_once()

    def test_handle_validation_rejects_bool_reuse_metadata_and_mixed_sources(self):
        self.assertEqual(dict(window=12, process=45), ScreenEngine.validate_region(dict(window=12, process=45)))
        for value in [dict(window=True, process=45), dict(window=12, process=False),
                      dict(window=0, process=45), dict(window=12, process=0),
                      dict(window=12, process=45, monitor="primary"), dict(window=12),
                      dict(window="12", process=45), dict(window=2**64, process=45)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScreenEngine.validate_region(value)

    @unittest.skipUnless(os.name == "nt", "Windows application capture")
    def test_pixels_have_target_coordinates_and_no_desktop_fallback(self):
        import tempfile
        target = dict(window=12, process=45)
        data = HEADER.pack(MAGIC, -600, 70, 6, 5) + bytes([20, 30, 40, 0] * 29 + [80, 90, 100, 0])
        with patch("window_capture.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=data)) as run, \
             tempfile.TemporaryDirectory() as root:
            engine = ScreenEngine(Path(root))
            frame = engine._capture(target, [123])
        self.assertEqual((12, 10), frame.size)
        self.assertEqual((-600, 70, .5, .5), frame.info["desktop_map"])
        original, left, top = frame.info["glyph_source"]
        self.assertEqual((-600, 70), (left, top))
        self.assertEqual((40, 30, 20), original.getpixel((0, 0)))
        self.assertEqual((100, 90, 80), original.getpixel((5, 4)))
        self.assertEqual(2.0, run.call_args.kwargs["timeout"])
        self.assertIn("-I", run.call_args.args[0])

    @unittest.skipUnless(os.name == "nt", "Windows application capture")
    def test_timeout_and_blank_frames_are_actionable_not_desktop_capture(self):
        target = dict(window=12, process=45)
        with patch("window_capture.subprocess.run", side_effect=subprocess.TimeoutExpired([], 2)):
            with self.assertRaisesRegex(RuntimeError, "did not provide a frame"):
                capture_application(target)
        blank = HEADER.pack(MAGIC, 0, 0, 5, 5) + bytes(5 * 5 * 4)
        with patch("window_capture.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=blank)):
            with self.assertRaisesRegex(RuntimeError, "blank frame"):
                capture_application(target)

    @unittest.skipUnless(os.name == "nt", "Windows application capture")
    def test_closed_and_malformed_frames_are_rejected(self):
        for result, message in [(SimpleNamespace(returncode=1, stderr=b"Restore its window"), "Restore its window"),
                                (SimpleNamespace(returncode=0, stdout=b"partial"), "incomplete frame"),
                                (SimpleNamespace(returncode=0, stdout=HEADER.pack(MAGIC, 0, 0, 30000, 30000)), "invalid frame")]:
            with self.subTest(message=message), patch("window_capture.subprocess.run", return_value=result), self.assertRaisesRegex(RuntimeError, message):
                capture_application(dict(window=12, process=45))

    def test_preview_is_bounded_in_memory_and_preserves_source_dimensions(self):
        import base64
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            engine = ScreenEngine(Path(root))
            image = Image.new("L", (4000, 2000))
            with patch.object(engine, "_capture", return_value=image):
                preview = engine.preview(dict(window=12, process=45))
        self.assertEqual((4000, 2000, "application"), (preview["width"], preview["height"], preview["source"]))
        with Image.open(io.BytesIO(base64.b64decode(preview["image"]))) as small:
            self.assertEqual((960, 480), small.size)

    def test_preview_diagnoses_the_exact_sample_without_turning_raw_text_into_captions(self):
        import tempfile
        from screen_geometry import LocatedText
        with tempfile.TemporaryDirectory() as root:
            engine = ScreenEngine(Path(root))
            frame = Image.new("L", (600, 160), 255)
            frame.info["capture_info"] = dict(source="display", width=600, height=160, masked_percent=0)
            rejected = LocatedText("")
            rejected.raw_ocr = "Home / invented characters"
            with patch.object(engine, "_capture", return_value=frame), patch.object(engine, "recognize", return_value=rejected) as read:
                preview = engine.preview(dict(left=0, top=0, width=600, height=160), language="jpn", source="ja")
            self.assertIs(frame, read.call_args.kwargs["_frame"])
            self.assertEqual("Home / invented characters", preview["diagnostics"]["raw_ocr"])
            self.assertEqual("", preview["diagnostics"]["accepted_ocr"])
            self.assertNotIn("text", preview)

    def test_missing_ocr_files_preserve_preview_with_a_separate_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            engine = ScreenEngine(Path(root))
            frame = Image.new("L", (60, 16), 255)
            with patch.object(engine, "_capture", return_value=frame), patch.object(engine, "recognize", side_effect=ValueError("Missing OCR model")):
                preview = engine.preview(dict(left=0, top=0, width=60, height=16), language="jpn", source="ja")
            self.assertTrue(preview["image"])
            self.assertEqual("Missing OCR model", preview["diagnostics"]["recognition_error"])


if __name__ == "__main__":
    unittest.main()
