"""Read the two LiveTranslate assets of an explicitly selected stable GitHub release."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


API = "https://api.github.com"
METADATA_LIMIT = 512 * 1024
ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com",
               "github-production-release-asset-2e65be.s3.amazonaws.com"}
REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}")


def repository(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise ValueError("Invalid GitHub repository URL.")
    parsed = urllib.parse.urlsplit(url)
    slug = parsed.path[1:].removesuffix("/")
    if (parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com"
            or "?" in url or "#" in url or not REPOSITORY.fullmatch(slug)
            or slug.split("/")[1] in (".", "..")):
        raise ValueError("Use a GitHub repository URL such as https://github.com/owner/repository.")
    return slug


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NoStableRelease(ValueError):
    """The repository can be read, but GitHub has no published stable release."""


class SourceUnavailable(ValueError):
    """GitHub or its configured credentials are unavailable."""


class PrivateRequestFailed(SourceUnavailable):
    """GitHub CLI completed, but could not fetch the requested endpoint."""


def public_read(endpoint, accept, limit):
    url = API + "/" + endpoint
    opener = urllib.request.build_opener(NoRedirect())
    headers = {"User-Agent":"LiveTranslate-Updater", "Accept":accept, "Accept-Encoding":"identity"}
    try:
        response = opener.open(urllib.request.Request(url, headers=headers), timeout=12)
    except urllib.error.HTTPError as error:
        if error.code != 302 or accept != "application/octet-stream":
            raise
        try:
            target = error.headers.get("Location", "")
            parsed = urllib.parse.urlsplit(target)
            if (len(target) > 8192 or parsed.scheme != "https" or parsed.netloc not in ASSET_HOSTS
                    or not parsed.path.startswith("/") or parsed.fragment
                    or "\\" in target or any(ord(c)<33 or ord(c)>126 for c in target)):
                raise ValueError("GitHub returned an unexpected asset download location.")
        finally:
            error.close()
        # New request with no credentials. Never accept a second redirect.
        response = opener.open(urllib.request.Request(target, headers=headers), timeout=12)
    with response:
        if response.status != 200 or response.headers.get("Content-Encoding","identity").lower() != "identity":
            raise ValueError("GitHub returned an unexpected response.")
        size = response.headers.get("Content-Length")
        if size is not None and not 0 <= int(size) <= limit:
            raise ValueError("GitHub response exceeds the allowed download size.")
        buf = bytearray()
        deadline = time.monotonic()+60
        while len(buf) <= limit:
            if time.monotonic() >= deadline:
                raise ValueError("GitHub download timed out.")
            chunk = response.read1(min(65536, limit+1-len(buf)))
            if not chunk:
                break
            buf.extend(chunk)
        if len(buf)>limit or (size is not None and int(size)!=len(buf)):
            raise ValueError("GitHub download size differs from its declared size.")
        return bytes(buf)


def installed_cli():
    # Use the system installation, never a gh.exe in the current app, cwd or PATH.
    for key in ("ProgramW6432","ProgramFiles","ProgramFiles(x86)"):
        directory = os.environ.get(key)
        if directory:
            path = Path(directory)/"GitHub CLI"/"gh.exe"
            if path.is_absolute() and path.is_file():
                return path
    raise SourceUnavailable("No public stable release was available. Private repositories require GitHub CLI installed in Program Files and signed in to github.com with read access.")


def private_read(endpoint, accept, limit):
    cli = installed_cli()
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_NO_EXTENSION_UPDATE_NOTIFIER="1",
               NO_COLOR="1", GH_PAGER="")
    env.pop("GH_FORCE_TTY", None)
    # gh owns authentication end to end. It receives only a fixed GitHub API
    # route that we construct, never a URL or a command from a release record.
    args = [str(cli),"api","--hostname","github.com","--method","GET","-H","Accept: "+accept,endpoint]
    with subprocess.Popen(args,cwd=cli.parent,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)) as child:
        done = queue.Queue(maxsize=1)
        def collect():
            try:
                done.put(child.stdout.read(limit+1))
            except OSError:
                done.put(None)
        reader = threading.Thread(target=collect,daemon=True)
        reader.start()
        try:
            try:
                data = done.get(timeout=70)
            except queue.Empty:
                raise SourceUnavailable("GitHub CLI download timed out.") from None
            if data is None or len(data)>limit:
                raise ValueError("GitHub CLI returned an invalid or oversized response.")
            try:
                status = child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                raise SourceUnavailable("GitHub CLI download did not finish.") from None
            if status:
                raise PrivateRequestFailed("GitHub CLI could not read the stable release. Check repository access and sign-in.")
            return data
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            reader.join(timeout=2)


@dataclass(frozen=True)
class Asset:
    endpoint: str
    size: int
    digest: str
    private: bool

    def read(self, limit):
        if self.size > limit:
            raise ValueError("GitHub release asset exceeds the expected size.")
        fetch = private_read if self.private else public_read
        try:
            data = fetch(self.endpoint,"application/octet-stream",self.size)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ValueError("GitHub could not return the release asset. Check again.") from None
        if len(data)!=self.size or (self.digest and hashlib.sha256(data).hexdigest()!=self.digest):
            raise ValueError("GitHub release asset failed its size or SHA-256 check.")
        return data


def release(url, manifest_limit, package_limit):
    slug = repository(url)
    repo_endpoint = "repos/" + slug
    base = repo_endpoint + "/releases/"
    endpoint = base+"latest"
    private = False
    try:
        raw = public_read(endpoint,"application/vnd.github+json",METADATA_LIMIT)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status not in (401,403,404,429):
            if 500 <= status <= 599:
                raise SourceUnavailable("GitHub release check returned HTTP "+str(status)+".") from None
            raise ValueError("GitHub release check returned HTTP "+str(status)+".") from None
        if status == 404:
            # GitHub uses the same status for an unpublished channel and an
            # inaccessible repository. Only identify an empty public channel
            # when the repository itself is independently readable.
            try:
                metadata = json.loads(public_read(repo_endpoint, "application/vnd.github+json", METADATA_LIMIT))
            except urllib.error.HTTPError as repo_error:
                repo_error.close()
            else:
                if (isinstance(metadata, dict) and metadata.get("private") is False
                        and str(metadata.get("full_name", "")).lower() == slug.lower()):
                    raise NoStableRelease("No stable release has been published to this GitHub repository.") from None
        try:
            raw = private_read(endpoint,"application/vnd.github+json",METADATA_LIMIT)
        except PrivateRequestFailed as latest_error:
            # gh returns the same exit code for missing and inaccessible releases.
            # An authenticated empty release list confirms access and publication state.
            try:
                page = private_read(repo_endpoint + "/releases?per_page=1", "application/vnd.github+json", METADATA_LIMIT)
            except ValueError:
                raise latest_error from None
            if json.loads(page) == []:
                raise NoStableRelease("No stable release has been published to this GitHub repository.") from None
            raise
        private = True
    release = json.loads(raw)
    if (not isinstance(release,dict) or release.get("draft") is not False
            or release.get("prerelease") is not False or not isinstance(release.get("assets"),list)):
        raise ValueError("Expected a published stable GitHub release.")
    tag = release.get("tag_name")
    if not isinstance(tag,str) or not re.fullmatch(r"v(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}",tag):
        raise ValueError("Expected a stable LiveTranslate release tag such as v0.6.5.")
    version = tag[1:]
    package = "LiveTranslate-"+version+".json"
    limits = {"latest.json":manifest_limit,package:package_limit}
    assets = {}
    ids = set()
    for row in release["assets"]:
        if not isinstance(row,dict) or not isinstance(row.get("name"),str) or row["name"] not in limits:
            continue
        name, size, identity = row["name"], row.get("size"), row.get("id")
        if (name in assets or row.get("state")!="uploaded" or type(size) is not int or not 0<size<=limits[name]
                or type(identity) is not int or not 0<identity<=2**63-1 or identity in ids):
            raise ValueError("GitHub release contains duplicate or invalid update assets.")
        digest = row.get("digest")
        if digest is not None and (not isinstance(digest,str) or not re.fullmatch(r"sha256:[0-9a-f]{64}",digest)):
            raise ValueError("Unknown GitHub release asset digest.")
        assets[name] = Asset(base+"assets/"+str(identity),size,digest[7:] if digest else "",private)
        ids.add(identity)
    if assets.keys()!=limits.keys():
        raise ValueError("This GitHub release needs both latest.json and "+package+".")
    return version, assets["latest.json"].read(manifest_limit), assets[package]
