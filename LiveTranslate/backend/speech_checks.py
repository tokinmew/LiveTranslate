"""Real, offline speech-model checks without capturing a device or downloading.

Optional owner-supplied fixtures live only in DATA/speech-test-fixtures. Put a
manifest.json there, for example {"ja": {"file": "ja.wav"}}, plus the named PCM
WAV. Speak the exact fixture phrase in PHRASES below. Relative WAV paths must
stay in that directory. Fixture text/expected output cannot be overridden.

The app includes four digest-checked test recordings. An optional fixed-phrase
Windows speech generator also supports earlier installations. Chinese, Japanese
and Korean have separate translation tests. English checks zero captions in
Auto and under an explicit foreign selection.
"""
from __future__ import annotations

from contextlib import ExitStack

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

os.environ["ORT_DISABLE_TELEMETRY"] = "1"


PHRASES = {
    "zh": "\u706b\u8eca\u4e94\u9ede\u51fa\u767c\u3002",
    "ja": "\u96fb\u8eca\u306f\u4e94\u6642\u306b\u51fa\u767a\u3057\u307e\u3059\u3002",
    "ko": "\uae30\ucc28\ub294 \ub2e4\uc12f \uc2dc\uc5d0 \ucd9c\ubc1c\ud569\ub2c8\ub2e4.",
    "en": "The train leaves at five.",
}

def _row(kind, language, status, detail, **extra):
    return {"kind": kind, "language": language, "status": status, "detail": detail, **extra}


def _tts_request(request: dict):
    if os.name != "nt":
        raise RuntimeError("Windows local speech synthesis is unavailable on this operating system.")
    helper = Path(__file__).resolve().parent.parent / "fixture-tools" / "SpeechFixture.exe"
    if not helper.is_file():
        raise RuntimeError("The optional bundled SpeechFixture.exe tool is missing. Supply the documented owner-recorded WAV fixtures to test foreign-language speech.")
    if request["mode"] == "voices":
        args = [str(helper), "--list"]
    elif request["mode"] == "speak":
        args = [str(helper), "--speak", str(request["voice"]), str(request["language"]), str(request["output"])]
    else:
        raise ValueError("Unknown speech fixture operation.")
    result = subprocess.run(args, shell=False,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Local TTS failed.").strip()[-2000:])
    return json.loads(result.stdout.lstrip("\ufeff")) if request["mode"] == "voices" else None


def _fixture_manifest(data_dir: Path) -> dict[str, Path]:
    directory = data_dir / "speech-test-fixtures"
    if directory.is_symlink():
        raise ValueError("The speech fixture directory must be a normal folder inside the selected data directory.")
    root = directory.resolve()
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return {}
    if manifest.resolve().parent != root:
        raise ValueError("The speech fixture manifest must stay inside speech-test-fixtures.")
    if manifest.stat().st_size > 16384:
        raise ValueError("The optional speech fixture manifest exceeds 16 KiB.")
    value = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or any(code not in PHRASES for code in value):
        raise ValueError("The speech fixture manifest may contain only zh, ja, ko and en entries.")
    paths = {}
    for code, entry in value.items():
        if not isinstance(entry, dict) or set(entry) != {"file"} or not isinstance(entry["file"], str):
            raise ValueError("Each speech fixture entry must contain only a relative file name.")
        relative = Path(entry["file"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".wav":
            raise ValueError("Speech fixtures must be relative WAV files in speech-test-fixtures.")
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise ValueError("A speech fixture is missing or outside speech-test-fixtures.")
        if candidate.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("A speech fixture exceeds 16 MiB.")
        paths[code] = candidate
    return paths


def _valid_wav(path: Path):
    with wave.open(str(path), "rb") as audio:
        if audio.getcomptype() != "NONE" or audio.getsampwidth() not in (1, 2, 3, 4):
            raise ValueError("Use an uncompressed PCM WAV fixture.")
        duration = audio.getnframes() / audio.getframerate()
        if not 0.3 <= duration <= 60:
            raise ValueError("Speech fixture duration must be between 0.3 and 60 seconds.")
        return round(duration, 2)


def _matches_train_phrase(text: str) -> bool:
    """Require all three facts; unrelated or generic hallucinations fail."""
    words = set(re.findall(r"[a-z]+|\d+", text.lower()))
    departure = any(word.startswith(("leav", "depart", "start")) for word in words)
    conflicting = words & {"not", "never", "no", "hundred", "fifty", "fifteen", "minutes", "minute",
                           "one", "two", "three", "four", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                           "thirteen", "fourteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "sixty"}
    conflicting = conflicting or any(word.isdigit() and word not in {"5", "05", "00"} for word in words)
    conflicting = conflicting or bool(re.search(r"n['\u2019]t\b", text.lower()))
    return "train" in words and bool(words & {"five", "5", "05"}) and departure and not conflicting


def _matches_recognition_phrase(text: str) -> bool:
    words = set(re.findall(r"[a-z]+", text.casefold()))
    test = bool(words & {"test", "tests", "testing", "tested", "trial"})
    subject = bool(words & {"speech", "voice", "voices", "vocal", "audio", "recognition", "recognize", "recognizing"})
    return test and subject and not words.intersection({"not", "never", "no"}) and not re.search(r"n['’]t\b", text, re.I)


def _bundled_fixture(folder: Path, code: str):
    row = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))[code]
    name = code + ".wav"
    path = folder / name
    if (code not in PHRASES or row.get("file") != name or path.is_symlink() or
            path.resolve().parent != folder.resolve() or not path.is_file()):
        raise ValueError("A bundled speech fixture is missing or has an unexpected name.")
    size = row.get("bytes")
    if not isinstance(size, int) or not 1 <= size <= 16 * 1024 * 1024 or path.stat().st_size != size:
        raise ValueError("Bundled speech fixture size differs from its manifest.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != row.get("sha256"):
        raise ValueError("Bundled speech fixture SHA-256 differs from its manifest.")
    return path


def check_speech(data_dir: Path) -> list[dict]:
    data_dir = Path(data_dir)
    model_dir = data_dir / "speech" / "base"
    from audio_engine import missing_model_files
    missing = missing_model_files(model_dir)
    if missing:
        return [_row("speech_model", "multilingual", "missing",
                     "The base speech model is incomplete. Install the shared base model before running real speech checks.",
                     model="base", missing_files=missing)]
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=max(1, min(4, os.cpu_count() or 1)),
                             num_workers=1, local_files_only=True)
    except Exception as exc:
        return [_row("speech_model", "multilingual", "failed", "The local base model could not load: " + str(exc), model="base")]
    try:
        fixtures = _fixture_manifest(data_dir)
    except Exception as exc:
        return [_row("speech_fixture", "multilingual", "failed", str(exc))]
    rows = []
    from speech_decode import fixture_samples, speech_captions
    from worker import Worker
    bundled = Path(__file__).resolve().parents[1] / "fixture-tools" / "audio"
    has_bundle = (bundled / "manifest.json").is_file()
    with ExitStack() as stack:
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="live-translate-speech-check-")))
        worker = Worker(data_dir, lambda _: None)
        stack.callback(worker.close)
        voices, voice_error = [], ""
        if not has_bundle and not all(code in fixtures for code in ("zh", "ja", "ko", "en")):
            try:
                voices = _tts_request({"mode": "voices"})
                if not isinstance(voices, list):
                    raise ValueError("Local TTS returned an unexpected voice list.")
            except Exception as exc:
                voice_error = str(exc)

        def fixture_for(code):
            if code in fixtures:
                return fixtures[code], "owner-supplied PCM WAV", "", "train"
            if has_bundle:
                return _bundled_fixture(bundled, code), "bundled verified PCM WAV", "", "recognition"
            voice = next((item for item in voices if isinstance(item, dict) and str(item.get("culture", "")).lower().startswith(code + "-")), None)
            if voice is None:
                return None, "", voice_error or ("No installed Windows " + code + " TTS voice and no owner-supplied fixture."), "train"
            output = scratch / (code + ".wav")
            _tts_request({"mode": "speak", "voice": voice["name"], "language": code, "output": str(output)})
            return output, "Windows local TTS: " + voice["name"], "", "train"

        for code in ("zh", "ja", "ko"):
            try:
                audio, origin, reason, case = fixture_for(code)
                if audio is None:
                    rows.append(_row("speech_translation", code, "skipped", reason + " This foreign-language translation has not been tested.", fixture_phrase=PHRASES[code]))
                    continue
                duration = _valid_wav(audio)
                captions = list(speech_captions(model, fixture_samples(audio), "auto", worker._translate_speech_source))
                text = " ".join(c["text"] for c in captions)
                if case == "train":
                    passed = _matches_train_phrase(text)
                    expected = "The train leaves at five."
                    fixture = PHRASES[code]
                else:
                    passed = _matches_recognition_phrase(text)
                    expected = "A greeting and a speech recognition test, followed by a comment on fine weather."
                    fixture = audio.name
                passed = passed and all(c["language"] == code for c in captions)
                rows.append(_row("speech_translation", code, "passed" if passed else "failed",
                                 "Speech language and main phrase matched." if passed else "The detected source or principal meaning failed the phrase check.",
                                 fixture=origin, fixture_input=fixture, expected_meaning=expected, english=text, duration_seconds=duration,
                                 original=" ".join(c["original"] for c in captions),
                                 source_mode="automatic language identification", model="base"))
            except Exception as exc:
                rows.append(_row("speech_translation", code, "failed", str(exc), fixture_phrase=PHRASES[code]))
        try:
            audio, origin, reason, case = fixture_for("en")
            if audio is None:
                rows.append(_row("speech_english_filter", "en", "skipped", reason))
            else:
                duration = _valid_wav(audio)
                samples = fixture_samples(audio)
                for selection in ("auto","ja"):
                    detected = []
                    def record_language(code, probability):
                        detected.append({"language":code, "confidence":round(probability,3)})
                    captions = list(speech_captions(model, samples, selection, worker._translate_speech_source,
                                                    observe_language=record_language))
                    passed = not captions and any(item["language"] == "en" for item in detected)
                    rows.append(_row("speech_english_filter", "en", "passed" if passed else "failed",
                                     "An identified English voice must produce zero captions.",
                                     fixture=origin, fixture_input=audio.name if case == "recognition" else PHRASES["en"],
                                     selection=selection, detected=detected, caption_count=len(captions),
                                     duration_seconds=duration, model="base"))
        except Exception as exc:
            rows.append(_row("speech_english_filter", "en", "failed", str(exc)))
    return rows
