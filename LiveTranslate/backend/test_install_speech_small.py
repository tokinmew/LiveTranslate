"""Optional model setup must stay scoped and fail before changed local scripts run."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import install_speech_small as setup


class SmallSpeechSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "space & yüzde% 日本語"
        folder = self.root / "quality"
        folder.mkdir(parents=True)
        for name in ("install.py", "scan.ps1"):
            (folder / name).write_bytes(name.encode("ascii"))
        reviewed = {b"install.py": "b0188fe186f778666bc4333c180a88fe471daa809227cd1c66a62c4d96180f6f",
                    b"scan.ps1": "91e74a878f18d40334c9026a58492abdc3e690d72699bef7a7ca475412c04bd9"}
        identity = patch.object(setup.hashlib, "sha256", side_effect=lambda data:
            SimpleNamespace(hexdigest=lambda: reviewed.get(data, "invalid")))
        identity.start()
        self.addCleanup(identity.stop)

    def test_only_small_is_requested_with_isolated_python_and_literal_paths(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(0, setup.install(self.root))
        command = run.call_args.args[0]
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(["-I", "-B", "-X", "utf8"], command[1:5])
        self.assertEqual(self.root / "quality/install.py", Path(command[5]))
        self.assertEqual(["--pack", "small"], command[6:])
        self.assertEqual(self.root, run.call_args.kwargs["cwd"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_failed_model_setup_does_not_report_success(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=23)):
            self.assertEqual(23, setup.install(self.root))

    def test_either_changed_checked_script_prevents_any_execution(self):
        for name in ("install.py", "scan.ps1"):
            with self.subTest(name=name):
                file = self.root / "quality" / name
                file.write_bytes(b"changed")
                with patch.object(setup.subprocess, "run") as run:
                    with self.assertRaisesRegex(ValueError, "missing or changed"):
                        setup.install(self.root)
                    run.assert_not_called()
                file.write_bytes(name.encode("ascii"))

    def test_missing_checked_file_prevents_any_execution(self):
        (self.root / "quality/scan.ps1").unlink()
        with patch.object(setup.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                setup.install(self.root)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
