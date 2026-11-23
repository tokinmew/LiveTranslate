"""Fixed local stub scripts only; no model downloads or capture."""
from pathlib import Path
import io
import os
import queue
import tempfile
import threading
import unittest

import checked_process


class CheckedProcessTests(unittest.TestCase):
    def test_progress_is_bounded_and_hides_url_tokens(self):
        line = checked_process._progress_line("\x1b[31mFetch https://example.invalid/file?token=PRIVATE&sig=PRIVATE \x1b[0m" + "x" * 5000)
        self.assertLessEqual(len(line), 1500)
        self.assertNotIn("PRIVATE", line)
        self.assertNotIn("https://", line)
        self.assertNotIn("\x1b", line)
        self.assertIn("[download URL]", line)

    def test_reader_drains_long_line_without_exposing_its_tail(self):
        data = b"first\nhttps://example.invalid/?token=" + b"SECRET" * 4000 + b"\nlast\n"
        lines, stopped, ended = queue.Queue(), threading.Event(), threading.Event()
        checked_process._output_reader(io.BytesIO(data), lines, stopped, ended)
        values = []
        while not lines.empty():
            values.append(lines.get_nowait())
        self.assertTrue(ended.is_set())
        self.assertEqual(values[0], "first")
        self.assertEqual(values[-1], "last")
        self.assertNotIn("SECRET", "\n".join(values))
        self.assertTrue(all(len(line) <= 1500 for line in values))

    def test_cancelled_before_start_never_executes_a_child(self):
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            checked_process.run_checked_powershell(Path("missing"), self.fail, event)

    def test_requires_the_fixed_normal_script(self):
        with tempfile.TemporaryDirectory(prefix="checked-helper-test-") as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                checked_process._validated_script(root)
            (root / "scripts" / "Get-CheckedModels.ps1").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "normal local file"):
                checked_process._validated_script(root)

    @unittest.skipUnless(os.name == "nt", "Windows job-object integration")
    def test_contained_local_stub_success_and_nonzero(self):
        with tempfile.TemporaryDirectory(prefix="checked helper with spaces ") as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "Get-CheckedModels.ps1"
            script.write_text("Write-Output 'STUB pipeline ran'\nexit 0\n", encoding="utf-8")
            messages = []
            checked_process.run_checked_powershell(root, messages.append, threading.Event())
            self.assertTrue(any("STUB pipeline ran" in message for message in messages))
            script.write_text("Write-Output 'STUB expected failure'\nexit 7\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exit code 7"):
                checked_process.run_checked_powershell(root, messages.append, threading.Event())

    @unittest.skipUnless(os.name == "nt", "Windows job-object integration")
    def test_cancels_a_contained_sleeping_stub(self):
        with tempfile.TemporaryDirectory(prefix="checked helper cancel ") as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "Get-CheckedModels.ps1").write_text("Write-Output 'STUB ready'\nStart-Sleep -Seconds 60\n", encoding="utf-8")
            cancel = threading.Event()

            def progress(value):
                if "STUB ready" in value:
                    cancel.set()

            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                checked_process.run_checked_powershell(root, progress, cancel)


if __name__ == "__main__":
    unittest.main()
