"""Local deterministic GitHub release and credential-boundary checks."""
from contextlib import ExitStack
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate/backend"))
import app_updates
import github_releases as gh


def encoded(obj):
    return json.dumps(obj, separators=(",", ":")).encode()


def rejected(code, location=""):
    return HTTPError("https://api.github.com/test", code, "Response", {"Location": location}, io.BytesIO())


class Response(io.BytesIO):
    status = 200
    headers = {}


class GitHubReleaseTests(unittest.TestCase):
    repo = "https://github.com/example/LiveTranslate"

    def setUp(self):
        self.package = encoded({"version": "0.6.5", "files": []})
        self.manifest = dict(schema=1, product="LiveTranslate", version="0.6.5",
                             package="LiveTranslate-0.6.5.json",size=len(self.package),sha256=sha256(self.package).hexdigest())
        self.content = encoded(self.manifest)
        self.metadata = {"tag_name": "v0.6.5", "draft": False, "prerelease": False,
                         "assets": [self.asset("latest.json", 10, self.content),
                                    self.asset("LiveTranslate-0.6.5.json", 22, self.package)]}
        self.endpoints = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.pub = self.stack.enter_context(patch.object(gh,"public_read",side_effect=self.reply))
        self.private = self.stack.enter_context(patch.object(gh,"private_read",side_effect=AssertionError("Authentication requested")))
        self.verify = Mock()
        signature = types.SimpleNamespace(OFFICIAL="tokinmew/livetranslate", verify_official_manifest=self.verify)
        self.stack.enter_context(patch.dict(sys.modules, release_signature=signature))

    def asset(self, name, identity, content):
        return {"name":name, "id":identity, "state":"uploaded","size":len(content),
                "digest":"sha256:"+sha256(content).hexdigest(),"url":"https://untrusted.invalid/disregard"}

    def reply(self, endpoint, media, limit):
        self.assertTrue(endpoint.startswith("repos/example/LiveTranslate/releases/"))
        self.endpoints.append(endpoint)
        suffix = endpoint.split("/")[-1]
        return {"latest":encoded(self.metadata),"10":self.content,"22":self.package}[suffix]

    def test_public_check_does_not_download_package_or_use_private_credential(self):
        self.assertTrue(app_updates.check_update(self.repo+"/","0.6.4")["available"])
        self.assertEqual(["latest","10"],[e.split("/")[-1] for e in self.endpoints])
        self.verify.assert_called_once_with("example/LiveTranslate",self.manifest)
        self.private.assert_not_called()
        self.assertFalse(app_updates.check_update(self.repo,"0.6.5")["available"])

    def test_official_check_repairs_old_snapshot_once_without_prefetching_an_upgrade(self):
        digest = self.manifest["sha256"]
        snapshot = {"version": "0.6.4", "sha256": "0" * 64}
        root = Path("isolated")
        sink = Mock(side_effect=lambda *args: snapshot.update(version="0.6.5", sha256=digest))
        local = types.SimpleNamespace(installed_snapshot=lambda _: snapshot, cache_official_snapshot=sink)
        official = "https://github.com/tokinmew/LiveTranslate"
        self.pub.side_effect = lambda endpoint, *args: self.reply(endpoint.replace("tokinmew/", "example/"), *args)
        with patch.dict(sys.modules, installed_feed=local):
            for installed in ("0.6.4", "0.6.5", "0.6.5"):
                result = app_updates.check_update(official, installed, root)
                self.assertEqual(result["available"], installed == "0.6.4")
            sink.assert_called_once_with(root, self.content, self.package)
            self.assertEqual(1, sum(url.endswith("/assets/22") for url in self.endpoints))
            snapshot["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "different content"):
                app_updates.check_update(official, "0.6.5", root)
            app_updates.check_update(self.repo, "0.6.5", root)
            self.assertEqual(1, sink.call_count)

    def test_download_bounds_digest_and_fixed_asset_id(self):
        manifest, asset, _ = app_updates._manifest(self.repo)
        self.assertEqual(self.package,app_updates._read(asset,manifest["size"]))
        self.assertTrue(self.endpoints[-1].endswith("/assets/22"))
        with self.assertRaises(ValueError):
            app_updates._read(asset,manifest["size"]-1)
        self.pub.side_effect = lambda *a:b"X"*asset.size
        with self.assertRaises(ValueError):
            app_updates._read(asset,asset.size)

    def test_private_reads_use_only_fixed_repo_api_paths(self):
        self.pub.side_effect = rejected(404)
        self.private.side_effect = self.reply
        manifest, asset, _ = app_updates._manifest(self.repo)
        self.assertEqual(self.package,app_updates._read(asset,manifest["size"]))
        self.assertEqual(3,self.private.call_count)
        self.assertEqual(2,self.pub.call_count)

    def test_unpublished_public_repository_has_distinct_status_without_cli(self):
        def empty_channel():
            self.pub.side_effect = [rejected(404), encoded({"full_name":"example/LiveTranslate","private":False})]
        empty_channel()
        self.assertEqual({"ok": True, "available": False, "status": "unpublished"},
                         app_updates.check_update(self.repo, "0.6.8"))
        self.assertEqual(["repos/example/LiveTranslate/releases/latest", "repos/example/LiveTranslate"],
                         [args.args[0] for args in self.pub.call_args_list])
        empty_channel()
        with self.assertRaises(gh.NoStableRelease):
            app_updates._manifest(self.repo)
        self.private.assert_not_called()
        self.verify.assert_not_called()

    def test_unpublished_private_repository_requires_readable_empty_collection(self):
        self.pub.side_effect = rejected(404)
        self.private.side_effect = [gh.PrivateRequestFailed("release unavailable"), encoded([])]
        self.assertEqual("unpublished", app_updates.check_update(self.repo, "0.6.8")["status"])
        self.assertEqual(["repos/example/LiveTranslate/releases/latest", "repos/example/LiveTranslate/releases?per_page=1"],
                         [args.args[0] for args in self.private.call_args_list])
        for response in (gh.PrivateRequestFailed("access denied"), encoded([{"draft": True}])):
            with self.subTest(response=response):
                self.private.side_effect = [gh.PrivateRequestFailed("release unavailable"), response]
                with self.assertRaisesRegex(gh.PrivateRequestFailed, "release unavailable"):
                    app_updates.check_update(self.repo, "0.6.8")

    def test_private_or_unreachable_feed_never_reports_current_or_empty(self):
        for status in (403, 404, 429):
            with self.subTest(status=status):
                self.pub.side_effect = [rejected(status), rejected(404)]
                self.private.side_effect = ValueError("GitHub CLI needs sign-in")
                with self.assertRaisesRegex(ValueError, "sign-in"):
                    app_updates.check_update(self.repo, "0.6.8")

    def test_early_server_error_does_not_request_auth(self):
        self.pub.side_effect = rejected(502)
        with self.assertRaises(ValueError):
            app_updates._manifest(self.repo)
        self.private.assert_not_called()

    def test_declines_drafts_prereleases_and_inconsistent_metadata(self):
        for key, value in (("draft",True),("prerelease",True),("tag_name","v0.6.5-alpha"),("tag_name","v0.6.6"),
                           ("assets",[]),("assets",[self.metadata["assets"][1]])):
            with self.subTest(field=key,value=value), patch.dict(self.metadata,{key:value}):
                with self.assertRaises(ValueError):
                    app_updates.check_update(self.repo,"0.6.4")

    def test_duplicate_unuploaded_damaged_or_oversized_release_is_refused(self):
        for key,value in (("id",10),("id",True),("name","latest.json"),("state","open"),
                          ("size",app_updates.MAX_PACKAGE+1),("size",1),("digest","sha256:"+"9"*64)):
            with self.subTest(field=key),patch.dict(self.metadata["assets"][1],{key:value}):
                with self.assertRaises(ValueError):
                    app_updates._manifest(self.repo)

    def test_no_asset_fetch_when_manifest_signature_declined(self):
        self.verify.side_effect = ValueError("Invalid signature")
        with self.assertRaisesRegex(ValueError,"signature"):
            app_updates.check_update(self.repo,"0.6.4")
        self.assertTrue(all(not e.endswith("/22") for e in self.endpoints))

    def test_reject_credentials_unsafe_urls_and_fake_repositories(self):
        for url in ("http://github.com/a/b","https://user@github.com/a/b","https://github.com.evil/a/b",
                    "https://github.com/a/..","https://github.com/a/b?token=x","https://github.com/a/b%2Fc",
                    "https://github.com/a\\b/repo","https://github.com/a/b/other"):
            with self.subTest(url=url),self.assertRaises(ValueError):
                gh.repository(url)


class TransportTests(unittest.TestCase):
    def test_anonymous_asset_redirect_allows_only_exact_https_cdn(self):
        for location in ("http://release-assets.githubusercontent.com/a","https://github.com.evil/a",
                         "https://release-assets.githubusercontent.com@other.example/a","file:///C:/test"):
            opener = Mock()
            opener.open.side_effect = rejected(302,location)
            with patch.object(gh.urllib.request,"build_opener",return_value=opener),self.assertRaises(ValueError):
                gh.public_read("repos/a/b/releases/assets/9","application/octet-stream",9)
            self.assertEqual(1,opener.open.call_count)
        opener = Mock()
        opener.open.side_effect = [rejected(302,"https://release-assets.githubusercontent.com/asset?s=one"), Response(b"abc")]
        with patch.object(gh.urllib.request,"build_opener",return_value=opener):
            self.assertEqual(b"abc",gh.public_read("repos/a/b/releases/assets/9","application/octet-stream",3))
        request = opener.open.call_args.args[0]
        self.assertFalse(request.has_header("Authorization"))

    def test_metadata_redirect_unavailable_cli_and_data_caps(self):
        opener = Mock()
        opener.open.side_effect = rejected(302,"https://release-assets.githubusercontent.com/a")
        with patch.object(gh.urllib.request,"build_opener",return_value=opener),self.assertRaises(HTTPError):
            gh.public_read("repos/a/b/releases/latest","application/vnd.github+json",100)
        opener.open.side_effect = None
        opener.open.return_value = Response(b"1234")
        with patch.object(gh.urllib.request,"build_opener",return_value=opener),self.assertRaises(ValueError):
            gh.public_read("repos/a/b/releases/assets/1","application/octet-stream",3)
        with patch.dict(gh.os.environ,{},clear=True),self.assertRaisesRegex(ValueError,"GitHub CLI"):
            gh.installed_cli()

    def test_private_cli_fixed_read_only_args_and_size_limit(self):
        cli = Path("C:/Program Files/GitHub CLI/gh.exe")
        proc = Mock()
        proc.__enter__ = lambda this:this
        proc.__exit__ = lambda *args:None
        proc.wait.return_value = 0
        with patch.object(gh,"installed_cli",return_value=cli),patch.object(gh.subprocess,"Popen",return_value=proc) as start:
            proc.stdout = io.BytesIO(b"abc")
            self.assertEqual(b"abc",gh.private_read("repos/a/b/releases/assets/9","application/octet-stream",3))
            args = start.call_args.args[0]
            self.assertEqual([str(cli),"api","--hostname","github.com","--method","GET","-H",
                              "Accept: application/octet-stream","repos/a/b/releases/assets/9"],args)
            self.assertEqual(gh.subprocess.DEVNULL,start.call_args.kwargs["stderr"])
            proc.stdout = io.BytesIO(b"abcde")
            with self.assertRaises(ValueError):
                gh.private_read("repos/a/b/releases/assets/9","application/octet-stream",3)


class AutomaticFeedTests(unittest.TestCase):
    repo = "https://github.com/tokinmew/LiveTranslate"

    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name)
        self.snapshot = Mock(return_value={"ok":True, "version":"0.6.8"})
        self.modules = patch.dict(sys.modules, installed_feed=types.SimpleNamespace(installed_snapshot=self.snapshot))
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_unavailable_or_unpublished_returns_verified_snapshot_without_install_offer(self):
        failures = (gh.SourceUnavailable("Access denied"), URLError("DNS unavailable"), None)
        for problem in failures:
            with self.subTest(problem=problem), patch.object(app_updates, "check_update", side_effect=problem,
                    return_value={"ok":True, "available":False, "status":"unpublished"}):
                result = app_updates.automatic_check(self.repo, "0.6.9", self.root)
                self.assertEqual("unavailable" if problem else "unpublished", result["github_status"])
                self.assertEqual(("bundled", False, "0.6.8"), (result["status"],result["available"],result["version"]))
                self.assertNotIn("sha256", result)
                self.snapshot.assert_called_with(self.root)

    def test_remote_content_or_certificate_failure_stops_before_snapshot(self):
        import ssl
        for problem in (ValueError("bad signature"), ValueError("digest mismatch"), URLError(ssl.SSLError("bad certificate"))):
            with self.subTest(problem=problem), patch.object(app_updates, "check_update", side_effect=problem):
                with self.assertRaises(type(problem)):
                    app_updates.automatic_check(self.repo, "0.6.9", self.root)
        self.snapshot.assert_not_called()

    def test_remote_result_precedes_bundled_and_custom_sources_are_excluded(self):
        for available in (False, True):
            online = {"ok":True, "available":available, "version":"0.6.9"}
            with patch.object(app_updates, "check_update", return_value=online):
                self.assertEqual(online, app_updates.automatic_check(self.repo, "0.6.9", self.root))
        with self.assertRaises(ValueError):
            app_updates.automatic_check("https://github.com/other/test", "0.6.9", self.root)
        self.snapshot.assert_not_called()

    def test_two_failures_remain_visible(self):
        self.snapshot.side_effect = ValueError("snapshot signature is invalid")
        with patch.object(app_updates, "check_update", side_effect=gh.SourceUnavailable("Access denied")):
            with self.assertRaisesRegex(ValueError, "Access denied.*snapshot signature is invalid"):
                app_updates.automatic_check(self.repo, "0.6.9", self.root)


if __name__ == "__main__":
    unittest.main()
