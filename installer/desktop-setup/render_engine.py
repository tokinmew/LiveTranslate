"""Generate the graphical setup's engine, file inventory and compiled resource pins."""
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_kit import read_package, render


def prepare(portable, launcher, output, version):
    pin, manifest = read_package(portable, version)
    launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
    script = render(pin, manifest, version, launcher_hash)
    (output / "Setup.ps1").write_bytes(script)
    (output / "files.json").write_bytes(manifest)
    constants = {
        "ScriptHash": hashlib.sha256(script).hexdigest(),
        "ManifestHash": hashlib.sha256(manifest).hexdigest(),
        "LauncherHash": launcher_hash,
        "PortableHash": pin,
    }
    lines = [f'internal const string {key} = "{value}";' for key,value in constants.items()]
    text = "namespace LiveTranslate.Setup { internal static class GeneratedPins {\n" + "\n".join(lines) + "\n} }\n"
    (output / "GeneratedPins.cs").write_text(text, "ascii")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
