"""Detect isolated columns of upright glyphs suitable for Japanese OCR."""
from dataclasses import dataclass
import math


@dataclass
class Column:
    box: tuple
    image: object
    reflowed: object
    fill: int


def _source_glyphs(text):
    from ocr_guard import has_target_script
    return ''.join(char for char in text if has_target_script(char))


def _accepted_source(vertical, horizontal):
    from difflib import SequenceMatcher
    from ocr_guard import has_target_script, join_vertical_glyphs, parse_tsv
    if not vertical or not horizontal:
        return ''
    text, tsv = vertical
    glyphs = _source_glyphs(text)
    alternate = _source_glyphs(horizontal)
    latin = sum(char.isascii() and char.isalnum() for char in text)
    if min(len(glyphs), len(alternate)) < 3 or latin > len(glyphs):
        return ''
    words = [word for word in parse_tsv(tsv) if has_target_script(word.text)]
    if not words or max(word.confidence for word in words) < 68:
        return ''
    match = SequenceMatcher(None, glyphs, alternate, autojunk=False)
    shared = sum(block.size for block in match.get_matching_blocks())
    if shared < 3 or shared / max(len(glyphs), len(alternate)) < 0.72:
        return ''
    return join_vertical_glyphs(text).strip()


def read_columns(image, columns, horizontal_language, read, english_guard, positions=None):
    """Mask agreed column bounds so horizontal OCR cannot read them as unrelated rows."""
    import time
    from ocr_guard import filter_words, has_target_script, observe_english
    masked = image.copy()
    lines = []
    incomplete = False
    deadline = time.monotonic() + 4.5
    for column in columns:
        budget = min(1.5, deadline - time.monotonic())
        if budget < 0.09:
            incomplete = True
            break
        horizontal = read(column.reflowed, horizontal_language, 7, budget)
        if not horizontal:
            incomplete = True
            continue
        text, tsv = horizontal
        target_count = sum(has_target_script(ch) for ch in text)
        if target_count < 3:
            # A clear row of upright stacked Latin letters (e.g. OPTIONS)
            # must also be removed from the horizontal screen pass.
            if sum(ch.isascii() and ch.isalnum() for ch in text)>=3:
                masked.paste(column.fill,column.box)
            continue
        observations = observe_english(english_guard, column.reflowed, tsv)
        filtered = filter_words(text, tsv, observations, column.reflowed)
        if not filtered:
            continue
        budget = min(1.8, deadline - time.monotonic())
        if budget < 0.09:
            incomplete = True
            break
        vertical = read(column.image, 'jpn_vert', 5, budget)
        if vertical is None:
            incomplete = True
        source = _accepted_source(vertical, filtered)
        if not source and observations and all(not any(ch.isalpha() for ch in w.text) for w in observations):
            # Windows English OCR occasionally calls kana strokes digits. Two
            # matching Japanese reads of a longer kana phrase are stronger.
            glyphs = _source_glyphs(text)
            if (vertical and _source_glyphs(vertical[0]) == glyphs and len(glyphs) >= 5 and
                    sum(0x3041 <= ord(ch) <= 0x30FA for ch in text) >= 2):
                source = _accepted_source(vertical, text)
        if not source and vertical and not vertical[0].strip() and not observations and target_count>=4:
            # Tesseract's vertical page segmenter can return an empty page on
            # a tidy column. Require a second line segmentation to reproduce
            # the source after reflow, including kana and the original order.
            remaining=min(1.1,deadline-time.monotonic())
            if remaining>0.09 and any(0x3041<=ord(ch)<=0x30FA for ch in filtered):
                checked=read(column.reflowed,'jpn',13,remaining)
                if checked and _source_glyphs(filtered) == _source_glyphs(checked[0]):
                    source = _accepted_source(checked, filtered)
        if source:
            masked.paste(column.fill,column.box)
            lines.append(source)
            if positions is not None:
                from screen_geometry import physical_box
                positions.append((source, physical_box(image, column.box)))
    return masked, lines, incomplete


def _candidate_boxes(mask, ndimage, np):
    # Bridge character spacing along the writing direction. Horizontal menus
    # normally merge into a wide component and cannot qualify as columns.
    horizontal = ndimage.maximum_filter1d(mask,5,axis=1)
    proposals = []
    for gap in (11,29):
        joined = ndimage.maximum_filter1d(horizontal,gap,axis=0)
        labels, count = ndimage.label(joined)
        if count == 0 or count > 5500:
            continue
        for ys, xs in ndimage.find_objects(labels):
            width, height = xs.stop-xs.start, ys.stop-ys.start
            if not 6 <= width <= 145 or height < max(35,3.5*width) or height > width*65:
                continue
            within = mask[ys,xs]
            rows, cols = np.nonzero(within)
            if len(rows) < 24:
                continue
            x = xs.start + int(cols.min())
            right = xs.start + int(cols.max()) + 1
            top = ys.start + int(rows.min())
            bottom = ys.start + int(rows.max()) + 1
            glyph_width = right - x
            occupied = np.unique(rows)
            for ratio in (0.16,0.28):
                glyphs = np.split(occupied,np.flatnonzero(np.diff(occupied)>max(2,glyph_width*ratio))+1)
                if not 3 <= len(glyphs) <= 65:
                    continue
                heights = [int(g[-1]-g[0]+1) for g in glyphs]
                if (max(heights)>glyph_width*1.7 or
                        sum(0.40*glyph_width <= h <= 1.45*glyph_width for h in heights)<0.65*len(heights)):
                    continue
                centers = np.array([(g[0] + g[-1]) / 2 for g in glyphs])
                steps = np.diff(centers)
                pitch = float(np.median(steps))
                if pitch < 0.55*glyph_width or pitch > 2.5*glyph_width or np.max(abs(steps-pitch))>pitch*0.65:
                    continue
                proposals.append((len(glyphs),(x,top,right,bottom),ratio))
                break
    return proposals


def upright_columns(image):
    """Return right-to-left column crops with independent horizontal reflows."""
    from PIL import Image, ImageFilter, ImageOps
    import numpy as np
    from scipy import ndimage
    from ocr_guard import vertical_verifier_image
    if not isinstance(image,Image.Image):
        return []
    gray = image if image.mode=='L' else image.convert('L')
    if gray.height>=2.5*gray.width:
        reflowed=vertical_verifier_image(gray)
        if reflowed is not None and reflowed.width>=16+3*34:
            hist = gray.histogram()
            fill = max(range(256), key=hist.__getitem__)
            return [Column((0,0,gray.width,gray.height),gray,reflowed,fill)]
    ratio = min(1,1080/max(gray.size),math.sqrt(800000/(gray.width*gray.height)))
    shape = tuple(max(1,round(v*ratio)) for v in gray.size)
    probe = gray.resize(shape,Image.Resampling.BILINEAR) if ratio<1 else gray
    values = np.asarray(probe,dtype=np.int16)
    hist = probe.histogram()
    background = max(range(256), key=hist.__getitem__)
    flat = sum(hist[max(0,background-12):min(256,background+13)]) >= values.size*0.72
    if flat:
        masks=[(abs(values-background)>42,0)]
    else:
        blur=np.asarray(probe.filter(ImageFilter.GaussianBlur(3)),dtype=np.int16)
        masks=[((values-blur>27)&(values>70),1),((blur-values>27)&(values<185),-1)]
    found=[]
    for mask,polarity in masks:
        for count,box,gap in _candidate_boxes(mask,ndimage,np):
            found.append((count,box,polarity,mask,gap))
    sx,sy=gray.width/probe.width,gray.height/probe.height
    columns=[]
    for _,box,polarity,mask,gap in sorted(found,key=lambda entry:-entry[0]):
        x,y,right,bottom=box
        physical=(max(0,math.floor(x*sx)-2),max(0,math.floor(y*sy)-2),
                  min(gray.width,math.ceil(right*sx)+2),min(gray.height,math.ceil(bottom*sy)+2))
        if any(min(physical[2],c.box[2])>max(physical[0],c.box[0]) and
               min(physical[3],c.box[3])>max(physical[1],c.box[1]) for c in columns):
            continue
        crop=gray.crop(physical)
        fill=background
        if not flat:
            crop_values = values[y:bottom, x:right]
            ink = mask[y:bottom, x:right]
            if not ink.any() or ink.all():
                continue
            tone = float(np.median(crop_values[ink]))
            bg = float(np.median(crop_values[~ink]))
            if polarity*(tone-bg)<35:
                continue
            fill=round(bg)
            weight=(np.asarray(crop,dtype=np.float32)-bg)/(tone-bg)
            crop=Image.fromarray((255*(1-np.clip((weight-0.25)/0.65,0,1))).astype(np.uint8))
        elif background<128:
            crop=ImageOps.invert(crop)
        crop=ImageOps.expand(crop,border=8,fill=255 if not flat else max(background,255-background))
        reflowed=vertical_verifier_image(crop,gap)
        if reflowed is not None:
            columns.append(Column(physical,crop,reflowed,fill))
            if len(columns)>=4:
                break
    return sorted(columns,key=lambda c:-c.box[0])
