"""Windows regression test for setup switches resolving the sibling verifier."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LiveTranslate/scripts/Download and test models.cmd"


@unittest.skipUnless(os.name == "nt", "requires Windows command processor")
class SetupCommandRouting(unittest.TestCase):
    def test_verifier_keeps_its_directory_and_receives_offline_switch(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            root = Path(temp) / "fixture & [test] !"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            shutil.copyfile(SOURCE, scripts / SOURCE.name)
            (scripts / "Get-CheckedModels.ps1").write_text(
                "param([switch]$Offline)\nif ($Offline) { exit 47 }; exit 48\n", "ascii"
            )
            # This prevents pass-by-coincidence if the old root path is selected.
            (root / "Get-CheckedModels.ps1").write_text("exit 49\n", "ascii")
            shell = str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe")
            for switches in ("--offline --non-interactive", "--non-interactive --offline",
                             "--offline --non-interactive --offline"):
                with self.subTest(switches=switches):
                    invocation = '"{}" /d /v:off /s /c ""scripts\\{}" {}"'.format(shell, SOURCE.name, switches)
                    result = subprocess.run(invocation, executable=shell, cwd=root,
                                            stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                    self.assertEqual(47, result.returncode, result.stderr)
                    self.assertIn("exit code 47", (root/"model-test-results/last-run.txt").read_text("utf8"))


if __name__ == "__main__":
    unittest.main()
