"""Local inference checks using real translation/OCR models and rendered text.

These checks never download files, read the screen, or use a remote service.
They are deliberately small acceptance probes, not translation benchmarks.
Native model inference is real; only OCR's image source is a generated fixture.
Every row is independently passed, failed, missing, or skipped so partial
installations produce useful results. Missing dependencies never turn into
fabricated output.
"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import unicodedata


TEXT_CASES = (
    {"language": "zt", "input": "\u6211\u60f3\u8cb7\u4e00\u676f\u5496\u5561\u3002",
     "meaning": "I would like to buy a cup of coffee.",
     "anchors": (("coffee",), ("want", "like", "buy", "get"))},
    {"language": "zh", "input": "\u56fe\u4e66\u9986\u5728\u54ea\u91cc\uff1f",
     "meaning": "Where is the library?", "anchors": (("where",), ("library",))},
    {"language": "ko", "input": "\uc800\ub294 \ubb3c\uc744 \ub9c8\uc2dc\uace0 \uc2f6\uc5b4\uc694.",
     "meaning": "I would like to drink water.", "anchors": (("water",), ("want", "like", "drink"))},
    {"language": "ja", "input": "\u99c5\u306f\u3069\u3053\u3067\u3059\u304b\u3002",
     "meaning": "Where is the station?", "anchors": (("where",), ("station",))},
)

OCR_CASES = (
    {"language": "chi_tra", "input": "\u6b61\u8fce\u4f7f\u7528\u5373\u6642\u7ffb\u8b6f", "vertical": False,
     "fonts": ("msjh.ttc", "mingliu.ttc", "simsun.ttc", "arialuni.ttf")},
    {"language": "chi_sim", "input": "\u6b22\u8fce\u4f7f\u7528\u5b9e\u65f6\u7ffb\u8bd1", "vertical": False,
     "fonts": ("msyh.ttc", "simsun.ttc", "msjh.ttc", "arialuni.ttf")},
    {"language": "kor", "input": "\uc2e4\uc2dc\uac04 \ubc88\uc5ed\uc744 \uc2dc\uc791\ud569\ub2c8\ub2e4", "vertical": False,
     "fonts": ("malgun.ttf", "gulim.ttc", "batang.ttc", "arialuni.ttf")},
    {"language": "jpn", "input": "\u65e5\u672c\u8a9e\u3092\u82f1\u8a9e\u306b\u7ffb\u8a33\u3057\u307e\u3059", "vertical": False,
     "fonts": ("YuGothM.ttc", "YuGothR.ttc", "meiryo.ttc", "msgothic.ttc", "arialuni.ttf")},
    {"language": "jpn_vert", "input": "\u65e5\u672c\u8a9e\u7ffb\u8a33", "vertical": True,
     "fonts": ("YuGothM.ttc", "YuGothR.ttc", "meiryo.ttc", "msgothic.ttc", "arialuni.ttf")},
)

TRANSLATION_WORDS = ("translation", "translations", "translate", "translates", "translated", "translating",
                     "translator", "interpretation", "interpretations", "interpret", "interpreting")
SCREEN_PROFILES = {
    "chi_tra": {"profile": "zt", "meaning": "Welcome to live translation.", "anchors": (TRANSLATION_WORDS,)},
    "chi_sim": {"profile": "zh", "meaning": "Welcome to live translation.", "anchors": (TRANSLATION_WORDS,)},
    "kor": {"profile": "ko", "meaning": "Starting real-time translation.", "anchors": (TRANSLATION_WORDS,)},
    "jpn": {"profile": "ja", "meaning": "Translate Japanese into English.",
            "anchors": (TRANSLATION_WORDS, ("japanese",), ("english",))},
    "jpn_vert": {"profile": "ja", "meaning": "Japanese translation.",
                 "anchors": (TRANSLATION_WORDS, ("japanese",))},
}


def _row(kind, language, status="missing", **fields):
    return {"kind": kind, "language": language, "status": status, **fields}


def _error_text(exc):
    # Keep each failure readable while preserving the actionable native error.
    return (type(exc).__name__ + ": " + str(exc)).replace("\r", " ").replace("\n", " ")[:450]


def _meaning_matches(output, anchor_groups):
    words = set(re.findall(r"[a-z]+", output.casefold()))
    return [list(group) for group in anchor_groups if not words.intersection(group)]


def check_text(data_dir: Path) -> list[dict]:
    """Run four explicit-source English translations using actual local packs.

    Returns exact input/output, a meaning reference, and light lexical checks.
    A pass establishes basic model loading and phrase meaning only; it does
    not assess arbitrary language accuracy or automatic source detection.
    """
    data_dir = Path(data_dir)
    try:
        from text_engine import TextEngine
        engine = TextEngine(data_dir)
        installed = {entry["code"] for entry in engine.installed()}
    except (ImportError, OSError, ValueError) as exc:
        return [_row("text", case["language"], reason="Text engine unavailable: " + _error_text(exc))
                for case in TEXT_CASES]
    rows = []
    for case in TEXT_CASES:
        language = case["language"]
        row = _row("text", language, input=case["input"], meaning=case["meaning"], source_mode="explicit")
        if language not in installed:
            row["reason"] = "The " + language + " -> English model pack is missing or incomplete."
            rows.append(row)
            continue
        try:
            result = engine.translate(case["input"], language)
            output = result["text"]
            row.update(output=output, output_language="en")
            missed = _meaning_matches(output, case["anchors"])
            untranslated = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]", output))
            if output.strip() and not missed and not untranslated:
                row["status"] = "passed"
            else:
                row.update(status="failed", reason="English phrase did not satisfy the basic meaning check.",
                           unmatched_anchor_groups=missed, unexpected_cjk=untranslated)
        except (ImportError, ModuleNotFoundError) as exc:
            row.update(status="missing", reason="Translation dependency missing: " + _error_text(exc))
        except Exception as exc:
            # The application may wrap an unavailable native module in
            # RuntimeError. Distinguish unavailable runtime from bad inference.
            missing = isinstance(exc.__cause__, (ImportError, OSError))
            row.update(status="missing" if missing else "failed", reason=_error_text(exc))
        rows.append(row)
    return rows


def check_screen_translation(data_dir: Path, ocr_rows: list[dict]) -> list[dict]:
    """Translate actual successful OCR output through matching real text packs.

    Returns five independent rows. Failed/unavailable OCR is skipped; missing
    translation packs/runtime are missing. OCR rows are never mutated, and a
    screen-translation failure does not change the isolated OCR result.
    """
    data_dir = Path(data_dir)
    upstream = {row.get("language"): row for row in ocr_rows if row.get("kind") == "ocr"}
    engine = None
    installed = set()
    engine_error = None
    rows = []
    try:
        for language, case in SCREEN_PROFILES.items():
            source = upstream.get(language, {})
            row = _row("screen_translation", language, status="skipped", source_profile=case["profile"],
                       meaning=case["meaning"], source_mode="explicit", ocr_status=source.get("status", "missing"))
            if source.get("status") != "passed":
                row["reason"] = "Screen translation skipped because the matching OCR check did not pass."
                rows.append(row)
                continue
            recognized = source.get("output")
            if not isinstance(recognized, str) or not recognized.strip():
                row["reason"] = "Screen translation skipped because OCR returned no usable text."
                rows.append(row)
                continue
            row.update(input=recognized, fixture_input=source.get("input", ""))
            if engine is None and engine_error is None:
                try:
                    from worker import Worker
                    engine = Worker(data_dir, lambda _: None)
                    installed = {entry["code"] for entry in engine.text.installed()}
                except (ImportError, OSError, ValueError) as exc:
                    engine_error = "Text engine unavailable: " + _error_text(exc)
            if engine_error is not None:
                row.update(status="missing", reason=engine_error)
                rows.append(row)
                continue
            if case["profile"] not in installed:
                row.update(status="missing", reason="The " + case["profile"] + " -> English text pack is missing or incomplete.")
                rows.append(row)
                continue
            try:
                filtered, result = engine.translate_screen_text(recognized, case["profile"])
                row["filtered_input"] = filtered
                output = result["text"]
                row.update(output=output, output_language="en")
                missed = _meaning_matches(output, case["anchors"])
                untranslated = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]", output))
                if output.strip() and not missed and not untranslated:
                    row["status"] = "passed"
                else:
                    row.update(status="failed", reason="OCR-to-English output did not satisfy the light meaning check.",
                               unmatched_anchor_groups=missed, unexpected_cjk=untranslated)
            except (ImportError, ModuleNotFoundError) as exc:
                row.update(status="missing", reason="Translation dependency missing: " + _error_text(exc))
            except Exception as exc:
                missing = isinstance(exc.__cause__, (ImportError, OSError))
                row.update(status="missing" if missing else "failed", reason=_error_text(exc))
            rows.append(row)
    finally:
        if engine is not None:
            engine.close()
    return rows


def _normalize_ocr(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum())


def _edit_distance(expected, actual):
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def _ocr_metrics(expected, actual):
    wanted = _normalize_ocr(expected)
    found = _normalize_ocr(actual)
    edits = _edit_distance(wanted, found)
    overlap = sum((Counter(wanted) & Counter(found)).values())
    return {"expected_normalized": wanted, "output_normalized": found,
            "character_error_rate": round(edits / max(1, len(wanted)), 4),
            "character_recall": round(overlap / max(1, len(wanted)), 4),
            "edit_distance": edits}


def _supports_text(font, text):
    # FreeType uses the same missing-glyph outline for unsupported codepoints.
    # Refuse a fixture rendered as tofu, instead of testing OCR against boxes.
    missing = font.getmask("\U0010ffff")
    signature = missing.size, bytes(missing)
    for char in set(text) - {" "}:
        mask = font.getmask(char)
        if (mask.size, bytes(mask)) == signature or not any(bytes(mask)):
            return False
    return True


def _fixture(case):
    from PIL import Image, ImageDraw, ImageFont
    font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [font_root / name for name in case["fonts"]]
    # Fixed cross-platform fallback paths make developer-side checks possible
    # without searching or downloading fonts. Windows candidates stay first.
    candidates.extend([
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ])
    font = None
    chosen = None
    for path in candidates:
        if not path.is_file():
            continue
        try:
            candidate = ImageFont.truetype(str(path), size=52, index=0)
            if _supports_text(candidate, case["input"]):
                font, chosen = candidate, path
                break
        except (OSError, ValueError):
            continue
    if font is None:
        raise FileNotFoundError("A system font with the required glyphs is missing; install the Windows language fonts.")
    margin = 36
    if case["vertical"]:
        # One upright Japanese column; no Latin/punctuation rotation is needed
        # for this deliberately simple five-kanji vertical acceptance fixture.
        step = 66
        image = Image.new("L", (52 + margin * 2, step * len(case["input"]) + margin * 2), 255)
        draw = ImageDraw.Draw(image)
        for index, char in enumerate(case["input"]):
            bounds = font.getbbox(char)
            x = (image.width - (bounds[2] - bounds[0])) // 2 - bounds[0]
            y = margin + index * step - bounds[1]
            draw.text((x, y), char, font=font, fill=0)
    else:
        bounds = font.getbbox(case["input"])
        image = Image.new("L", (bounds[2] - bounds[0] + margin * 2,
                                bounds[3] - bounds[1] + margin * 2), 255)
        ImageDraw.Draw(image).text((margin - bounds[0], margin - bounds[1]), case["input"], font=font, fill=0)
    # Mirror ScreenEngine._capture's grayscale/resize behavior on small images.
    if image.width < 1200 and image.height < 1000:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    return image, str(chosen)


def check_ocr(data_dir: Path) -> list[dict]:
    """OCR five deterministic images with real models and the app's PSM path.

    Models: chi_tra, chi_sim, kor, jpn, jpn_vert. The OCR implementation is the
    application's ScreenEngine. A subclass supplies the image fixture in place
    of display capture; model loading, native/CLI selection and OCR stay real.
    Pass threshold: normalized character error rate <= 0.20, nonempty output.
    """
    data_dir = Path(data_dir)
    rows = []
    for case in OCR_CASES:
        language = case["language"]
        row = _row("ocr", language, input=case["input"], layout="vertical" if case["vertical"] else "horizontal",
                   maximum_character_error_rate=0.2)
        model = data_dir / "tessdata" / (language + ".traineddata")
        try:
            if not model.is_file() or model.stat().st_size <= 1000:
                row["reason"] = "The " + language + " OCR model is missing or incomplete."
                rows.append(row)
                continue
            from screen_engine import ScreenEngine, page_segmentation_mode
            image, font_path = _fixture(case)
            class FixtureScreenEngine(ScreenEngine):
                @staticmethod
                def _capture(rect):
                    return image
            engine = FixtureScreenEngine(data_dir)
            if not engine.engine_ready():
                row.update(reason="No usable local Tesseract OCR engine is installed.")
                rows.append(row)
                continue
            row.update(font=font_path, image_size=list(image.size), psm=page_segmentation_mode(language))
            output = engine.recognize({"left": 0, "top": 0, "width": image.width, "height": image.height}, language)
            metrics = _ocr_metrics(case["input"], output)
            row.update(output=output, **metrics)
            if metrics["output_normalized"] and metrics["character_error_rate"] <= 0.2:
                row["status"] = "passed"
            else:
                row.update(status="failed", reason="OCR exceeded the 20% normalized character error threshold.")
        except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
            row.update(status="missing", reason=_error_text(exc))
        except Exception as exc:
            row.update(status="failed", reason=_error_text(exc))
        rows.append(row)
    return rows
