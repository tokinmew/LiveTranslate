"""Pinned model identity and failure recovery for app-owned Latin OCR files."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import extra_ocr_models as extra


def identity(code, payload):
    return code, len(payload), hashlib.sha256(payload).hexdigest(), hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


class ExtraOcrTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payloads = [b"reviewed German model", b"reviewed Italian model", b"reviewed Spanish model"]
        self.models = tuple(identity(code, value) for code, value in zip(("deu", "ita", "spa"), self.payloads))
        self.patch = patch.object(extra, "MODELS", self.models)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_downloads_only_pinned_files_scans_before_install_and_works_offline(self):
        def download(url, timeout):
            self.assertIn("/" + extra.COMMIT + "/", url)
            self.assertEqual(30, timeout)
            return io.BytesIO(self.payloads[("deu", "ita", "spa").index(url.split("/")[-1].split(".")[0])])
        with patch.object(extra.urllib.request, "urlopen", side_effect=download) as opened, patch.object(extra, "_scan") as scan:
            self.assertEqual(0, extra.install(self.root))
            self.assertEqual(3, opened.call_count)
            self.assertEqual(3, scan.call_count)
            self.assertEqual(0, extra.install(self.root, offline=True))
            self.assertEqual(3, opened.call_count)
        self.assertTrue(all(extra._verified(self.root / "data/tessdata" / (m[0] + ".traineddata"), m) for m in self.models))

    def test_corrupt_or_oversized_download_leaves_existing_models_untouched(self):
        target = self.root / "data/tessdata"
        target.mkdir(parents=True)
        old = target / "deu.traineddata"
        old.write_bytes(b"prior installed model")
        for payload in (b"bad", b"x" * 100):
            with patch.object(extra.urllib.request, "urlopen", return_value=io.BytesIO(payload)), patch.object(extra, "_scan") as scan:
                with self.assertRaises(ValueError):
                    extra.install(self.root)
                scan.assert_not_called()
            self.assertEqual(b"prior installed model", old.read_bytes())
            self.assertEqual([], list((self.root / ".lt-setup/extra-ocr").iterdir()))

    def test_failed_defender_scan_never_installs_staged_models(self):
        with patch.object(extra.urllib.request, "urlopen", return_value=io.BytesIO(self.payloads[0])), \
             patch.object(extra, "_scan", side_effect=ValueError("scan failed")):
            with self.assertRaisesRegex(ValueError, "scan failed"):
                extra.install(self.root)
        self.assertEqual([], list((self.root / "data/tessdata").iterdir()))

    def test_offline_missing_file_never_contacts_network(self):
        with patch.object(extra.urllib.request, "urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "online once"):
                extra.install(self.root, offline=True)
            opened.assert_not_called()

    def test_git_blob_identity_is_checked_as_well_as_sha256(self):
        path = self.root / "candidate"
        path.write_bytes(self.payloads[0])
        self.assertTrue(extra._verified(path, self.models[0]))
        model = self.models[0][:3] + ("0" * 40,)
        self.assertFalse(extra._verified(path, model))


if __name__ == "__main__":
    unittest.main()
