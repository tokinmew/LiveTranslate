"""Checked GUI install gates; no downloads, model loading, or capture."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from checked_model_setup import CheckedModelSetup


class CheckedSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("backend", "scripts", "config"):
            (self.root / folder).mkdir()
        for name in ("scripts/Get-CheckedModels.ps1", "backend/verify_reviewed_models.py", "backend/check_models.py"):
            (self.root / name).write_text("# local test input", encoding="utf-8")
        self.files = [{"kind": kind, "name": f"{kind}-{number}"}
                      for kind, count in (("text", 4), ("ocr", 5), ("speech", 4)) for number in range(count)]
        (self.root / "config" / "model-sources.json").write_text(json.dumps({"files": self.files}), encoding="utf-8")
        self.cancel = threading.Event()
        self.trace = []
        self.importer = Mock(side_effect=lambda *args: self.trace.append("import"))
        self.runner = Mock(side_effect=self.write_report)
        self.setup = CheckedModelSetup(self.root, self.root / "data", self.trace.append, self.cancel,
                                       process_runner=self.runner, importer=self.importer,
                                       lock_factory=self.lock)

    @contextmanager
    def lock(self, data):
        self.trace.append("locked")
        yield
        self.trace.append("unlocked")

    def write_report(self, root, emit, cancel):
        self.trace.append("scan")
        now = datetime.now(timezone.utc).isoformat()
        report = {"status": "verified", "started": now, "finished": now,
                  "files": [{**row, "status": "verified", "sha256": "a" * 64} for row in self.files]}
        (root / "model-test-results" / "model-file-checks.json").write_text(json.dumps(report), encoding="utf-8")

    def test_scan_and_fresh_report_are_required_before_offline_import(self):
        self.setup.install()
        self.assertLess(self.trace.index("locked"), self.trace.index("scan"))
        self.assertLess(self.trace.index("scan"), self.trace.index("import"))
        self.assertLess(self.trace.index("import"), self.trace.index("unlocked"))
        self.importer.assert_called_once_with(self.root, self.root / "data", self.root / "model-test-results")

    def test_scanner_failure_never_imports_and_no_alternative_runner_exists(self):
        self.runner.side_effect = RuntimeError("Defender verdict unavailable")
        with self.assertRaisesRegex(RuntimeError, "Defender"):
            self.setup.install()
        self.importer.assert_not_called()
        self.runner.assert_called_once()

    def test_partial_report_never_imports(self):
        def partial(*args):
            self.write_report(*args)
            path = self.root / "model-test-results/model-file-checks.json"
            value = json.loads(path.read_text())
            value["files"][0]["status"] = "failed"
            path.write_text(json.dumps(value))
        self.runner.side_effect = partial
        with self.assertRaisesRegex(RuntimeError, "13 reviewed"):
            self.setup.install()
        self.importer.assert_not_called()

    def test_stale_report_never_imports(self):
        def stale(*args):
            self.write_report(*args)
            path = self.root / "model-test-results/model-file-checks.json"
            value = json.loads(path.read_text())
            value["started"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            path.write_text(json.dumps(value))
        self.runner.side_effect = stale
        with self.assertRaisesRegex(RuntimeError, "this setup attempt"):
            self.setup.install()
        self.importer.assert_not_called()

    def test_unchanged_report_cannot_be_reused(self):
        result = self.root / "model-test-results"
        result.mkdir()
        self.write_report(self.root, None, None)
        self.runner.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "did not change"):
            self.setup.install()
        self.importer.assert_not_called()

    def test_cancel_after_scan_prevents_import(self):
        def cancel(*args):
            self.write_report(*args)
            self.cancel.set()
        self.runner.side_effect = cancel
        with self.assertRaisesRegex(RuntimeError, "cancelled before import"):
            self.setup.install()
        self.importer.assert_not_called()

    def test_missing_manifest_fails_before_process_start(self):
        (self.root / "config" / "model-sources.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "complete checked edition"):
            self.setup.install()
        self.runner.assert_not_called()

    def test_simultaneous_setup_is_rejected_and_guard_releases_after_failure(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def blocked(*args):
            entered.set()
            release.wait(2)
            raise RuntimeError("test interruption")
        def run():
            try:
                self.setup.install()
            except RuntimeError as exc:
                errors.append(str(exc))
        self.runner.side_effect = blocked
        task = threading.Thread(target=run)
        task.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaisesRegex(RuntimeError, "already running"):
                self.setup.install()
        finally:
            release.set()
            task.join(3)
        self.assertFalse(task.is_alive())
        self.assertEqual(["test interruption"], errors)
        self.runner.side_effect = self.write_report
        self.setup.install()
        self.importer.assert_called_once()


if __name__ == "__main__":
    unittest.main()

