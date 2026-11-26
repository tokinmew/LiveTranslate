"""Replay authored desktop/app-style panels through real local OCR, never a display.

These are simulated layouts, not captures or tests of the named services or a
physical headset. No logos, remote images, personal text, or model downloads
are used. Output is JSON lines on stdout; no report or image files are written.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
WIDTH, HEIGHT = 900, 540


def installed_app():
    roots = [Path(os.environ.get("LOCALAPPDATA", "")), Path.home() / "AppData/Local"]
    candidates = [root / "Programs/LiveTranslate/app" for root in roots]
    return next((path for path in candidates if (path / "runtime/python.exe").is_file()), candidates[-1])


def face(name, size):
    path = FONTS / name
    if not path.is_file():
        raise RuntimeError("Required Windows fixture font is unavailable: " + name)
    return ImageFont.truetype(str(path), size)


def icon(draw, kind, x, y, color, size=16):
    """Ordinary authored UI strokes that can resemble Han/kana to forced OCR."""
    pad = max(2, size // 5)
    l, t, r, b = x + pad, y + pad, x + size - pad, y + size - pad
    cx, cy = x + size // 2, y + size // 2
    if kind == "square":
        draw.rectangle((l, t, r, b), outline=color, width=2)
    elif kind == "copy":
        draw.rectangle((l + 3, t, r + 3, b - 3), outline=color, width=1)
        draw.rectangle((l, t + 3, r, b), outline=color, width=1)
    elif kind == "plus":
        draw.line((l, cy, r, cy), fill=color, width=2)
        draw.line((cx, t, cx, b), fill=color, width=2)
    elif kind == "minus":
        draw.line((l, cy, r, cy), fill=color, width=2)
    elif kind == "menu":
        for dy in (-4, 0, 4):
            draw.line((l, cy + dy, r, cy + dy), fill=color, width=1)
    elif kind == "chevron":
        draw.line((l, t + 1, cx, b - 1, r, t + 1), fill=color, width=2)
    elif kind == "share":
        draw.line((l, cy, cx, t, r, cy), fill=color, width=1)
        draw.line((cx, t, cx, b), fill=color, width=1)
    elif kind == "play":
        draw.polygon(((l + 1, t), (r, cy), (l + 1, b)), outline=color)
    elif kind == "close":
        draw.line((l, t, r, b), fill=color, width=1)
        draw.line((l, b, r, t), fill=color, width=1)
    else:
        draw.ellipse((l, t, r, b), outline=color, width=2)


def toolbar(draw, x, y, ink, variant=0):
    kinds = ("menu", "plus", "minus", "square", "copy", "share", "chevron", "close")
    for index, kind in enumerate(kinds):
        icon(draw, kind, x + index * (27 + variant), y, ink, 16 + variant)


def panel(style, dark=False):
    bg, surface, rail = ((24, 26, 31), (36, 39, 46), (29, 32, 39)) if dark else \
                        ((255, 255, 255), (247, 248, 250), (239, 241, 244))
    ink = (232, 234, 239) if dark else (34, 38, 45)
    muted = (167, 174, 188) if dark else (98, 106, 119)
    line = (65, 70, 82) if dark else (210, 215, 223)
    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)
    regular, small, heading = face("segoeui.ttf", 18), face("segoeui.ttf", 14), face("segoeui.ttf", 24)
    draw.rectangle((0, 0, WIDTH, 48), fill=surface)
    toolbar(draw, WIDTH - 254, 16, muted, int(dark))
    draw.text((22, 9), "Desktop workspace", font=heading, fill=ink)
    if style == "repository":
        draw.text((25, 67), "Project / Source", font=heading, fill=ink)
        draw.text((25, 111), "Code     Issues     Changes     Actions     Settings", font=regular, fill=ink)
        draw.line((20, 147, WIDTH - 20, 147), fill=line)
        draw.text((40, 165), "main", font=regular, fill=ink)
        icon(draw, "chevron", 94, 168, muted)
        toolbar(draw, WIDTH - 264, 166, muted)
        for index, label in enumerate(("Source", "Documentation", "Installer", "Publisher", "Tests", "Tools", "Readme")):
            y = 220 + index * 39
            icon(draw, "square", 32, y + 2, muted)
            draw.text((63, y), label, font=regular, fill=ink)
            draw.text((430, y + 2), "Update project files", font=small, fill=muted)
            draw.line((25, y + 31, WIDTH - 25, y + 31), fill=line)
    elif style == "video":
        draw.rounded_rectangle((20, 74, 660, 412), radius=8, fill=(10, 12, 16), outline=line)
        icon(draw, "play", 312, 214, (224, 229, 236), 42)
        draw.line((41, 371, 637, 371), fill=(155, 160, 171), width=3)
        toolbar(draw, 40, 384, (220, 225, 231))
        for index, label in enumerate(("Next video", "Watch later", "Saved clips", "Play all", "More options")):
            y = 83 + index * 73
            draw.rectangle((687, y, 875, y + 37), fill=surface, outline=line)
            draw.text((697, y + 6), label, font=regular, fill=ink)
        draw.text((25, 435), "A sample video title in English", font=heading, fill=ink)
        draw.text((25, 477), "Share      Save      Comments      Show more", font=regular, fill=muted)
    elif style == "vr_menu":
        draw.rounded_rectangle((134, 71, 766, 514), radius=14, fill=surface, outline=line, width=2)
        draw.text((164, 88), "Quick menu", font=heading, fill=ink)
        icon(draw, "close", 722, 94, muted, 20)
        labels = ("Home", "Friends", "Worlds", "Avatar", "Settings", "Audio", "Microphone", "Comfort", "Safety")
        for index, label in enumerate(labels):
            x, y = 159 + (index % 3) * 194, 144 + (index // 3) * 101
            draw.rounded_rectangle((x, y, x + 175, y + 85), radius=7, fill=bg, outline=line)
            icon(draw, ("square", "plus", "share", "copy", "menu", "minus", "circle", "chevron", "close")[index],
                 x + 72, y + 9, ink, 25)
            bounds = draw.textbbox((0, 0), label, font=regular)
            draw.text((x + (175 - bounds[2]) // 2, y + 48), label, font=regular, fill=ink)
        draw.text((164, 468), "Selected: desktop audio     Volume: 70", font=small, fill=muted)
    else:
        draw.rectangle((0, 48, 225, HEIGHT), fill=rail)
        labels = {
            "conversation": ("New chat", "Search chats", "Library", "Projects", "Settings", "Help"),
            "team_chat": ("General", "Voice chat", "Friends", "Messages", "Downloads", "Settings"),
            "library": ("Home", "Library", "Downloads", "Favorites", "Installed", "Settings"),
        }[style]
        for index, label in enumerate(labels):
            y = 82 + index * 49
            icon(draw, ("plus", "circle", "square", "copy", "menu", "chevron")[index], 19, y + 1, muted)
            draw.text((49, y), label, font=regular, fill=ink)
        draw.text((249, 74), {"conversation": "New conversation", "team_chat": "General discussion", "library": "Game library"}[style], font=heading, fill=ink)
        draw.text((249, 126), "Welcome back. Choose an item to continue.", font=regular, fill=ink)
        draw.text((249, 166), "This panel contains English interface labels.", font=regular, fill=muted)
        draw.rounded_rectangle((249, 213, 873, 389), radius=9, fill=surface, outline=line)
        draw.text((269, 229), "Recent activity", font=regular, fill=ink)
        toolbar(draw, 270, 280, muted, int(dark))
        draw.text((269, 344), "Open     Share     Copy     More options", font=small, fill=muted)
        draw.rounded_rectangle((249, 450, 873, 511), radius=12, fill=surface, outline=line)
        icon(draw, "plus", 267, 471, muted, 19)
        draw.text((304, 468), "Type a message", font=regular, fill=muted)
        icon(draw, "square", 831, 471, muted, 19)
    return image


def add_source(image, text, font_name, font_size=33):
    draw = ImageDraw.Draw(image)
    background = image.getpixel((WIDTH - 10, HEIGHT - 10))
    ink = (240, 242, 247) if sum(background) < 384 else (20, 25, 33)
    draw.rectangle((244, 235, 883, 328), fill=background)
    draw.text((261, 252), text, font=face(font_name, font_size), fill=ink)
    return image


@dataclass
class Case:
    name: str
    image: object
    expected: str = ""
    profile: str = "auto"
    language: str = "auto"
    full_display: bool = True
    optional: bool = False


def cases():
    result = [
        Case("conversation_light", panel("conversation")),
        Case("conversation_dark", panel("conversation", True)),
        Case("repository_light", panel("repository")),
        Case("repository_dark", panel("repository", True)),
        Case("video_player_dark", panel("video", True)),
        Case("team_chat_dark", panel("team_chat", True)),
        Case("game_library_dark", panel("library", True)),
        Case("vr_quick_menu_dark", panel("vr_menu", True)),
        Case("japanese_amid_english", add_source(panel("conversation"), "次の電車は何時ですか。", "YuGothM.ttc", 39), "次の電車は何時ですか。"),
        Case("chinese_amid_english", add_source(panel("repository"), "我们明天见。", "msyh.ttc"), "我们明天见。"),
        Case("korean_amid_english", add_source(panel("team_chat", True), "도서관은 어디에 있나요?", "malgun.ttf"), "도서관은 어디에 있나요?"),
    ]
    label = Image.new("RGB", (120, 100), "white")
    draw = ImageDraw.Draw(label)
    glyph_font = face("msyh.ttc", 32)
    bounds = draw.textbbox((0, 0), "口", font=glyph_font)
    draw.text(((label.width - bounds[2]) // 2, (label.height - (bounds[3] - bounds[1])) // 2 - bounds[1]),
              "口", font=glyph_font, fill="black")
    result.append(Case("explicit_selected_han_label", label, "口", "zh", "chi_sim", False))
    for name, text, font_name in (
            ("tokyo", "東京", "YuGothM.ttc"),
            ("hai", "はい", "YuGothM.ttc"),
            ("korean", "한국", "malgun.ttf"),
            ("gate", "門", "msjh.ttc"),
            ("one_mouth", "一口", "msyh.ttc"),
            ("twenty", "二十", "msyh.ttc"),
            ("factory_entrance", "工場入口", "YuGothM.ttc"),
            ("japanese", "日本語", "YuGothM.ttc")):
        image = Image.new("RGB", (200, 150), "white")
        draw = ImageDraw.Draw(image)
        label_font = face(font_name, 32)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=label_font)
        draw.text(((image.width - (right - left)) // 2 - left,
                   (image.height - (bottom - top)) // 2 - top), text, font=label_font, fill="black")
        result.append(Case("auto_short_" + name, image, text, optional=True))
    if (FONTS / "segmdl2.ttf").is_file():
        symbols = panel("conversation")
        draw = ImageDraw.Draw(symbols)
        # Authored font-symbol row; these private-use codepoints are icons,
        # not words from a source language. No site logos are used.
        glyph_font = face("segmdl2.ttf", 20)
        for index, value in enumerate((0xE710, 0xE721, 0xE74D, 0xE8A5, 0xE8A7, 0xE8B7, 0xE8BB)):
            draw.text((268 + index * 48, 405), chr(value), font=glyph_font, fill=(55, 63, 75))
        draw.text((268, 432), "Add    Search    Delete    Copy    Paste    More", font=face("segoeui.ttf", 14), fill=(80, 89, 103))
        result.append(Case("windows_toolbar_symbols_light", symbols, optional=True))
    return result


def capture_frame(rgb):
    """Match ScreenEngine._capture preprocessing, including its conditional resize."""
    frame = ImageOps.grayscale(rgb)
    if frame.width < 1200 and frame.height < 1000:
        frame = frame.resize((frame.width * 2, frame.height * 2), Image.Resampling.LANCZOS)
    frame.info["desktop_map"] = (0, 0, rgb.width / frame.width, rgb.height / frame.height)
    frame.info["glyph_source"] = (rgb, 0, 0)
    return frame


def main():
    app = installed_app()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, default=ROOT / "LiveTranslate/backend")
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("LIVETRANSLATE_TEST_DATA", app / "data")))
    parser.add_argument("--helper", type=Path, default=Path(os.environ.get("LIVETRANSLATE_TEST_HELPER", app / "ocr-tools/EnglishOcr.exe")))
    parser.add_argument("--only", help="Comma-separated fixture names or shortlabels; by default run the 12 authored UI cases")
    parser.add_argument("--trace", action="store_true", help="Print target-script OCR word boxes/confidence for authored images")
    parser.add_argument("--all-cjk-profiles", action="store_true", help="Check every no-text UI scene under Auto and all four selected CJK profiles")
    parser.add_argument("--without-english-guard", action="store_true", help="Exercise the independent CJK fallback with Windows English OCR unavailable")
    args = parser.parse_args()
    if (not args.data.joinpath("tessdata").is_dir() or
            not args.without_english_guard and not args.helper.is_file()):
        parser.error("Provide existing checked data and EnglishOcr.exe using --data/--helper or LIVETRANSLATE_TEST_DATA/LIVETRANSLATE_TEST_HELPER.")
    sys.path.insert(0, str(args.backend.resolve()))
    import ocr_guard
    from screen_engine import ScreenEngine
    ocr_guard._HELPER = args.helper.resolve()
    engine = ScreenEngine(args.data.resolve())
    if engine._native_engine() is None:
        parser.error("Use the prepared LiveTranslate runtime containing the native OCR engine.")
    if args.without_english_guard:
        engine.english_guard.detect = lambda image: None
    else:
        probe = Image.new("L", (430, 70), 255)
        ImageDraw.Draw(probe).text((8, 8), "Open the settings menu", font=face("segoeui.ttf", 27), fill=0)
        english = engine.english_guard.detect(probe)
        if english is None or len(english) < 2:
            parser.error("The independent Windows English OCR helper is unavailable; use --without-english-guard to explicitly test that fallback.")
    all_cases = cases()
    if args.all_cjk_profiles:
        expanded = []
        profiles = (("auto", "auto"), ("ja", "jpn"), ("ko", "kor"), ("zh", "chi_sim"), ("zt", "chi_tra"))
        for case in all_cases:
            if case.expected:
                expanded.append(case)
            else:
                expanded.extend(replace(case, name=case.name + ":" + profile, profile=profile,
                                        language=language, optional=False) for profile, language in profiles)
        all_cases = expanded
    wanted = set(args.only.split(",")) if args.only else {case.name for case in all_cases if not case.optional}
    if "shortlabels" in wanted:
        wanted.remove("shortlabels")
        wanted.update(case.name for case in all_cases if case.name.startswith("auto_short_"))
    unknown = wanted - {case.name for case in all_cases}
    if unknown:
        parser.error("Unknown authored fixture: " + ", ".join(sorted(unknown)))
    print(json.dumps(dict(fixture_set="authored_desktop_icons", backend=str(args.backend.resolve()),
                          automatic_ocr=engine.auto_language(), english_guard_available=not args.without_english_guard,
                          selected_profile_negatives=args.all_cjk_profiles,
                          without_english_guard=args.without_english_guard)), flush=True)
    failures = 0
    started = time.monotonic()
    active_case = [""]
    original_reader = engine._reader

    class TracedReader:
        def __init__(self, reader, language, mode):
            self.reader, self.language, self.mode = reader, language, mode
            self.image, self.text = None, ""

        def __getattr__(self, name):
            return getattr(self.reader, name)

        def SetImage(self, image):
            self.image = image
            return self.reader.SetImage(image)

        def GetUTF8Text(self):
            self.text = self.reader.GetUTF8Text()
            return self.text

        def GetTSVText(self, page):
            value = self.reader.GetTSVText(page)
            if args.trace:
                from screen_geometry import physical_box
                words = [word for word in ocr_guard.parse_tsv(value) if ocr_guard.has_target_script(word.text)]
                if words:
                    report = [dict(text=word.text, confidence=round(word.confidence, 2),
                                   box=word.box, width=word.box[2] - word.box[0], height=word.box[3] - word.box[1],
                                   physical_box=physical_box(self.image, word.box)) for word in words[:20]]
                    print(json.dumps(dict(trace=True, fixture=active_case[0], language=self.language, psm=self.mode,
                                          image_size=self.image.size, raw=self.text.strip()[:300], words=report),
                                     ensure_ascii=True), flush=True)
            return value

    @contextmanager
    def traced_reader(native, language, mode, primary):
        with original_reader(native, language, mode, primary) as reader:
            yield TracedReader(reader, language, mode)

    if args.trace:
        engine._reader = traced_reader
    with engine.watch_models():
        for case in all_cases:
            if case.name not in wanted:
                continue
            active_case[0] = case.name
            before = time.monotonic()
            region = dict(left=0, top=0, width=case.image.width, height=case.image.height,
                          full_display=case.full_display)
            try:
                with patch.object(engine, "_capture", return_value=capture_frame(case.image)):
                    result = engine.recognize_watched(region, case.language, "", case.profile, [])
                glyphs = lambda value: "".join(ch for ch in value if ocr_guard.has_target_script(ch))
                regions = getattr(result, "regions", ())
                boxes = [box for _, spans in regions for _, _, box in spans if box]
                bounded = all(0 <= left < right <= case.image.width and
                              0 <= top < bottom <= case.image.height for left, top, right, bottom in boxes)
                passed = glyphs(str(result)) == glyphs(case.expected) and bounded and (not case.expected or bool(boxes))
                report = dict(fixture=case.name, profile=case.profile, full_display=case.full_display,
                              passed=passed, expected=case.expected, observed=str(result),
                              regions=len(regions), boxes_in_bounds=bounded)
            except Exception as error:
                passed = False
                report = dict(fixture=case.name, profile=case.profile, passed=False, error=str(error))
            failures += not passed
            report["seconds"] = round(time.monotonic() - before, 3)
            print(json.dumps(report, ensure_ascii=True), flush=True)
    print(json.dumps(dict(authored_simulations=True, live_capture=False, tested=len(wanted),
                          failed=failures, without_english_guard=args.without_english_guard,
                          elapsed_seconds=round(time.monotonic() - started, 3))), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
