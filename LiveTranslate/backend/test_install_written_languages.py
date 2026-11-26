"""A combined setup cannot report success after a failed translation/OCR stage."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import install_written_languages as setup


class WrittenSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        folder = self.root / "quality"
        folder.mkdir()
        for name in ("install.py", "scan.ps1"):
            (folder / name).write_bytes(name.encode("ascii"))
        reviewed = {b"install.py": "b0188fe186f778666bc4333c180a88fe471daa809227cd1c66a62c4d96180f6f",
                    b"scan.ps1": "91e74a878f18d40334c9026a58492abdc3e690d72699bef7a7ca475412c04bd9"}
        bypass_identity = patch.object(setup.hashlib, "sha256", side_effect=lambda data: SimpleNamespace(hexdigest=lambda: reviewed.get(data, "invalid")))
        bypass_identity.start()
        self.addCleanup(bypass_identity.stop)

    def test_translation_failure_does_not_start_ocr_or_report_success(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=7)), patch.object(setup, "install_extra_ocr") as ocr:
            self.assertEqual(7, setup.install(self.root))
            ocr.assert_not_called()

    def test_both_stages_run_in_order_with_the_same_offline_scope(self):
        order = []
        with patch.object(setup.subprocess, "run", side_effect=lambda *a, **k: order.append("translation") or SimpleNamespace(returncode=0)) as run, \
             patch.object(setup, "install_extra_ocr", side_effect=lambda *a, **k: order.append("ocr") or 0) as ocr:
            self.assertEqual(0, setup.install(self.root, offline=True))
            self.assertEqual(["translation", "ocr"], order)
            self.assertIn("--offline", run.call_args.args[0])
            self.assertIn("-I", run.call_args.args[0])
            ocr.assert_called_once_with(self.root, offline=True)

    def test_ocr_failure_is_not_hidden_by_a_successful_translation_download(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
             patch.object(setup, "install_extra_ocr", side_effect=ValueError("OCR verification failed")):
            with self.assertRaisesRegex(ValueError, "OCR verification failed"):
                setup.install(self.root)

    def test_changed_checked_script_prevents_both_stages(self):
        (self.root / "quality/install.py").write_bytes(b"changed")
        with patch.object(setup.subprocess, "run") as run, patch.object(setup, "install_extra_ocr") as ocr:
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                setup.install(self.root)
            run.assert_not_called()
            ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
