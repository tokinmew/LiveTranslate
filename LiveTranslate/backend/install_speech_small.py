"""Install only the existing pinned Whisper Small model through checked setup."""
import hashlib
from pathlib import Path
import subprocess
import sys


def install(root):
    root = Path(root).resolve()
    expected = {"install.py": "b0188fe186f778666bc4333c180a88fe471daa809227cd1c66a62c4d96180f6f",
                "scan.ps1": "91e74a878f18d40334c9026a58492abdc3e690d72699bef7a7ca475412c04bd9"}
    for name, digest in expected.items():
        path = root / "quality" / name
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("The checked speech setup files are missing or changed. Restore the full application package.")
    return subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(root / "quality/install.py"), "--pack", "small"], cwd=root).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(install(Path(__file__).resolve().parents[1]))
    except (OSError, ValueError, KeyboardInterrupt) as error:
        print("Small speech model setup stopped:", error, file=sys.stderr, flush=True)
        raise SystemExit(1)
