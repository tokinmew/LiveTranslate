"""Bounded, pause-aware PCM capture and fair scheduling of independent sources."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class CapturedPhrase:
    payload: bytes
    rate: int
    channels: int
    source: str
    endpoint: int
    captured: float
    epoch: int = 0


class PendingPhrases:
    """A busy game output must not evict the entire call or microphone stream."""
    MAX_PHRASES = 12
    DIALOGUE_PHRASES = 32
    DIALOGUE_AUDIO_SECONDS = 30
    DIALOGUE_MAX_WAIT = 45

    def __init__(self, chunk_seconds=5, *, keep_dialogue=False):
        self._condition = threading.Condition()
        self._queues = {}
        self._closed = False
        # Two maximum-length chunks, as before, can instead hold several
        # short replies while the model is warming up or another route decodes.
        self._audio_seconds = self.DIALOGUE_AUDIO_SECONDS if keep_dialogue else 2 * (chunk_seconds + min(0.88, chunk_seconds / 4))
        self._max_phrases = self.DIALOGUE_PHRASES if keep_dialogue else self.MAX_PHRASES
        self._keep_dialogue = keep_dialogue
        self._epoch = 0

    def push(self, item):
        with self._condition:
            if self._closed or (self._keep_dialogue and item.epoch != self._epoch):
                return False
            byte_limit = int(self._audio_seconds * item.rate * item.channels * 2)
            if self._keep_dialogue and len(item.payload) > byte_limit:
                return True
            queue = self._queues.setdefault((item.source, item.endpoint), deque())
            queue.append(item)
            size = sum(len(phrase.payload) for phrase in queue)
            dropped = False
            while len(queue) > 1 and (len(queue) > self._max_phrases or size > byte_limit):
                size -= len(queue.popleft().payload)
                dropped = True
            self._condition.notify()
            return dropped

    def expire_and_oldest(self, cutoff):
        """Prune stale queued PCM and return the oldest remaining capture time."""
        with self._condition:
            expired = False
            oldest = None
            for queue in self._queues.values():
                while queue and queue[0].captured < cutoff:
                    queue.popleft()
                    expired = True
                if queue and (oldest is None or queue[0].captured < oldest):
                    oldest = queue[0].captured
            return expired, oldest

    def next(self, timeout):
        with self._condition:
            if not self._condition.wait_for(lambda: self._closed or any(self._queues.values()), timeout) or self._closed:
                return None
            queue = min((q for q in self._queues.values() if q), key=lambda q: q[0].captured)
            return queue.popleft()

    def clear(self, epoch=None):
        with self._condition:
            self._queues.clear()
            if epoch is not None:
                self._epoch = epoch

    def close(self):
        with self._condition:
            self._closed = True
            self._queues.clear()
            self._condition.notify_all()


class PhraseBuffer:
    """Emit at a pause, a short idle loopback, or the configured maximum duration.

    Fixed-size energy frames keep boundaries independent of the driver's packet
    size. Recognition performs a separate model-based voice activity check.
    """
    FRAME_MS = 20
    # Keep soft initial consonants while a louder part of the word opens the gate.
    PREROLL = 12
    SILENCE = 18
    MIN_VOICE_MS = 60
    MIN_RMS = 6
    IDLE_SECONDS = 0.38

    def __init__(self, rate, channels, seconds, submit):
        import numpy as np
        self._np = np
        self._channels = channels
        self._bytes_per_second = rate * channels * 2
        self._packet_seconds = 0.0
        self._frame_bytes = max(1, round(rate * self.FRAME_MS / 1000)) * channels * 2
        self._voice_bytes = max(1, round(rate * self.MIN_VOICE_MS / 1000)) * channels * 2
        self._target = max(1, int(seconds * 1000 / self.FRAME_MS))
        # Allow an ongoing final word to finish just beyond the target. A
        # brief pause after the target releases a phrase immediately.
        self._max = self._target + min(44, self._target // 4)
        self._submit = submit
        self._lock = threading.Lock()
        self._partial = b""
        self._before = deque(maxlen=self.PREROLL)
        self._frames = []
        self._levels = []
        self._silent = 0
        self._last = None

    def _emit(self, cut=None):
        cut = len(self._frames) if cut is None else cut
        voiced_bytes = sum(len(frame) for frame, level in zip(self._frames[:cut], self._levels[:cut])
                           if level >= self.MIN_RMS)
        if voiced_bytes >= self._voice_bytes:
            self._submit(b"".join(self._frames[:cut]))
        self._frames = self._frames[cut:]
        self._levels = self._levels[cut:]
        self._silent = 0

    def _level(self, frame):
        np = self._np
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32).reshape(-1, self._channels)
        # One quiet centre channel can carry all the dialogue in a 7.1 stream.
        return float(np.sqrt(np.max(np.mean(samples * samples, axis=0))))

    def _add_frame(self, frame):
        level = self._level(frame)
        voiced = level >= self.MIN_RMS
        if not self._frames and not voiced:
            self._before.append(frame)
            return
        if not self._frames and self._before:
            self._frames.extend(self._before)
            self._levels.extend([0] * len(self._before))
            self._before.clear()
        self._frames.append(frame)
        self._levels.append(level)
        self._silent = 0 if voiced else self._silent + 1
        if self._silent >= self.SILENCE or (len(self._frames) >= self._target and self._silent >= 6):
            self._emit()
        elif len(self._frames) >= self._max:
            # Prefer a nearby trough to slicing through a loud syllable.
            start_at = max(1, self._max - 24)
            trough = min(range(start_at, len(self._levels)), key=self._levels.__getitem__)
            low = self._levels[trough] < max(self._levels) * 0.15
            self._emit(trough + 1 if low else len(self._frames))

    def _finish_idle(self, now, incoming_seconds=0.0):
        if self._last is None:
            return
        elapsed = now - self._last
        if elapsed < self.IDLE_SECONDS:
            # Loopback can deliver several silent frames, then stop delivering
            # packets. This is one pause. Reserve one driver packet for sound
            # still in flight, including an unusually large incoming callback.
            allowance = max(self._packet_seconds, incoming_seconds, self.FRAME_MS / 1000)
            recorded_silence = self._silent * self.FRAME_MS / 1000
            if not self._silent or recorded_silence + elapsed - allowance < self.IDLE_SECONDS:
                return
            # A short voiced partial frame after silence starts a new syllable.
            # Keep the original idle deadline until that tail can be decoded.
            aligned = len(self._partial) // (self._channels * 2) * (self._channels * 2)
            if aligned and self._level(self._partial[:aligned]) >= self.MIN_RMS:
                return
        # Count the actual tail as speech. A final WASAPI packet may contain
        # the last audible part of a syllable and no subsequent silence packet.
        alignment = self._channels * 2
        end = len(self._partial) // alignment * alignment
        if end:
            self._add_frame(self._partial[:end])
        if self._frames:
            self._emit()
        self._partial = b""
        self._before.clear()
        self._last = None

    def add(self, payload, now=None):
        if not payload:
            return
        with self._lock:
            now = time.monotonic() if now is None else now
            packet_seconds = len(payload) / self._bytes_per_second
            self._finish_idle(now, packet_seconds)
            self._last = now
            self._packet_seconds = packet_seconds
            data = self._partial + payload
            end = len(data) // self._frame_bytes * self._frame_bytes
            self._partial = data[end:]
            for start in range(0, end, self._frame_bytes):
                self._add_frame(data[start:start+self._frame_bytes])

    def flush_idle(self, now=None):
        # Some WASAPI loopback drivers stop delivering callbacks when playback
        # stops. Finish the last short utterance even without a silence packet.
        with self._lock:
            current = time.monotonic() if now is None else now
            self._finish_idle(current)
