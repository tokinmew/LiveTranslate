"""Opt-in Windows WASAPI capture and local Whisper speech translation.

Models download only through download_model(). Audio is retained in bounded RAM
buffers, never written to a recording file. Importing this module captures nothing.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import queue
import shutil
import stat
import threading
import time
from typing import Callable
import uuid
from dataclasses import dataclass, field
# The ONNX runtime reads this flag during native initialization.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
from audio_chunks import CapturedPhrase, PendingPhrases, PhraseBuffer
from audio_diagnostics import SignalMonitor
from audio_devices import (DEFAULT_PLAYBACK, DEFAULT_PLAYBACK_AND_MIC, capture_routes,
                           input_devices, windows_default_routes)
from speech_decode import SPOKEN_LANGUAGES, downmix, mono_16k, speech_captions
from multilingual_speech import CJK_SPEECH
from speech_memory import SpeechCaptionMemory

MODELS = ("tiny", "base", "small", "medium", "large-v3")
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")


def missing_model_files(folder: Path):
    def available(name):
        try:
            entry = (folder / name).stat()
        except OSError:
            return False
        return stat.S_ISREG(entry.st_mode) and entry.st_size > 0
    missing = [name for name in MODEL_FILES if not available(name)]
    # Older CTranslate2 packs use the text vocabulary; newer converters can
    # use vocabulary.json. A tokenizer alone cannot initialize Whisper.
    if not any(available(name) for name in ("vocabulary.txt", "vocabulary.json")):
        missing.append("vocabulary.txt or vocabulary.json")
    return missing


@dataclass
class _Session:
    generation: int
    device_id: int
    model: str
    language: str
    chunk_seconds: int
    threads: int
    session_id: str
    stop: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    capture_done: threading.Event = field(default_factory=threading.Event)
    chunks: PendingPhrases = field(init=False)
    overrun: threading.Event = field(default_factory=threading.Event)
    capture_error: Exception | None = None
    selected_identity: tuple | None = None
    route_epoch: int = 0
    pump: threading.Thread | None = None
    stopped_reported: bool = False
    failed: bool = False
    korean_dialogue: str = "standard"
    next_lag_notice: float = 0
    next_drop_notice: float = 0
    signals: SignalMonitor = field(default_factory=SignalMonitor)

    def __post_init__(self):
        self.chunks = PendingPhrases(self.chunk_seconds, keep_dialogue=self.korean_dialogue == "nvidia")


def put_latest(target: queue.Queue, item) -> bool:
    """Bound latency: discard oldest pending chunk when a consumer is behind."""
    dropped = False
    while True:
        try:
            target.put_nowait(item)
            return dropped
        except queue.Full:
            try:
                target.get_nowait()
                dropped = True
            except queue.Empty:
                pass


def validate_model(name: str) -> str:
    if name not in MODELS:
        raise ValueError("Choose a multilingual model: " + ", ".join(MODELS) + ". English-only and turbo models cannot translate speech.")
    return name


def pcm_to_mono(data: bytes, channels: int, sample_rate: int):
    """Decode interleaved signed 16-bit PCM and resample to Whisper's 16 kHz."""
    import numpy as np
    if not 1 <= channels <= 32 or not 8000 <= sample_rate <= 384000:
        raise ValueError("Invalid recording format.")
    aligned = len(data) - len(data) % (channels * 2)
    samples = np.frombuffer(data, dtype="<i2", count=aligned // 2)
    if not len(samples):
        return np.empty(0, dtype=np.float32)
    return mono_16k(downmix(samples.astype(np.float32).reshape(-1, channels) / 32768.0), sample_rate)


def _waveform_digest(samples):
    """Match a copied waveform across buses with different gain or zero padding."""
    import numpy as np
    active = np.flatnonzero(samples)
    if not len(active):
        return None
    waveform = samples[active[0]:active[-1] + 1]
    peak = float(np.max(np.abs(waveform)))
    if not np.isfinite(peak) or len(waveform) < 320:
        return None
    normalized = np.rint(waveform * (32767.0 / peak)).astype("<i2")
    return hashlib.blake2s(normalized, digest_size=16).digest()


def _mirrored_capture(recent, phrase, waveform, language):
    route = (phrase.source, phrase.endpoint)
    signature = (waveform, language)
    for stamp, previous, routes in reversed(recent):
        if previous == signature and route not in routes and abs(phrase.captured - stamp) <= .35:
            routes.add(route)
            return True
    recent.append((phrase.captured, signature, {route}))
    return False


def _distinct_routes(captions, phrase, samples, recent, cancelled):
    waveform = None
    mirrored_languages = {}
    for caption in captions:
        if cancelled():
            return
        if waveform is None:
            waveform = _waveform_digest(samples)
        if waveform is not None:
            # The same recording on a second audio bus may be transcribed
            # into different words or a different number of clauses.
            language = caption["language"]
            if language not in mirrored_languages:
                mirrored_languages[language] = _mirrored_capture(recent, phrase, waveform, language)
            if mirrored_languages[language]:
                continue
        yield caption


class AudioEngine:
    def __init__(self, data_dir: Path, emit: Callable[[dict], None]):
        self.root = Path(data_dir) / "speech"
        self.root.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self._generation = 0
        self._cached_model = None
        self._cached_key = None
        self._condition = threading.Condition(self._lock)
        self._desired = None
        self._current = None
        self._closed = False
        self._device_identities = {}
        self.translate_source = None

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._desired or (self._current and not self._current.stop.is_set()))

    def devices(self) -> list[dict]:
        import pyaudiowpatch as pa
        audio = pa.PyAudio()
        try:
            wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
            inputs = input_devices(audio, int(wasapi["index"]))
            inputs.sort(key=lambda item: (not item.get("isLoopbackDevice"), str(item["name"]).casefold()))
            result = []
            defaults = windows_default_routes(True)
            try:
                capture_routes(audio, DEFAULT_PLAYBACK, defaults)
            except (LookupError, OSError, ValueError, RuntimeError):
                pass
            else:
                result.append({"id": DEFAULT_PLAYBACK, "kind": "pc", "name": "Default playback and calls"})
                try:
                    capture_routes(audio, DEFAULT_PLAYBACK_AND_MIC, defaults)
                except (LookupError, OSError, ValueError, RuntimeError):
                    pass
                else:
                    result.append({"id": DEFAULT_PLAYBACK_AND_MIC, "kind": "both", "name": "Windows defaults"})
            for item in inputs:
                result.append({"id": int(item["index"]), "name": str(item["name"]),
                               "kind": "pc" if item.get("isLoopbackDevice") else "microphone"})
            with self._lock:
                self._device_identities = {r["id"]: (r["name"], r["kind"]) for r in result if r["id"] >= 0}
            return result
        finally:
            audio.terminate()

    def installed_models(self) -> list[str]:
        return [name for name in MODELS if not missing_model_files(self.root / name)]

    def download_model(self, name: str) -> str:
        validate_model(name)
        from faster_whisper.utils import download_model
        destination = self.root / name
        if name in self.installed_models():
            return str(destination)
        staging = self.root / (".download-" + uuid.uuid4().hex)
        try:
            self.emit({"type": "status", "message": "Downloading speech model " + name + ". This is a one-time setup."})
            download_model(name, output_dir=str(staging), local_files_only=False)
            if missing_model_files(staging):
                raise RuntimeError("Speech model download is incomplete; retry its download.")
            if destination.exists():
                shutil.rmtree(destination)
            staging.rename(destination)
            return str(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _event(self, generation: int, event: dict) -> None:
        # Retained for callers/tests of the previous generation gate.
        with self._lock:
            if generation == self._generation and not self._stop.is_set():
                self.emit(event)

    def _session_event(self, session: _Session, event: dict, route_epoch=None) -> None:
        with self._lock:
            if (session.generation == self._generation and not session.stop.is_set()
                    and (route_epoch is None or session.route_epoch == route_epoch)):
                self.emit({**event, "channel": "audio", "session_id": session.session_id})

    def _stopped(self, session: _Session) -> None:
        with self._lock:
            if not session.stopped_reported and not session.failed:
                session.stopped_reported = True
                self.emit({"type": "capture_state", "channel": "audio", "session_id": session.session_id,
                           "state": "stopped", "message": "Audio stopped."})

    def _dialogue_queue_notice(self, session, now, epoch, dropped):
        with self._lock:
            if session.generation != self._generation or session.stop.is_set() or epoch != session.route_epoch:
                return
            if dropped:
                if now < session.next_drop_notice:
                    return
                session.next_drop_notice = now + 10
                message = "Translation is catching up. Older audio was skipped."
            else:
                if now < session.next_lag_notice:
                    return
                message = "Live captions are delayed. Earlier audio is still queued."
            session.next_lag_notice = now + 10
            self._session_event(session, {"type": "status", "message": message}, epoch)

    def _check_dialogue_queue(self, session, now, epoch):
        # Runs on the capture monitor, outside the device callback. A slow native
        # decode cannot postpone the age limit or the first visible delay notice.
        with self._lock:
            if session.generation != self._generation or session.stop.is_set() or epoch != session.route_epoch:
                return
            expired, oldest = session.chunks.expire_and_oldest(now - PendingPhrases.DIALOGUE_MAX_WAIT)
            if expired or session.overrun.is_set():
                session.overrun.clear()
                self._dialogue_queue_notice(session, now, epoch, True)
            elif oldest is not None and now - oldest >= 6:
                self._dialogue_queue_notice(session, now, epoch, False)

    def start(self, device_id: int, model: str = "base", language: str = "auto", chunk_seconds: int = 5, threads: int = 4, session_id: str = "", korean_dialogue: str = "standard") -> None:
        validate_model(model)
        if korean_dialogue not in ("standard", "nvidia"):
            raise ValueError("Choose standard or nvidia for Korean dialogue.")
        if model not in self.installed_models():
            if model == "base":
                raise RuntimeError("Download the base speech model using Install all four or the checked model setup first.")
            raise RuntimeError(f"The {model} speech model is missing. Choose base or select a model already installed on this PC.")
        if language != "auto" and language not in SPOKEN_LANGUAGES:
            raise ValueError("Choose Auto or a supported foreign speech language.")
        if language == "yue" and model != "large-v3":
            raise ValueError("Cantonese speech requires the Large-v3 multilingual Whisper model.")
        chunk_seconds = max(3, min(12, int(chunk_seconds)))
        threads = max(1, min(8, int(threads), os.cpu_count() or 1))
        with self._condition:
            if self._closed:
                raise RuntimeError("The audio engine has been closed.")
            if self._desired is not None:
                self._desired.stop.set()
                self._stopped(self._desired)
            if self._current is not None:
                self._current.stop.set()
                self._current.chunks.close()
            self._generation += 1
            session = _Session(self._generation, int(device_id), model, language, chunk_seconds, threads, str(session_id),
                               korean_dialogue=korean_dialogue)
            session.selected_identity = self._device_identities.get(session.device_id)
            self._stop = session.stop
            self._desired = session
            self.emit({"type": "capture_state", "channel": "audio", "session_id": session.session_id,
                       "state": "starting", "message": "Preparing local audio translation..."})
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="local-audio-translation", daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._stop.set()
            self._generation += 1
            if self._desired is not None:
                self._desired.stop.set()
                self._stopped(self._desired)
                self._desired = None
            if self._current is not None:
                self._current.stop.set()
                self._current.chunks.close()
                if self._current.pump is None:
                    self._stopped(self._current)
            self._condition.notify_all()
        # The capture pump owns the stream and closes on its own thread. It is
        # never blocked behind model inference or the model-loading thread.

    def close(self):
        """Conclude the controller after any already-running native call ends."""
        with self._condition:
            self._closed = True
            self.stop()
            self._condition.notify_all()

    def _load_model(self, name: str, threads: int, use_cjk=True):
        from faster_whisper import WhisperModel
        key = (name, threads)
        if self._cached_key != key:
            self._cached_model = None
            self._cached_key = None
            model = WhisperModel(str(self.root / name), device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1, local_files_only=True)
            self._cached_model = model
            self._cached_key = key
        model = self._cached_model
        if use_cjk and not hasattr(model, "sensevoice"):
            model.sensevoice = None
            secondary = self.root / "sensevoice"
            if secondary.is_dir():
                try:
                    from sensevoice_engine import SenseVoice
                    model.sensevoice = SenseVoice(secondary, threads)
                except (OSError, ImportError, RuntimeError, ValueError) as exc:
                    self.emit({"type": "status", "message": "Using Whisper for speech recognition. "
                               "Run scripts/Install quality models.cmd to repair the optional files. " + str(exc)})
        return self._cached_model

    @contextmanager
    def session_model(self, session: _Session):
        """Acquire one controller session's real decoder and release its optional GPU model."""
        use_cjk = session.language == "auto" or session.language in CJK_SPEECH
        model = self._load_model(session.model, session.threads, use_cjk)
        tokenizer = getattr(model, "hf_tokenizer", None)
        if (session.language != "auto" and tokenizer is not None
                and tokenizer.token_to_id(f"<|{session.language}|>") is None):
            raise ValueError(f"The installed {session.model} speech model has no token for {session.language}.")
        dialogue = None
        if session.korean_dialogue == "nvidia" and session.language in ("auto", "ko"):
            def report(state, message):
                self._session_event(session, {"type": "status", "topic": "korean_dialogue", "state": state, "message": message})
            if session.model == "small" and getattr(model, "sensevoice", None) is not None:
                from dialogue_acceleration import LazyKoreanDialogue
                dialogue = LazyKoreanDialogue(self.root.parent, session.threads, report, session.stop.is_set)
                model.dialogue_model = dialogue
            else:
                report("fallback", "Korean dialogue uses the installed Small and SenseVoice models. Continuing standard speech translation.")
        try:
            yield model
        finally:
            if dialogue is not None:
                dialogue.close()
                del model.dialogue_model

    def _run(self) -> None:
        # A single controller serializes native model work. Rapid reconfiguration
        # replaces one pending request instead of spawning overlapping decoders.
        while True:
            with self._condition:
                while self._desired is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    self._cached_model = None
                    self._cached_key = None
                    return
                session = self._desired
                self._desired = None
                self._current = session
            try:
                self._session_event(session, {"type": "status", "message": "Loading local speech model..."})
                if session.stop.is_set():
                    continue
                session.pump = threading.Thread(target=self._capture, args=(session,), name="audio-capture", daemon=True)
                try:
                    session.pump.start()
                except Exception:
                    session.pump = None
                    raise
                # Collect the first words while native model initialization runs.
                # The pump owns the stream and can still close it promptly on Off.
                with self.session_model(session) as model:
                    while not session.ready.wait(0.05):
                        if session.stop.is_set():
                            break
                    if session.capture_error:
                        raise session.capture_error
                    if not session.stop.is_set():
                        self._translate(session, model)
            except Exception as exc:
                with self._lock:
                    if session.generation == self._generation and not session.stop.is_set():
                        session.failed = True
                        message = "Audio: " + str(exc)
                        self._session_event(session, {"type": "capture_state", "state": "error", "message": message})
            finally:
                session.stop.set()
                if session.pump is not None:
                    session.capture_done.wait()
                session.chunks.close()
                self._stopped(session)
                with self._lock:
                    if self._current is session:
                        self._current = None

    def _capture(self, session: _Session) -> None:
        """Capture/close on a thread independent of loading and inference."""
        try:
            import pyaudiowpatch as pa
            while not session.stop.is_set():
                if not self._capture_devices(session, pa):
                    break
                with self._lock:
                    session.route_epoch += 1
                    session.signals.reset()
                    if session.korean_dialogue == "nvidia":
                        session.overrun.clear()
                        session.next_lag_notice = session.next_drop_notice = 0
                        session.chunks.clear(epoch=session.route_epoch)
                    else:
                        session.chunks.clear()
                self._session_event(session, {"type": "capture_state", "state": "starting",
                                             "message": "Windows changed the default audio routing. Reconnecting..."})
        except Exception as exc:
            session.capture_error = exc
            with self._lock:
                if session.generation == self._generation and not session.stop.is_set():
                    session.failed = True
                    self._session_event(session, {"type": "capture_state", "state": "error", "message": "Audio: " + str(exc)})
            session.stop.set()
        finally:
            session.ready.set()
            session.capture_done.set()
            if session.stop.is_set():
                self._stopped(session)

    def _capture_devices(self, session, pa):
        """Open all requested routes before starting any. Close every stream on failure."""
        audio = pa.PyAudio()
        opened = []
        default_mode = session.device_id in (DEFAULT_PLAYBACK, DEFAULT_PLAYBACK_AND_MIC)
        include_mic = session.device_id == DEFAULT_PLAYBACK_AND_MIC
        try:
            defaults = windows_default_routes(include_mic) if default_mode else ()
            routes = capture_routes(audio, session.device_id, defaults)
            if session.selected_identity and (routes[0].info.get("name"), routes[0].source) != session.selected_identity:
                raise RuntimeError("The selected audio device changed. Refresh sources and choose the intended output or microphone.")
            for route in routes:
                if session.stop.is_set():
                    return False
                opened.append(self._open_device(session, pa, audio, route))
            if session.stop.is_set():
                return False
            for stream, _ in opened:
                if session.stop.is_set():
                    return False
                stream.start_stream()
            names = [str(route.info.get("name", route.source)).removesuffix(" [Loopback]") for route in routes]
            self._session_event(session, {"type": "capture_state", "state": "active",
                                         "message": "Listening to " + " + ".join(names) + "."})
            session.ready.set()
            next_check = time.monotonic() + 3
            next_queue_check = 0.0
            while not session.stop.wait(0.05):
                now = time.monotonic()
                if default_mode and now >= next_check:
                    new = windows_default_routes(include_mic)
                    if new and new != defaults:
                        return True
                    next_check = now + 3
                for stream, phrases in opened:
                    if not stream.is_active():
                        if default_mode and windows_default_routes(include_mic) != defaults:
                            return True
                        raise RuntimeError("The audio device stopped. Refresh audio sources and start again.")
                    phrases.flush_idle(now)
                for diagnostic in session.signals.snapshots(now):
                    self._session_event(session, diagnostic, session.route_epoch)
                if session.korean_dialogue == "nvidia" and now >= next_queue_check:
                    self._check_dialogue_queue(session, now, session.route_epoch)
                    next_queue_check = now + 0.25
            return False
        finally:
            for stream, _ in opened:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            try:
                audio.terminate()
            except Exception:
                pass

    @staticmethod
    def _open_device(session, pa, audio, route):
        import numpy as np
        info = route.info
        index = int(info["index"])
        native_channels = int(info.get("maxInputChannels", 0))
        native_rate = round(float(info.get("defaultSampleRate", 0)))
        if not 1 <= native_channels <= 32 or not 8000 <= native_rate <= 384000:
            raise ValueError("The audio endpoint reported an unsupported channel count or sample rate.")
        # Prefer the endpoint's native format. Some virtual drivers expose a
        # multichannel mix format but only open a shared stereo or mono stream.
        rates = tuple(dict.fromkeys((native_rate, 48000, 44100, 16000)))
        counts = tuple(dict.fromkeys((native_channels, min(2, native_channels), 1)))
        formats = (pa.paInt16,) if not hasattr(pa, "paFloat32") else (pa.paInt16, pa.paFloat32)
        last_error = None
        epoch = session.route_epoch
        for rate in rates:
            for channels in counts:
                for fmt in formats:
                    if session.stop.is_set():
                        raise RuntimeError("Audio setup stopped.")
                    def submit(payload, rate=rate, channels=channels):
                        if not session.stop.is_set() and epoch == session.route_epoch:
                            item = CapturedPhrase(payload, rate, channels, route.source, index, time.monotonic(), epoch)
                            if session.chunks.push(item):
                                session.overrun.set()

                    phrases = PhraseBuffer(rate, channels, session.chunk_seconds, submit)
                    session.signals.register(route.source, index, channels, rate)

                    def callback(data, frame_count, time_info, status, phrases=phrases, fmt=fmt):
                        if session.stop.is_set() or epoch != session.route_epoch:
                            return (None, pa.paComplete)
                        if data:
                            if fmt != pa.paInt16:
                                floats = np.frombuffer(data, dtype="<f4")
                                data = (np.clip(floats, -1, 32767/32768) * 32768).astype("<i2").tobytes()
                            session.signals.observe(route.source, index, data, channels)
                            phrases.add(data)
                        return (None, pa.paContinue)

                    try:
                        stream = audio.open(format=fmt, channels=channels, rate=rate, input=True,
                                            input_device_index=index, frames_per_buffer=0,
                                            stream_callback=callback, start=False)
                        return stream, phrases
                    except OSError as exc:
                        last_error = exc
                        # PortAudio: unsupported rate/channels/format/buffer, or
                        # the WASAPI host rejecting one otherwise valid format.
                        code = exc.errno if exc.errno is not None else (exc.args[0] if exc.args else None)
                        if code not in (-9999, -9998, -9997, -9994, -9991, -9990):
                            raise
        name = info.get("name", "selected endpoint")
        raise RuntimeError(f"Could not open {name} using its advertised audio formats. {last_error}") from last_error

    def _translate(self, session: _Session, model) -> None:
        # Keep simultaneous render/mic sources separate. Their sample clocks,
        # channel layouts and language can all differ.
        recent = deque(maxlen=24)
        memory = SpeechCaptionMemory(self.translate_source)
        current_epoch = session.route_epoch
        next_warning = 0.0
        decoder_ready = time.monotonic()
        keep_dialogue = session.korean_dialogue == "nvidia"
        while not session.stop.is_set():
            if session.capture_error:
                raise session.capture_error
            phrase = session.chunks.next(0.1)
            if phrase is None:
                continue
            if phrase.epoch != session.route_epoch:
                continue
            if phrase.epoch != current_epoch:
                recent.clear()
                memory = SpeechCaptionMemory(self.translate_source)
                current_epoch = phrase.epoch
            now = time.monotonic()
            # First-use model load time should not age out a queued greeting.
            if keep_dialogue:
                old = now - phrase.captured > PendingPhrases.DIALOGUE_MAX_WAIT
            else:
                old = now - max(phrase.captured, decoder_ready) > max(session.chunk_seconds * 2, 8)
            if session.overrun.is_set() or old:
                session.overrun.clear()
                if keep_dialogue:
                    self._dialogue_queue_notice(session, now, phrase.epoch, True)
                elif now >= next_warning:
                    self._session_event(session, {"type": "status", "message": "Translation is catching up. Older audio was skipped."})
                    next_warning = now + 10
                if old:
                    continue
            samples = pcm_to_mono(phrase.payload, phrase.channels, phrase.rate)
            def cancelled():
                return session.stop.is_set() or phrase.epoch != session.route_epoch
            diagnostic = {}
            captions = speech_captions(model, samples, session.language, memory, cancelled, diagnostics=diagnostic)
            if session.device_id in (DEFAULT_PLAYBACK, DEFAULT_PLAYBACK_AND_MIC):
                captions = _distinct_routes(captions, phrase, samples, recent, cancelled)
            delivered = 0
            last_caption = None
            for caption in memory.stabilize(phrase, captions, cancelled):
                self._session_event(session, {"type": "audio", **caption, "source": phrase.source,
                                             "seconds": round(time.monotonic() - now, 2)}, phrase.epoch)
                delivered += 1
                last_caption = caption
            if delivered:
                diagnostic.update(decision="accepted", message="Translated " + str(delivered) + " voice caption(s).")
                language = last_caption.get("language", "")
                if language != diagnostic.get("language"):
                    diagnostic.pop("probability", None)
                diagnostic.update(language=language,
                                  recognized=" ".join(last_caption.get("original", "").split())[:240])
            elif diagnostic.get("decision") == "accepted":
                diagnostic.update(decision="duplicate_filtered", message="A matching voice caption was already delivered.")
            self._session_event(session, {"type": "audio_diagnostic", "stage": "recognition", **diagnostic,
                                         "source": phrase.source, "endpoint": phrase.endpoint,
                                         "captions": delivered}, phrase.epoch)
