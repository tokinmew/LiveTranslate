"""Use word locations to reject English that CJK OCR mistook for foreign script."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import struct
import subprocess
import time


# Ask Windows' separately installed English recognizer only on frames that
# have plausible foreign text. The helper never receives a path or network URL.
_HELPER = Path(__file__).resolve().parents[1] / "ocr-tools" / "EnglishOcr.exe"


def has_target_script(text):
    # Include kana, hangul jamo/syllables, Han compatibility/extension planes.
    return any(0x3400 <= n <= 0x4DBF or 0x4E00 <= n <= 0x9FFF or
               0xF900 <= n <= 0xFAFF or 0x20000 <= n <= 0x323AF or
               0x3041 <= n <= 0x30FA or 0x31F0 <= n <= 0x31FF or
               0xFF66 <= n <= 0xFF9F or 0x1100 <= n <= 0x11FF or
               0x3131 <= n <= 0x318E or 0xA960 <= n <= 0xA97F or
               0xAC00 <= n <= 0xD7A3 or 0xD7B0 <= n <= 0xD7FF
               for n in map(ord, text))


def _ambiguous_mixed_line(text):
    # These source glyphs can be visually identical to a bracket, dash, or
    # Latin letter. Treat an isolated occurrence conservatively in English UI.
    target = [ch for ch in text if has_target_script(ch)]
    if (len(target) == 1 and target[0] in "くへヘニロノ口一エ工リ" and
            any(ch.isascii() and not ch.isspace() for ch in text)):
        return True
    # Forced Korean OCR sometimes converts an entire row of tiny Latin glyphs
    # into apparently random digits and a single Hangul syllable. Short real
    # quantities such as "20분" remain valid.
    return len(target) == 1 and sum(ch.isascii() and ch.isdigit() for ch in text) >= 10


@dataclass(frozen=True)
class Word:
    text: str
    box: tuple[int, int, int, int]
    confidence: float = 100
    line: tuple[str, ...] = ()


def parse_tsv(tsv):
    """Parse both tesserocr's headerless output and CLI TSV with a header."""
    words = []
    for line in tsv.splitlines():
        fields = line.split("\t", 11)
        if len(fields) != 12 or fields[0] != "5" or not fields[11]:
            continue
        try:
            left, top, width, height = map(int, fields[6:10])
            confidence = float(fields[10])
        except ValueError:
            continue
        if width > 0 and height > 0 and math.isfinite(confidence):
            words.append(Word(fields[11], (left, top, left + width, top + height), confidence,
                              tuple(fields[1:5])))
    return words


def english_observation(word):
    # An English OCR engine looking at Hangul can report short approximations
    # such as "7", "|" and "Ch.". Those are unreliable evidence for masking.
    core = word.strip(".,:;!?()[]{}'\"-")
    letters = re.sub("[^a-zA-Z]", "", core)
    if len(letters) >= 3 and re.search("[aeiouy]", letters, re.I):
        return True
    return bool(re.fullmatch(r"[0-9][0-9:.,/-]{2,}", core))


def plain_horizontal_rows(image, limit=7):
    """Return tightly normalized lines only when ink forms clear horizontal bands."""
    from PIL import Image, ImageOps
    from screen_geometry import map_crop
    import numpy as np
    if not isinstance(image, Image.Image):
        return []
    probe = image.convert("L")
    if probe.width * probe.height > 2200000:
        factor = min(1, 1600 / max(probe.size))
        size = tuple(max(1, round(n * factor)) for n in probe.size)
        probe = probe.resize(size, Image.Resampling.BILINEAR)
    histogram = probe.histogram()
    bg = max(range(256), key=histogram.__getitem__)
    if sum(histogram[max(0, bg - 12):min(256, bg + 13)]) < probe.width * probe.height * 0.73:
        return []
    ink = np.abs(np.asarray(probe, dtype=np.int16) - bg) > 35
    rows = np.flatnonzero(ink.any(axis=1))
    if not len(rows):
        return []
    # Require a real blank interval, not small gaps inside kanji strokes.
    gap = min(12, max(5, round(probe.height * 0.012)))
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > gap) + 1)
    if len(groups) > limit:
        return []
    sx, sy = image.width / probe.width, image.height / probe.height
    normalized = []
    for band in groups:
        top, bottom = int(band[0]), int(band[-1]) + 1
        cols = np.flatnonzero(ink[top:bottom].any(axis=0))
        left, right = int(cols[0]), int(cols[-1]) + 1
        height, width = bottom - top, right - left
        if height < 6 or width < height * 2.8 or width > height * 100:
            return []
        if ink[top:bottom, left:right].mean() > 0.67:
            return []  # A bar or shape, not a run of separated glyphs.
        box = (math.floor(left * sx), math.floor(top * sy), math.ceil(right * sx), math.ceil(bottom * sy))
        crop = image.crop(box)
        size = (max(1, round(crop.width * 30 / crop.height)), 30)
        padded = ImageOps.expand(crop.resize(size, Image.Resampling.LANCZOS), border=12, fill=int(bg))
        normalized.append(map_crop(padded, image, box, 12))
    return normalized


def isolated_horizontal_line(image):
    rows = plain_horizontal_rows(image, limit=1)
    return rows[0] if rows else None


def combine_row_results(rows, recognized):
    """Map independent row OCR geometry to one in-memory canvas for the English guard."""
    from PIL import Image
    height = sum(row.height + 8 for row in rows)
    canvas = Image.new("L", (max(row.width for row in rows), height), rows[0].getpixel((0, 0)))
    canvas.info["desktop_rows"] = []
    y = 0
    raw_lines, tsv_lines = [], []
    for number, (row, (raw, tsv)) in enumerate(zip(rows, recognized), 1):
        canvas.paste(row, (0, y))
        canvas.info["desktop_rows"].append((y, y+row.height, row.info.get("desktop_map"),row.info.get("content_box")))
        if raw:
            raw_lines.append(raw)
        for pos, word in enumerate(parse_tsv(tsv), 1):
            left, top, right, bottom = word.box
            fields = (5, 1, number, 1, 1, pos, left, top + y, right - left, bottom - top,
                      word.confidence, word.text)
            tsv_lines.append("\t".join(map(str, fields)))
        y += row.height + 8
    return canvas, "\n".join(raw_lines), "\n".join(tsv_lines)


def single_foreign_band(image, tsv):
    """Localize joined fragments of a single subtitle inside a sparse screen."""
    words = [word for word in parse_tsv(tsv) if has_target_script(word.text)]
    if len(words) < 2:
        return None
    left = min(w.box[0] for w in words)
    top = min(w.box[1] for w in words)
    right = max(w.box[2] for w in words)
    bottom = max(w.box[3] for w in words)
    heights = sorted(w.box[3]-w.box[1] for w in words)
    typical = heights[len(heights)//2]
    centers = [(w.box[1]+w.box[3])/2 for w in words]
    if typical<8 or max(centers)-min(centers)>typical*0.7 or right-left < typical*2.8:
        return None
    # Include contiguous Latin names that share the subtitle's baseline.
    nearby = [w for w in parse_tsv(tsv) if abs((w.box[1]+w.box[3])/2-(top+bottom)/2) < typical*0.65]
    for word in sorted(nearby,key=lambda w:-w.box[2]):
        if word.box[2] >= left-2*typical and word.box[0] <= right:
            left=min(left,word.box[0])
    for word in sorted(nearby,key=lambda w:w.box[0]):
        if word.box[0] <= right+2*typical and word.box[2] >= left:
            right=max(right,word.box[2])
    # Include adjacent Latin names, punctuation and source glyphs Tesseract
    # may have missed. Horizontal blank margins distinguish a complete row
    # from a portion of a longer unknown line.
    margin = max(40,typical*3)
    ypad = max(7,typical//2)
    box=(max(0,left-margin),max(0,top-ypad),min(image.width,right+margin),min(image.height,bottom+ypad))
    if box[0]>=box[2] or box[1]>=box[3]:
        return None
    from screen_geometry import map_crop
    return isolated_horizontal_line(map_crop(image.crop(box), image, box))


def plausible_band_repair(original, other, data):
    from collections import Counter
    count = Counter(ch for ch in original if has_target_script(ch))
    new = Counter(ch for ch in other if has_target_script(ch))
    total,sum_new = sum(count.values()),sum(new.values())
    words=[w for w in parse_tsv(data) if has_target_script(w.text)]
    if not words or sum_new < max(2,total*0.62) or sum_new > 2.0*total+2:
        return False
    return (sum((count & new).values()) >= max(1,min(total,sum_new)*0.43) and
            sum(w.confidence for w in words)/len(words)>=68)


def _hangul(char):
    return 0xAC00 <= ord(char) <= 0xD7A3 or 0x1100 <= ord(char) <= 0x11FF


def _han(char):
    n = ord(char)
    return (0x3400 <= n <= 0x4DBF or 0x4E00 <= n <= 0x9FFF or 0xF900 <= n <= 0xFAFF or
            0x20000 <= n <= 0x323AF)


def uncertain_korean_row(tsv):
    """A multilingual recognizer can switch scripts inside a Korean ending."""
    words = parse_tsv(tsv)
    if any(0x3041 <= ord(ch) <= 0x30FA for word in words for ch in word.text):
        return False
    anchors = sum(_hangul(ch) for word in words if word.confidence >= 78 for ch in word.text)
    han_scores = [word.confidence for word in words for ch in word.text if _han(ch)]
    return (anchors >= 3 and 1 <= len(han_scores) <= anchors and
            sum(han_scores) / len(han_scores) < 64)


def prefer_korean_row(original, candidate):
    """Require known text to survive and strong Hangul to cover the uncertain span."""
    from difflib import SequenceMatcher
    old, new = parse_tsv(original), parse_tsv(candidate)
    old_hangul = ''.join(ch for word in old for ch in word.text if _hangul(ch))
    new_hangul = ''.join(ch for word in new for ch in word.text if _hangul(ch))
    added = len(new_hangul) - len(old_hangul)
    if added < 1 or added > sum(_han(ch) for word in old for ch in word.text) + 2:
        return False
    # Preserve the order of the original Hangul and any high-confidence Han,
    # Latin names and numbers; a genuine Hanja name can coexist with Korean.
    anchors = ''.join(ch for word in old for ch in word.text if _hangul(ch) or
                      (word.confidence >= 78 and (_han(ch) or ch.isascii() and ch.isalnum())))
    new_text = ''.join(word.text for word in new)
    cursor = iter(new_text)
    if not all(ch in cursor for ch in anchors):
        return False
    confidences = [word.confidence for word in new for ch in word.text if _hangul(ch)]
    changes = SequenceMatcher(None, old_hangul, new_hangul, autojunk=False).get_opcodes()
    inserted = [score for tag, _, _, start, end in changes if tag != 'equal' for score in confidences[start:end]]
    return bool(inserted) and sum(inserted) / len(inserted) >= 65


class EnglishGuard:
    def __init__(self):
        self.retry_after = 0

    def detect(self, image):
        """Return a list on success, or None when the English OCR is unavailable."""
        if time.monotonic() < self.retry_after:
            return None
        # Windows' max OCR image dimension on Windows 11 is normally 4096.
        # Keep RAM, pipe transfers and latency bounded for large monitors.
        scaled = image
        if max(image.size) > 3072 or image.width * image.height > 6000000:
            ratio = min(3072 / max(image.size), math.sqrt(6000000 / (image.width * image.height)))
            from PIL import Image
            scaled = image.resize(tuple(max(1, round(v * ratio)) for v in image.size), Image.Resampling.LANCZOS)
        try:
            data = struct.pack("<ii", *scaled.size) + scaled.convert("L").tobytes()
            process = subprocess.run([str(_HELPER)], input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     timeout=6, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            self.retry_after = time.monotonic() + 30
            return None
        if process.returncode or len(process.stdout) > 2 * 1024 * 1024:
            self.retry_after = time.monotonic() + (300 if process.returncode == 2 else 30)
            return None
        sx, sy = image.width / scaled.width, image.height / scaled.height
        lines = {}
        for line in process.stdout.decode("ascii", "replace").splitlines():
            parts = line.split("\t", 5)
            if len(parts) != 6:
                continue
            try:
                left, top, right, bottom = map(int, parts[1:5])
            except ValueError:
                continue
            if 0 <= left < right <= scaled.width and 0 <= top < bottom <= scaled.height:
                lines.setdefault(parts[0], []).append(Word(parts[5], (math.floor(left*sx), math.floor(top*sy),
                                                                       math.ceil(right*sx), math.ceil(bottom*sy))))
        words = []
        short_keys = []
        qualified_key_rows = []
        for line in lines.values():
            # Numbers, initials and brackets offer weak language evidence alone.
            # They corroborate English in a line with multiple readable words.
            anchors = sum(english_observation(hit.text) for hit in line)
            keys = [hit for hit in line if re.fullmatch(r"[A-Za-z0-9]{2,4}",hit.text)]
            numeric_keys = sum(any(ch.isdigit() for ch in hit.text) for hit in keys)
            key_row = len(keys) >= 3 and numeric_keys >= 2
            if key_row:
                qualified_key_rows.append((min(h.box[0] for h in keys),min(h.box[1] for h in keys),
                                           max(h.box[2] for h in keys),max(h.box[3] for h in keys)))
            else:
                short_keys.extend(keys)
            words.extend(hit for hit in line if anchors >= 2 or key_row or english_observation(hit.text))
        # Windows sometimes segments separate keycaps from the same row into
        # independent OCR "lines", e.g. G1 G2 G3 ... R1 R2 A1. Include those
        # detections only when their baselines and scale match a corroborated row.
        for hit in short_keys:
            l,t,r,b = hit.box
            if any(abs((t+b)-(y0+y1)) <= max(3,0.6*(b-t)) and max(l-x1,x0-r) <= (b-t)*18
                   for x0,y0,x1,y1 in qualified_key_rows):
                words.append(hit)
        return words


def observe_english(guard, image, tsv):
    """Magnify tiny UI text for Windows OCR while retaining full-frame coordinates."""
    words = [word for word in parse_tsv(tsv) if has_target_script(word.text)]
    if not words or not any(w.box[3]-w.box[1] <= 13 for w in words):
        return guard.detect(image)
    from PIL import Image
    if not isinstance(image, Image.Image):
        return guard.detect(image)
    # The extra context covers adjacent keycaps that Tesseract may have read
    # as numbers. Bound the second engine's pixel footprint for 4K displays.
    l=max(0,min(w.box[0] for w in words)-150)
    t=max(0,min(w.box[1] for w in words)-50)
    r=min(image.width,max(w.box[2] for w in words)+150)
    b=min(image.height,max(w.box[3] for w in words)+50)
    if r<=l or b<=t or (r-l)*(b-t)>1300000 or max(r-l,b-t)>1500:
        return guard.detect(image)
    crop=image.crop((l,t,r,b)).resize(((r-l)*2,(b-t)*2),Image.Resampling.LANCZOS)
    hits=guard.detect(crop)
    if hits is None:
        return None
    return [Word(h.text,(l+h.box[0]//2,t+h.box[1]//2,l+(h.box[2]+1)//2,t+(h.box[3]+1)//2)) for h in hits]


def _covers(candidate, observed):
    """Require strong overlap on both axes, not just the line's bounding box."""
    l, t, r, b = candidate
    x0, y0, x1, y1 = observed
    w = max(0, min(r, x1) - max(l, x0))
    h = max(0, min(b, y1) - max(t, y0))
    return w >= (r-l)*0.65 and h >= (b-t)*0.55


def overlapping_text_lines(tsv):
    """PSM 6 occasionally splits one Japanese subtitle into two overlapping rows."""
    groups = {}
    for word in parse_tsv(tsv):
        groups.setdefault(word.line, []).append(word)
    if len(groups) != 2 or any(not any(has_target_script(w.text) for w in row) for row in groups.values()):
        return False
    bounds = [(min(w.box[0] for w in row), min(w.box[1] for w in row),
               max(w.box[2] for w in row), max(w.box[3] for w in row)) for row in groups.values()]
    a,b = bounds
    overlap_y = min(a[3],b[3]) - max(a[1],b[1])
    overlap_x = min(a[2],b[2]) - max(a[0],b[0])
    return (overlap_y >= 0.65 * max(a[3]-a[1],b[3]-b[1]) and
            overlap_x >= 0.12 * min(a[2]-a[0],b[2]-b[0]))


def prefer_single_line(first, initial_tsv, candidate, candidate_tsv):
    words = parse_tsv(candidate_tsv)
    if not words or len({w.line for w in words}) != 1:
        return False
    count = sum(has_target_script(c) for c in first)
    alternate_count = sum(has_target_script(c) for c in candidate)
    if not 0.55*count <= alternate_count <= 1.1*count or alternate_count < 2:
        return False
    prior = parse_tsv(initial_tsv)
    mean = sum(w.confidence for w in words)/len(words)
    return mean >= 60 and mean >= sum(w.confidence for w in prior)/len(prior) - 3


def join_vertical_glyphs(text):
    def joined_glyph(ch):
        return has_target_script(ch) or ch in '々〆〇ー、。！？「」『』（）…〜～・'
    def join(match):
        start, end = match.span()
        if start and end < len(text) and joined_glyph(text[start-1]) and joined_glyph(text[end]):
            return ""
        return match.group()
    return re.sub("[ \t]+", join, text)


def corroborate_lines(text, alternate):
    """Retain a subtitle if a second OCR configuration sees related script.

    Used when the separate Windows English recognizer is unavailable. Several
    matching source glyphs are required for longer lines. Alternate OCR never
    supplies text to translation.
    """
    from collections import Counter
    import unicodedata
    def symbols(line):
        return Counter(ch for ch in unicodedata.normalize("NFKC",line) if has_target_script(ch))
    evidence = symbols(alternate)
    def compact(value):
        return ''.join(unicodedata.normalize('NFKC', value).split())
    alternate_rows = {compact(row) for row in alternate.splitlines()}
    kept = []
    for line in text.splitlines():
        chars = symbols(line)
        count = sum(chars.values())
        latin_digits = sum(ch.isascii() and ch.isalnum() for ch in line)
        if _ambiguous_mixed_line(line):
            continue
        if latin_digits > max(2, 2*count) or _repeated_numeric_guess(line):
            # With long serials (or one repeated syllable woven through digits)
            # a partial character match can be meaningless. Require the other
            # segmentation to reproduce the entire source and the same number.
            has_serial = sum(ch.isascii() and ch.isdigit() for ch in line) >= 6
            if (count >= 3 and has_serial and not any(ch.isascii() and ch.isalpha() for ch in line)
                    and compact(line) in alternate_rows):
                kept.append(line)
            continue
        shared = sum((chars & evidence).values())
        if count and shared >= min(4, math.ceil(count * 0.28)):
            kept.append(line)
    return "\n".join(kept)


def _repeated_numeric_guess(text):
    # A forced Korean model can render unfamiliar scripts as one repeated
    # syllable woven through digits. Corroborate this shape separately while
    # preserving genuine laughter, repeated names, serials and train numbers.
    if sum(ch.isascii() and ch.isdigit() for ch in text) < 6:
        return False
    glyphs = {ch for ch in text if has_target_script(ch)}
    if len(glyphs) != 1:
        return False
    repeated = next(iter(glyphs))
    transitions = sum((a == repeated and b.isascii() and b.isdigit()) or
                      (b == repeated and a.isascii() and a.isdigit()) for a, b in zip(text, text[1:]))
    return transitions >= 2


def weak_foreign_line(text):
    """Identify potentially forced CJK guesses in Latin or numeric UI."""
    count = sum(has_target_script(ch) for ch in text)
    latin = sum(ch.isascii() and ch.isalnum() for ch in text)
    return count <= 2 or (count <= 5 and latin >= count * 1.3) or _repeated_numeric_guess(text)


DESKTOP_ICON_CONFUSABLE = frozenset("一二三十口回ロノニヘへくエ工リ全図圖图丨丿丶ᄆᄉᄂᄀ")


def filter_desktop_fragments(text, positions, verified_spans=()):
    """Require local text evidence for CJK OCR of an entire desktop/application.

    Call only for a full-display request, never for a selected
    region or independently verified vertical column. Icons
    can look exactly like isolated CJK glyphs even to two OCR configurations.
    A separate exact crop reread can verify complex single-character labels or
    unusually narrow text. Supply those results as Word objects with original
    physical boxes and confidence >= 88. A lone icon-confusable glyph remains
    ambiguous; a real word made from those glyphs needs compact word geometry
    and an exact reread of the whole word, not individual icon matches.
    Unrelated rows and repeated readings of the same box provide no support.
    Update positions in place so rejected duplicate labels cannot reappear.
    """
    import unicodedata
    from collections import defaultdict, deque

    confusable = DESKTOP_ICON_CONFUSABLE
    def compact(value):
        return "".join(unicodedata.normalize("NFKC", value).split())

    anchors = {(compact(hit.text), tuple(hit.box)) for hit in verified_spans
               if isinstance(hit, Word) and math.isfinite(hit.confidence) and hit.confidence >= 88}
    def verified(value, box):
        return (compact(value), tuple(box)) in anchors

    available = defaultdict(deque)
    for line, spans in positions:
        available[line].append(spans)
    rows, nodes, physical_spans = [], [], set()
    for line in text.splitlines():
        spans = available[line].popleft() if available[line] else ()
        row = len(rows)
        rows.append(line)
        for start, end, box in spans:
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(line)
                    or not isinstance(box, (tuple, list)) or len(box) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box)):
                continue
            left, top, right, bottom = box
            glyphs = "".join(ch for ch in unicodedata.normalize("NFKC", line[start:end]) if has_target_script(ch))
            identity = tuple(box), compact(line[start:end])
            if glyphs and left < right and top < bottom and identity not in physical_spans:
                physical_spans.add(identity)
                nodes.append((row, start, end, box, glyphs))

    heights, eligible, regular = [], [], []
    row_nodes = defaultdict(list)
    for index, (row, start, end, box, glyphs) in enumerate(nodes):
        row_nodes[row].append(index)
        height = box[3] - box[1]
        value = rows[row][start:end]
        aspect = (box[2] - box[0]) / len(compact(value)) / height
        icon_stroke = len(glyphs) == 1 and glyphs in confusable and len(compact(value)) == 1
        heights.append(max(height, box[2] - box[0]) if icon_stroke else height)
        regular.append(0.45 <= aspect <= 1.8 or len(glyphs) >= 3)
        eligible.append(regular[-1] or icon_stroke or
                        (0.3 <= aspect <= 2.2 and verified(value, box)))

    # Established prose provides context for narrow or unusually tall word
    # boxes in that same physical source row. A distant icon, or a narrow
    # two-character guess by itself, cannot establish that context.
    from statistics import median
    context_rows, proven_rows = set(), set()
    for row, indices in row_nodes.items():
        glyphs = "".join(nodes[index][4] for index in indices)
        ordered = sorted((nodes[index][3] for index in indices), key=lambda box: box[0])
        union_box = (min(box[0] for box in ordered), min(box[1] for box in ordered),
                     max(box[2] for box in ordered), max(box[3] for box in ordered))
        height = median(box[3] - box[1] for box in ordered)
        centers = [(box[1] + box[3]) / 2 for box in ordered]
        row_glyphs = "".join(ch for ch in compact(rows[row]) if has_target_script(ch))
        complete_source = glyphs == row_glyphs
        compact_row = (max(centers) - min(centers) <= 0.7 * height and
                       all(right[0] - left[2] <= 1.5 * height for left, right in zip(ordered, ordered[1:])))
        if (complete_source and len(glyphs) >= 2 and verified(rows[row], union_box)
                and compact_row and 0.55 <= (union_box[2] - union_box[0]) / len(glyphs) /
                    (union_box[3] - union_box[1]) <= 1.35):
            # Tesseract can give the first glyph the whole word's envelope,
            # overlapping later glyphs. An exact whole-word crop proof remains
            # valid even though those boxes cannot form independent neighbors.
            proven_rows.add(row)
        density = (union_box[2] - union_box[0]) / len(glyphs) / height
        ordinary_glyphs = sum(len(nodes[index][4]) for index in indices if regular[index])
        # Tall overlapping OCR envelopes can make real Japanese rows look
        # narrow. Existing ordinary glyph boxes corroborate that case; a lone
        # square plus an implausibly narrow two-character guess does not.
        if (len(glyphs) >= 3 and any(ch not in confusable for ch in glyphs) and compact_row
                and (0.55 <= density <= 1.8 or (0.45 <= density < 0.55 and ordinary_glyphs >= 3))):
            context_rows.add(row)
        if row in context_rows or row in proven_rows:
            for index in indices:
                eligible[index] = True

    parents = list(range(len(nodes)))
    def group(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # Sharing a vertical bucket is necessary for comparable, same-baseline
    # glyphs. Sorting each bucket avoids comparing far-apart desktop controls.
    buckets = defaultdict(list)
    for index, (_, _, _, (left, top, right, bottom), _) in enumerate(nodes):
        if not eligible[index]:
            continue
        for band in range(math.floor(top / 64), math.floor(bottom / 64) + 1):
            buckets[band].append(index)
    compared = set()
    for indices in buckets.values():
        indices.sort(key=lambda index: nodes[index][3][0])
        tallest = max(heights[index] for index in indices)
        for offset, first in enumerate(indices):
            a = nodes[first][3]
            ah = heights[first]
            for second in indices[offset + 1:]:
                b = nodes[second][3]
                if b[0] - a[2] > 1.5 * tallest:
                    break
                pair = min(first, second), max(first, second)
                if pair in compared:
                    continue
                compared.add(pair)
                bh = heights[second]
                if (max(ah, bh) > 1.8 * min(ah, bh)
                        or abs((a[1] + a[3]) - (b[1] + b[3])) > 1.1 * max(ah, bh)
                        or b[0] - a[2] > 1.5 * max(ah, bh)
                        or b[0] - a[2] < -0.25 * min(a[2] - a[0], b[2] - b[0])
                        or abs((a[0] + a[2]) - (b[0] + b[2])) < 0.7 * min(ah, bh)):
                    continue
                parents[group(second)] = group(first)

    components = defaultdict(list)
    for index, node in enumerate(nodes):
        if eligible[index]:
            components[group(index)].append(index)
    supported = set()
    for key, indices in components.items():
        indices.sort(key=lambda index: nodes[index][3][0])
        glyphs = "".join(nodes[index][4] for index in indices)
        meaningful = any(ch not in confusable for ch in glyphs)
        boxes = [nodes[index][3] for index in indices]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        value = "".join(rows[nodes[index][0]][nodes[index][1]:nodes[index][2]] for index in indices)
        proof = verified(value, box)
        if len(glyphs) >= 3 and meaningful:
            supported.add(key)
        elif meaningful and (proof or all(verified(rows[nodes[index][0]][nodes[index][1]:nodes[index][2]],
                                                  nodes[index][3]) for index in indices)):
            supported.add(key)
        elif len(glyphs) >= 2 and proof:
            height = max(heights[index] for index in indices)
            # Tight text tracking can distinguish a verified word such as 一口
            # from spaced toolbar buttons. Confidence alone cannot do that.
            if (0.55 <= (box[2] - box[0]) / len(glyphs) / height <= 1.35 and
                    all(right[0] - left[2] <= 0.65 * height for left, right in zip(boxes, boxes[1:]))):
                supported.add(key)
    kept = defaultdict(list)
    for index, (row, start, end, box, _) in enumerate(nodes):
        # OCR word boxes inside an established source line can be very narrow
        # or have different ink heights. Do not turn a genuine sentence into
        # fragments merely because a short word lacks icon-sized proportions.
        if row in context_rows or row in proven_rows or (eligible[index] and group(index) in supported):
            kept[row].append((start, end, box))

    result, retained = [], []
    for row, line in enumerate(rows):
        spans = kept[row]
        if not spans:
            continue
        covered = {index for start, end, _ in spans for index in range(start, end)}
        cleaned = "".join(ch if not has_target_script(ch) or index in covered else " "
                          for index, ch in enumerate(line))
        trim = len(cleaned) - len(cleaned.lstrip())
        cleaned = cleaned.strip()
        result.append(cleaned)
        retained.append((cleaned, [(start - trim, end - trim, box) for start, end, box in spans]))
    positions[:] = retained
    return "\n".join(result)


def vertical_verifier_image(image, gap_ratio=0.16):
    """Reflow a clear upright Japanese column for a second horizontal read.

    This fallback is deliberately limited to an isolated column. Reading a
    horizontal English desktop as vertical Japanese can produce fluent-looking
    kana shapes when no separately installed English recognizer exists.
    """
    import numpy as np
    from PIL import Image
    gray = image.convert("L")
    if gray.width > 1600 or gray.height > 4000:
        return None
    hist = gray.histogram()
    background = max(range(256), key=hist.__getitem__)
    ink = np.abs(np.asarray(gray,dtype=np.int16)-background)>35
    occupied_y = np.flatnonzero(ink.any(axis=1))
    occupied_x = np.flatnonzero(ink.any(axis=0))
    if not len(occupied_x) or not len(occupied_y):
        return None
    width = int(occupied_x[-1]-occupied_x[0]+1)
    if width < 6 or occupied_y[-1]-occupied_y[0] < 1.8*width:
        return None
    bands = np.split(occupied_y,np.flatnonzero(np.diff(occupied_y)>max(2,width*gap_ratio))+1)
    if not 2 <= len(bands) <= 100:
        return None
    out = Image.new("L",(16+34*len(bands),58),background)
    for n,band in enumerate(bands):
        glyph = gray.crop((int(occupied_x[0]),int(band[0]),int(occupied_x[-1]+1),int(band[-1]+1)))
        if glyph.height > 1.7*width:
            return None
        target = (30,max(1,round(30*glyph.height/width)))
        out.paste(glyph.resize(target,Image.Resampling.LANCZOS),(8+34*n, max(0,(58-target[1])//2)))
    return out


class _InkCoverage:
    """Measure whether actual strokes in a broad CJK box belong to English words.

    Vertical OCR can assign a box as large as a whole line to one glyph. Pixel
    coverage avoids assuming every label in a mixed-language line is English.
    """
    def __init__(self, image, english):
        import numpy as np
        from PIL import Image
        ratio = min(1.0, 1400 / max(image.size))
        shape = tuple(max(1, round(v * ratio)) for v in image.size)
        reduced = image.resize(shape, Image.Resampling.BILINEAR) if shape != image.size else image
        self.sx, self.sy = shape[0] / image.width, shape[1] / image.height
        gray = np.asarray(reduced.convert("L"), dtype=np.int16)
        edges = np.zeros(gray.shape, dtype=bool)
        edges[:, 1:] |= np.abs(gray[:, 1:] - gray[:, :-1]) > 15
        edges[1:, :] |= np.abs(gray[1:, :] - gray[:-1, :]) > 15
        mask = np.zeros(gray.shape, dtype=bool)
        for hit in english:
            x0,y0,x1,y1 = self._box(hit.box)
            mask[max(0,y0-2):y1+2, max(0,x0-2):x1+2] = True
        self.edges, self.masked = edges, edges & mask

    def _box(self, box):
        l,t,r,b = box
        return math.floor(l*self.sx), math.floor(t*self.sy), math.ceil(r*self.sx), math.ceil(b*self.sy)

    def covered(self, box):
        x0,y0,x1,y1 = self._box(box)
        # Tesseract can publish boxes partly outside image bounds.
        roi = (slice(max(0,y0),max(0,y1)), slice(max(0,x0),max(0,x1)))
        total = self.edges[roi].sum()
        return total >= 4 and self.masked[roi].sum() >= total * 0.78


def verify_hangul_suffixes(image, raw, tsv, observations, read):
    """Check a short Latin OCR guess embedded inside an otherwise clear Hangul word."""
    if not observations or not any(_hangul(ch) for ch in raw):
        return observations
    guesses = [hit for hit in observations if re.fullmatch(r"[B-DF-HJ-NP-TV-Z]{2,4}[-.]?",hit.text)]
    if not guesses:
        return observations
    rows = {}
    for word in parse_tsv(tsv):
        rows.setdefault(word.line, []).append(word)
    unconfirmed = set()
    deadline = time.monotonic() + 1.5
    for words in rows.values():
        letters = "".join(w.text for w in words)
        hangul = "".join(c for c in letters if _hangul(c))
        if len(hangul) < 8 or any(c.isascii() and c.isalpha() for c in letters):
            continue
        # A standalone Latin label next to Hangul still receives the full English veto.
        suffix_hits = []
        for hit in guesses:
            overlaps = [i for i,w in enumerate(words) if _covers(w.box,hit.box)]
            if not overlaps or overlaps[0] == 0:
                continue
            start, end = overlaps[0]-1, overlaps[-1]+1
            term = "".join(w.text for w in words[start:end])
            if (len(term) >= 3 and all(_hangul(c) for c in term) and term in raw and
                    all(w.confidence >= 88 for w in words[start:end]) and
                    sum(sum(_hangul(c) for c in w.text) for i,w in enumerate(words)
                        if i not in overlaps and w.confidence >= 85) >= 6):
                suffix_hits.append(hit)
        if not suffix_hits:
            continue
        # The dedicated recognizer must reproduce the entire row, including the
        # disputed syllables, from these pixels before releasing any English veto.
        x = max(0,min(w.box[0] for w in words)-10)
        y = max(0,min(w.box[1] for w in words)-8)
        r = min(image.width,max(w.box[2] for w in words)+10)
        b = min(image.height,max(w.box[3] for w in words)+8)
        remaining = deadline - time.monotonic()
        if remaining < 0.08:
            break
        if r <= x or b <= y:
            continue
        checked = read(image.crop((x,y,r,b)), "kor", 7, min(1.2,remaining))
        if checked and "".join(c for c in checked[0] if _hangul(c)) == hangul:
            unconfirmed.update((h.text,h.box) for h in suffix_hits)
    return [h for h in observations if (h.text,h.box) not in unconfirmed]


def filter_words(raw, tsv, observations, image=None, positions=None, *, desktop_auto=False):
    """Preserve source spacing/layout where possible. Never reconstruct English as CJK."""
    if not has_target_script(raw):
        return ""
    words = parse_tsv(tsv)
    if not words:
        # A frame without usable spatial/confidence evidence cannot be safely
        # vetoed if English recognition found words occupying the same frame.
        return ""
    typical_height = {}
    if positions is not None:
        from statistics import median
        heights = {}
        for word in words:
            if has_target_script(word.text):
                heights.setdefault(word.line, []).append(word.box[3] - word.box[1])
        typical_height = {line: median(values) for line, values in heights.items() if len(values) >= 3}
    # Vertical buckets keep overlap tests linear in typical page height.
    # On slow/absent English OCR, require stronger evidence from CJK OCR.
    bins = {}
    for hit in observations or ():
        for bucket in range(hit.box[1] // 64, hit.box[3] // 64 + 1):
            bins.setdefault(bucket, []).append(hit.box)
    stroke_map = _InkCoverage(image, observations) if image is not None and observations else None
    # Without an English reader, a selected CJK recognizer can turn a fragment
    # of an English label into one plausible syllable. A tighter reread by the
    # same biased recognizer is not independent evidence for that weak first
    # guess. Full scenes require the existing strong-word threshold; explicit
    # crops and weak pieces supported by two strong words retain their path.
    minimum = 75 if desktop_auto and observations is None else 66 if observations is None or desktop_auto else 40
    vetoed = set()
    supported = {}
    for i, word in enumerate(words):
        if not has_target_script(word.text):
            continue
        similar = [ch for ch in word.text if has_target_script(ch)]
        repeated_box_shape = (len(similar) > 1 and len(set(similar)) == 1 and similar[0] in "ロ口ニ一" and
                              word.confidence < 70 and any(
                                  en[0] < word.box[2] and en[2] > word.box[0] and en[1] < word.box[3] and en[3] > word.box[1]
                                  for b in range(word.box[1] // 64, word.box[3] // 64 + 1) for en in bins.get(b, ())))
        l,t,r,b = word.box
        thin_key_stroke = (word.confidence < 65 and b-t <= 16 and r-l <= (b-t)*0.37 and
                           any(abs((y0+y1)-(t+b)) <= b-t and max(l-x1,x0-r) <= (b-t)*2.2
                               for band in range(t//64,b//64+1) for x0,y0,x1,y1 in bins.get(band,())))
        if (repeated_box_shape or thin_key_stroke or (stroke_map is not None and stroke_map.covered(word.box)) or
                any(_covers(word.box, en) for bucket in range(word.box[1] // 64, word.box[3] // 64 + 1)
                    for en in bins.get(bucket, ()))):
            vetoed.add(i)
        elif word.confidence >= max(minimum, 75):
            supported[word.line] = supported.get(word.line, 0) + 1
    cursor = 0
    chunks = []
    offset = 0
    accepted_words = []
    for i, word in enumerate(words):
        index = raw.find(word.text, cursor)
        if index < 0:
            # A difference between TSV and formatted text can occur with
            # ligatures. Drop uncorroborated target-script text in that gap.
            continue
        gap = raw[cursor:index]
        gap = "".join(ch for ch in gap if not has_target_script(ch))
        chunks.append(gap)
        offset += len(gap)
        # Japanese vertical glyphs and joined words can score zero inside a
        # clearly foreign line. Preserve them when two nearby words corroborate
        # the line and there is no spatial evidence of English at their position.
        reject = i in vetoed or (has_target_script(word.text) and word.confidence < minimum and
                                  supported.get(word.line, 0) < 2)
        piece = " " if reject else word.text
        if positions is not None and not reject and has_target_script(piece):
            from screen_geometry import physical_box, trim_oversized_word
            box = physical_box(image, trim_oversized_word(image, word.box, typical_height.get(word.line)))
            if box:
                accepted_words.append((offset, offset+len(piece), box))
        chunks.append(piece)
        offset += len(piece)
        cursor = index + len(word.text)
    chunks.append("".join(ch for ch in raw[cursor:] if not has_target_script(ch)))
    result = []
    offset = 0
    word_index = 0
    for line in "".join(chunks).splitlines(keepends=True):
        end = offset + len(line)
        start = offset + len(line) - len(line.lstrip())
        words_on_line = []
        while word_index < len(accepted_words) and accepted_words[word_index][0] < end:
            begin, stop, box = accepted_words[word_index]
            words_on_line.append((begin-start, stop-start, box))
            word_index += 1
        offset = end
        line = line.strip()
        if has_target_script(line) and not (observations and _ambiguous_mixed_line(line)):
            result.append(line)
            if positions is not None:
                positions.append((line, words_on_line))
    return "\n".join(result)
