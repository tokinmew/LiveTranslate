"""Keep the first accepted wording while the original lettering remains on screen."""
from collections import OrderedDict
import hashlib
import re
import unicodedata

from foreign_text import script
from screen_geometry import positioned_segments

_MEANING_MARKS = re.compile(
    r"[+-]?\d+(?:[.,:/－-]\d+)*|[零〇一二三四五六七八九十百千万萬亿億两兩壹貳參肆伍陸柒捌玖拾]+|"
    r"ません|ない|なかった|ぬ|ず|아니|아닌|안|않|없|못|[不无無没沒未非勿禁别別莫否]|[?!！？]")


def _sample_margin(box):
    return max(2, min(24, min(box[2]-box[0], box[3]-box[1])//2))


def _sample(image, left, top, box):
    x, y, right, bottom = box
    w, h = right - x, bottom - y
    if w <= 0 or h <= 0 or w*h > 196608:
        return None
    # Include the ends of the line. Appending a minus sign, digit, or negative
    # particle just outside the old OCR box must invalidate the old reading.
    margin = _sample_margin(box)
    x, y, right, bottom = x-left, y-top, right-left, bottom-top
    if not (0 <= x < right <= image.width and 0 <= y < bottom <= image.height):
        return None
    crop = image.crop((max(0,x-margin), max(0,y-margin), min(image.width,right+margin), min(image.height,bottom+margin)))
    raw = hashlib.blake2b(crop.tobytes(), digest_size=16).digest()
    gray = crop.convert("L")
    levels = gray.histogram()
    bg = max(range(256), key=levels.__getitem__)
    total = gray.width * gray.height
    if sum(levels[max(bg-6,0):bg+7]) < .62*total:
        return raw, None
    # A conservative second signature tolerates recoloring the same lettering
    # on flat panels. Require exact agreement on each thresholded pixel.
    distances = sorted(range(256), key=lambda level: abs(level-bg), reverse=True)
    count = 0
    contrast = 0
    for level in distances:
        count += levels[level]
        if count >= .02*total:
            contrast = abs(level-bg)
            break
    if contrast < 48:
        return raw, None
    threshold = [255 if abs(level-bg) >= contrast*.5 else 0 for level in range(256)]
    density = sum(n for n, active in zip(levels, threshold) if active) / total
    if not .018 <= density <= .38:
        return raw, None
    mask = gray.point(threshold, "1")
    return raw, hashlib.blake2b(mask.tobytes(), digest_size=16).digest()


def sample_frame(result, source_frame, tracking):
    if not tracking or source_frame is None:
        return result
    profile, tracked = tracking
    image, left, top = source_frame
    # A cache hit has identical geometry and pixels. Retain the measured
    # signatures and add only newly requested rectangles when necessary.
    samples = dict(getattr(result, "screen_samples", {}))
    current = (box for text, spans in result.regions for _,box in positioned_segments(text, spans, profile) if box)
    boxes = list(dict.fromkeys(tracked))[:32]
    for box in current:
        if box not in boxes:
            boxes.append(box)
        if len(boxes) >= 64:
            break
    budget = 1048576
    kept = {}
    for box in boxes:
        if box in samples:
            kept[box] = samples[box]
            continue
        size = (box[2]-box[0]) * (box[3]-box[1])
        if size > min(196608, budget):
            continue
        sample = _sample(image, left, top, box)
        if sample:
            kept[box] = sample
            budget -= size
    result.screen_samples = kept
    return result


def _identity(key):
    language, raw = key
    # Fold OCR width variants only. Whole-string NFKC would collapse
    # superscripts or circled quantities that can genuinely change meaning.
    value = unicodedata.normalize("NFC", "".join(
        unicodedata.normalize("NFKC", ch) if "\uff01" <= ch <= "\uff9f" or ch == "\u3000" else ch for ch in raw))
    value = " ".join(value.split())
    if language in ("han", "zh", "zt", "ja") and " " in value:
        # OCR can insert spaces between characters, but separated number
        # groups and a single compound number can mean different things.
        def native_space(match):
            left, right = value[match.start()-1], value[match.end()]
            if script(left) and script(right) and not (left.isnumeric() and right.isnumeric()):
                return ""
            return " "
        value = re.sub(" ", native_space, value)
    return language, value


def _overlap(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width*height
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0


class ScreenTracker:
    def __init__(self):
        self.previous = {}
        self.first = OrderedDict()

    def placements(self, observed, samples):
        available = dict(self.previous)
        output = []
        prior_order = []
        held = {}
        for key, box in observed:
            identity = _identity(key)
            stable = self.first.get(identity, key)
            match = None
            score = .70
            if box:
                for old, (old_key, saved, row, was_held) in available.items():
                    agreement = _overlap(box, old)
                    if agreement < score:
                        continue
                    # The old patch cannot confirm words outside its measured
                    # pixels or justify carrying omitted words into a shorter box.
                    within_margin = box == old or max(abs(a-b) for a,b in zip(box, old)) <= _sample_margin(old)
                    probes = [samples.get(old)] if within_margin else []
                    if box != old and (box[2]-box[0],box[3]-box[1]) == (old[2]-old[0],old[3]-old[1]):
                        # Text and its OCR box may scroll together. Compare
                        # the complete translated source patch at its new origin.
                        probes.append(samples.get(box))
                    same_rgb = saved and any(p and p[0] == saved[0] for p in probes)
                    identical_ink = (saved and saved[1] and any(p and p[1] == saved[1] for p in probes) and
                                     _MEANING_MARKS.findall(key[1]) == _MEANING_MARKS.findall(old_key[1]))
                    if (identity == _identity(old_key) or
                            same_rgb or identical_ink):
                        match, score = old, agreement
            if match is not None:
                stable = available.pop(match)[0]
                prior_order.append(match)
            output.append((stable, box))
        for box, (key, saved, row, was_held) in available.items():
            now = samples.get(box)
            if (not was_held and now and saved and now[0] == saved[0]
                    and not any(new_box and _overlap(box,new_box) > .05 for _,new_box in observed)):
                # Bridge only one incomplete observation. Reuse the old patch
                # only when the exact original RGB pixels still match.
                held[box] = row
                output.append((key, box))
                prior_order.append(box)
        if prior_order and len(prior_order) == len(output) == len(self.previous):
            placed = dict(zip(prior_order, output))
            output = [placed[box] for box in self.previous]
        return tuple(output), held

    def accept(self, placements, result, samples, held):
        rows = {}
        for row in result.get("regions", ()):
            x, y = row["left"], row["top"]
            box = x, y, x+row["width"], y+row["height"]
            if box in held and row is not held[box]:
                row.clear()
                row.update(held[box])
            rows[box] = row
        current = {}
        for key, box in placements:
            if box not in rows or rows[box].get("original") != key[1]:
                continue
            identity = _identity(key)
            if len(key[1]) <= 2048:
                self.first[identity] = key
                self.first.move_to_end(identity)
                if len(self.first) > 512:
                    self.first.popitem(last=False)
            if len(current) < 32:
                current[box] = key, samples.get(box), rows[box], box in held
        self.previous = current
