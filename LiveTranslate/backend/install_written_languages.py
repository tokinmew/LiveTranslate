"""Install the reviewed multilingual text pack and three app-local Latin OCR models."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from extra_ocr_models import install as install_extra_ocr


def install(root, offline=False):
    folder = root / "quality"
    expected = {"install.py": "b0188fe186f778666bc4333c180a88fe471daa809227cd1c66a62c4d96180f6f",
                "scan.ps1": "91e74a878f18d40334c9026a58492abdc3e690d72699bef7a7ca475412c04bd9"}
    for name, digest in expected.items():
        path = folder / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("The checked quality setup files are missing or changed. Extract the full portable ZIP.")
    args = [sys.executable, "-I", "-B", "-X", "utf8", str(folder / "install.py"), "--pack", "nllb"]
    if offline:
        args.append("--offline")
    result = subprocess.run(args, cwd=root).returncode
    if result:
        return result
    return install_extra_ocr(root, offline=offline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="verify an installed or staged pack")
    parser.add_argument("--pause", action="store_true", help="keep the setup window open to read the result")
    args = parser.parse_args()
    print("Multilingual written translation for personal, noncommercial use, plus German, Italian and Spanish OCR.", flush=True)
    try:
        result = install(Path(__file__).resolve().parents[1], args.offline)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        print("Setup stopped.", error, file=sys.stderr, flush=True)
        result = 1
    if args.pause and sys.stdin.isatty():
        try:
            input("Press Enter to close.")
        except (KeyboardInterrupt, EOFError):
            pass
    raise SystemExit(result)
