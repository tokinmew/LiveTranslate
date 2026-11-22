"""Offline release tests. All GitHub actions terminate in a local in-memory fake."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import github_publish as pub


class GitHub:
    def __init__(self):
        self.login = pub.OWNER
        self.repo = {"full_name":pub.REPO,"private":True,"permissions":{"push":True}}
        self.release = None
        self.latest = None
        self.files = {}
        self.actions = []
        self.fail_next = False
        self.substitute_download = False

    def api(self,path,method="GET",body=None,optional=False,raw=False):
        if method != "GET":
            self.actions.append((method,path))
        if path == "user":
            return {"login": self.login}
        if path == "user/repos":
            assert body == {"private":True, "name":pub.NAME,"auto_init":False} and self.repo is None
            self.repo = {"full_name":pub.REPO,"private":True,"permissions":{"push":True}}
            return self.repo
        if path == pub.API:
            return self.repo
        if path.endswith("/releases/latest"):
            return self.latest
        if "/releases?" in path:
            return [copy.deepcopy(self.release)] if self.release else []
        if path.endswith("/releases") and method=="POST":
            self.release=dict(body,id=1,assets=[])
            return copy.deepcopy(self.release)
        if path.endswith("/releases/1"):
            if method=="PATCH":
                self.release.update(body)
                self.latest = self.release
            return copy.deepcopy(self.release)
        if "/releases/assets/" in path:
            assert raw
            value = self.files[int(path.split("/")[-1])]
            return b"x"*len(value) if self.substitute_download else value
        raise AssertionError((path,method))

    def upload(self, tag, path):
        self.actions.append(("upload",path.name))
        self.assert_draft(tag)
        if self.fail_next and self.files:
            self.fail_next = False
            raise RuntimeError("network interrupted")
        data = path.read_bytes()
        ident = len(self.files)+1
        self.files[ident]=data
        self.release["assets"].append({"id":ident,"name":path.name,"size":len(data),"state":"uploaded",
                                       "digest":"sha256:"+pub.sha(data)})

    def assert_draft(self,tag):
        assert self.release["draft"] and tag == self.release["tag_name"]


class Publication(unittest.TestCase):
    def setUp(self):
        self.gh = GitHub()
        self.files = {"LiveTranslate-0.6.5.json":b'{"version":"0.6.5"}',"latest.json":b'{"release_signature":"test"}'}
        self.signature = self.enterContext(patch.object(pub,"check_signature"))
        self.sources = Mock(commit="a"*40,tag_id="b"*40)
        self.sources.refs.return_value = {"refs/tags/v0.6.5":self.sources.tag_id}

    def publish(self,initialize=False):
        return pub.publish(self.gh, "0.6.5", self.files, self.sources, initialize)

    def test_successful_private_draft_and_idempotent_retry(self):
        self.assertIn("Verified",self.publish())
        self.assertFalse(self.gh.release["draft"])
        count = len(self.gh.actions)
        self.assertIn("already",self.publish())
        self.assertEqual(count,len(self.gh.actions))

    def test_private_creation_is_explicit_and_verifies_owner(self):
        self.gh.repo = None
        with self.assertRaisesRegex(ValueError,"missing"):
            self.publish()
        self.assertFalse(self.gh.actions)
        self.publish(True)
        self.assertTrue(self.gh.repo["private"])
        self.assertEqual(("POST","user/repos"),self.gh.actions[0])

    def test_refuses_wrong_account(self):
        self.gh.login="elsewhere"
        with self.assertRaisesRegex(ValueError,"active"):
            self.publish(True)
        self.assertFalse(self.gh.actions)

    def test_refuses_public_or_different_target(self):
        for change in ({"private":False},{"full_name":"tokinmew/other"},{"permissions":{}}):
            self.gh=GitHub()
            self.gh.repo.update(change)
            with self.assertRaises(ValueError):
                self.publish()
            self.assertFalse(self.gh.actions)

    def test_rejects_rollback(self):
        self.gh.latest = {"tag_name":"v0.6.6"}
        with self.assertRaisesRegex(ValueError,"newer"):
            self.publish()
        self.assertFalse(self.gh.actions)

    def test_interrupted_upload_stays_draft_and_resumes(self):
        self.gh.fail_next = True
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertTrue(self.gh.release["draft"])
        self.assertEqual(1,len(self.gh.files))
        self.publish()
        self.assertEqual(2,len(self.gh.files))
        self.assertFalse(self.gh.release["draft"])

    def test_readback_detects_wrong_bytes_even_for_valid_metadata(self):
        self.gh.substitute_download = True
        with self.assertRaisesRegex(ValueError,"contents differ"):
            self.publish()
        self.assertTrue(self.gh.release["draft"])

    def test_preexisting_conflicting_asset_cannot_be_replaced(self):
        self.gh.fail_next=True
        with self.assertRaises(RuntimeError):
            self.publish()
        self.gh.release["assets"][0]["digest"]="sha256:"+"0"*64
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            self.publish()
        self.assertTrue(self.gh.release["draft"])

    def test_incomplete_published_release_never_edited(self):
        self.publish()
        self.gh.release["assets"].pop()
        count=len(self.gh.actions)
        with self.assertRaisesRegex(ValueError,"incomplete"):
            self.publish()
        self.assertEqual(count,len(self.gh.actions))

    def test_requires_latest_stable_to_reference_identical_release(self):
        self.publish()
        self.gh.latest = {"id":77,"tag_name":"v0.6.4"}
        count = len(self.gh.actions)
        with self.assertRaisesRegex(ValueError,"points elsewhere"):
            self.publish()
        self.assertEqual(count,len(self.gh.actions))

    def test_signature_failure_precedes_github_access(self):
        self.signature.side_effect=ValueError("invalid signature")
        with self.assertRaisesRegex(ValueError,"signature"):
            pub.publish(None, "0.6.5", self.files, None)

    def test_source_sync_required_before_release_creation(self):
        self.sources.sync.side_effect=ValueError("conflicting source")
        with self.assertRaisesRegex(ValueError,"conflicting"):
            self.publish()
        self.assertFalse(self.gh.actions)

    def test_changed_remote_tag_after_upload_blocks_promotion(self):
        self.sources.refs.return_value = {"refs/tags/v0.6.5":"f"*40}
        with self.assertRaisesRegex(ValueError,"tag changed"):
            self.publish()
        self.assertTrue(self.gh.release["draft"])

    def test_extra_asset_prevents_draft_publication(self):
        self.gh.fail_next=True
        with self.assertRaises(RuntimeError):
            self.publish()
        self.gh.release["assets"].append({"name":"other-file"})
        with self.assertRaisesRegex(ValueError,"unexpected asset"):
            self.publish()
        self.assertTrue(self.gh.release["draft"])


class LocalPackage(unittest.TestCase):
    def test_feed_checks_aggregate_and_file_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            version="0.6.5"
            name=f"LiveTranslate-{version}.json"
            files=[dict(path=x,text="x",sha256=pub.sha(b"x")) for x in ("ui/Program.cs","backend/app_updates.py","backend/update_install.py","backend/worker.py")]
            def write():
                content=json.dumps(dict(version=version,files=files)).encode()
                (root/name).write_bytes(content)
                (root/"latest.json").write_text(json.dumps(dict(schema=1,product=pub.NAME,version=version,package=name,size=len(content),sha256=pub.sha(content))),"utf8")
            write()
            self.assertEqual(version,pub.load_feed(root)[0])
            (root/name).write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                pub.load_feed(root)
            files[0]["sha256"]="0"*64
            write()
            with self.assertRaisesRegex(ValueError,"contents"):
                pub.load_feed(root)

    def test_missing_signature_rejected(self):
        with self.assertRaisesRegex(ValueError,"Sign latest"):
            pub.check_signature({})

if __name__ == "__main__":
    unittest.main()
