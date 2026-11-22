"""Use synthetic frames to check source overlays never replace input to OCR."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from screen_engine import ScreenCaptureUnavailable, ScreenEngine


class ScreenSampleTests(unittest.TestCase):
    def test_end_matching_lease_on_success_and_capture_failure(self):
        calls = []
        def exchange(message, token):
            calls.append((message, token))
            return True
        with patch.object(ScreenEngine, "_sample_messages", return_value=exchange):
            with ScreenEngine._sample_lease([10]) as held:
                self.assertTrue(held)
            with self.assertRaisesRegex(OSError, "grab failed"):
                with ScreenEngine._sample_lease([10]):
                    raise OSError("grab failed")
        self.assertEqual([0x8241, 0x8242, 0x8241, 0x8242], [m for m, _ in calls])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual(calls[2][1], calls[3][1])

    def test_failed_begin_never_grabs_and_attempts_cleanup(self):
        exchange = MagicMock(return_value=False)
        with patch.object(ScreenEngine, "_sample_messages", return_value=exchange):
            with self.assertRaises(ScreenCaptureUnavailable):
                with ScreenEngine._sample_lease([10]):
                    self.fail("An unacknowledged sample must not begin")
        self.assertEqual([0x8241, 0x8242], [call.args[0] for call in exchange.call_args_list])

    def test_expired_or_superseded_grab_discards_frame(self):
        exchange = MagicMock(side_effect=[True, False])
        with patch.object(ScreenEngine, "_sample_messages", return_value=exchange):
            with self.assertRaises(ScreenCaptureUnavailable):
                with ScreenEngine._sample_lease([10]) as held:
                    self.assertTrue(held)

    def test_legacy_capture_uses_normal_bounds(self):
        with patch.object(ScreenEngine, "_sample_messages", return_value=None):
            with ScreenEngine._sample_lease([10]) as held:
                self.assertFalse(held)

    def test_changes_under_direct_fallback_are_visible_and_caption_pixels_are_absent(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is needed for synthetic pixel verification")
        fake = MagicMock()
        capture = fake.mss.return_value.__enter__.return_value
        background = Image.new("RGB", (60, 16), (12, 34, 56))
        capture_box = dict(left=-918, top=42, width=60, height=16)
        sample_point = (12, 7)
        ink = (250, 253, 245)
        paused = False
        calls = []

        def exchange(message, token):
            nonlocal paused
            self.assertEqual(0x8241 if not paused else 0x8242, message)
            paused = not paused
            calls.append("hide" if paused else "restore")
            return True

        def bounds(handles, include_source_windows=True):
            self.assertFalse(include_source_windows)
            return [(-918, 42, -915, 44)]

        def grab(rect):
            self.assertEqual(capture_box, rect)
            image = background.copy()
            if not paused:
                image.putpixel(sample_point, ink)
            calls.append("grab")
            return SimpleNamespace(size=image.size, rgb=image.tobytes())

        capture.grab.side_effect = grab
        with patch.dict(sys.modules, {"mss":fake, "mss.exception":SimpleNamespace(ScreenShotError=OSError)}), \
             patch.object(ScreenEngine, "_sample_messages", return_value=exchange), \
             patch.object(ScreenEngine, "_visible_bounds", side_effect=bounds):
            for underlying in ((160, 32, 9), (29, 15, 235)):
                background.putpixel(sample_point, underlying)
                frame = ScreenEngine._capture(capture_box, [10, 11, 12])
                original, x, y = frame.info["glyph_source"]
                self.assertEqual((-918, 42), (x, y))
                self.assertEqual((120, 32), frame.size)
                self.assertEqual((60, 16), original.size)
                self.assertEqual(underlying, original.getpixel(sample_point))
                self.assertEqual((255, 255, 255), original.getpixel((1, 1)))
                self.assertFalse(paused)
        self.assertEqual(["hide", "grab", "restore"] * 2, calls)


if __name__ == "__main__":
    unittest.main()
