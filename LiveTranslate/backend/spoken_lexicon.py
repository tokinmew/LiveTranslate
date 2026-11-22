"""Resolve short, complete source words after the spoken-language gate."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import unicodedata
from ja_expressions import expression_reply


@lru_cache(maxsize=1)
def _words():
    path = Path(__file__).with_name("spoken-words.json.gz")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, EOFError):
        # Installations updating from earlier builds can still translate through
        # the ordinary local text model if this optional word table is absent.
        return {}


def _entry(source, lang):
    table = _words().get(lang, {})
    if lang == "ja":
        hiragana = "".join(
            chr(ord(char) - 96) if "\u30a1" <= char <= "\u30f6" else char
            for char in source
        )
        return table.get(source) or table.get(hiragana)
    return table.get(source)


def lexical_reply(original, language, replies=None):
    """Return English for an independently recognized complete word or sequence of replies."""
    if language not in ("ja", "zh", "ko") or not isinstance(original, str) or len(original) > 100:
        return None
    text = unicodedata.normalize("NFKC", original).strip()
    if not text or re.search("[A-Za-z0-9]", text):
        return None
    separator = " " if language == "ko" else ""
    source = separator.join(text.rstrip("。.!?").split())
    replies = replies or {}
    punctuation = text[-1] if text[-1] in "!?" else "."

    def lookup(piece, preserve_punctuation=False):
        value = replies.get(piece) or expression_reply(piece, language) or _entry(piece, language)
        if value:
            label = value[:1].upper() + value[1:]
            if preserve_punctuation:
                ending = punctuation if punctuation != "." else (label[-1] if label[-1] in "!?" else ".")
                return label.rstrip(" .?!") + ending
            return label.rstrip(" .?!")
        return None

    # Some dictionary examples include a comma as part of their full meaning.
    complete = lookup(source, preserve_punctuation=True)
    if complete:
        return complete
    if language == "ko" and " " in source and replies:
        # ASR often inserts spaces inside one spoken reply or omits the comma
        # between two replies. Only join words when the full text is known.
        compact_replies = {word.replace(" ", ""): english for word, english in replies.items()}
        compact = source.replace(" ", "")
        if compact in compact_replies:
            return compact_replies[compact].rstrip(" .?!") + punctuation
        first, rest = source.split(" ", 1)
        second = compact_replies.get(rest.replace(" ", ""))
        if first in replies and second:
            return replies[first].rstrip(" .?!") + ". " + second.rstrip(" .?!") + punctuation
    pieces = [piece.strip() for piece in re.split(r"[。.!?、,]+", source) if piece.strip()]
    if not 2 <= len(pieces) <= 3:
        return None
    translated = [lookup(piece) for piece in pieces]
    if all(translated):
        return ". ".join(translated) + punctuation
    return None
