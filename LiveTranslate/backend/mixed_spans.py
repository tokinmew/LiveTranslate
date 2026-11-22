"""Separate English and supported speech only across verified pauses in 16 kHz mono audio."""
import re

import numpy as np


_LATIN_WORD = re.compile("[a-zA-Z]{2,}")
_JAPANESE_OR_KOREAN = re.compile(r"[\u3040-\u30ff\uff66-\uff9d\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3]")


def quiet_boundaries(samples):
    if len(samples) < 12000:
        return []
    step = 160  # 10 ms
    frames = samples[:len(samples) // step * step].reshape(-1, step)
    levels = np.sqrt(np.mean(frames * frames, axis=1))
    quiet_limit = min(0.0015, 0.028 * np.percentile(levels, 95))
    if quiet_limit <= 0:
        return []
    edges = np.flatnonzero(np.diff(np.r_[False, levels <= quiet_limit, False]))
    cuts = [
        (int(start) + int(end)) * step // 2 for start, end in edges.reshape(-1, 2)
        if end - start >= 24 and start >= 10 and len(levels) - end >= 10
    ]
    return cuts if len(cuts) <= 5 else []


def _language(result, scripts):
    lang = result.get("language")
    text = result.get("text", "")
    if "<|Speech|>" not in result.get("tags", ()) or result.get("probs", {}).get(lang, 0) < 0.64:
        return None
    if lang == "en":
        if _LATIN_WORD.search(text) and not any(script.search(text) for script in scripts.values()):
            return lang
    elif lang in scripts and scripts[lang].search(text) and not _LATIN_WORD.search(text):
        if lang != "zh" or not _JAPANESE_OR_KOREAN.search(text):
            return lang
    return None


def _language_changes(recognizer, samples, cancelled, scripts):
    cuts = quiet_boundaries(samples)
    if not cuts:
        return []
    bounds = [0, *cuts, len(samples)]
    parts = [samples[left:right] for left, right in zip(bounds, bounds[1:])]
    # Reject a stutter or weak fragment before running any extra recognition.
    for part in parts:
        magnitude = np.abs(part)
        active = np.flatnonzero(magnitude > max(0.0001, magnitude.max() * 0.025))
        if not active.size or active[-1] - active[0] < 2400:
            return []
    languages = []
    for part in parts:
        if cancelled():
            return []
        lang = _language(recognizer.transcribe_trimmed(part, "auto"), scripts)
        if lang is None:
            return []
        languages.append(lang)
    if "en" not in languages or len(set(languages)) == 1:
        return []
    return [cut for cut, a, b in zip(cuts, languages, languages[1:]) if a != b]


def partition(model, samples, original, cancelled, scripts):
    """Return ordinary VAD spans unless both sides have independent evidence of a language change."""
    if cancelled():
        return []
    recognizer = getattr(model, "sensevoice", None)
    changes = _language_changes(recognizer, samples, cancelled, scripts) if recognizer is not None else []
    if not changes:
        if cancelled():
            return []
        spans = original(samples)
        return [] if cancelled() else spans
    spans = []
    for left, right in zip([0, *changes], [*changes, len(samples)]):
        if cancelled():
            return []
        for span in original(samples[left:right]):
            spans.append({"start": left + span["start"], "end": left + span["end"]})
    if len(spans) == 1:
        # Only one side survived VAD. Keep the rejected language out of the
        # full-phrase acoustic read used for standalone words.
        spans[0]["partitioned"] = True
    return [] if cancelled() else spans
