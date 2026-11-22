"""Publish a checked LiveTranslate feed to the owner's private GitHub Releases."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from source_bundle import open_sources

OWNER = "tokinmew"
NAME = "LiveTranslate"
REPO = OWNER + "/" + NAME
API = "repos/" + REPO
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}")
SOURCE = re.compile(r"(?:backend/[A-Za-z][A-Za-z0-9_]*\.py|ui/[A-Za-z][A-Za-z0-9_]*\.cs|README\.md|VALIDATION\.md|START-HERE\.txt)")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def version_parts(version):
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("Use a stable three-part release version.")
    parts = tuple(map(int, version.split(".")))
    if max(parts) > 65534:
        raise ValueError("Version exceeds the Windows limit.")
    return parts


def bounded(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path.name} exceeds the update size limit.")
    return data


def parse(data):
    def pairs(items):
        obj = dict(items)
        if len(obj) != len(items):
            raise ValueError("Duplicate JSON field.")
        return obj
    obj = json.loads(data, object_pairs_hook=pairs)
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object.")
    return obj


def load_feed(folder):
    manifest = bounded(folder/"latest.json", 64 * 1024)
    meta = parse(manifest)
    version = meta.get("version")
    version_parts(version)
    name = "LiveTranslate-" + version + ".json"
    if (type(meta.get("schema")) != int or meta["schema"] != 1 or meta.get("product") != NAME
            or meta.get("package") != name or type(meta.get("size")) != int):
        raise ValueError("Feed identity or package filename is invalid.")
    body = bounded(folder/name, 8 * 1024 * 1024)
    if len(body) != meta["size"] or sha(body) != meta.get("sha256"):
        raise ValueError("Package size or SHA-256 differs from latest.json.")
    package = parse(body)
    files = package.get("files")
    if package.get("version") != version or not isinstance(files,list) or not 1 <= len(files) <= 160:
        raise ValueError("Invalid cumulative update package.")
    seen = set()
    for file in files:
        path = file["path"]
        if (not SOURCE.fullmatch(path) or path.casefold() in seen or len(path)>120
                or re.fullmatch(r"(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])",Path(path).stem)):
            raise ValueError("Unexpected, duplicate or reserved path in update package.")
        data = file["text"].encode("utf8")
        if sha(data) != file["sha256"] or len(data)>1024**2 or b"\0" in data:
            raise ValueError("Invalid contents or hash for " + path)
        seen.add(path.casefold())
    if not {"ui/program.cs","backend/app_updates.py","backend/update_install.py","backend/worker.py"} <= seen:
        raise ValueError("The package is missing application or updater source.")
    return version, {name:body, "latest.json":manifest}


def check_signature(manifest):
    if not manifest.get("release_signature"):
        raise ValueError("Sign latest.json with Sign-Release.ps1 before publishing.")
    folder = Path(__file__).resolve().parent
    verifier = folder/"release_signature.py"
    if not verifier.is_file():
        verifier = folder.parent/"LiveTranslate"/"backend"/"release_signature.py"
    if not verifier.is_file():
        raise ValueError("The checked-in official signature verifier is missing. Extract the full publisher kit.")
    spec = importlib.util.spec_from_file_location("release_signature",verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_official_manifest(REPO, manifest)


class GitHub:
    def __init__(self):
        for root, subpath in (("ProgramFiles", "GitHub CLI/gh.exe"), ("ProgramFiles(x86)", "GitHub CLI/gh.exe"),
                              ("LOCALAPPDATA", "Programs/GitHub CLI/gh.exe")):
            if os.environ.get(root):
                path = Path(os.environ[root])/subpath
                if path.is_file():
                    self.exe = path
                    return
        raise ValueError("GitHub CLI is not installed in a standard Windows installation folder.")

    def run(self, args, *, stdin=None, optional=False):
        env = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
        env.pop("GH_DEBUG",None)
        proc = subprocess.run([str(self.exe),*args], input=stdin or b"", capture_output=True, env=env, timeout=120)
        if proc.returncode:
            # Error text can contain signed asset URLs, request metadata or environment details.
            if optional and re.search(rb"\bHTTP 404\b",proc.stderr):
                return None
            status = re.search(rb"\bHTTP (\d{3})\b",proc.stderr)
            detail = (" (HTTP " + status.group(1).decode() + ")") if status else ""
            raise RuntimeError("GitHub CLI request failed" + detail + ". Check your github.com login and repository access.")
        return proc.stdout

    def api(self, path, *, method="GET", body=None, optional=False, raw=False):
        args = ["api","--hostname","github.com","--method",method,"-H","X-GitHub-Api-Version: 2022-11-28"]
        if raw:
            args += ["-H","Accept: application/octet-stream"]
        if body is not None:
            args += ["--input","-"]
        result = self.run(args+[path],stdin=json.dumps(body).encode() if body is not None else None,optional=optional)
        if result is None or raw:
            return result
        return json.loads(result)

    def upload(self, tag, path):
        self.run(["release","upload",tag,str(path),"--repo","github.com/"+REPO])


def require_private(gh):
    repo = gh.api(API)
    if repo.get("full_name","").casefold() != REPO.casefold() or repo.get("private") is not True:
        raise ValueError("The target must be the dedicated private repository " + REPO + ".")
    if not repo.get("permissions",{}).get("push"):
        raise ValueError("Push access is required for " + REPO + ".")


def locate(gh, tag):
    page = 1
    while True:
        rows = gh.api(f"{API}/releases?per_page=100&page={page}")
        for row in rows:
            if row.get("tag_name") == tag:
                return row
        if len(rows)<100:
            return None
        page += 1


def guard_latest(gh, version):
    latest = gh.api(API+"/releases/latest",optional=True)
    if latest and version_parts(latest["tag_name"].removeprefix("v")) > version_parts(version):
        raise ValueError("A newer stable release already exists. The stable feed remains on that version.")


def verify_latest(gh, release_id, tag):
    latest = gh.api(API+"/releases/latest", optional=True)
    if not latest or latest.get("id") != release_id or latest.get("tag_name") != tag:
        raise ValueError("The tagged release exists but GitHub's latest stable endpoint points elsewhere. Check the repository release settings.")


def verified_assets(gh, release, assets):
    if release.get("prerelease") is not False:
        raise ValueError("The existing tag belongs to a prerelease.")
    found = set()
    for row in release["assets"]:
        name = row.get("name")
        if name not in assets:
            if release.get("draft"):
                raise ValueError("The draft contains an unexpected asset. Inspect the release before publishing.")
            continue
        if name in found or type(row.get("id")) != int or row["id"] <= 0:
            raise ValueError("Unexpected or duplicate release asset identity.")
        expected = assets[name]
        if row.get("state") != "uploaded" or row.get("size") != len(expected):
            raise ValueError("Incomplete or conflicting remote asset: " + name)
        if row.get("digest") and row["digest"] != "sha256:" + sha(expected):
            raise ValueError("Conflicting GitHub SHA-256 for " + name)
        remote = gh.api(f"{API}/releases/assets/{row['id']}",raw=True)
        if sha(remote) != sha(expected):
            raise ValueError("Remote asset contents differ for " + name)
        found.add(name)
    return found


def publish(gh, version, assets, sources, init_private=False):
    check_signature(parse(assets["latest.json"]))
    if gh.api("user").get("login","").casefold() != OWNER.casefold():
        raise ValueError("The active github.com account must be " + OWNER + ".")
    repo = gh.api(API, optional=True)
    if repo is None:
        if not init_private:
            raise ValueError("Private repository missing or inaccessible. Use --init-private only to create it.")
        gh.api("user/repos",method="POST",body={"name":NAME,"private":True,"auto_init":False})
    require_private(gh)
    guard_latest(gh, version)
    tag = "v"+version
    release = locate(gh,tag)
    if release is not None:
        # Check for a conflicting preexisting tag/release before pushing Git refs.
        verified_assets(gh, release, assets)
    require_private(gh)
    sources.sync(gh)
    if release is None:
        require_private(gh)
        release = gh.api(API+"/releases",method="POST",body={"tag_name":tag,"target_commitish":sources.commit,"name":"LiveTranslate "+version,
                         "body":"Stable Windows update. The numbered package and latest.json form the application feed.",
                         "draft":True,"prerelease":False})
    release_id = release.get("id")
    if type(release_id) != int or release_id <= 0 or release.get("tag_name") != tag:
        raise ValueError("GitHub returned an unexpected release identity.")
    path = f"{API}/releases/{release_id}"
    def current():
        row = gh.api(path)
        if row.get("tag_name") != tag or row.get("id") != release_id or row.get("prerelease") is not False:
            raise ValueError("The remote release changed. Inspect it and retry.")
        return row
    release = current()
    found = verified_assets(gh,release,assets)
    if not release["draft"]:
        if found != set(assets):
            raise ValueError("Published release is incomplete. Existing stable assets cannot be overwritten.")
        verify_latest(gh,release_id,tag)
        return "The identical stable release is already published."
    with tempfile.TemporaryDirectory(prefix="LiveTranslate-release-") as temp:
        for name, data in assets.items():
            if name not in found:
                require_private(gh)
                if not current()["draft"]:
                    raise ValueError("The draft changed during upload. Inspect it and retry.")
                local = Path(temp)/name
                local.write_bytes(data)
                gh.upload(tag,local)
    final = current()
    if verified_assets(gh,final,assets) != set(assets):
        raise ValueError("Missing required asset. The draft is incomplete.")
    if final["draft"]:
        require_private(gh)
        guard_latest(gh, version)
        if sources.refs(gh).get("refs/tags/"+tag) != sources.tag_id:
            raise ValueError("The remote source tag changed before publication.")
        gh.api(path,method="PATCH",body={"draft":False,"make_latest":"legacy"})
    if current()["draft"] or verified_assets(gh,current(),assets) != set(assets):
        raise ValueError("Release publication could not be verified.")
    verify_latest(gh,release_id,tag)
    return "Verified private stable release at https://github.com/"+REPO+"/releases/tag/"+tag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True, help="folder containing latest.json and the numbered package")
    parser.add_argument("--source-bundle",type=Path,default=None,help="version-matched bundle with main and vX.Y.Z; default ../LiveTranslate-source.bundle next to this publisher directory")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run",action="store_true",help="offline validation; the default")
    action.add_argument("--publish",action="store_true",help="upload validated files to a private draft, verify and publish")
    parser.add_argument("--init-private",action="store_true",help="create the dedicated private repo when missing")
    args = parser.parse_args()
    if args.init_private and not args.publish:
        parser.error("--init-private requires --publish")
    version, assets = load_feed(args.feed)
    print(f"{REPO} (private)   v{version}")
    for name,data in assets.items():
        print(f"{name}   {len(data):,} bytes   SHA-256 {sha(data)}")
    manifest = parse(assets["latest.json"])
    if manifest.get("release_signature") or args.publish:
        check_signature(manifest)
        print("Official release signature verified.")
    else:
        print("The manifest needs its official release signature before publication.")
    bundle = args.source_bundle or (Path(__file__).resolve().parent.parent/"LiveTranslate-source.bundle")
    with tempfile.TemporaryDirectory(prefix="LiveTranslate-source-") as temp:
        sources = None
        if args.publish or args.source_bundle or bundle.exists():
            sources = open_sources(bundle,temp,version,assets)
            print(f"Tagged source v{version} matches all update files. Commit {sources.commit}.")
        if args.publish:
            print(publish(GitHub(),version,assets,sources,args.init_private))
        elif sources:
            print("Offline preview passed.")
        else:
            print("Offline package preview passed. Supply the matching source bundle before publication.")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("Publisher stopped:",error,file=sys.stderr)
        raise SystemExit(1)
