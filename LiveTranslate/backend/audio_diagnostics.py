"""Bounded, in-memory audio observations; no recording files or model inference."""
from __future__ import annotations

import math
import threading
import time


class SignalMonitor:
    """Measure the opened endpoint, including quiet channels and callback stalls.

    The device callback only updates three numeric observations. The capture
    monitor emits snapshots at a bounded rate outside the realtime callback.
    """
    INTERVAL = .5
    STALE_AFTER = 1.25

    def __init__(self):
        self._lock = threading.Lock()
        self._routes = {}
        self._next = 0.0

    def reset(self):
        with self._lock:
            self._routes.clear()
            self._next = 0.0

    def register(self, source, endpoint, channels, rate):
        with self._lock:
            self._routes[(source, endpoint)] = {"source": source, "endpoint": endpoint,
                "channels": channels, "sample_rate": rate, "rms": 0.0, "peak": 0.0,
                "last": None, "frames": 0}

    def observe(self, source, endpoint, payload, channels, now=None):
        import numpy as np
        aligned = len(payload) // (channels * 2) * (channels * 2)
        if not aligned:
            return
        raw = np.frombuffer(payload, dtype="<i2", count=aligned // 2).reshape(-1, channels)
        # Bounded RMS work even when a driver sends an unusually large packet.
        stride = max(1, (len(raw) + 4095) // 4096)
        measured = raw[::stride].astype(np.float64) / 32768.0
        rms = float(np.sqrt(np.max(np.mean(measured * measured, axis=0))))
        peak = max(abs(int(raw.min())), abs(int(raw.max()))) / 32768.0
        stamp = time.monotonic() if now is None else now
        with self._lock:
            item = self._routes.get((source, endpoint))
            if item is not None:
                item.update(rms=rms, peak=peak, last=stamp, frames=item["frames"] + len(raw))

    @staticmethod
    def _db(value):
        return round(max(-120.0, min(0.0, 20 * math.log10(value))), 1) if value > 0 else -120.0

    def snapshots(self, now=None):
        stamp = time.monotonic() if now is None else now
        with self._lock:
            if stamp < self._next:
                return []
            self._next = stamp + self.INTERVAL
            items = [dict(value) for value in self._routes.values()]
        output = []
        for item in items:
            received = item["last"] is not None and stamp - item["last"] <= self.STALE_AFTER
            rms, peak = (item["rms"], item["peak"]) if received else (0.0, 0.0)
            active = received and rms >= 6 / 32768
            source = "computer audio" if item["source"] == "pc" else "microphone"
            message = ("Signal received from " + source + "." if active else
                       "The " + source + " endpoint is sending silence." if received else
                       "No audio samples arriving from " + source + ". Check the selected playback device or microphone.")
            db = self._db(rms)
            output.append({"type": "audio_diagnostic", "stage": "signal", "source": item["source"],
                "endpoint": item["endpoint"], "channels": item["channels"], "sample_rate": item["sample_rate"],
                "rms_dbfs": db, "peak_dbfs": self._db(peak), "level": round(max(0.0, min(100.0, (db + 80) * 1.25))),
                "activity": bool(active), "samples_received": received, "clipping": peak >= .999,
                "message": message})
        return output
