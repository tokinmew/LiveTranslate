"""Private JSON-lines worker. No capture or model downloads at startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import math
from collections import OrderedDict
from contextlib import contextmanager, ExitStack, nullcontext
from dataclasses import dataclass, field

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("CT2_VERBOSE", "0")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

from audio_engine import AudioEngine
from screen_engine import ScreenCaptureUnavailable, ScreenEngine
from text_engine import TextEngine
from language_routes import with_source_options
from language_catalog import NLLB_TAGS
from multilingual_text import model_files_present
from profiles import get_profile, profile_status, screen_languages, speech_language
from checked_model_setup import CheckedModelSetup, CHECKED_TEXT_CODES, CHECKED_OCR_CODES
from foreign_text import PRIORITY, foreign_segments, script
validate_screen_region = ScreenEngine.validate_region
REPLY_TARGETS = list(dict.fromkeys(("zt", "zh", "ja", "ko", *NLLB_TAGS)))


CAPTURE_COMMANDS = {"start_audio": "audio", "start_screen": "screen", "read_screen_once": "screen_once"}
# The optional conversational model has a 96-token output limit. The standard
# text engine already chunks long input and reassembles it without dropping the tail.
SHORT_KOREAN_TEXT = 64


@dataclass
class _ScreenRequest:
    ticket: int
    session_id: str
    request_id: object
    region: dict
    source: str
    language: str
    executable: str
    interval: float
    channel: str
    exclude_windows: tuple = ()
    available_sources: frozenset | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    tracked_boxes: tuple = ()


class _Cancelled(Exception):
    pass


class Worker:
    def __init__(self, data_dir: Path, send):
        self.send = send
        self.text = TextEngine(data_dir)
        self.audio = AudioEngine(data_dir, send)
        self.screen = ScreenEngine(data_dir)
        self.text_lock = threading.RLock()
        self.screen.accepts_source_line = self._accepts_source_line
        self.speech_translation_lock = threading.Lock()
        self.speech_translation_dir = Path(data_dir) / "speech-translation"
        self.speech_translator = None
        self.speech_translation_checked = False
        self.audio.translate_source = self._translate_speech_source
        self.closing = threading.Event()
        self.screen_stop = threading.Event()
        self.screen_thread = None
        self.control_lock = threading.RLock()
        self.audio_ticket = 0
        self.screen_ticket = 0
        self.screen_once_ticket = 0
        self.sessions = {"audio": "", "screen": "", "screen_once": ""}
        self.screen_once_stop = threading.Event()
        self.screen_once_thread = None
        self.screen_condition = threading.Condition(self.control_lock)
        self.screen_desired = None
        self.screen_current = None
        self.screen_work_lock = threading.Lock()
        self.checked_setup = CheckedModelSetup(
            Path(data_dir).absolute().parent, Path(data_dir).absolute(),
            self._setup_status, self.closing)
        # One heavy setup/text job at a time; bound pending button clicks.
        self.jobs = queue.Queue(maxsize=8)
        self.job_thread = threading.Thread(target=self._jobs, daemon=True)
        self.job_thread.start()

    def _jobs(self):
        while not self.closing.is_set():
            try:
                item = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.execute(item)
            except Exception as exc:
                self._failure(item, exc)

    def _ticket(self, channel):
        return getattr(self, {"audio": "audio_ticket", "screen": "screen_ticket", "screen_once": "screen_once_ticket"}[channel])

    def _setup_status(self, message):
        if not self.closing.is_set():
            self.send({"type": "status", "message": message})

    def _state(self, channel, session_id, state, message=""):
        self.send({"type": "capture_state", "channel": channel, "session_id": session_id,
                   "state": state, "message": message})

    def _failure(self, item, exc):
        if self.closing.is_set():
            return
        channel = CAPTURE_COMMANDS.get(item.get("command"))
        if channel:
            with self.control_lock:
                if self.closing.is_set() or item.get("_ticket") != self._ticket(channel):
                    return
                self._state(channel, item.get("session_id", ""), "error", str(exc))
        else:
            self.send({"type": "error", "id": item.get("id"), "message": str(exc)})

    def _remove_queued_capture(self, channel):
        with self.jobs.mutex:
            kept = [value for value in self.jobs.queue if CAPTURE_COMMANDS.get(value.get("command")) != channel]
            self.jobs.queue.clear()
            self.jobs.queue.extend(kept)
            self.jobs.not_full.notify_all()

    def dispatch(self, item):
        if not isinstance(item, dict):
            raise ValueError("Commands must be JSON objects.")
        item = dict(item)
        command = item.get("command")
        if command == "stop_audio":
            with self.control_lock:
                self.audio_ticket += 1
                self.audio.stop()
                self._remove_queued_capture("audio")
                self._state("audio", self.sessions["audio"], "stopped", "Audio stopped.")
            self.send({"type": "ok", "id": item.get("id"), "message": "Audio stopped."})
        elif command == "stop_screen":
            with self.control_lock:
                self.screen_ticket += 1
                self.screen_stop.set()
                if self.screen_desired:
                    self.screen_desired.stop.set()
                    self.screen_desired = None
                self._remove_queued_capture("screen")
                self._state("screen", self.sessions["screen"], "stopped", "Screen watching stopped.")
            self.send({"type": "ok", "id": item.get("id"), "message": "Screen translation stopped."})
        elif command == "cancel_read_screen_once":
            with self.control_lock:
                self.screen_once_ticket += 1
                self.screen_once_stop.set()
                self._remove_queued_capture("screen_once")
                self._state("screen_once", self.sessions["screen_once"], "stopped", "Screen read cancelled.")
            self.send({"type": "ok", "id": item.get("id"), "message": "Screen read cancelled."})
        elif command == "shutdown":
            self.close()
        else:
            with self.control_lock:
                if self.closing.is_set():
                    return
                channel = CAPTURE_COMMANDS.get(command)
                if channel:
                    session_id = item.get("session_id", "")
                    if not isinstance(session_id, str) or len(session_id) > 128:
                        raise ValueError("session_id must be a string of at most 128 characters.")
                    item["session_id"] = session_id
                    self.sessions[channel] = session_id
                    self._remove_queued_capture(channel)
                if command == "start_audio":
                    self.audio_ticket += 1
                    self.audio.stop()
                    item["_ticket"] = self.audio_ticket
                elif command == "start_screen":
                    self.screen_ticket += 1
                    self.screen_stop.set()
                    if self.screen_desired:
                        self.screen_desired.stop.set()
                    item["_ticket"] = self.screen_ticket
                elif command == "read_screen_once":
                    self.screen_once_ticket += 1
                    self.screen_once_stop.set()
                    item["_ticket"] = self.screen_once_ticket
                if channel:
                    self._state(channel, item["session_id"], "starting", "Preparing local translation...")
            try:
                self.jobs.put_nowait(item)
            except queue.Full:
                exc = RuntimeError("Several operations are already pending. Wait for the current operation to finish.")
                self._failure(item, exc)

    def execute(self, item):
        if self.closing.is_set():
            return
        command = item.get("command")
        reply = {"type": "ok", "id": item.get("id")}
        if command in CAPTURE_COMMANDS:
            reply.update(channel=CAPTURE_COMMANDS[command], session_id=str(item.get("session_id", "")))
        if command == "status":
            reply.update(type="status", **self.asset_status(str(item.get("tesseract_path", ""))))
        elif command == "devices":
            reply.update(type="devices", devices=self.audio.devices())
        elif command == "preview_screen":
            with self.screen_work_lock:
                reply.update(type="screen_preview", **self.screen.preview(
                    item.get("region", {"monitor": "primary"}), item.get("exclude_windows", ()),
                    language=str(item.get("ocr_language", "auto")), executable=str(item.get("tesseract_path", "")),
                    source=str(item.get("source", "auto"))))
        elif command == "catalog":
            from profiles import PROFILES
            languages = [{"code": p.code, "name": p.name} for p in PROFILES if p.code in CHECKED_TEXT_CODES]
            reply.update(type="catalog", languages=with_source_options(languages),
                         message="The starter set includes these four languages. The language picker shows all local translation options.")
        elif command == "install_language":
            if item.get("language") not in CHECKED_TEXT_CODES:
                raise ValueError("This checked edition downloads only Traditional Chinese, Simplified Chinese, Korean, and Japanese. Import a compatible local .argosmodel file for another language.")
            raise ValueError("Individual text downloads are disabled in the checked edition. Click Install all four to download and verify the complete reviewed set. No files were downloaded by this button.")
        elif command == "import_pack":
            with self.text_lock:
                self.text.import_pack(str(item["path"]))
            reply["message"] = "Local user-supplied text archive imported. It is separate from the reviewed download set."
        elif command == "download_speech":
            if item.get("model", "base") != "base":
                raise ValueError("Only the base speech model has a reviewed download in this edition. Small and medium downloads are disabled; no alternative source was used.")
            raise ValueError("Individual speech downloads are disabled in the checked edition. Click Install all four to download and verify the complete set, including base. No files were downloaded by this button.")
        elif command == "install_ocr":
            if item.get("language") not in CHECKED_OCR_CODES:
                raise ValueError("Reviewed OCR downloads are chi_tra, chi_sim, kor, jpn, and jpn_vert. Other OCR downloads are disabled; an existing local OCR installation can still be selected.")
            raise ValueError("Individual OCR downloads are disabled in the checked edition. Click Install all four to download and verify the complete set. No files were downloaded by this button.")
        elif command == "install_all_profiles":
            self._install_checked_models()
            reply.update(message="All four reviewed language profiles are installed.", **self.asset_status())
        elif command == "install_profile":
            profile = get_profile(str(item.get("language", "")))
            self.install_profile(profile.code)
        elif command == "practice_reply":
            reply.update(type="practice_reply", **self._practice_reply(item))
        elif command == "translate":
            value = str(item.get("text", ""))
            if not value.strip():
                raise ValueError("Paste or type some text first.")
            if len(value) > 50000:
                raise ValueError("Translate at most 50,000 characters at a time.")
            source = str(item.get("source", "auto"))
            if source in PRIORITY or source == "en":
                result = self._translate_segments(foreign_segments(value, source), source)[1]
            else:
                with self.text_lock:
                    only_priority = source == "auto" and not model_files_present(self.speech_translation_dir) and all(
                        entry["code"] in PRIORITY for entry in self.text.installed())
                result = (self._translate_segments(foreign_segments(value, source), source)[1] if only_priority
                          else self._multilingual(value, source))
            reply.update(result)
            reply.update(type="result", kind="text")
        elif command == "start_audio":
            with self.control_lock:
                if self.closing.is_set() or item.get("_ticket") != self.audio_ticket:
                    return
                self.audio.start(int(item["device_id"]), str(item.get("model", "base")),
                                 speech_language(str(item.get("profile", item.get("language", "auto")))),
                                 int(item.get("chunk_seconds", 5)), int(item.get("threads", 4)),
                                 session_id=str(item.get("session_id", "")),
                                 korean_dialogue=str(item.get("korean_dialogue", "standard")))
            reply["message"] = "Audio starting."
        elif command == "start_screen":
            with self.control_lock:
                if self.closing.is_set() or item.get("_ticket") != self.screen_ticket:
                    return
            self.start_screen(item)
            reply["message"] = "Screen translation starting."
        elif command == "read_screen_once":
            with self.control_lock:
                if self.closing.is_set() or item.get("_ticket") != self.screen_once_ticket:
                    return
            self.read_screen_once(item)
            reply["message"] = "Reading the selected screen rectangle once."
        else:
            raise ValueError("Unknown command: " + str(command))
        if not self.closing.is_set():
            self.send(reply)

    def asset_status(self, executable=""):
        with self.text_lock:
            installed = self.text.installed()
        speech = self.audio.installed_models()
        source_map = getattr(self.screen, "ocr_sources", None)
        providers = source_map(executable) if source_map else {}
        ocr = sorted(providers) if source_map else self.screen.languages()
        executable_ready = self.screen.engine_ready(executable) if executable else self.screen.engine_ready()
        multilingual = model_files_present(self.speech_translation_dir)
        rows = profile_status([entry["code"] for entry in installed], ocr, speech, executable_ready,
                              multilingual_ready=multilingual)
        for row in rows:
            row["ocr_provider"] = providers.get(row["ocr_language"], "")
        return {"installed_languages": with_source_options(installed), "speech_models": speech, "ocr_languages": ocr,
                "ocr_engine_ready": executable_ready, "tesseract_path": executable,
                "download_policy": {"mode": "checked_four_language_set", "text_languages": sorted(CHECKED_TEXT_CODES),
                                    "ocr_languages": sorted(CHECKED_OCR_CODES), "speech_models": ["base"],
                                    "local_import_allowed": True},
                "multilingual_text_ready": multilingual,
                "reply_targets": REPLY_TARGETS,
                "profiles": rows}

    def _practice_reply(self, item):
        from reply_phrases import lookup
        target = item.get("target")
        if not isinstance(target, str) or target not in NLLB_TAGS:
            raise ValueError("Choose a reply language.")
        draft = item.get("text")
        if not isinstance(draft, str) or not draft.strip():
            raise ValueError("Type an English reply first.")
        draft = draft.strip()
        if len(draft) > 500:
            raise ValueError("Keep your reply to 500 characters or fewer.")
        starter = lookup(draft, target)
        if starter is not None:
            return {**starter, "target": target, "method": "phrasebook"}
        engine = self._quality_engine(None)
        if engine is None:
            raise ValueError("Free-form replies need the multilingual text pack. Open Settings, "
                             "Language files, Get more text languages, then restart the app. "
                             "You can practise built-in starter phrases in Chinese, Japanese, or Korean now.")
        with self._quality_access(None):
            translated = engine.translate_many([("en", draft)], target=target)[0]
        if not translated:
            raise ValueError("No translation was produced. Try rewording the reply.")
        if target in ("zh", "zt"):
            with self.text_lock:
                translated = self.text.convert_chinese(translated, target)
        # A missing local reading provider should never discard a usable translation.
        try:
            from reply_reading import pronunciation
            reading = pronunciation(translated, target)
        except Exception:
            reading = {"pronunciation": "", "pronunciation_scheme": "",
                       "pronunciation_note": "A pronunciation guide is unavailable for this reply."}
        return {"target": target, "text": translated, "method": "model", **reading}

    def _accepts_source_line(self, value, source):
        with self.text_lock:
            return self.text.accepts_source_line(value, source)

    def _multilingual(self, value, source, request=None):
        def priority(text, code):
            return self._translate_segments(foreign_segments(text, code), code, request)[1]
        def quality(texts, code):
            return self._quality_translation(texts, code, request)
        with self.text_lock:
            self._check_translation_request(request)
            return self.text.translate_multilingual(value, source, quality, priority)

    def install_profile(self, language):
        """A single-profile action must not silently fetch the complete set."""
        get_profile(language)
        raise ValueError("Single-profile downloads are disabled in the checked edition. Click Install all four to explicitly download and verify the complete reviewed set. No files were downloaded by Set up selected.")

    def _install_checked_models(self):
        """Only the explicit all-four action reaches the reviewed downloader."""
        if self.audio.running:
            raise RuntimeError("Turn listening Off before installing language files, then click Install all four again.")
        with self.control_lock:
            if ((self.screen_current is not None and not self.screen_current.stop.is_set())
                    or (self.screen_desired is not None and not self.screen_desired.stop.is_set())
                    or (self.screen_once_thread is not None and self.screen_once_thread.is_alive()
                        and not self.screen_once_stop.is_set())):
                raise RuntimeError("Turn screen watching Off and let any Read once finish before checking model files.")
        acquired = False
        try:
            while not self.screen_work_lock.acquire(timeout=0.1):
                if self.closing.is_set():
                    raise RuntimeError("Model setup was cancelled.")
            acquired = True
            with self.text_lock:
                self.checked_setup.install()
        except Exception as exc:
            raise RuntimeError("Checked model setup stopped: " + str(exc)
                               + " No alternative downloader was used. Verified completed files were kept; review model-test-results/model-file-checks.json and retry.") from exc
        finally:
            if acquired:
                self.screen_work_lock.release()
            if not self.closing.is_set():
                self.send({"type": "status", **self.asset_status()})

    def _screen_request(self, item, channel):
        region = item.get("region")
        region = validate_screen_region({"monitor": "primary"} if region is None else region)
        source = item.get("profile", item.get("source", "auto"))
        if not isinstance(source, str) or source == "en":
            raise ValueError("Choose a foreign screen language or Auto.")
        profile = None if source == "auto" else get_profile(source)
        if profile and not profile.ocr_language:
            raise ValueError("This language has no supported screen recognizer.")
        allowed_ocr = CHECKED_OCR_CODES if source == "auto" else set(profile.ocr_languages)
        excluded = item.get("exclude_windows", [])
        if (not isinstance(excluded, list) or len(excluded) > 16 or
                any(type(handle) is not int or not 0 < handle < 2**64 for handle in excluded)):
            raise ValueError("Invalid window exclusions for screen capture.")
        vertical = item.get("vertical", False)
        if not isinstance(vertical, bool):
            raise ValueError("The vertical-layout setting must be true or false.")
        ocr = item.get("ocr_language", "auto")
        if not isinstance(ocr, str):
            raise ValueError("Choose an OCR language or Auto.")
        if ocr not in ("", "auto"):
            # Older saved configurations can contain an English recognition
            # model. English is allowed only as internal OCR evidence.
            parts = [code for code in ocr.split("+") if code != "eng"]
            if any(code not in allowed_ocr for code in parts):
                raise ValueError("Choose an OCR language that matches the selected screen profile.")
            ocr = "+".join(parts) or "auto"
        _, language = screen_languages(source, ocr, vertical)
        source = profile.code if profile else source
        executable = self.screen.resolve_engine(str(item.get("tesseract_path", "")))
        if language in ("", "auto"):
            suggested = with_source_options([{"code": source}])[0]["ocr_language"] if source != "auto" else ""
            language = suggested or self.screen.auto_language(executable)
        # Validate the selected OCR names before taking even a one-shot image.
        selected_ocr = set(language.split("+")) - {"eng"}
        if not selected_ocr or not selected_ocr <= allowed_ocr:
            raise ValueError("Install a matching screen recognition language first.")
        if source not in PRIORITY and source != "auto" and not selected_ocr <= set(self.screen.languages(executable)):
            raise ValueError("The screen recognition files for " + profile.name + " are missing.")
        if source != "auto":
            with self.text_lock:
                installed = {entry["code"] for entry in self.text.installed()}
            if source not in installed and not (source in NLLB_TAGS and model_files_present(self.speech_translation_dir)):
                raise ValueError("Install local text translation files for " + profile.name + " before using screen captions.")
        interval = float(item.get("interval", 0.5))
        if not math.isfinite(interval) or not 0.5 <= interval <= 30:
            raise ValueError("The screen scan interval must be between 0.5 and 30 seconds.")
        available = None
        if source == "auto":
            with self.text_lock:
                available = frozenset(entry["code"] for entry in self.text.installed()) & PRIORITY
            if model_files_present(self.speech_translation_dir):
                available = PRIORITY
            if not available:
                raise ValueError("Install a Chinese, Korean or Japanese text model before starting screen captions.")
        return _ScreenRequest(item.get("_ticket", self._ticket(channel)), str(item.get("session_id", "")),
                              item.get("id"), region, source, language, executable, interval, channel,
                              tuple(dict.fromkeys(excluded)), available)

    def _screen_current_request(self, request):
        return not self.closing.is_set() and not request.stop.is_set() and request.ticket == self._ticket(request.channel)

    def _screen_event(self, request, event):
        with self.control_lock:
            if self._screen_current_request(request):
                self.send({**event, "channel": request.channel, "session_id": request.session_id})

    def _recognize_screen(self, request):
        # Native OCR can finish an already captured image after Off, but no new
        # screenshot or translation starts once that request is cancelled.
        while not self.screen_work_lock.acquire(timeout=0.05):
            if not self._screen_current_request(request):
                raise _Cancelled()
        try:
            if not self._screen_current_request(request):
                raise _Cancelled()
            options = {"exclude_windows": request.exclude_windows} if request.exclude_windows else {}
            watch = getattr(self.screen, "recognize_watched", None)
            if request.channel == "screen" and watch is not None:
                original = watch(request.region, request.language, request.executable, request.source,
                                 request.tracked_boxes, **options)
            else:
                if request.source not in PRIORITY and request.source != "auto":
                    options["source"] = request.source
                manual = getattr(self.screen, "manual_capture", None)
                with manual() if manual is not None else nullcontext():
                    original = self.screen.recognize(request.region, request.language, request.executable, **options)
        finally:
            self.screen_work_lock.release()
        if not self._screen_current_request(request):
            raise _Cancelled()
        return original

    def _translate_segments(self, segments, source, request=None, cache=None, placements=(), quality_korean=True,
                            glyph_covers=None):
        """Translate only approved source segments, grouped by model and kept in display order."""
        results = {}
        by_language = {}
        for key in dict.fromkeys(segments):
            self._check_translation_request(request)
            if cache is not None and key in cache:
                # Geometry and color-only updates do not need a model. They
                # can render even while another channel holds the text lock.
                cache.move_to_end(key)
                results[key] = cache[key]
                continue
            language, value = key
            if language == "han":
                with self.text_lock:
                    language = self.text.caption_han_language(value)
            if request and request.available_sources is not None and language not in request.available_sources:
                results[key] = {"text": "", "language": language}
                continue
            by_language.setdefault(language, []).append(key)
        for language, keys in by_language.items():
            for key in keys:
                self._check_translation_request(request)
                result = None
                if quality_korean and language == "ko" and len(key[1]) <= SHORT_KOREAN_TEXT:
                    try:
                        result = self._quality_translation([key[1]], language, request)
                        if result and any(script(char) for char in result["text"]):
                            result = None
                    except (OSError, RuntimeError, ValueError):
                        # A checked optional model can still fail on one input.
                        # The standard translator retains this entire segment.
                        pass
                if not result or not result["text"]:
                    with self.text_lock:
                        self._check_translation_request(request)
                        use_multilingual = language not in PRIORITY or (model_files_present(self.speech_translation_dir)
                            and not any(row["code"] == language for row in self.text.installed()))
                        result = (self._multilingual(key[1], language, request) if use_multilingual
                                  else self.text.translate(key[1], language))
                self._check_translation_request(request)
                results[key] = result
                if cache is not None and len(key[1]) <= 2048 and len(result["text"]) <= 4096:
                    cache[key] = result
                    if len(cache) > 512:
                        cache.popitem(last=False)
        visible = []
        for key in segments:
            output = results[key]["text"].strip()
            # A model occasionally echoes unrecognized CJK verbatim; that is
            # not an English caption. Keep numbers and mixed English names.
            if (output and not results[key].get("ignored") and
                    (results[key]["language"] not in PRIORITY or any(c.isascii() and c.isalpha() for c in output)
                     or not any(script(c) for c in output))):
                visible.append(key)
        if not visible:
            return "", {"text": "", "language": source, "ignored": True}
        languages = {results[key]["language"] for key in visible}
        caption = {"text": "\n".join(results[key]["text"].strip() for key in visible),
                   "language": next(iter(languages)) if len(languages) == 1 else "mul"}
        if placements:
            approved = set(visible)
            regions = []
            for key, box in placements:
                if box and key in approved:
                    left, top, right, bottom = box
                    regions.append({"text": results[key]["text"].strip(), "original": key[1],
                                    "left": left, "top": top, "width": right-left, "height": bottom-top})
            if regions:
                if glyph_covers:
                    from glyph_cover import attach_covers
                    attach_covers(regions, glyph_covers)
                caption["regions"] = regions
                missing = [results[key]["text"].strip() for key, box in placements if not box and key in approved]
                if missing:
                    caption["unlocated"] = "\n".join(dict.fromkeys(missing))
        return "\n".join(key[1] for key in visible), caption

    def _read_screen(self, request):
        original = self._recognize_screen(request)
        return self.translate_screen_text(original, request.source, request)

    def translate_screen_text(self, original, source, request=None):
        """Translate a recognized screen frame through the live caption filter."""
        placements = self._screen_layout(original, source, self._accepts_source_line)
        segments = tuple(dict.fromkeys(key for key, _ in placements))
        return self._translate_segments(segments, source, request, placements=placements,
                                        glyph_covers=getattr(original, "glyph_covers", None))

    def _check_translation_request(self, request):
        if request and not self._screen_current_request(request):
            raise _Cancelled()

    @contextmanager
    def _quality_access(self, request):
        if request is None:
            self.speech_translation_lock.acquire()
        else:
            while not self.speech_translation_lock.acquire(timeout=0.05):
                self._check_translation_request(request)
        try:
            self._check_translation_request(request)
            yield
        finally:
            self.speech_translation_lock.release()

    def _quality_engine(self, request):
        """Load a single optional model shared by speech, captions and reply drafts."""
        if not self.speech_translation_checked:
            with self._quality_access(request):
                if not self.speech_translation_checked:
                    from speech_translation import load_local_model
                    try:
                        self.speech_translator = load_local_model(self.speech_translation_dir)
                    except (OSError, ImportError, RuntimeError, ValueError) as exc:
                        self.speech_translation_checked = True
                        self.send({"type": "status", "message": "Using the standard translator. "
                                   "Run scripts/Install quality models.cmd to repair the optional files. " + str(exc)})
                    else:
                        # An external quality install may arrive after the app starts.
                        self.speech_translation_checked = self.speech_translator is not None
        return self.speech_translator

    def _quality_translation(self, texts, language, request=None):
        engine = self._quality_engine(request)
        if engine is None:
            return None
        if language == "zh":
            # Normalize recognized Mandarin before taking the model lock.
            with self.text_lock:
                texts = [self.text.convert_chinese(value, "zh") for value in texts]
        with self._quality_access(request):
            values = engine.translate_many([(language, value) for value in texts])
        self._check_translation_request(request)
        english = " ".join(value.strip() for value in values if value.strip())
        if not any(c.isascii() and c.isalpha() for c in english):
            english = ""
        return {"text": english, "language": language, "engine": engine.name}

    def _translate_speech_source(self, text, language):
        """Translate the recognized source script after Whisper's language gate."""
        source = "zt" if language == "zh" else language
        segments = foreign_segments(text, source)
        if not segments:
            return {"text": "", "language": language, "ignored": True}
        try:
            quality = self._quality_translation([value for _, value in segments], language)
        except (OSError, RuntimeError, ValueError):
            # One rejected utterance must not close every input device. The
            # next utterance can still use the already-loaded optional model.
            quality = None
        if quality is not None:
            return quality if quality["text"] else None
        with self.text_lock:
            installed = {row["code"] for row in self.text.installed()}
            if language == "zh":
                # Mandarin speech has no writing-system preference. Whisper can
                # alternate between scripts within and across utterances.
                # Normalize the transcript for a consistent text model.
                source = "zh" if "zh" in installed else "zt"
            if source not in installed:
                return None
            segments = [(source, self.text.convert_chinese(value, source) if language == "zh" else value)
                        for _, value in segments]
        try:
            _, result = self._translate_segments(segments, source, quality_korean=False)
        except (OSError, RuntimeError, ValueError):
            # The speech decoder can translate the approved time span directly.
            return None
        # Let the speech decoder retry when the standard text pack echoes the source.
        return None if result.get("ignored") else result

    @staticmethod
    def _screen_segments(original, source):
        # OCR sometimes reports the same label twice. Discard English rows and
        # normalize spaces before comparison so a changing English UI neither
        # triggers another model call nor refreshes the overlay.
        return tuple(dict.fromkeys((hint, " ".join(value.split()))
                                   for hint, value in foreign_segments(original, source)))

    @classmethod
    def _screen_layout(cls, original, source, accepts=None):
        from screen_geometry import positioned_segments
        regions = getattr(original, "regions", ())
        if not regions:
            if source not in PRIORITY and source != "auto" and accepts:
                return tuple(dict.fromkeys(((source, " ".join(line.split())), None) for line in original.splitlines()
                                           if line.strip() and accepts(line, source)))
            return tuple((key, None) for key in cls._screen_segments(original, source))
        return tuple(dict.fromkeys(placement for text, words in regions
                                   for placement in positioned_segments(text, words, source)))

    def start_screen(self, item):
        request = self._screen_request(item, "screen")
        with self.screen_condition:
            if self.closing.is_set() or request.ticket != self.screen_ticket:
                return
            self.screen_stop.set()
            if self.screen_desired:
                self.screen_desired.stop.set()
            self.screen_stop = request.stop
            self.screen_desired = request
            if not self.screen_thread or not self.screen_thread.is_alive():
                self.screen_thread = threading.Thread(target=self._watch_screen, name="screen-watch", daemon=True)
                self.screen_thread.start()
            self.screen_condition.notify_all()

    def _watch_screen(self):
        while not self.closing.is_set():
            with self.screen_condition:
                while self.screen_desired is None and not self.closing.is_set():
                    self.screen_condition.wait()
                if self.closing.is_set():
                    return
                request = self.screen_desired
                self.screen_desired = None
                self.screen_current = request
            failed = False
            resources = ExitStack()
            try:
                from screen_tracking import ScreenCaptionHistory, ScreenTracker
                tracker = ScreenTracker()
                caption_history = ScreenCaptionHistory()
                model_scope = getattr(self.screen, "watch_models", None)
                if model_scope:
                    resources.enter_context(model_scope())
                name = "Chinese, Korean and Japanese" if request.source == "auto" else get_profile(request.source).name
                self._screen_event(request, {"type": "capture_state", "state": "active", "message": "Watching for " + name + " text."})
                last = ()
                last_placements = ()
                last_covers = None
                last_held = set()
                last_result = {}
                displayed = False
                last_scan_status = None
                cache = OrderedDict()
                while self._screen_current_request(request):
                    scan_start = time.monotonic()
                    request.tracked_boxes = tuple(tracker.previous)
                    original = self._recognize_screen(request)
                    samples = getattr(original, "screen_samples", {})
                    placements, held = tracker.placements(self._screen_layout(original, request.source, self._accepts_source_line), samples)
                    segments = tuple(dict.fromkeys(key for key, _ in placements))
                    covers = getattr(original, "glyph_covers", None)
                    if placements != last_placements or (placements and covers != last_covers) or held.keys() != last_held:
                        filtered, result = self._translate_segments(segments, request.source, request, cache, placements,
                                                                    glyph_covers=covers)
                        tracker.accept(placements, result, samples, held)
                        if result["text"]:
                            fresh_caption = caption_history.observe(segments, result["text"], time.monotonic())
                            if not displayed or result != last_result or segments != last:
                                self._screen_event(request, {"type": "screen", "original": filtered,
                                                    "layout_only": not fresh_caption, **result})
                            displayed = True
                        elif displayed:
                            self._screen_event(request, {"type": "screen_clear"})
                            displayed = False
                        last = segments
                        last_placements = placements
                        last_covers = covers
                        last_result = result
                        last_held = set(held)
                    else:
                        tracker.accept(placements, last_result, samples, held)
                        if displayed:
                            caption_history.observe(last, last_result.get("text", ""), time.monotonic())
                    scan_status = ("Text recognized and translated." if displayed else
                                   "Text recognized, but no translation accepted. Check the selected language and language files." if placements else
                                   "Scanning. No supported foreign text confirmed. Preview captured view to check the source and text size.")
                    capture_info = getattr(original, "capture_info", {})
                    covered = capture_info.get("masked_percent", 0) if isinstance(capture_info, dict) else 0
                    if not displayed and covered > 0:
                        scan_status = ("No confirmed foreign text. LiveTranslate covers " + str(round(covered)) +
                                       "% of this capture; minimize the dashboard or choose Application window.")
                    if scan_status != last_scan_status:
                        self._screen_event(request, {"type": "capture_state", "state": "active", "sampled": True, "message": scan_status})
                        last_scan_status = scan_status
                    elapsed = time.monotonic() - scan_start
                    # The requested interval is start-to-start. An expensive
                    # frame still gives the display/CPU a breather, and an Off
                    # request interrupts the wait immediately.
                    rest = min(request.interval, max(0.04, min(.20, elapsed / 10)))
                    request.stop.wait(max(rest, request.interval - elapsed))
            except _Cancelled:
                pass
            except Exception as exc:
                failed = True
                self._screen_event(request, {"type": "capture_state", "state": "error",
                                             "retryable": isinstance(exc, ScreenCaptureUnavailable),
                                             "message": "Screen watching stopped: " + str(exc)})
            finally:
                resources.close()
                if not failed:
                    self._screen_event(request, {"type": "capture_state", "state": "stopped", "message": "Screen watching stopped."})
                request.stop.set()
                with self.control_lock:
                    if self.screen_current is request:
                        self.screen_current = None

    def read_screen_once(self, item):
        request = self._screen_request(item, "screen_once")
        with self.control_lock:
            if self.closing.is_set() or request.ticket != self.screen_once_ticket:
                return
            previous = self.screen_once_thread
            self.screen_once_stop.set()
            self.screen_once_stop = request.stop

        def run():
            failed = False
            try:
                # Only the newest pending read survives a rapid repeat click.
                while previous and previous.is_alive():
                    if not self._screen_current_request(request):
                        return
                    previous.join(timeout=0.05)
                if not self._screen_current_request(request):
                    return
                self._screen_event(request, {"type": "capture_state", "state": "active", "message": "Reading the selected rectangle once."})
                original, result = self._read_screen(request)
                self._screen_event(request, {"type": "screen_once", "id": request.request_id, "original": original, **result})
            except _Cancelled:
                pass
            except Exception as exc:
                failed = True
                self._screen_event(request, {"type": "capture_state", "state": "error", "message": "Screen read failed: " + str(exc)})
            finally:
                if not failed:
                    self._screen_event(request, {"type": "capture_state", "state": "stopped", "message": "Screen read complete."})
                request.stop.set()

        self.screen_once_thread = threading.Thread(target=run, name="screen-read-once", daemon=True)
        self.screen_once_thread.start()

    def close(self):
        with self.control_lock:
            self.closing.set()
            self.audio_ticket += 1
            self.screen_ticket += 1
            self.screen_once_ticket += 1
            self.screen_stop.set()
            self.screen_once_stop.set()
            if self.screen_desired:
                self.screen_desired.stop.set()
            self.screen_condition.notify_all()
            getattr(self.audio, "close", self.audio.stop)()
        # Remove starts/downloads still waiting behind a long operation.
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Third-party prints must not corrupt JSON replies.
    output_lock = threading.Lock()

    def send(event):
        with output_lock:
            protocol.write(json.dumps(event, ensure_ascii=False) + "\n")
            protocol.flush()

    # Initialize numerical native libraries on the Windows process main thread.
    # A cold import from the first capture thread can block while the main
    # thread is parked inside a redirected stdin readline.
    try:
        import numpy
        from scipy import ndimage
        from scipy.signal import resample_poly
    except (ImportError, OSError) as exc:
        send({"type": "error", "message": "The numerical runtime could not load. Run scripts/Setup.cmd to repair it. " + str(exc)})
        return 1
    worker = Worker(Path(__file__).resolve().parent.parent / "data", send)
    try:
        while not worker.closing.is_set():
            line = sys.stdin.readline(1_000_001)
            if not line:
                break
            try:
                if len(line) > 1_000_000:
                    # Drain a malformed oversized command without parsing fragments.
                    while line and not line.endswith("\n"):
                        line = sys.stdin.readline(1_000_001)
                    raise ValueError("Command is too large.")
                worker.dispatch(json.loads(line))
            except Exception as exc:
                send({"type": "error", "message": str(exc)})
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
