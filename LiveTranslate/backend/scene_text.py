"""Find horizontal text over photos and game scenery before invoking desktop OCR."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    box: tuple
    mask: object
    area: int
    bright: bool
    contrast: float


def _textured(gray):
    import numpy as np
    from PIL import Image

    sample = gray.resize((min(192, gray.width), min(132, gray.height)), Image.Resampling.BILINEAR)
    values = np.asarray(sample)
    histogram = np.bincount(values.ravel(), minlength=256)
    flat_fraction = np.convolve(histogram, np.ones(7), mode="same").max() / values.size
    return flat_fraction < 0.57 and np.percentile(values, 90) - np.percentile(values, 10) > 22


def _seeds(pixels, mask, bright):
    """Identify rows with multiple letter-like components on a common baseline."""
    import numpy as np
    from scipy import ndimage

    neighbors = np.ones((3, 3), bool)
    labels, count = ndimage.label(mask, neighbors)
    if count == 0 or count > 65000:
        return []
    sizes = np.bincount(labels.ravel())
    boxes = ndimage.find_objects(labels)
    keep = np.zeros(count + 1, bool)
    for index, (ys, xs) in enumerate(boxes, 1):
        height, width = ys.stop - ys.start, xs.stop - xs.start
        if not (2 <= height <= 96 and width <= min(170, 6 * height) and height <= 5 * width):
            continue
        density = sizes[index] / (width * height)
        keep[index] = sizes[index] >= 3 and 0.08 <= density <= 0.97
    if not keep.any():
        return []
    filtered = keep[labels]
    groups = ndimage.maximum_filter1d(filtered, 11, axis=1)
    groups = ndimage.maximum_filter1d(groups, 3, axis=0)
    grouped, count = ndimage.label(groups, neighbors)
    areas = np.bincount(grouped[filtered], minlength=count + 1)
    candidates = []
    for index, (ys, xs) in enumerate(ndimage.find_objects(grouped), 1):
        height, width = ys.stop - ys.start, xs.stop - xs.start
        if not (7 <= height <= 100 and max(10, height * 0.6) <= width <= min(2800, height * 100)):
            continue
        if areas[index] < 24 or not 0.055 <= areas[index] / (height * width) <= 0.58:
            continue
        ink = filtered[ys, xs] & (grouped[ys, xs] == index)
        pieces = np.unique(labels[ys, xs][ink])
        if len(pieces) < 4:
            continue
        heights = [boxes[p - 1][0].stop - boxes[p - 1][0].start for p in pieces if sizes[p] >= 6]
        if len(heights) < 2 or np.percentile(heights, 80) < 4 or sum(h >= 0.30 * height for h in heights) < 2:
            continue
        margin = max(4, height // 3)
        context = pixels[max(0, ys.start - margin):ys.stop + margin, max(0, xs.start - margin):xs.stop + margin]
        contrast = abs(np.median(pixels[ys, xs][ink]) - np.median(context))
        if contrast >= 30:
            candidates.append(Candidate((xs.start, ys.start, xs.stop, ys.stop), ink, areas[index], bright, contrast))
    return candidates


def _overlap(first, second):
    x, y, right, bottom = first
    left, top, end, base = second
    intersection = max(0, min(right, end) - max(left, x)) * max(0, min(bottom, base) - max(top, y))
    return intersection / min((right - x) * (bottom - y), (end - left) * (base - top))


def _lines(candidates):
    # Prefer the fill over the weaker outline of the same glyph. Bound work
    # before OCR on an unusually busy screen containing many potential rows.
    selected = []
    for row in sorted(candidates, key=lambda r: r.contrast ** 1.7 * r.area ** 0.6, reverse=True):
        if all(_overlap(row.box, old.box) <= 0.5 for old in selected):
            selected.append(row)
            if len(selected) >= 40:
                break
    lines = []
    for row in sorted(selected, key=lambda r: (r.box[0], r.box[1])):
        x, y, right, bottom = row.box
        for line in lines:
            previous = line[-1]
            left, top, end, base = previous.box
            height = max(bottom - y, base - top)
            if (row.bright == previous.bright and min(bottom, base) - max(y, top) >= 0.55 * height
                    and x - end <= 2.1 * height and abs(y - top) < 0.45 * height):
                line.append(row)
                break
        else:
            lines.append([row])
    return lines


def _clean_line(line, pixels, english_boxes):
    import numpy as np
    from PIL import Image, ImageOps
    from scipy import ndimage

    x = min(part.box[0] for part in line)
    y = min(part.box[1] for part in line)
    right = max(part.box[2] for part in line)
    bottom = max(part.box[3] for part in line)
    rect = pixels[y:bottom, x:right]
    ink = np.zeros(rect.shape, bool)
    for part in line:
        left, top, end, base = part.box
        ink[top-y:base-y, left-x:end-x] |= part.mask
    covered = np.zeros(rect.shape, bool)
    for left, top, end, base in english_boxes:
        if left < right and end > x and top < bottom and base > y:
            covered[max(0, top-2-y):max(0, base+2-y), max(0, left-2-x):max(0, end+2-x)] = True
    if (covered & ink).sum() > 0.65 * ink.sum():
        return None
    tone = float(np.median(rect[ink]))
    background = float(np.median(rect[~ink]))
    if abs(tone - background) < 20:
        return None
    # Extend past a word whose edge character did not seed a component.
    # Adjacent glyphs need matching fill, height and short horizontal gaps.
    height = bottom - y
    margin = max(2, round(0.12 * height))
    top, base = max(0, y - margin), min(pixels.shape[0], bottom + margin)
    strip = pixels[top:base]
    threshold = background + 0.43 * (tone - background)
    if line[0].bright:
        matching = (strip > threshold) & (strip > tone - 46)
    else:
        matching = (strip < threshold) & (strip < tone + 46)
    cols = np.flatnonzero(matching.sum(axis=0) >= max(2, round(0.1 * height)))
    for group in np.split(cols, np.flatnonzero(np.diff(cols) > max(7, 1.3 * height)) + 1):
        if len(group) and group[-1] >= x and group[0] <= right and group[-1] - group[0] < height * 82:
            if group[-1] - group[0] > 4 * (right - x):
                # A small seed extending through several times its own width
                # on similarly colored scenery needs independent glyph seeds.
                return None
            x, right = max(0, min(x, int(group[0]) - 3)), min(pixels.shape[1], max(right, int(group[-1]) + 4))
            y, bottom = top, base
            break
    # Restore antialiasing against a clean background using the local fills.
    # This preserves thin Hangul strokes which a binary mask can join.
    weights = (pixels[y:bottom, x:right] - background) / (tone - background)
    values = np.clip((weights - 0.38) / 0.58, 0, 1)
    foreground = Image.fromarray((values * 255).astype(np.uint8))
    bounds = foreground.point(lambda value: 255 if value > 60 else 0).getbbox()
    if bounds is None:
        return None
    crop = ImageOps.invert(foreground.crop(bounds))
    # Preserve a little more interpolation detail for small source lettering.
    # Larger display glyphs can be downsampled to the standard OCR line size.
    normalized_height = 32 if crop.height <= 36 else 30
    width = max(1, round(crop.width * normalized_height / crop.height))
    if width > 3000:
        return None
    crop = crop.resize((width, normalized_height), Image.Resampling.LANCZOS)
    ink = np.asarray(crop) < 155
    if not ink.any():
        return None
    # Scenery can contain baseline-like rows of filled silhouettes. Ordinary
    # glyphs at this normalized height consist predominantly of narrow strokes.
    radius = ndimage.distance_transform_edt(np.pad(ink, 1))[1:-1, 1:-1]
    if np.count_nonzero(radius > normalized_height / 5) > np.count_nonzero(ink) * 0.02:
        return None
    contrast = sum(part.contrast * part.area for part in line) / sum(part.area for part in line)
    padded = ImageOps.expand(crop, border=12, fill=255)
    padded.info["scene_crop"] = (x+bounds[0], y+bounds[1], x+bounds[2], y+bounds[3])
    return (x, y, right, bottom), padded, contrast


def textured_rows(image, detect_english):
    """Return None for flat documents, or individually prepared rows for scenery."""
    from PIL import Image, ImageFilter
    import numpy as np

    if not isinstance(image, Image.Image):
        return None
    gray = image if image.mode == "L" else image.convert("L")
    if not _textured(gray):
        return None
    scale = min(1, 2400 / max(gray.size), (3200000 / (gray.width * gray.height)) ** 0.5)
    if scale < 1:
        gray = gray.resize(tuple(max(1, round(n * scale)) for n in gray.size), Image.Resampling.BILINEAR)
    pixels = np.asarray(gray, dtype=np.int16)
    blur = np.asarray(gray.filter(ImageFilter.GaussianBlur(3.5)), dtype=np.int16)
    candidates = _seeds(pixels, (pixels - blur >= 24) & (pixels > 65), True)
    candidates.extend(_seeds(pixels, (blur - pixels >= 24) & (pixels < 195), False))
    if not candidates:
        return []
    observations = detect_english(gray) or ()
    english_boxes = [word.box for word in observations]
    rows = []
    for line in _lines(candidates):
        row = _clean_line(line, pixels, english_boxes)
        if row is None:
            continue
        for index, prior in enumerate(rows):
            if _overlap(row[0], prior[0]) > 0.65:
                # Two seeds can recover the same word from the fill and its
                # outline. Prefer the high-contrast fill over the near-empty
                # outline even if its normalized bounding box is narrower.
                if row[2] > prior[2]:
                    rows[index] = row
                break
        else:
            rows.append(row)
    from screen_geometry import map_crop
    sx, sy = image.width / gray.width, image.height / gray.height
    for _, row, _ in rows:
        a, b, c, d = row.info["scene_crop"]
        map_crop(row, image, (a*sx,b*sy,c*sx,d*sy), 12)
    return [row[1] for row in sorted(rows, key=lambda item: (item[0][1], item[0][0]))]


def confirmed_scene_row(recognition):
    """Short HUD hints need a confidently recognized foreign word."""
    if not recognition:
        return recognition
    from ocr_guard import has_target_script, parse_tsv
    text, geometry = recognition
    if sum(has_target_script(char) for char in text) > 4:
        return recognition
    words = [w for w in parse_tsv(geometry) if has_target_script(w.text)]
    if words and max(w.confidence for w in words) < 68:
        return "", ""
    return recognition
