"""Resolve binary dependencies on official PyPI, then bind each wheel to its release record."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, quote
from urllib.request import HTTPRedirectHandler, build_opener, Request


def official_url(url, hosts):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or
            parsed.port not in (None, 443) or parsed.username is not None or
            parsed.password is not None or parsed.fragment):
        raise ValueError("Refused an address outside the approved HTTPS package hosts.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError("Unexpected redirect while checking the PyPI release record.")


def release_data(project, version):
    uri = "https://pypi.org/pypi/{}/{}/json".format(quote(project, safe=""), quote(version, safe=""))
    with build_opener(NoRedirect).open(Request(uri, headers={"Accept": "application/json"}), timeout=45) as response:
        if response.status != 200:
            raise ValueError("Could not read the official PyPI release record.")
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Package release metadata exceeded its size limit.")
    return json.loads(body)


def check_wheel(path, project, version, data):
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import Version

    if (canonicalize_name(data["info"]["name"]) != project or
            Version(data["info"]["version"]) != version):
        raise ValueError(f"Unexpected project or version for {path.name}.")
    matches = [r for r in data["urls"] if r["filename"] == path.name and r["packagetype"] == "bdist_wheel"]
    if len(matches) != 1:
        raise ValueError(f"Missing or ambiguous PyPI release file for {path.name}.")
    record = matches[0]
    official_url(record["url"], {"files.pythonhosted.org"})
    if record.get("yanked"):
        raise ValueError(f"PyPI marked {path.name} as withdrawn.")
    digest = record["digests"]["sha256"]
    if (not re.fullmatch("[0-9a-f]{64}", digest) or path.stat().st_size != record["size"]
            or record["size"] <= 0):
        raise ValueError(f"Invalid file size or published digest for {path.name}.")
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
            raise ValueError(f"The file differs from its PyPI SHA-256 for {path.name}.")
    return digest


def download(requirements, wheelhouse):
    from pip._internal.cli.main import main as pip_main
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.requests.sessions import Session

    # Apply the same origin rule to pip's redirected requests and wheels' direct
    # dependencies. Resolution reads wheel metadata only. Source distributions
    # and build hooks are disabled.
    for line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and (line.startswith("-") or Requirement(line).url):
            raise ValueError("Requirements must name packages from the official PyPI index.")
    original_send = Session.send

    def send(session, request, **kwargs):
        official_url(request.url, {"pypi.org", "files.pythonhosted.org"})
        if kwargs.get("verify") is False:
            raise ValueError("Package requests require HTTPS certificate validation.")
        return original_send(session, request, **kwargs)

    for key in list(os.environ):
        if key.startswith("PIP_"):
            del os.environ[key]
    os.environ["PIP_CONFIG_FILE"] = os.devnull
    Session.send = send
    try:
        return pip_main(["--isolated", "--no-input", "--disable-pip-version-check", "--no-cache-dir",
                         "download", "--only-binary=:all:", "--keyring-provider", "disabled",
                         "--index-url", "https://pypi.org/simple", "--retries", "1", "--timeout", "45",
                         "--dest", str(wheelhouse), "-r", str(requirements)])
    finally:
        Session.send = original_send


def main():
    from pip._vendor.packaging.utils import parse_wheel_filename

    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=Path)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("locked_requirements", type=Path)
    args = parser.parse_args()
    args.wheelhouse.mkdir()
    result = download(args.requirements, args.wheelhouse)
    if result != 0:
        return result
    locked = []
    names = set()
    for path in sorted(args.wheelhouse.iterdir()):
        if not path.is_file() or path.is_symlink() or path.suffix != ".whl":
            raise ValueError("Unexpected entry in the isolated wheel download folder.")
        project, version, _, _ = parse_wheel_filename(path.name)
        if project in names:
            raise ValueError(f"Multiple wheels for {project}.")
        names.add(project)
        digest = check_wheel(path, project, version, release_data(project, str(version)))
        print(f"Matched PyPI size and SHA-256 for {path.name}", flush=True)
        locked.append(f"{project}=={version} --hash=sha256:{digest}")
    if not locked:
        raise ValueError("No runtime wheels were downloaded.")
    args.locked_requirements.write_text("\n".join(locked) + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
