"""Deterministic public GitHub update and transport checks; no network is used."""
from contextlib import ExitStack
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate/backend"))
import app_updates
import github_releases as gh
import release_signature as official_signature


def encoded(obj):
    return json.dumps(obj, separators=(",", ":")).encode()


def rejected(code, location=""):
    return HTTPError("https://api.github.com/test", code, "Response", {"Location": location}, io.BytesIO())


class Response(io.BytesIO):
    status = 200
    headers = {}


class GitHubReleaseTests(unittest.TestCase):
    repo = "https://github.com/tokinmew/LiveTranslate"

    def setUp(self):
        self.package = encoded({"version": "0.6.5", "files": []})
        self.manifest = dict(schema=1, product="LiveTranslate", version="0.6.5",
                             package="LiveTranslate-0.6.5.json", size=len(self.package),
                             sha256=sha256(self.package).hexdigest())
        self.content = encoded(self.manifest)
        self.metadata = {"tag_name": "v0.6.5", "draft": False, "prerelease": False,
                         "assets": [self.asset("latest.json", 10, self.content),
                                    self.asset("LiveTranslate-0.6.5.json", 22, self.package)]}
        self.endpoints = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.pub = self.stack.enter_context(patch.object(gh, "public_read", side_effect=self.reply))
        self.verify = Mock()
        signature = types.SimpleNamespace(verify_official_manifest=self.verify)
        self.stack.enter_context(patch.dict(sys.modules, release_signature=signature))
        self.process = self.stack.enter_context(patch.object(subprocess, "Popen"))
        self.addCleanup(self.process.assert_not_called)

    def asset(self, name, identity, content):
        return {"name": name, "id": identity, "state": "uploaded", "size": len(content),
                "digest": "sha256:" + sha256(content).hexdigest(),
                "url": "https://untrusted.invalid/disregard"}

    def reply(self, endpoint, media, limit):
        self.assertTrue(endpoint.startswith("repos/tokinmew/LiveTranslate/releases/"))
        self.endpoints.append(endpoint)
        suffix = endpoint.split("/")[-1]
        return {"latest": encoded(self.metadata), "10": self.content, "22": self.package}[suffix]

    def test_check_uses_official_public_channel_without_package_prefetch_or_credentials(self):
        result = app_updates.check_update("0.6.4")
        self.assertTrue(result["available"])
        self.assertEqual("0.6.5", result["version"])
        self.assertEqual(["latest", "10"], [e.split("/")[-1] for e in self.endpoints])
        self.verify.assert_called_once_with("tokinmew/livetranslate", self.manifest)
        current = app_updates.check_update("0.6.5")
        self.assertFalse(current["available"])
        self.assertEqual("0.6.5", current["version"])
        self.assertNotIn("bundled", current.values())

    def test_download_bounds_digest_and_fixed_asset_id(self):
        manifest, asset = app_updates._manifest()
        self.assertEqual(self.package, app_updates._read(asset, manifest["size"]))
        self.assertTrue(self.endpoints[-1].endswith("/assets/22"))
        with self.assertRaises(ValueError):
            app_updates._read(asset, manifest["size"] - 1)
        self.pub.side_effect = lambda *args: b"X" * asset.size
        with self.assertRaises(ValueError):
            app_updates._read(asset, asset.size)

    def test_unpublished_public_repository_has_distinct_status(self):
        def empty_channel():
            self.pub.side_effect = [rejected(404), encoded({"full_name": "tokinmew/LiveTranslate", "private": False})]
        empty_channel()
        self.assertEqual({"ok": True, "available": False, "status": "unpublished"},
                         app_updates.check_update("0.6.8"))
        self.assertEqual(["repos/tokinmew/LiveTranslate/releases/latest", "repos/tokinmew/LiveTranslate"],
                         [args.args[0] for args in self.pub.call_args_list])
        empty_channel()
        with self.assertRaises(gh.NoStableRelease):
            app_updates._manifest()
        self.verify.assert_not_called()

    def test_missing_private_or_inaccessible_channel_never_requests_credentials(self):
        for repository in (rejected(404), encoded({"full_name": "tokinmew/LiveTranslate", "private": True}),
                           encoded({"full_name": "other/project", "private": False})):
            with self.subTest(repository=repository):
                self.pub.side_effect = [rejected(404), repository]
                with self.assertRaisesRegex(gh.SourceUnavailable, "public GitHub repository"):
                    app_updates.check_update("0.6.8")

    def test_server_auth_and_rate_errors_are_actionable_not_current(self):
        for status in (401, 403, 429, 502):
            with self.subTest(status=status):
                self.pub.side_effect = rejected(status)
                with self.assertRaisesRegex(gh.SourceUnavailable, "HTTP " + str(status)):
                    app_updates.check_update("0.6.8")
        self.pub.side_effect = URLError("DNS unavailable")
        with self.assertRaises(URLError):
            app_updates.check_update("0.6.8")

    def test_declines_drafts_prereleases_and_inconsistent_metadata(self):
        for key, value in (("draft", True), ("prerelease", True), ("tag_name", "v0.6.5-alpha"),
                           ("tag_name", "v0.6.6"), ("assets", []), ("assets", [self.metadata["assets"][1]])):
            with self.subTest(field=key, value=value), patch.dict(self.metadata, {key: value}):
                with self.assertRaises(ValueError):
                    app_updates.check_update("0.6.4")

    def test_duplicate_unuploaded_damaged_or_oversized_release_is_refused(self):
        for key, value in (("id", 10), ("id", True), ("name", "latest.json"), ("state", "open"),
                           ("size", app_updates.MAX_PACKAGE + 1), ("size", 1), ("digest", "sha256:" + "9" * 64)):
            with self.subTest(field=key), patch.dict(self.metadata["assets"][1], {key: value}):
                with self.assertRaises(ValueError):
                    app_updates._manifest()

    def test_signature_failure_stops_before_package_download(self):
        self.verify.side_effect = ValueError("Invalid signature")
        with self.assertRaisesRegex(ValueError, "signature"):
            app_updates.check_update("0.6.4")
        self.assertTrue(all(not e.endswith("/22") for e in self.endpoints))

    def test_missing_official_signature_is_rejected_by_real_verifier(self):
        with patch.dict(sys.modules, release_signature=official_signature):
            with self.assertRaisesRegex(ValueError, "signature"):
                app_updates.check_update("0.6.4")

    def test_rejects_alternate_repositories_and_unsafe_urls_before_transport(self):
        for url in ("http://github.com/tokinmew/LiveTranslate", "https://user@github.com/tokinmew/LiveTranslate",
                    "https://github.com.evil/tokinmew/LiveTranslate", "https://github.com/a/..",
                    self.repo + "?token=x", "https://github.com/a/b%2Fc", "https://github.com/a/b/other",
                    "https://github.com/other/LiveTranslate", "https://example.com/latest.json",
                    "file:///C:/latest.json", "http://127.0.0.1:8080/latest.json"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                gh.release(url, app_updates.MAX_MANIFEST, app_updates.MAX_PACKAGE)
        self.pub.assert_not_called()

    def test_manifest_identity_is_checked_even_when_signature_fixture_accepts_it(self):
        for key, value in (("schema", True), ("product", "Other"), ("package", "elsewhere.json"),
                           ("version", "0.6.5-beta"), ("size", True), ("sha256", "invalid")):
            with self.subTest(field=key), patch.dict(self.manifest, {key: value}):
                self.content = encoded(self.manifest)
                self.metadata["assets"][0] = self.asset("latest.json", 10, self.content)
                with self.assertRaises(ValueError):
                    app_updates.check_update("0.6.4")


class TransportTests(unittest.TestCase):
    def test_anonymous_asset_redirect_allows_only_exact_https_cdn(self):
        for location in ("http://release-assets.githubusercontent.com/a", "https://github.com.evil/a",
                         "https://release-assets.githubusercontent.com@other.example/a", "file:///C:/test"):
            opener = Mock()
            opener.open.side_effect = rejected(302, location)
            with patch.object(gh.urllib.request, "build_opener", return_value=opener), self.assertRaises(ValueError):
                gh.public_read("repos/tokinmew/LiveTranslate/releases/assets/9", "application/octet-stream", 9)
            self.assertEqual(1, opener.open.call_count)
        opener = Mock()
        opener.open.side_effect = [rejected(302, "https://release-assets.githubusercontent.com/asset?s=one"), Response(b"abc")]
        with patch.object(gh.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(b"abc", gh.public_read("repos/tokinmew/LiveTranslate/releases/assets/9", "application/octet-stream", 3))
        for call in opener.open.call_args_list:
            self.assertFalse(call.args[0].has_header("Authorization"))

    def test_metadata_redirect_and_oversized_response_are_refused(self):
        opener = Mock()
        opener.open.side_effect = rejected(302, "https://release-assets.githubusercontent.com/a")
        with patch.object(gh.urllib.request, "build_opener", return_value=opener), self.assertRaises(HTTPError):
            gh.public_read("repos/tokinmew/LiveTranslate/releases/latest", "application/vnd.github+json", 100)
        opener.open.side_effect = None
        opener.open.return_value = Response(b"1234")
        with patch.object(gh.urllib.request, "build_opener", return_value=opener), self.assertRaises(ValueError):
            gh.public_read("repos/tokinmew/LiveTranslate/releases/assets/1", "application/octet-stream", 3)


if __name__ == "__main__":
    unittest.main()
