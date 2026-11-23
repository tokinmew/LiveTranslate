"""Verify release sources and push only to the dedicated private repository."""
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

REMOTE = "https://github.com/tokinmew/LiveTranslate.git"


def installed_git():
    candidates = []
    for name, subpath in (("ProgramFiles", "Git/cmd/git.exe"), ("ProgramFiles(x86)", "Git/cmd/git.exe"),
                          ("LOCALAPPDATA", "Programs/Git/cmd/git.exe")):
        if os.environ.get(name):
            candidates.append(Path(os.environ[name])/subpath)
    on_path = shutil.which("git.exe")
    if on_path:
        path = Path(on_path).resolve()
        apps = Path(os.environ["ProgramFiles"])/"WindowsApps"
        if path.is_relative_to(apps) and path.relative_to(apps).parts[0].startswith("OpenAI.CodexPrimaryRuntime."):
            candidates.append(path)
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError("Git for Windows was not found in a standard installation folder.")


def normalized(data):
    return data.decode("utf-8-sig").replace("\r\n","\n").replace("\r","\n")


class Sources:
    def __init__(self, bundle, directory, version, files):
        if not bundle.is_file():
            raise ValueError("The matching LiveTranslate-source.bundle is missing. Choose it with --source-bundle.")
        self.tag = "v"+version
        self.git = installed_git()
        self.cwd = Path(directory)
        self.blank = self.cwd/"empty"
        self.blank.mkdir()
        self.gitdir = self.cwd/"source.git"
        self.gitdir.mkdir()
        self.run(["init","--bare","--template="+str(self.blank)])
        source = str(bundle.resolve())
        self.run(["bundle","verify",source])
        self.run(["-c","fetch.fsckObjects=true","fetch","--no-tags",source,
                  "refs/heads/main:refs/heads/main",f"refs/tags/{self.tag}:refs/tags/{self.tag}"])
        self.tag_id = self.run(["rev-parse","--verify","refs/tags/"+self.tag]).decode().strip()
        self.commit = self.run(["rev-parse","--verify","refs/tags/"+self.tag+"^{commit}"]).decode().strip()
        self.run(["merge-base","--is-ancestor",self.commit,"refs/heads/main"])
        tree = self.run(["ls-tree","-r","-z",self.commit])
        entries = {}
        for row in tree.split(b"\0"):
            if row:
                meta, name = row.split(b"\t",1)
                mode, kind, oid = meta.split()
                if mode in (b"100644",b"100755") and kind == b"blob":
                    entries[name] = oid
        ids = []
        for record in files:
            logical = record["path"]
            if tuple(map(int, version.split("."))) >= (0,6,8) and logical in ("README.md","START-HERE.txt","VALIDATION.md"):
                logical = "docs/" + logical
            path = ("LiveTranslate/"+logical).encode("utf8")
            if path not in entries:
                raise ValueError("Tagged source bundle is missing a regular file: "+record["path"])
            ids.append(entries[path])
        stream = io.BytesIO(self.run(["cat-file","--batch"], stdin=b"\n".join(ids)+b"\n"))
        for oid,record in zip(ids,files):
            got, kind, size = stream.readline().split()
            if got != oid or kind != b"blob" or int(size) > 2 * 1024 * 1024:
                raise ValueError("Invalid source blob: "+record["path"])
            data = stream.read(int(size))
            if normalized(data) != normalized(record["text"].encode("utf8")) or stream.read(1) != b"\n":
                raise ValueError("Tagged sources differ from the update package: "+record["path"])

    def run(self, args, *, stdin=b"", gh=None):
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith(("GIT_","GCM_"))}
        env.pop("GH_DEBUG", None)
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                   GIT_NO_REPLACE_OBJECTS="1", GCM_INTERACTIVE="never", GH_HOST="github.com",
                   GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
        options = ["-c","core.hooksPath="+str(self.blank)]
        if gh is not None:
            helper = "!"+shlex.quote(gh.exe.as_posix())+" auth git-credential"
            options.extend(["-c","http.sslVerify=true","-c","http.sslBackend=schannel",
                            "-c","http.followRedirects=false","-c","credential.helper=",
                            "-c","credential.https://github.com.helper="+helper])
        result = subprocess.run([str(self.git),*options,*args], cwd=self.gitdir, env=env, input=stdin,
                                capture_output=True,timeout=120)
        if result.returncode:
            raise ValueError("Git could not complete "+args[0]+". Check the bundle, private repository access and remote refs.")
        return result.stdout

    def refs(self, gh):
        lines = self.run(["ls-remote","--refs",REMOTE,"refs/heads/*","refs/tags/*"],gh=gh).decode("utf8").splitlines()
        refs = {}
        for line in lines:
            oid, ref = line.split("\t")
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}",oid):
                raise ValueError("Unexpected Git object ID from remote.")
            refs[ref] = oid
        return refs

    def sync(self, gh):
        tag = "refs/tags/"+self.tag
        main = "refs/heads/main"
        refs = self.refs(gh)
        if tag in refs and refs[tag] != self.tag_id:
            raise ValueError("The remote release tag points to different source. Refusing to retag it.")
        if tag not in refs:
            args = ["push","--atomic"]
            if not refs:
                # Empty lease requires the branch to be absent; a concurrent
                # initialization fails instead of updating anyone's existing main.
                args.extend(["--force-with-lease="+main+":",REMOTE,self.commit+":"+main])
            else:
                args.append(REMOTE)
            args.append(tag+":"+tag)
            self.run(args,gh=gh)
        after = self.refs(gh)
        if after.get(tag) != self.tag_id or (not refs and after.get(main) != self.commit):
            raise ValueError("The exact source tag or the newly seeded main branch could not be verified.")


def open_sources(bundle, directory, version, assets):
    package = json.loads(assets[f"LiveTranslate-{version}.json"])
    return Sources(bundle,directory,version,package["files"])
