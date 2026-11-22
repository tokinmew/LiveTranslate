"""Verify the lifetime and frame boundaries of cached native OCR models."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock

from screen_engine import ScreenEngine


class WatchModelTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.screen = ScreenEngine(Path(temp.name))
        self.native = MagicMock()
        self.native.PyTessBaseAPI.side_effect = lambda **kw: MagicMock()

    def test_clear_frame_state_reuse_primary_and_release_both_at_stop(self):
        with self.screen.watch_models():
            with self.screen._reader(self.native, 'kor+jpn', 7, True) as main:
                with self.screen._reader(self.native, 'kor', 7, False) as verifier:
                    pass
            with self.screen._reader(self.native, 'kor+jpn', 11, True) as again:
                self.assertIs(main, again)
            with self.screen._reader(self.native, 'jpn', 6, False) as other:
                verifier.End.assert_called_once()
                main.End.assert_not_called()
                other.End.assert_not_called()
            self.assertEqual(main.SetPageSegMode.call_args.args, (11,))
            self.assertEqual(main.Clear.call_count, 2)
            self.assertEqual(main.ClearAdaptiveClassifier.call_count, 2)
        main.End.assert_called_once()
        other.End.assert_called_once()

    def test_failed_native_instance_is_discarded_and_next_frame_can_retry(self):
        with self.screen.watch_models():
            with self.assertRaisesRegex(RuntimeError, 'invalid frame'):
                with self.screen._reader(self.native, 'kor', 7, True) as failed:
                    raise RuntimeError('invalid frame')
            failed.End.assert_called_once()
            with self.screen._reader(self.native, 'kor', 7, True) as next_api:
                self.assertIsNot(failed, next_api)
        next_api.End.assert_called_once()
