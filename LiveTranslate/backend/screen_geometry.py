"""Carry OCR word positions through image preparation into Windows desktop pixels."""
import math


class LocatedText(str):
    def __new__(cls, text, regions=()):
        value = super().__new__(cls, text)
        value.regions = tuple(regions)
        return value


def capture_map(image, rect):
    info = getattr(image, "info", None)
    if isinstance(info, dict) and "desktop_map" not in info:
        info["desktop_map"] = (rect.get("left", 0), rect.get("top", 0),
                               rect.get("width", image.width) / image.width,
                               rect.get("height", image.height) / image.height)


def map_crop(child, parent, box, padding=0):
    """Map a padded/resized child to the rectangle it was sampled from."""
    left, top, right, bottom = box
    x, y, sx, sy = parent.info.get("desktop_map", (0, 0, 1, 1))
    dx = sx * (right - left) / (child.width - 2 * padding)
    dy = sy * (bottom - top) / (child.height - 2 * padding)
    child.info["desktop_map"] = (x + sx * left - dx * padding, y + sy * top - dy * padding, dx, dy)
    child.info["content_box"] = (padding, padding, child.width - padding, child.height - padding)
    return child


def physical_box(image, box):
    info = getattr(image, "info", None)
    if not isinstance(info, dict):
        return None
    left, top, right, bottom = box
    mapping = info.get("desktop_map")
    content = info.get("content_box")
    for start, end, row_map, row_content in info.get("desktop_rows", ()):
        if start <= (top + bottom) / 2 < end:
            top, bottom, mapping = top - start, bottom - start, row_map
            content = row_content
            break
    if mapping is None:
        return None
    if content:
        left, top = max(left, content[0]), max(top, content[1])
        right, bottom = min(right, content[2]), min(bottom, content[3])
        if right <= left or bottom <= top:
            return None
    x, y, sx, sy = mapping
    return (math.floor(x + sx * left), math.floor(y + sy * top),
            math.ceil(x + sx * right), math.ceil(y + sy * bottom))


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def positioned_segments(text, words, source):
    if source not in ("auto", "zh", "zt", "ko", "ja"):
        # The explicit-language reader classifies each physically distinct
        # label before exposing it as a LocatedText region.
        if source != "en" and text.strip() and words:
            yield (source, text.strip()), union([box for _, _, box in words])
        return
    from foreign_text import located_foreign_segments

    segments = []
    for hint, _, start, stop in located_foreign_segments(text, source):
        # Some engines deliver a whole caption/vertical column as one
        # OCR token, including sentence breaks. Its individual sentences
        # cannot be positioned separately; translate their shared box once.
        if segments:
            prior_hint, first, last = segments[-1]
            if ((hint == prior_hint or "han" in (hint, prior_hint)) and not text[last:start].strip()
                    and any(begin < last and end > start for begin, end, _ in words)):
                # A neighboring phonetic script identifies an otherwise
                # ambiguous Han sentence in this same indivisible OCR token.
                segments[-1] = (prior_hint if hint == "han" else hint), first, stop
                continue
        segments.append((hint, start, stop))

    for hint, start, stop in segments:
        boxes = []
        for begin, end, box in words:
            if begin >= stop or end <= start:
                continue
            # When OCR supplies only one box for a mixed-language token,
            # there are no measured glyph coordinates for the accepted part.
            # Keep it in the transcript rather than obscuring its neighbor.
            outside = text[begin:start] + text[stop:end]
            if any(c.isalnum() for c in outside):
                boxes = []
                break
            boxes.append(box)
        key = (hint, " ".join(text[start:stop].split()))
        yield key, union(boxes) if boxes else None


def trim_oversized_word(image, box, typical_height):
    """Some Tesseract suffix boxes span the capture. Trim clear margins for placement only."""
    if typical_height is None or box[3] - box[1] <= 1.6 * typical_height:
        return box
    from PIL import Image
    if not isinstance(image, Image.Image):
        return box
    left, top = max(0, box[0]), max(0, box[1])
    right, bottom = min(image.width, box[2]), min(image.height, box[3])
    area = (right - left) * (bottom - top)
    if right <= left or bottom <= top or area > 400000:
        return box
    patch = image.crop((left, top, right, bottom)).convert("L")
    counts = patch.histogram()
    background = max(range(256), key=counts.__getitem__)
    if sum(counts[max(0, background-10):background+11]) < area * 0.68:
        return box
    ink = patch.point([255 if abs(level-background) > 38 else 0 for level in range(256)]).getbbox()
    if ink and ink[3] - ink[1] >= typical_height * 0.3:
        return left + ink[0], top + ink[1], left + ink[2], top + ink[3]
    return box


def _separate_labels(first, second):
    """Treat a full glyph-sized gutter as a label break in the writing direction."""
    left, top, right, bottom = first
    x, y, end_x, end_y = second
    gap_x = max(x - right, left - end_x)
    gap_y = max(y - bottom, top - end_y)
    if gap_y <= 0:
        em = min(bottom - top, end_y - y)
        return gap_x >= max(6, 1.2 * em)
    if gap_x <= 0:
        # Vertically stacked Japanese glyphs within the same column should
        # stay together when their spacing follows the local character width.
        em = min(right - left, end_x - x)
        return gap_y >= max(6, 1.2 * em)
    # Raised punctuation and small kana can leave a few blank pixels on
    # both axes while still belonging to the preceding word.
    return math.hypot(gap_x, gap_y) >= max(6, 0.75 * min(bottom - top, end_y - y))


def line_regions(line, words):
    """Split neighboring labels at physical gutters, retaining logical OCR order."""
    start = 0
    group = []
    for pos, end, box in words:
        if group:
            prev = group[-1][2]
            if _separate_labels(prev, box):
                split = group[-1][1]
                yield line[start:split], [(s - start, e - start, b) for s, e, b in group]
                start, group = split, []
        group.append((pos, end, box))
    if group:
        yield line[start:], [(s - start, e - start, b) for s, e, b in group]
