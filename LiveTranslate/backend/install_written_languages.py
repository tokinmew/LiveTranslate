"""Install the reviewed multilingual text pack without the optional audio packs."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys


def install(root, offline=False):
    folder = root / "quality"
    expected = {"install.py": "b0188fe186f778666bc4333c180a88fe471daa809227cd1c66a62c4d96180f6f",
                "scan.ps1": "e770132c71e338a54167ff9a34a06f9261080010eee0af04ed767aa1e0bbccf3"}
    for name, digest in expected.items():
        path = folder / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("The checked quality setup files are missing or changed. Extract the full portable ZIP.")
    args = [sys.executable, "-I", "-B", "-X", "utf8", str(folder / "install.py"), "--pack", "nllb"]
    if offline:
        args.append("--offline")
    return subprocess.run(args, cwd=root).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="verify an installed or staged pack")
    parser.add_argument("--pause", action="store_true", help="keep the setup window open to read the result")
    args = parser.parse_args()
    print("Multilingual written translation for personal, noncommercial use.", flush=True)
    try:
        result = install(Path(__file__).resolve().parents[1], args.offline)
    except (OSError, ValueError, KeyboardInterrupt) as error:
        print("Setup stopped.", error, file=sys.stderr, flush=True)
        result = 1
    if args.pause and sys.stdin.isatty():
        try:
            input("Press Enter to close.")
        except (KeyboardInterrupt, EOFError):
            pass
    raise SystemExit(result)
