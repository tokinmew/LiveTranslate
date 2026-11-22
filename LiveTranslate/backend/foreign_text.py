"""Select Chinese, Korean and Japanese source text before any translation call."""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata


PRIORITY = frozenset(("zh", "zt", "ko", "ja"))
_COLUMNS = re.compile(r"\t+|[|｜•▪]+|\s+[/／—–→]\s+|[^\S\r\n]{2,}")
_SENTENCES = re.compile(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_JOINED_KANA = frozenset("ーｰゝゞヽヾ々〻")
_PARTICLES = ("を", "で", "の", "から", "は", "に", "が", "と", "へ",
              "은", "는", "이", "가", "을", "를", "에", "와", "과", "으로",
              "的", "和", "与", "與", "在", "是")
_ENGLISH_WORDS = frozenset(("a", "an", "and", "are", "as", "at", "by", "for",
                            "from", "has", "in", "is", "it", "of", "on", "or",
                            "the", "this", "to", "was", "we", "with", "you", "your"))


def _identifier(token):
    return (any(c.isdigit() for c in token) or token.isupper()
            or any(c.isupper() for c in token[1:]))


@lru_cache(maxsize=8192)
def script(char):
    if char.isascii() or not char.isalpha() or char in _JOINED_KANA:
        return ""
    name = unicodedata.name(char, "")
    if name.startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")):
        return "han"
    if name.startswith(("HIRAGANA LETTER ", "KATAKANA LETTER ", "HALFWIDTH KATAKANA LETTER ",
                        "HIRAGANA DIGRAPH ", "KATAKANA DIGRAPH ", "HENTAIGANA LETTER ")):
        return "ja"
    if name.startswith(("HANGUL ", "HALFWIDTH HANGUL ")):
        return "" if "FILLER" in name else "ko"
    if name.startswith("BOPOMOFO LETTER "):
        return "zt"
    return ""


def _language(scripts, selected):
    if selected == "auto":
        # Han is shared. An accompanying phonetic script disambiguates it.
        specific = scripts - {"han"}
        if len(specific) == 1:
            return next(iter(specific))
        return "han" if not specific else None
    allowed = {"han", selected}
    return selected if selected in PRIORITY and scripts <= allowed else None


def _inside_foreign_phrase(run):
    """Preserve e.g. 'USB-C' or 'New York' inside an actual foreign phrase."""
    words = re.findall(r"[^\W\d_]+", run, re.UNICODE)
    if len(words) <= 1:
        return True
    has_english_grammar = any(word.casefold() in _ENGLISH_WORDS for word in words)
    return len(words) <= 4 and not has_english_grammar


def _trim_edges(text, first, last):
    before, after = text[:first], text[last + 1:]
    if any(c.isalpha() and c not in _JOINED_KANA for c in before):
        # Preserve an adjacent identifier such as an iPhone model number,
        # or a proper name followed by a Japanese/Korean/Chinese particle.
        tail = before.rstrip()
        # Match once from the edge. A forward substring search could retry
        # every position in a long Latin string ending with punctuation.
        match = re.match(r"[\w.+-]+", tail[::-1])
        token = match.group(0)[::-1] if match else ""
        separated = before[-1:].isspace()
        if token and token[0].isalnum() and (text[first:].startswith(_PARTICLES) or
                                               (not separated and _identifier(token))):
            before = before[len(tail)-len(token):]
        else:
            before = ""
    if any(c.isalpha() and c not in _JOINED_KANA for c in after):
        # A space followed by English after a subtitle is commonly a gloss.
        # Keep the punctuation of the foreign sentence and directly suffixed
        # model identifiers, e.g. 東京2025 or 型A.
        identifier = re.match(r"[\w.+-]+", after)
        if identifier and _identifier(identifier.group(0)):
            after = identifier.group(0)
        else:
            after = re.match(r"[^\w\s]*", after).group(0)
    # Both retained edges are literal slices of the original. Keep their
    # offsets so screen captions can anchor repeated words unambiguously.
    begin = first - len(before)
    raw = text[begin:last + 1 + len(after)]
    return raw.strip(), begin + len(raw) - len(raw.lstrip())


def _pieces(text, source):
    positions = [(i, kind) for i, char in enumerate(text) if (kind := script(char))]
    if not positions:
        return
    if len(positions) == 1:
        index = positions[0][0]
        if (0 < index < len(text) - 1 and text[index-1].isalpha() and text[index+1].isalpha()
                and text[index-1].isascii() and text[index+1].isascii()):
            # A single OCR substitution in a Latin word (S日ttings) is weak
            # evidence for a subtitle. Genuine single-glyph labels still work.
            return
    begin = 0
    last_kind = ""
    for number, (index, kind) in enumerate(positions):
        if number:
            previous = positions[number - 1][0]
            gap = text[previous + 1:index]
            incompatible = kind != "han" and last_kind and kind != last_kind
            if incompatible or not _inside_foreign_phrase(gap):
                # Never combine distinct phonetic scripts under a single pack.
                part = text[:previous + 1] if begin == 0 else text[positions[begin][0]:previous + 1]
                offset = 0 if begin == 0 else positions[begin][0]
                value, start = _trim_edges(part, positions[begin][0] - offset, previous - offset)
                route = _language({k for _, k in positions[begin:number]}, source)
                if value and route:
                    yield route, value, offset + start
                begin, last_kind = number, ""
        if kind != "han":
            last_kind = kind
    offset = positions[begin][0] if begin else 0
    first, last = positions[begin][0], positions[-1][0]
    value, start = _trim_edges(text[offset:], first - offset, last - offset)
    route = _language({k for _, k in positions[begin:]}, source)
    if value and route:
        yield route, value, offset + start


def _fields(pattern, text, begin, end):
    """Yield nonempty slices between separators, retaining source offsets."""
    for match in pattern.finditer(text, begin, end):
        if begin < match.start():
            yield begin, match.start()
        begin = match.end()
    if begin < end:
        yield begin, end


def _column_segments(text, source, begin, end):
    for left, right in _fields(_COLUMNS, text, begin, end):
        for start, stop in _fields(_SENTENCES, text, left, right):
            sentence = text[start:stop]
            first = start + len(sentence) - len(sentence.lstrip())
            for hint, value, offset in _pieces(sentence.strip(), source):
                yield hint, value, first + offset


def located_foreign_segments(text, source):
    """Accepted screen segments and their exact [start, stop) in the OCR string."""
    if source != "auto" and source not in PRIORITY:
        return
    offset = 0
    for line in text.splitlines(keepends=True):
        # A link is its own field on screen. Joining its two sides could
        # otherwise place a translated label over the link between them.
        for begin, end in _fields(_URL, line, 0, len(line)):
            for hint, value, start in _column_segments(line, source, begin, end):
                yield hint, value, offset + start, offset + start + len(value)
        offset += len(line)


def foreign_segments(text, source):
    """Return source hints and eligible rows, preserving original script.

    Latin-only text (including romanized input), non-target writing systems,
    numeric panels, and punctuation cannot trigger a model load. A 'han'
    hint defers the shared-character case to the language router.
    """
    if source != "auto" and source not in PRIORITY:
        return []
    output = []
    for line in text.splitlines():
        line = _URL.sub("", line.strip())
        output.extend((hint, value) for hint, value, _ in _column_segments(line, source, 0, len(line)))
    return output
