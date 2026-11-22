"""Recover the local background behind source lettering in physical screen pixels."""
import base64
import io
import math

from foreign_text import script


MAX_SIDE = 2048
MAX_REGION_PIXELS = 65536
MAX_PNG = 32768
MAX_FRAME_PNG = 96 * 1024
MAX_FRAME_PIXELS = 4 * MAX_REGION_PIXELS
MAX_WORDS = 128


class _WordCovers(dict):
    """Keep replacements and their local panel colors together through the watch cache."""
    def __init__(self):
        super().__init__()
        self.colors = {}

    def __eq__(self, other):
        return isinstance(other, dict) and dict.__eq__(self, other) and self.colors == getattr(other, "colors", {})

    def __ne__(self, other):
        return not self == other


def _size_allowed(width, height):
    return (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE and
            width * height <= MAX_REGION_PIXELS)


def _encode(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=2)
    data = buf.getvalue()
    return data if len(data) <= MAX_PNG else None


def _packed_color(color):
    rr, gg, bb = (int(max(0,min(255,round(channel)))) for channel in color)
    return rr << 16 | gg << 8 | bb


def _border_color(image, box):
    """Sample narrow edges even when an entire repair would exceed its pixel budget."""
    from PIL import Image
    import numpy as np

    l,t,r,b = box
    samples = []
    for y in {max(0,t-1), min(image.height-1,b)}:
        strip = image.crop((l,y,r,y+1)).convert("RGB")
        samples.extend(np.asarray(strip.resize((min(r-l,32),1),Image.Resampling.NEAREST))[0])
    for x in {max(0,l-1), min(image.width-1,r)}:
        strip = image.crop((x,t,x+1,b)).convert("RGB")
        samples.extend(np.asarray(strip.resize((1,min(b-t,32)),Image.Resampling.NEAREST))[:,0])
    return _packed_color(np.median(samples,axis=0))


def _background(rgb):
    """Fit a smooth RGB panel to a trimmed sample, excluding letters and outlines."""
    import numpy as np

    height, width, _ = rgb.shape
    step_x, step_y = max(1, math.ceil(width / 64)), max(1, math.ceil(height / 48))
    y, x = np.mgrid[0:height:step_y, 0:width:step_x]
    xn = x.ravel() / max(1, width - 1)
    yn = y.ravel() / max(1, height - 1)
    plane = np.column_stack((np.ones(xn.size), xn, yn))
    pixels = rgb[::step_y, ::step_x].reshape(-1, 3).astype(np.float64)
    if len(pixels) < 12:
        return None
    # Cell medians initialize the fit without letting a dark stroke pull the
    # background toward the foreground. Include all real pixels at the crop edge.
    centers, colors = [], []
    cells_x = np.minimum((3 * xn).astype(int), 2)
    cells_y = np.minimum((3 * yn).astype(int), 2)
    for cell_y in range(3):
        for cell_x in range(3):
            cell = (cells_x == cell_x) & (cells_y == cell_y)
            if cell.any():
                centers.append(plane[cell].mean(axis=0))
                colors.append(np.median(pixels[cell], axis=0))
    coeff = np.linalg.lstsq(centers, colors, rcond=None)[0]
    for _ in range(3):
        err = np.abs(pixels - plane @ coeff).max(axis=1)
        threshold = min(48., max(6., float(np.quantile(err, .58)) * 1.6 + 2.))
        keep = err <= threshold
        if np.count_nonzero(keep) < len(err) * .53:
            return None
        coeff = np.linalg.lstsq(plane[keep], pixels[keep], rcond=None)[0]
    error = np.abs(pixels - plane @ coeff).max(axis=1)
    noise = float(np.quantile(error, .55))
    if noise > 13.0:
        return None
    return coeff, noise


def _repair(actual, predicted, noise):
    from PIL import Image, ImageFilter
    import numpy as np

    predicted = np.clip(predicted, 0, 255)
    residual = np.abs(actual - predicted).max(axis=2)
    strong = residual >= max(16., 3.6 * noise + 8.)
    fraction = np.count_nonzero(strong) / strong.size
    if fraction < .009 or fraction > .78:
        return None
    # Recover low-contrast antialiasing only beside high-confidence strokes.
    near = np.asarray(Image.fromarray(strong.astype("uint8") * 255).filter(ImageFilter.MaxFilter(3))) > 0
    ink = near & (residual > max(2., 2.0 * noise + 1.))
    if (np.count_nonzero(ink) > .84 * ink.size or
            np.count_nonzero((~ink) & (residual > max(6., 2.7 * noise + 1.))) > .03 * ink.size):
        return None
    # Never include the original pixels or even their RGB in transparent space.
    # Only the estimated background under source ink crosses the worker boundary.
    repair = np.zeros((*actual.shape[:2], 4), dtype="uint8")
    repair[ink, :3] = np.rint(predicted[ink]).astype("uint8")
    repair[ink, 3] = 255
    return _encode(Image.fromarray(repair))


def _continue_rows(rgb, top, bottom, left, right):
    """Continue vertical stripes, repeating textures, or a gradient between exterior rows."""
    import numpy as np

    height = bottom - top
    above, below = top, len(rgb) - bottom
    if not above or not below:
        return None
    period = 1
    limit = min(12, above, below, height // 2)
    if limit >= 2:
        # Look for a period in columns outside the source ink. A pattern with
        # a longer period than the observed margins cannot be reconstructed.
        sides = np.concatenate((rgb[:, max(0, left-3):left], rgb[:, right:right+3]), axis=1)
        if sides.shape[1]:
            errors = [np.abs(sides[p:] - sides[:-p]).mean() for p in range(1, limit+1)]
            best = int(np.argmin(errors))
            if best and errors[best] < min(4., errors[0]*.45):
                period = best + 1
    ys = np.arange(top, bottom)
    first = top - 1 - ((top - 1 - ys) % period)
    last = bottom + ((ys - bottom) % period)
    blend = ((ys - first) / (last - first)).astype(np.float32)[:, None, None]
    return rgb[first, left:right] * (1-blend) + rgb[last, left:right] * blend


def _inpaint_distinct_ink(rgb, actual, edges, left, top):
    """Replace a distinctive ink color on an irregular surface using nearby clean pixels."""
    import numpy as np
    from PIL import Image, ImageFilter

    low, high = np.quantile(edges,[.02,.98],axis=0)
    if np.max(high-low) > 125.:
        return None
    outside = np.maximum(actual-high,low-actual).max(axis=2)
    unusual = outside > 32.
    if not .012 <= unusual.mean() <= .65:
        return None
    colors = actual[unusual].astype(np.int32)
    bins = colors >> 4
    keys = (bins[:,0] << 8) | (bins[:,1] << 4) | bins[:,2]
    mode = np.bincount(keys,minlength=4096).argmax()
    foreground = np.median(colors[keys==mode],axis=0)
    core = unusual & (np.abs(actual-foreground).max(axis=2) <= 22.)
    if core.sum() < max(4.,actual.shape[0]*actual.shape[1]*.015):
        return None
    y,x = np.nonzero(core)
    if x.max()-x.min()+1 < .43*actual.shape[1] or y.max()-y.min()+1 < .43*actual.shape[0]:
        return None
    if np.mean(np.abs(edges-foreground).max(axis=1) <= 22.) > .015:
        return None
    core_image = Image.fromarray(core.astype("uint8")*255)
    near = np.asarray(core_image.filter(ImageFilter.MaxFilter(3))) > 0
    fringe = np.asarray(core_image.filter(ImageFilter.MaxFilter(5))) > 0
    erase = near | (fringe & (outside>3.))
    if erase.mean() > .80 or np.count_nonzero((outside>16.) & ~erase) > max(1,.004*erase.size):
        return None
    # Progressive normalized averaging cannot sample any identified ink.
    # Thin antialiased edges use their nearest background while thicker
    # strokes get a larger neighborhood. The rest of the scene remains live.
    ys = slice(top,top+actual.shape[0])
    xs = slice(left,left+actual.shape[1])
    clean = np.ones(rgb.shape[:2],dtype=bool)
    clean[ys,xs] = ~erase
    color_image = Image.fromarray(np.where(clean[...,None],rgb,0).astype("uint8"))
    weight_image = Image.fromarray(clean.astype("uint8")*255)
    result = np.zeros((*erase.shape,4),dtype="uint8")
    remaining = erase.copy()
    for radius in (2,4,8,16):
        blur = ImageFilter.BoxBlur(radius)
        weight = np.asarray(weight_image.filter(blur))[ys,xs]
        active = remaining & (weight >= 42)
        if active.any():
            summed = np.asarray(color_image.filter(blur))[ys,xs][active].astype(np.float32)
            result[active,:3] = np.rint(summed*(255./weight[active,None])).clip(0,255).astype("uint8")
            result[active,3] = 255
            remaining[active] = False
        if not remaining.any():
            return _encode(Image.fromarray(result))
    return None


def _word_patch(image, box):
    import numpy as np

    l, t, r, b = box
    margin = min(12, max(3, min(r-l,b-t) // 2))
    x0, y0 = max(0,l-margin), max(0,t-margin)
    x1, y1 = min(image.width,r+margin), min(image.height,b+margin)
    rgb = np.asarray(image.crop((x0,y0,x1,y1)).convert("RGB"))
    left, top, right, bottom = l-x0, t-y0, r-x0, b-y0
    outer = np.ones(rgb.shape[:2], dtype=bool)
    outer[top:bottom,left:right] = False
    actual = rgb[top:bottom,left:right].astype(np.float32)
    # Sample near the outside border; at a capture edge, use the other sides.
    # If the entire capture is one word, a robust interior median is the fallback.
    adjacent = np.s_[max(0,top-3):bottom+3,max(0,left-3):right+3]
    edges = rgb[adjacent][outer[adjacent]] if outer.any() else actual.reshape(-1,3)
    edges = edges[::max(1, len(edges)//2048)]
    sampled = np.median(edges,axis=0)
    color = _packed_color(sampled)
    if np.all(edges == sampled):
        predicted = np.broadcast_to(sampled, actual.shape)
        return _repair(actual, predicted, 0.), color

    # Excluding a larger border from the plane fit avoids contamination by
    # neighboring controls. More samples remain available for periodic textures.
    pad = min(5, max(2, min(r-l,b-t)//5))
    a, c = max(0,top-pad), min(len(rgb),bottom+pad)
    d, f = max(0,left-pad), min(rgb.shape[1],right+pad)
    neighborhood = rgb[a:c,d:f]
    fit = _background(neighborhood)
    if fit is not None:
        coeff, noise = fit
        y, x = np.mgrid[:c-a,:f-d]
        predicted = coeff[0] + x[...,None]*(coeff[1]/max(1,f-d-1)) + y[...,None]*(coeff[2]/max(1,c-a-1))
        near = outer[a:c,d:f]
        edge_error = np.abs(neighborhood[near] - predicted[near]).max(axis=1)
        if not len(edge_error) or np.mean(edge_error > max(17.,noise*3.+7.)) <= .13:
            estimate = predicted[top-a:bottom-a,left-d:right-d]
            patch = _repair(actual, estimate, noise)
            if patch is not None and noise <= 1.5 and (not len(edge_error) or edge_error.max() <= 8.):
                return patch, _packed_color(np.mean(estimate,axis=(0,1)))
        else:
            patch = None
    else:
        patch = None
    # Directional reconstruction uses only exterior pixels and must also agree
    # with most of the interior. A busy photograph that fails that test keeps
    # just its sampled color as an opaque last resort.
    context = rgb.astype(np.float32)
    # Reserve one known row/column around the word to score how each proposed
    # background crosses the seam. This protects a thin stripe passing behind it.
    a, c = max(0,top-1), min(len(rgb),bottom+1)
    d, f = max(0,left-1), min(rgb.shape[1],right+1)
    vertical = _continue_rows(context,a,c,d,f)
    crosswise = _continue_rows(context.transpose(1,0,2),d,f,a,c)
    horizontal = None if crosswise is None else crosswise.transpose(1,0,2)
    candidates = [value for value in (vertical,horizontal) if value is not None]
    if vertical is not None and horizontal is not None:
        candidates.append(.5*(vertical+horizontal))
    estimate = None
    best_score = float("inf")
    best_error = 0.
    for candidate in candidates:
        seam = outer[a:c,d:f]
        if not seam.any():
            continue
        border_error = np.abs(context[a:c,d:f][seam]-candidate[seam]).max(axis=1)
        # A few neighboring marks may touch the ring; tolerate sparse outliers.
        ring_error = np.minimum(border_error,48.).mean()
        candidate = candidate[top-a:bottom-a,left-d:right-d]
        error = np.abs(actual-candidate).max(axis=2)
        typical = float(np.quantile(error, .55))
        score = typical + ring_error
        if typical <= 7. and ring_error <= 8. and score < best_score and np.mean(error < 16.) > .55:
            estimate, best_error, best_score = candidate, typical, score
    if estimate is not None:
        recovered = _repair(actual,estimate,best_error)
        if recovered is not None:
            return recovered, _packed_color(np.mean(estimate,axis=(0,1)))
    local = _inpaint_distinct_ink(rgb,actual,edges,left,top)
    if local is not None:
        return local, color
    return patch, color


def collect_covers(ocr_image, located):
    """Return bounded PNG repairs keyed by physical OCR boxes from this capture."""
    from PIL import Image

    meta = getattr(ocr_image, "info", None)
    frame = meta.get("glyph_source") if isinstance(meta, dict) else None
    if not isinstance(frame, tuple) or len(frame) != 3:
        return {}
    image, left, top = frame
    if not isinstance(image, Image.Image):
        return {}
    covers = _WordCovers()
    pixels, encoded = 0, 0
    for line, spans in getattr(located, "regions", ()):
        for start, end, box in spans:
            word = line[start:end]
            if not box:
                continue
            box = tuple(box)
            if box in covers:
                continue
            if len(covers) >= MAX_WORDS:
                # Unexamined boxes could overlap a contextual phrase. Use its
                # unambiguous cover fallback instead of sending a partial repair.
                return {}
            # Unknown words must remain present as sentinels, so a phrase can
            # never receive a repair that leaves an unaccounted source word.
            covers[box] = None
            if (not getattr(located, "verified_source", None) and
                    (not any(script(ch) for ch in word) or any(ch.isalpha() and not script(ch) for ch in word))):
                continue
            l, t, r, b = box
            width, height = r - l, b - t
            if not (left <= l < r <= left + image.width and top <= t < b <= top + image.height):
                continue
            local = l-left, t-top, r-left, b-top
            if not _size_allowed(width,height) or pixels+width*height > MAX_FRAME_PIXELS or encoded >= MAX_FRAME_PNG:
                covers.colors[box] = _border_color(image,local)
                continue
            pixels += width * height
            data, color = _word_patch(image, local)
            covers.colors[box] = color
            if data is not None and encoded + len(data) <= MAX_FRAME_PNG:
                covers[box] = data
                encoded += len(data)
    return covers if covers.colors else {}


def attach_covers(regions, covers):
    """Attach repairs only to translated, physically located screen results."""
    if not covers:
        return
    from PIL import Image

    sent = 0
    for region in regions[:32]:
        l, t = region["left"], region["top"]
        width, height = region["width"], region["height"]
        rect = l, t, l + width, t + height
        matches = [(box, data) for box, data in covers.items() if
                   box[0] < rect[2] and l < box[2] and box[1] < rect[3] and t < box[3]]
        colors = getattr(covers,"colors",{})
        sampled = [b for b,_ in matches if b in colors]
        if sampled:
            # Use the physical panel behind the largest word. Channel-wise
            # averages can invent a color shared by none of the actual panels.
            main_box = max(sampled,key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
            region["background_rgb"] = colors[main_box]
        if not _size_allowed(width, height):
            continue
        # Every participating word must be fully located and individually
        # covered. An unidentified or partially shared box cannot be repaired.
        if not matches or any((not data and box not in colors) or not
                              (l <= box[0] < box[2] <= rect[2] and t <= box[1] < box[3] <= rect[3])
                              for box,data in matches):
            continue
        data = covers.get(rect)
        if data is None:
            if len(matches) == 1 and matches[0][0] == rect:
                continue  # The GUI can paint this word's opaque local color without a PNG.
            # A contextual line's source rectangle can contain several words.
            # An unrepairable word gets a solid fill in its own box. Keep
            # the other words' individual backgrounds and the gaps untouched.
            canvas = Image.new("RGBA", (width, height))
            for box,word in matches:
                x,y,right,bottom = box
                if word:
                    with Image.open(io.BytesIO(word)) as patch:
                        canvas.alpha_composite(patch,(x-l,y-t))
                else:
                    color = colors[box]
                    fill = ((color>>16)&255,(color>>8)&255,color&255,255)
                    canvas.paste(fill,(x-l,y-t,right-l,bottom-t))
            data = _encode(canvas)
        if data and sent + len(data) <= MAX_FRAME_PNG:
            region["cover_png"] = base64.b64encode(data).decode("ascii")
            sent += len(data)
