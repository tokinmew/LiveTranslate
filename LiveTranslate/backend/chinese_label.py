"""Confirm uncertain, isolated horizontal Han labels on flat, bounded selections."""
from foreign_text import script
from ocr_guard import parse_tsv
from screen_geometry import map_crop


def _label_crop(image):
    from PIL import Image, ImageOps
    import numpy as np

    if (not isinstance(image, Image.Image) or image.width > 1100 or image.height > 400
            or image.width * image.height > 240000):
        return None
    gray = image.convert("L")
    histogram = gray.histogram()
    background = max(range(256), key=histogram.__getitem__)
    if sum(histogram[max(0,background-10):background+11]) < gray.width * gray.height * .74:
        return None
    ink = np.abs(np.asarray(gray, dtype=np.int16) - background) > 36
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if not len(rows) or not len(cols):
        return None
    left, top, right, bottom = int(cols[0]), int(rows[0]), int(cols[-1])+1, int(rows[-1])+1
    width, height = right - left, bottom - top
    if not (12 <= height <= 150 and 1.4 * height <= width <= 4.6 * height):
        return None
    if (np.diff(rows).max() > max(3, height * .15) or np.diff(cols).max() > height * .62
            or not .08 <= ink[top:bottom, left:right].mean() <= .58):
        return None
    box = left, top, right, bottom
    glyphs = gray.crop(box)
    if background < 128:
        glyphs = ImageOps.invert(glyphs)
        background = 255 - background
    # A consistent line height and margin give both recognizer modes room
    # around dense strokes on both dark and light user interfaces.
    target_height = 36
    padding = round(.15 * target_height)
    normalized = glyphs.resize((round(width * target_height / height), target_height), Image.Resampling.LANCZOS)
    padded = ImageOps.expand(normalized, border=padding, fill=background)
    return map_crop(padded, image, box, padding)


def _confident_han(result):
    if not result:
        return None
    text, tsv = result
    label = "".join(text.split())
    words = parse_tsv(tsv)
    if (not 2 <= len(label) <= 4 or any(script(ch) != "han" for ch in label)
            or not words or any(w.confidence < 85 for w in words)
            or len({w.line for w in words}) != 1 or "".join(w.text for w in words) != label):
        return None
    return label, min(w.confidence for w in words)


def confirm_label(image, primary, language, read):
    words = parse_tsv(primary[1])
    if (not words or not any(script(ch) == "han" for ch in primary[0])
            or all(w.confidence >= 85 for w in words)
            or any(w.confidence >= 80 and any(script(ch) in ("ja","ko") for ch in w.text) for w in words)
            or any(w.confidence >= 65 and any(ch.isascii() and ch.isalpha() for ch in w.text) for w in words)):
        return None
    crop = _label_crop(image)
    if crop is None:
        return None
    # A combined model may normalize Simplified characters to Traditional
    # just because Traditional occurs first in the automatic language list.
    anchors = {ch for w in words if w.confidence >= 40 for ch in w.text if script(ch) == "han"}
    candidates = []
    for code in (c for c in language.split("+") if c in ("chi_sim", "chi_tra")):
        row = _confident_han(read(crop, code, 7, 1.2))
        if not row:
            continue
        word = read(crop, code, 8, 1.2)
        single = _confident_han(word)
        if single and single[0] == row[0]:
            support = len(anchors.intersection(row[0]))
            candidates.append((support, min(single[1], row[1]), row[0], word))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = candidates[0]
    if len(candidates) > 1:
        other = candidates[1]
        if best[2] != other[2] and best[0] == other[0] and best[1] - other[1] < 8:
            return None
    return crop, best[3]
