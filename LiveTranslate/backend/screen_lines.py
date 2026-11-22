"""Keep source-identified lines and their individual physical word rectangles."""
import re
import unicodedata

from screen_geometry import line_regions, physical_box
from multilingual_text import english_words

# Only enable a shared Windows Latin reader for explicitly selected sources.
# A matching local OCR pack always takes precedence.
LATIN_FALLBACKS = frozenset(("deu", "fra", "ita", "nld", "por", "spa"))
_BREAK = re.compile(r"[.!?…;:।؟。！？][\"'’”)]*$")
_MENU = frozenset("""
apply back browse cancel click close confirm done download enable exit fullscreen
help install loading microphone mute next open pause play press quit record redo
restart retry save search settings skip start stop subtitles undo unmute upload
""".split())


def _writing_system(token):
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return None
    return "latin" if all("LATIN" in unicodedata.name(c, "") for c in letters) else "other"


def _english_ui_runs(words):
    """English actions next to a foreign caption may share its OCR line."""
    hidden = set()
    start = 0
    values = [w.text.casefold().strip(".,:;!?()[]{}'’\"") for w in words]
    for i in range(len(values) + 1):
        if i < len(values) and values[i] and english_words([values[i]]):
            continue
        run = values[start:i]
        if len(run) >= 2 and _MENU.intersection(run):
            hidden.update(range(start, i))
        start = i+1
    return hidden


def accepted_regions(image, words, source, accepts, english_guard=None):
    """Test each subtitle or menu label independently, retaining measured boxes."""
    grouped = {}
    for word in words:
        grouped.setdefault(word.line, []).append(word)
    output = []
    for row in grouped.values():
        english_indices = _english_ui_runs(row)
        line = ""
        spans = []
        def flush():
            if not spans:
                return
            for value, boxes in line_regions(line, spans):
                if value.strip() and accepts(value.strip(), source):
                    offset = len(value) - len(value.lstrip())
                    output.append((value.strip(), [(a-offset, b-offset, box) for a,b,box in boxes]))
        previous_script = None
        for idx, word in enumerate(row):
            token = word.text.strip()
            box = physical_box(image, word.box)
            script = _writing_system(token)
            if not token or box is None or word.confidence < 45 or idx in english_indices:
                flush()
                line, spans, previous_script = "", [], None
                continue
            if spans and (_BREAK.search(line) or (script and previous_script and script != previous_script)):
                flush()
                line, spans = "", []
            if line:
                line += " "
            start = len(line)
            line += token
            spans.append((start, len(line), box))
            if script:
                previous_script = script
        flush()
    # Some source-specific OCR models can read English controls as Cyrillic
    # (e.g. "COPY" and its visual Cyrillic equivalents). Veto words backed
    # by independent Windows readings of common English UI vocabulary.
    if english_guard and any(_writing_system(line) == "other" for line, _ in output):
        from ocr_guard import _covers
        observed = english_guard.detect(image) or ()
        menu_boxes = [physical_box(image, w.box) for w in observed
                      if w.text.casefold().strip(".,:;!?()[]") in _MENU]
        output = [(line, words) for line, words in output
                  if not any(box and _covers(word_box, box)
                             for box in menu_boxes for _, _, word_box in words)]
    return output
