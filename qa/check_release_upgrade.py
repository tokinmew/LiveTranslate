"""Exercise a signed candidate with the old installed updater in a disposable copy.

Only GitHub transport is replaced with local candidate bytes. Signature/package
verification, the old compiler/Defender gate and installation/rollback are real.
The installed application, runtime, models and preferences are never modified.
"""
from contextlib import contextmanager, ExitStack
from hashlib import sha256
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch


MODULES = ("app_updates", "github_releases", "release_signature", "update_install")
DOCS = {"README.md", "VALIDATION.md", "START-HERE.txt"}


def digest(content):
    return sha256(content).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def emit(event, **details):
    print(json.dumps({"event": event, **details}, sort_keys=True), flush=True)


def old_files(app):
    paths = [app / "LiveTranslate.exe", app / "ui/LiveTranslate.ico"]
    paths.extend(sorted((app / "ui").glob("*.cs")))
    paths.extend(sorted((app / "backend").glob("*.py")))
    require(len(paths) > 4, "Expected an installed app with UI/backend sources.")
    for path in paths:
        require(path.is_file() and not path.is_symlink(), "Missing or linked old source: " + str(path))
    return {path.relative_to(app).as_posix(): path.read_bytes() for path in paths}


@contextmanager
def old_modules(directory):
    previous = {name: sys.modules.pop(name, None) for name in MODULES}
    previous_path = list(sys.path)
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(directory))
    try:
        loaded = [importlib.import_module(name) for name in MODULES]
        require(all(Path(module.__file__).resolve().is_relative_to(directory.resolve()) for module in loaded),
                "A test imported current updater code instead of the old client.")
        yield loaded
    finally:
        for name in MODULES:
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]
        sys.path[:] = previous_path
        sys.dont_write_bytecode = previous_bytecode


def tree_hashes(root):
    return {path.relative_to(root).as_posix(): digest(path.read_bytes())
            for path in root.rglob("*") if path.is_file()
            and path.relative_to(root).parts[0] != ".livetranslate-update"}


def exercise(feed, old_app, version, work):
    require(os.name == "nt", "Windows is required for the real compiler, Defender and file-version checks.")
    feed, old_app, work = feed.resolve(strict=True), old_app.resolve(strict=True), work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    originals = old_files(old_app)
    originals_hashes = {name: digest(data) for name, data in originals.items()}
    manifest_bytes = (feed / "latest.json").read_bytes()
    require(len(manifest_bytes) <= 64 * 1024, "Candidate manifest exceeds the old client's limit.")
    manifest = json.loads(manifest_bytes)
    require(manifest.get("version") == version, "Candidate version differs from --version.")
    require(manifest.get("package") == "LiveTranslate-" + version + ".json", "Unexpected candidate package filename.")
    payload = (feed / manifest["package"]).read_bytes()
    api_calls, process_calls = [], []

    # Never clone installed runtime/model/preferences. These known bytes detect
    # changes to the corresponding directories during a real update transaction.
    sentinels = {
        "runtime/qa-preserve.bin": b"disposable runtime sentinel\x00\xff",
        "data/models/qa-preserve.model": b"disposable local model sentinel\x00\xff",
        "data/tessdata/qa-preserve.traineddata": b"disposable OCR model sentinel",
        "data/spoken-english.json": b'{"Audio":false,"Screen":true,"Voice":"qa-voice","Device":"qa-device"}\n',
        "data/app-update-source.txt": b"obsolete-local-source-must-remain-untouched\n",
        "scripts/Prepare-Offline.ps1": b"# Disposable organized-layout marker; never executed.\n",
        "docs/README.md": b"old disposable README\n",
    }

    with tempfile.TemporaryDirectory(prefix="release-upgrade-", dir=work) as temp:
        temporary = Path(temp).resolve()
        require(temporary.is_relative_to(work), "Disposable fixture escaped the selected work directory.")
        app = temporary / "app"
        backend = temporary / "old-client"
        backend.mkdir()
        for name, data in originals.items():
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if name.startswith("backend/"):
                (backend / Path(name).name).write_bytes(data)
        for name, data in sentinels.items():
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        before = tree_hashes(app)

        with old_modules(backend) as (updates, github, signature, installer), ExitStack() as stack:
            signature.verify_official_manifest("tokinmew/LiveTranslate", manifest)
            files = updates._check_package(payload, manifest)
            original_version = updates._file_version(app / "LiveTranslate.exe")
            old_version = ".".join(map(str, original_version[:3]))
            if original_version[3]:
                old_version += "." + str(original_version[3])
            require(updates._version(version) > original_version, "Candidate must be newer than the old installed app.")
            old_ui = {name for name in originals if name.startswith("ui/") and name.endswith(".cs")}
            incoming_ui = {name for name in files if name.startswith("ui/")}
            require("docs/VALIDATION.md" not in files and "VALIDATION.md" in files,
                    "Candidate must retain the old client's documented wire filenames.")

            def public_read(endpoint, accept, limit):
                api_calls.append(endpoint)
                base = "repos/tokinmew/LiveTranslate/releases/"
                require(endpoint.startswith(base), "Updater attempted an unexpected repository.")
                resource = endpoint[len(base):]
                if resource == "latest":
                    require(accept == "application/vnd.github+json", "Unexpected release metadata accept header.")
                    rows = []
                    for ident, name, body in ((1, "latest.json", manifest_bytes), (2, manifest["package"], payload)):
                        rows.append(dict(id=ident, name=name, state="uploaded", size=len(body), digest="sha256:"+digest(body)))
                    result = json.dumps(dict(tag_name="v"+version, draft=False, prerelease=False, assets=rows)).encode()
                else:
                    require(accept == "application/octet-stream", "Unexpected asset accept header.")
                    require(resource in {"assets/1", "assets/2"}, "Unexpected asset request.")
                    result = manifest_bytes if resource == "assets/1" else payload
                require(len(result) <= limit, "Fixture transport exceeded the real request limit.")
                return result

            real_run = subprocess.run

            def traced_run(command, **options):
                result = real_run(command, **options)
                process_calls.append({"program": Path(command[0]).name, "returncode": result.returncode})
                return result

            def no_network(*_args, **_kwargs):
                raise AssertionError("Unexpected Python network access during local signed-candidate test.")

            stack.enter_context(patch.object(github, "public_read", side_effect=public_read))
            stack.enter_context(patch.object(socket, "create_connection", side_effect=no_network))
            stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=no_network))
            stack.enter_context(patch.object(updates.subprocess, "run", side_effect=traced_run))
            offer = updates.check_update(old_version)
            require(offer["available"] and offer["version"] == version, "Old client did not offer the candidate.")
            require(not any(path.endswith("assets/2") for path in api_calls), "Checking downloaded the full package.")
            emit("candidate-validated", old_version=old_version, candidate=version, files=len(files),
                 package_sha256=digest(payload), original_signature_verified=True,
                 old_updater_sha256=digest(originals["backend/app_updates.py"]),
                 old_ui_files=len(old_ui), combined_ui_files=len(old_ui | incoming_ui))
            ready = updates.prepare_update(app, old_version, version, offer["sha256"])
            require(ready.get("ok") is True and tree_hashes(app) == before, "Preparing changed installed fixture files.")
            require(any(row["program"].lower() == "csc.exe" and row["returncode"] == 0 for row in process_calls),
                    "The real old compiler did not run successfully.")
            require(any(row["program"].lower() == "mpcmdrun.exe" and row["returncode"] == 0 for row in process_calls),
                    "The real old Defender scan did not run successfully.")
            emit("stage-ready", native_compile=True, defender_clean=True, installed_fixture_unchanged=True,
                 process_calls=process_calls)

            real_commit = installer._commit_file
            written = []

            class InjectedFailure(RuntimeError):
                pass

            def fail_mid_commit(root, stage, name, expected):
                if name == "docs/VALIDATION.md":
                    require(len(written) >= 2, "Failure injection did not occur after real writes.")
                    raise InjectedFailure("QA interrupted commit after real writes")
                real_commit(root, stage, name, expected)
                written.append(name)

            with patch.object(installer, "_commit_file", side_effect=fail_mid_commit):
                try:
                    installer.apply_stage(app, ready["stage"], restart=False)
                except InjectedFailure:
                    pass
                else:
                    raise AssertionError("Commit failure injection was not reached.")
            require(tree_hashes(app) == before, "Rollback failed to restore every old fixture file or remove new files.")
            state = app / installer._STATE
            require(not (state / "transaction.json").exists(), "Rollback left an active transaction journal.")
            require(updates._file_version(app / "LiveTranslate.exe") == original_version, "Rollback did not restore the old executable.")
            emit("rollback-verified", real_writes_before_interruption=len(written),
                 all_original_files_restored=True, new_files_removed=True, same_stage_retry=True)
            installer.apply_stage(app, ready["stage"], restart=False)
            require(updates._file_version(app / "LiveTranslate.exe") == updates._version(version), "Installed executable version differs.")
            for name, data in files.items():
                actual = "docs/"+name if name in DOCS else name
                require((app / actual).read_bytes() == data, "Installed source differs: " + actual)
            for name, data in sentinels.items():
                if name not in {"docs/README.md"}:
                    require((app / name).read_bytes() == data, "An update changed a retained sentinel: " + name)
            require(not (state / "transaction.json").exists(), "Successful retry left an active journal.")
            require(not updates.check_update(version)["available"], "An equal release was offered again.")
            parts = list(updates._version(version)[:3])
            parts[2] += 1
            next_patch = ".".join(map(str, parts))
            require(updates._version(next_patch) > updates._version(version), "Next patch does not compare newer.")
            require(not updates.check_update(next_patch)["available"], "A downgrade was offered to the next patch version.")
            for installed in (version, next_patch):
                try:
                    updates.prepare_update(app, installed, version, offer["sha256"])
                except ValueError as error:
                    require("newer" in str(error).lower(), "Equal/downgrade failed for the wrong reason.")
                else:
                    raise AssertionError("An equal or older release could be prepared.")
            retained_ui = old_ui-incoming_ui
            for name in retained_ui:
                require((app/name).read_bytes() == originals[name], "Old non-replaced UI source was lost: "+name)
            result = dict(old_version=old_version, installed_version=version, source_files=len(files),
                          package_sha256=digest(payload), original_signature_verified=True, native_compile=True,
                          defender_clean=True, rollback_verified=True, retry_verified=True,
                          preserved_runtime_model_settings_sentinels=True, retained_legacy_ui=sorted(retained_ui),
                          equal_offer=False, downgrade_offer=False, equal_install_blocked=True,
                          downgrade_install_blocked=True, next_patch_comparison=next_patch,
                          next_patch_signed_upgrade_tested=False, release_transport="local fixture of public GitHub API",
                          python_network_used=False, restart=False)

    require({name: digest(data) for name, data in old_files(old_app).items()} == originals_hashes,
            "The real old installation's source or executable bytes changed.")
    result["real_installed_files_unchanged"] = True
    emit("upgrade-verified", **result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True, help="Folder with original-key-signed latest.json and source package")
    parser.add_argument("--old-app", type=Path, required=True, help="Read-only installed app root containing LiveTranslate.exe/ui/backend")
    parser.add_argument("--version", required=True)
    parser.add_argument("--work", type=Path, default=Path(__file__).resolve().parents[3]/"work")
    args = parser.parse_args()
    exercise(args.feed, args.old_app, args.version, args.work)


if __name__ == "__main__":
    main()
