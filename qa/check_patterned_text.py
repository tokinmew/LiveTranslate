"""Replay authored cloth/pattern scenes through real local OCR, without capturing a display.

Run with the prepared application's Python and --data pointing to its data folder.
These are generated OCR fixtures, not live VRChat or physical-headset validation.
"""
import argparse
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]


SIZE = (800, 480)
FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
CASES = (
    dict(name="dark_diagonal_cloth", pattern="diagonal", dark=True, expected=()),
    dict(name="light_checker_cloth", pattern="checks", dark=False, expected=()),
    dict(name="dark_seams_emblems", pattern="emblems", dark=True, expected=()),
    dict(name="light_curves_triangles", pattern="curves", dark=False, expected=()),
    dict(name="printed_japanese", pattern="diagonal", dark=True,
         expected=("ここで待ってください",), source="ja", language="jpn", font="YuGothM.ttc"),
    dict(name="printed_korean", pattern="checks", dark=False,
         expected=("여기에서 기다려 주세요",), source="ko", language="kor", font="malgun.ttf"),
    dict(name="printed_simplified_chinese", pattern="emblems", dark=True,
         expected=("请在这里等我",), source="zh", language="chi_sim", font="msyh.ttc"),
    dict(name="printed_traditional_chinese", pattern="curves", dark=False,
         expected=("請在這裡等我",), source="zt", language="chi_tra", font="msjh.ttc"),
    dict(name="printed_short_chinese_labels", pattern="diagonal", dark=False,
         expected=("門", "一口", "入口"), source="zt", language="chi_tra", font="msjh.ttc"),
)


def cloth(case):
    """Geometric weave/folds/pseudo-emblems only: no letters in negative scenes."""
    dark = case["dark"]
    base = (31, 43, 54) if dark else (216, 217, 203)
    image = Image.new("RGB", SIZE, base)
    draw = ImageDraw.Draw(image)
    faint = (42, 55, 65) if dark else (197, 202, 190)
    edge = (78, 96, 105) if dark else (130, 146, 137)
    detail = (128, 149, 152) if dark else (98, 118, 109)
    for y in range(0, SIZE[1], 6):
        draw.line((0, y, SIZE[0], y), fill=faint)
    for x in range(0, SIZE[0], 9):
        draw.line((x, 0, x, SIZE[1]), fill=faint)
    kind = case["pattern"]
    if kind == "diagonal":
        for x in range(-500, 900, 32):
            draw.line((x, 0, x + 480, 480), fill=edge, width=3)
            draw.line((x + 8, 0, x + 488, 480), fill=faint, width=2)
    elif kind == "checks":
        for y in range(0, SIZE[1], 32):
            for x in range(0, SIZE[0], 32):
                if (x // 32 + y // 32) % 2:
                    draw.rectangle((x, y, x + 14, y + 14), fill=edge)
                else:
                    draw.line((x, y + 16, x + 16, y + 16), fill=detail, width=2)
    elif kind == "emblems":
        for y in (82, 146, 338, 402):
            for x in range(60, 780, 82):
                draw.ellipse((x - 14, y - 14, x + 14, y + 14), outline=edge, width=3)
                draw.polygon(((x, y - 9), (x + 9, y + 8), (x - 9, y + 8)), outline=detail)
                draw.arc((x - 23, y - 23, x + 23, y + 23), 30, 150, fill=detail, width=2)
    else:
        for y in range(-20, SIZE[1] + 60, 42):
            points = [(x, y + round(17 * math.sin(x / 49))) for x in range(0, SIZE[0], 5)]
            draw.line(points, fill=edge, width=3)
        for x in range(35, 790, 68):
            for y in (97, 367):
                draw.polygon(((x, y), (x + 18, y + 29), (x - 18, y + 29)), outline=detail)
    # Authored collar and stitched seams make a clothing-like field rather
    # than an ordinary flat OCR card. They are geometry, never text.
    draw.arc((270, -86, 530, 110), 0, 180, fill=detail, width=5)
    for x in (107, 693):
        for y in range(35, 456, 15):
            draw.line((x, y, x + 6, y + 8), fill=detail, width=2)
    draw.line([(x, 446 + round(7 * math.sin(x / 90))) for x in range(0, 800, 4)], fill=edge, width=4)
    if case["expected"]:
        face = FONTS / case["font"]
        size = 48 if len(case["expected"]) > 1 else 36
        font = ImageFont.truetype(str(face), size)
        ink = (247, 248, 243) if dark else (16, 26, 28)
        if len(case["expected"]) > 1:
            for x, label in zip((124, 334, 558), case["expected"]):
                draw.text((x, 212), label, font=font, fill=ink, stroke_width=1)
        else:
            text = case["expected"][0]
            bounds = draw.textbbox((0, 0), text, font=font)
            draw.text(((800 - (bounds[2] - bounds[0])) // 2, 218), text, font=font, fill=ink, stroke_width=1)
    return image


def frame(image, bounds):
    left, top, right, bottom = bounds
    crop = image.crop(bounds)
    gray = crop.convert("L").resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    gray.info.update(desktop_map=(left, top, .5, .5), glyph_source=(crop, left, top))
    return gray


def letters(value):
    return "".join(ch for ch in value if ch.isalnum())


def replay(engine, case, image, mode):
    full = mode == "auto-full"
    bounds = (0, 0, *SIZE) if full else (75, 180, 725, 305)
    rectangle = dict(left=bounds[0], top=bounds[1], width=bounds[2] - bounds[0], height=bounds[3] - bounds[1])
    if full:
        rectangle["full_display"] = True
    source = case["source"] if mode == "explicit-region" else "auto"
    language = case["language"] if mode == "explicit-region" else "auto"
    sample = frame(image, bounds)
    started = time.perf_counter()
    with patch.object(engine, "_capture", return_value=sample):
        observed = engine.recognize_watched(rectangle, language, "", source, [])
    normalized = letters(str(observed))
    expected_found = [letters(text) in normalized for text in case["expected"]]
    exact_source = normalized == "".join(letters(text) for text in case["expected"])
    return dict(case=case["name"], theme="dark" if case["dark"] else "light", mode=mode,
                expected=list(case["expected"]), observed=str(observed),
                expected_found=expected_found, exact_source=exact_source,
                passed=all(expected_found) and exact_source if expected_found else not str(observed).strip(),
                located_regions=len(observed.regions), milliseconds=round((time.perf_counter() - started) * 1000, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Prepared app data directory with local tessdata")
    parser.add_argument("--backend", type=Path, default=ROOT / "LiveTranslate/backend",
                        help="Alternative source backend for a separate-process baseline replay")
    parser.add_argument("--cases", nargs="+", choices=[case["name"] for case in CASES])
    parser.add_argument("--modes", nargs="+", choices=("auto-full", "auto-region", "explicit-region"),
                        default=("auto-full", "auto-region", "explicit-region"))
    parser.add_argument("--images", type=Path, help="Optional scratch folder for the authored fixture PNGs")
    parser.add_argument("--strict", action="store_true", help="Return nonzero when a measured case fails")
    args = parser.parse_args()
    sys.path.insert(0, str(args.backend.resolve()))
    from screen_engine import ScreenEngine
    if args.images:
        if args.images.resolve().is_relative_to(ROOT):
            parser.error("Save fixture images outside the source repository.")
        args.images.mkdir(parents=True, exist_ok=True)
    results = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network request in local OCR fixture")))
        stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=AssertionError("Network lookup in local OCR fixture")))
        engine = ScreenEngine(args.data)
        with engine.watch_models():
            for case in CASES:
                if args.cases and case["name"] not in args.cases:
                    continue
                image = cloth(case)
                if args.images:
                    image.save(args.images / (case["name"] + ".png"))
                for mode in args.modes:
                    if mode == "explicit-region" and not case["expected"]:
                        continue
                    try:
                        result = replay(engine, case, image, mode)
                    except Exception as error:
                        result = dict(case=case["name"], mode=mode, passed=False,
                                      error=type(error).__name__ + ": " + str(error))
                    results.append(result)
                    print(json.dumps(result, ensure_ascii=True), flush=True)
    summary = dict(summary=True, generated_scenes=True, actual_screen_capture=False,
                   live_game_or_headset_test=False, cases=len(results), passed=sum(row["passed"] for row in results),
                   failed=sum(not row["passed"] for row in results))
    print(json.dumps(summary), flush=True)
    return int(args.strict and summary["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
