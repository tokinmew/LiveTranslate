"""Test the legacy wire names and 0.6.8 physical rollback paths without external processes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def run(directory):
    backend = Path(__file__).resolve().parents[1] / "LiveTranslate/backend"
    sys.path.insert(0, str(backend))
    import app_updates
    import github_releases
    import update_install
    sha = lambda value: hashlib.sha256(value).hexdigest()
    with tempfile.TemporaryDirectory(dir=directory, prefix="u68-") as tmp:
        tmp = Path(tmp)
        root = tmp / "organized"
        for group in ("docs","scripts","ui","backend"):
            (root / group).mkdir(parents=True)
        (root / "scripts/Prepare-Offline.ps1").write_text("synthetic")
        (root / "LiveTranslate.exe").write_bytes(b"older")
        (root / "docs/README.md").write_bytes(b"older readme")
        (root / "ui/Program.cs").write_bytes(b"older source")
        docs = ["README.md", "START-HERE.txt", "VALIDATION.md"]
        records = [{"path": name, "text": name, "sha256": sha(name.encode())} for name in ["ui/Program.cs", *docs]]
        raw = json.dumps({"version": "0.6.9", "files": records}).encode()
        manifest = {"schema": 1, "product": "LiveTranslate", "version": "0.6.9", "package": "LiveTranslate-0.6.9.json",
                    "size": len(raw), "sha256": sha(raw)}
        asset = github_releases.Asset("repos/tokinmew/LiveTranslate/releases/assets/2", len(raw), sha(raw))

        def build(root, stage, files, version):
            (stage / "LiveTranslate.exe").write_bytes(b"new executable")
        with patch.object(app_updates, "_file_version", return_value=(0, 6, 8, 0)), \
                patch.object(app_updates, "_build_and_scan", build), \
                patch.object(app_updates, "_manifest", return_value=(manifest, asset)), \
                patch.object(github_releases, "public_read", return_value=raw):
            key = app_updates.prepare_update(root, "0.6.8", "0.6.9", sha(raw))["stage"]
        state = root / update_install._STATE
        _, receipt = update_install._receipt(state, key)
        assert all("docs/" + name in receipt["files"] and name not in receipt["files"] for name in docs)

        commit = update_install._commit_file
        def interrupted(root, stage, name, digest):
            if name == "docs/VALIDATION.md":
                raise RuntimeError("simulated interrupted organized update")
            return commit(root, stage, name, digest)
        with patch.object(update_install, "_commit_file", interrupted):
            try:
                update_install.apply_stage(root, key)
            except RuntimeError as err:
                assert str(err) == "simulated interrupted organized update"
            else:
                raise AssertionError("The simulated failure was not reached")
        assert (root / "docs/README.md").read_bytes() == b"older readme"
        assert (root / "LiveTranslate.exe").read_bytes() == b"older"
        assert not (root / "docs/START-HERE.txt").exists()
        update_install.apply_stage(root,key)
        assert (root / "LiveTranslate.exe").read_bytes() == b"new executable"
        assert all((root / "docs" / name).read_text() == name and not (root / name).exists() for name in docs)
        assert not (state / "transaction.json").exists()
        print("PASS legacy wire names, organized staged paths, rollback, retry and zero top-level documents.")


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
