"""Exercise real Git bundles, source comparison, and atomic pushes against local bare repositories."""
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import source_bundle


class GitWire(BaseHTTPRequestHandler):
    """Serve native Git RPC only for one disposable repo bound to loopback."""
    def log_message(self,*args):
        pass

    def reply(self,kind,data):
        self.send_response(200)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        for service in ("upload-pack","receive-pack"):
            if self.path == "/fixture/info/refs?service=git-"+service:
                data=subprocess.check_output([str(self.server.exe),service,"--stateless-rpc","--advertise-refs",str(self.server.repo)],timeout=10)
                announcement=("# service=git-"+service+"\n").encode()
                prefix=f"{4+len(announcement):04x}".encode()+announcement+b"0000"
                self.reply("application/x-git-"+service+"-advertisement",prefix+data)
                return
        self.send_error(404)

    def do_POST(self):
        for service in ("upload-pack","receive-pack"):
            if self.path == "/fixture/git-"+service:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=65536:
                    self.send_error(400)
                    return
                data=subprocess.check_output([str(self.server.exe),service,"--stateless-rpc",str(self.server.repo)],
                                             input=self.rfile.read(size),timeout=10)
                self.reply("application/x-git-"+service+"-result",data)
                return
        self.send_error(404)


class Bundles(unittest.TestCase):
    def git(self, cwd, *args):
        env=dict(os.environ,GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output([str(self.exe),"-c","user.name=Fixture","-c","user.email=fixture@invalid",
                                        "-c","core.autocrlf=false",*args],cwd=cwd,env=env,stderr=subprocess.PIPE).strip()

    def setUp(self):
        self.exe=source_bundle.installed_git()
        base=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root=base/"work"
        self.root.mkdir()
        self.remote=base/"remote.git"
        self.remote.mkdir()
        self.git(self.root,"init","-b","main")
        self.git(self.remote,"init","--bare")
        self.app=self.root/"LiveTranslate"
        self.app.mkdir()
        (self.app/"README.md").write_bytes(b"hello\r\n")
        self.git(self.root,"add","--all")
        self.git(self.root,"commit","-m","baseline")
        self.git(self.root,"tag","-a","v0.6.5","-m","release")
        self.bundle=base/"release.bundle"
        self.git(self.root,"bundle","create",str(self.bundle),"refs/heads/main","refs/tags/v0.6.5")
        self.scratch=base/"scratch"
        self.scratch.mkdir()
        server = self.enterContext(ThreadingHTTPServer(("127.0.0.1",0), GitWire))
        server.repo = self.remote
        server.exe = self.exe
        service = threading.Thread(target=server.serve_forever,kwargs={"poll_interval":0.025})
        service.start()
        self.addCleanup(service.join,2)
        self.addCleanup(server.shutdown)
        self.url=f"http://127.0.0.1:{server.server_address[1]}/fixture"
        self.enterContext(patch.object(source_bundle, "REMOTE", self.url))

    def build(self,version="0.6.5",source="hello\n"):
        return source_bundle.Sources(self.bundle,self.scratch,version,[{"path":"README.md","text":source}])

    def test_initializes_empty_remote_with_exact_main_and_annotated_tag(self):
        sources=self.build()
        sources.sync(None)
        self.assertEqual(sources.commit,self.git(self.remote,"rev-parse","refs/heads/main").decode())
        self.assertEqual(sources.tag_id,self.git(self.remote,"rev-parse","refs/tags/v0.6.5").decode())
        self.assertNotEqual(sources.commit,sources.tag_id)
        sources.sync(None)

    def test_existing_main_never_rewritten_even_when_diverged(self):
        sources=self.build()
        self.git(self.root,"switch","--orphan","independent")
        (self.root/"other.txt").write_text("unrelated")
        self.git(self.root,"add","--all")
        self.git(self.root,"commit","-m","separate history")
        self.git(self.root,"push",self.url,"HEAD:refs/heads/main")
        before=self.git(self.remote,"rev-parse","refs/heads/main")
        sources.sync(None)
        self.assertEqual(before,self.git(self.remote,"rev-parse","refs/heads/main"))
        self.assertEqual(sources.commit,self.git(self.remote,"rev-parse","refs/tags/v0.6.5^{commit}").decode())

    def test_refuses_conflicting_tag_even_if_it_peels_to_same_commit(self):
        sources=self.build()
        self.git(self.root,"push",self.url,"HEAD:refs/tags/v0.6.5")
        with self.assertRaisesRegex(ValueError,"different source"):
            sources.sync(None)
        self.assertEqual(sources.commit,self.git(self.remote,"rev-parse","refs/tags/v0.6.5").decode())

    def test_wrong_tagged_contents_prevent_any_push(self):
        with self.assertRaisesRegex(ValueError,"differ"):
            self.build(source="mismatch")
        self.assertEqual(b"",self.git(self.remote,"for-each-ref"))

    def test_absent_exact_tag_rejected(self):
        with self.assertRaises(ValueError):
            self.build(version="0.6.6")

if __name__ == "__main__":
    unittest.main()
