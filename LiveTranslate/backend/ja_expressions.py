"""Exact Japanese expression lookup for an already identified Japanese source."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import unicodedata


@lru_cache(maxsize=1)
def _entries():
    try:
        with gzip.open(Path(__file__).with_name("ja-expressions.json.gz"), "rt", encoding="utf8") as data:
            return json.load(data)
    except (ValueError, OSError, EOFError):
        return {}


def expression_reply(source, language):
    if language != "ja" or not isinstance(source, str) or not 1 < len(source) <= 100:
        return None
    cleaned = unicodedata.normalize("NFKC", source).strip()
    cleaned = cleaned.strip("「」『』\" ")
    punctuation = cleaned[-1] if cleaned and cleaned[-1] in "!?" else ""
    source_word = re.sub(r"\s+", "", cleaned.rstrip("。!?… ."))
    if not source_word or not re.fullmatch(r"[ぁ-ゖァ-ヺー一-鿿々ヶヵ]+", source_word):
        return None
    normalized = "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in source_word)
    english = _entries().get(normalized)
    if not english:
        return None
    ending = punctuation or (english[-1] if english[-1] in "!?" else ".")
    return (english[:1].upper() + english[1:]).rstrip(".!?") + ending
