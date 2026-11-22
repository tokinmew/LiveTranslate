"""Recover an isolated word using time-aligned native speech context.

Call only after identifying the language from the user's audio. The supplied
context must never contribute to the language decision or appear in a caption.
"""
from functools import lru_cache
from pathlib import Path
import re
import unicodedata
import wave


# Sample ranges are from the three MIT-licensed, 16 kHz mono recordings shipped
# in fixture-tools/audio. The Korean prefix reads "hello; this is ...".
_PREFIXES = {"ja": (11200, "こんにち"), "ko": (23680, "안녕하"), "zh": (7360, "你好")}
_SCRIPTS = {
    "ja": re.compile(r"[\u3041-\u30ff\u3400-\u9fff]"),
    "ko": re.compile(r"[\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3]"),
    "zh": re.compile(r"[\u3400-\u9fff]"),
}


@lru_cache(maxsize=3)
def _context_audio(language):
    import numpy as np
    count, _ = _PREFIXES[language]
    path = Path(__file__).resolve().parents[1] / "fixture-tools" / "audio" / (language + ".wav")
    try:
        with wave.open(str(path), "rb") as sound:
            if (sound.getframerate(), sound.getnchannels(), sound.getsampwidth()) != (16000, 1, 2):
                return None
            data = sound.readframes(count)
    except (OSError, EOFError, wave.Error):
        return None
    if len(data) != 2 * count:
        return None
    return np.frombuffer(data, dtype="<i2").astype("float32") / 32768


def _letters(text):
    return "".join(ch for ch in unicodedata.normalize("NFKC", text) if ch.isalnum())


def _separate(words, language, boundary, before):
    # Whisper's DTW sometimes assigns the gap preceding a word to that word.
    # Use its centre and the edge on the side away from the marker to partition it.
    if before:
        target = [w for w in words if w.end > boundary + .16 and (w.start + w.end)/2 > boundary]
    else:
        target = [w for w in words if w.start < boundary + .16 and (w.start + w.end)/2 < boundary + .25]
    if not target:
        return None
    pilot = [w for w in words if w not in target]
    pilot_text = _letters("".join(w.word for w in pilot))
    if _PREFIXES[language][1] not in pilot_text:
        return None
    text = "".join(w.word for w in target).strip()
    target_text = _letters(text)
    if (not _SCRIPTS[language].search(target_text) or target_text in pilot_text or
            _PREFIXES[language][1] in target_text):
        # An independent direct read can still represent "hello". Do not
        # resurrect a greeting leaked by the marker when a source word is missing.
        return None
    weight = sum(max(1, len(_letters(w.word))) for w in target)
    score = sum(w.probability * max(1, len(_letters(w.word))) for w in target) / weight
    return text, float(score)


def context_transcript(model, samples, language, placement="before", cancelled=lambda: False):
    """Return (target text, target-word probability) or None. Samples are original mono 16 kHz."""
    import numpy as np
    if language not in _PREFIXES or placement not in ("before", "after") or cancelled():
        return None
    if not 960 <= len(samples) <= 35200:
        return None
    prefix = _context_audio(language)
    if prefix is None:
        return None
    gap = np.zeros(4320, np.float32)
    before = placement == "before"
    if before:
        signal = np.concatenate((prefix, gap, samples))
        boundary = (len(prefix) + len(gap)) / 16000
    else:
        signal = np.concatenate((samples, gap, prefix))
        boundary = len(samples) / 16000
    waveform = np.pad(signal, (2560, 3200))
    # The language argument here is intentional. The caller classified the
    # untreated recording first. We decode only the time-aligned target words.
    result, _ = model.transcribe(waveform, language=language, task="transcribe", beam_size=5,
                                 temperature=0.0, condition_on_previous_text=False,
                                 word_timestamps=True, without_timestamps=False, max_new_tokens=60)
    words = []
    for seg in result:
        if cancelled():
            return None
        words.extend(seg.words or ())
    return _separate(words, language, boundary, before) if not cancelled() else None
