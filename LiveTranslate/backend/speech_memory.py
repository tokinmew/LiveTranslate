"""Keep the first English wording of a recognized source phrase during live listening."""
from collections import OrderedDict
import hashlib
import re
import unicodedata
from multilingual_speech import SPOKEN_LANGUAGES


class SpeechCaptionMemory:
    MAX_PHRASES = 256
    MAX_RECORDINGS = 48

    def __init__(self, translate):
        self.translate = translate
        self._phrases = OrderedDict()
        self._recordings = OrderedDict()

    def __call__(self, text, language):
        return self.translate(text, language) if self.translate is not None else None

    @staticmethod
    def _key(original, language):
        if not isinstance(original, str) or not original or len(original) > 1024:
            return None
        # Keep interrogatives, negatives, amounts, English proper names, and
        # meaningful word boundaries intact when recognizers vary punctuation.
        # Width variants are common when two recognizers write the same phrase.
        value = unicodedata.normalize("NFC", original).translate(_WIDTH_PUNCTUATION)
        value = " ".join(value.split())
        value = re.sub(r"\s*([.?!,])", r"\1", value)
        if language in ("ja", "zh"):
            # Whisper may separate successive native-script segments with a
            # space. Keep spoken number groups distinct, e.g. 一 二 and 一二.
            value = _INNER_SPACE.sub(_native_space, value)
        if value.endswith(".") and not value.endswith(".."):
            value = value[:-1].rstrip()
        elif value.endswith("!") and len(value) > 1 and value[-2].isalpha():
            # A single mark after a word is often added on a louder read.
            # Keep emphatic runs, question combinations and numeric expressions.
            value = value[:-1]
        if value and language in SPOKEN_LANGUAGES:
            return language, value
        return None

    def lookup(self, original, language):
        key = self._key(original, language)
        if key in self._phrases:
            self._phrases.move_to_end(key)
            return self._phrases[key]
        return None

    def accept(self, caption):
        key = self._key(caption.get("original"), caption.get("language"))
        english = caption.get("text")
        if key is None or not isinstance(english, str) or not english.strip() or len(english) > 4096:
            return caption
        if key in self._phrases:
            self._phrases.move_to_end(key)
            return {**caption, "text": self._phrases[key]}
        self._phrases[key] = english
        if len(self._phrases) > self.MAX_PHRASES:
            self._phrases.popitem(last=False)
        return caption

    def _replay(self, recording, language):
        key = recording, language
        if key in self._recordings:
            self._recordings.move_to_end(key)
            return self._recordings[key]
        return None

    def _remember_recording(self, recording, caption):
        original, english, language = caption.get("original"), caption.get("text"), caption.get("language")
        if not self._key(original, language) or not isinstance(english, str) or not english.strip() or len(english) > 4096:
            return
        key = recording, language
        if key not in self._recordings:
            self._recordings[key] = {"original": original, "text": english, "language": language}
            if len(self._recordings) > self.MAX_RECORDINGS:
                self._recordings.popitem(last=False)

    def stabilize(self, phrase, captions, cancelled):
        recording = None
        first = None
        count = 0
        replayed = set()
        for caption in captions:
            if cancelled():
                return
            if caption.get("ignored"):
                continue
            count += 1
            if recording is None and caption.get("original"):
                digest = hashlib.blake2s(phrase.payload, digest_size=16).digest()
                recording = phrase.rate, phrase.channels, digest
            # Only an approved caption can trigger replay. Input bytes, rate,
            # channels and detected language must match a completed single turn.
            language = caption["language"]
            previous = self._replay(recording, language) if recording is not None and caption.get("original") else None
            if previous is None:
                caption = self.accept(caption)
            else:
                if language in replayed:
                    continue
                replayed.add(language)
                caption = {**caption, **previous}
            if count == 1:
                first = caption
            yield caption
        if recording is not None and count == 1 and not cancelled():
            self._remember_recording(recording, first)


_WIDTH_PUNCTUATION = str.maketrans({"。": ".", "．": ".", "？": "?", "！": "!", "，": ","})
_HAN_KANA = r"\u3041-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef"
_INNER_SPACE = re.compile("(?<=[" + _HAN_KANA + "]) (?=[" + _HAN_KANA + "])")


def _native_space(match):
    value = match.string
    return " " if value[match.start()-1].isnumeric() and value[match.end()].isnumeric() else ""
