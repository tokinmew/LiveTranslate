"""Render local fixtures; the screen reader's capture function is replaced for every test."""
from pathlib import Path
import json
import os
import statistics
import sys
import time

BASE = Path(__file__).resolve().parent
PROJECT = BASE if (BASE / "LiveTranslate").is_dir() else BASE.parent
sys.path.insert(0, str(PROJECT / "LiveTranslate/backend"))
from PIL import Image, ImageDraw, ImageFont
from screen_engine import ScreenEngine
from screen_geometry import positioned_segments
from text_engine import TextEngine
from language_routes import ocr_code
from unittest.mock import patch

DATA = Path(os.environ.get("LIVETRANSLATE_TEST_DATA", PROJECT.parent / "captions-v06/quality-data"))
LATIN = {
    "de": ["Bitte schließe das Fenster.", "Der Zug kommt heute später.", "Wo ist der nächste Bahnhof?", "Danke für deine Hilfe."],
    "es": ["¿Dónde está la estación?", "La puerta está cerrada.", "Necesito ayuda con esto.", "Muchas gracias por venir."],
    "fr": ["Veuillez ouvrir la porte.", "Où se trouve la gare ?", "Merci beaucoup pour votre aide.", "Le train arrive dans cinq minutes."],
    "it": ["Per favore apri la porta.", "Dove si trova la stazione?", "Grazie mille per il tuo aiuto.", "Il treno è in ritardo."],
    "nl": ["Ik wil graag naar huis.", "Waar is het station?", "Bedankt voor de hulp.", "Het venster is gesloten."],
    "pt": ["Onde fica a estação?", "O trem chega em cinco minutos.", "Muito obrigado pela ajuda.", "A porta está fechada."],
}
CJK = {
    "zh": ("msyh.ttc", ["请打开窗户。", "我们明天见。", "谢谢你的帮助。"]),
    "zt": ("msjh.ttc", ["請打開窗戶。", "我們明天見。", "謝謝你的幫助。"]),
    "ja": ("YuGothM.ttc", ["明日また会いましょう。", "窓を開けてください。", "ありがとうございます。"]),
    "ko": ("malgun.ttf", ["창문을 열어 주세요.", "우리 내일 만나요.", "도와주셔서 감사합니다."]),
}
UI = ["Open the settings menu.", "Press here to continue.", "Save all changes?", "Exit the current session."]
engine = ScreenEngine(DATA)
text_engine = TextEngine(DATA)
engine.accepts_source_line = text_engine.accepts_source_line
outputs = []
for code in [*LATIN, *CJK]:
    face, lines = ("segoeui.ttf", LATIN[code]) if code in LATIN else CJK[code]
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / face), 33)
    regular = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/segoeui.ttf"), 32)
    with engine.watch_models():
        for idx, target in enumerate(lines):
            image = Image.new("RGB", (840, 150), (221, 231, 242))
            draw = ImageDraw.Draw(image)
            draw.text((28, 12), target, font=font, fill=(22, 34, 44))
            draw.text((28, 85), UI[idx], font=regular, fill=(22, 34, 44))
            gray = image.convert("L").resize((image.width*2, image.height*2), Image.Resampling.LANCZOS)
            gray.info["desktop_map"] = (-100, 20, .5, .5)
            gray.info["glyph_source"] = (image, -100, 20)
            rect = dict(left=-100, top=20, width=image.width, height=image.height)
            with patch.object(engine, "_capture", return_value=gray):
                t = time.perf_counter()
                first = engine.recognize_watched(rect, ocr_code(code), "", code, [])
                recognized_ms = (time.perf_counter() - t) * 1000
                t = time.perf_counter()
                second = engine.recognize_watched(rect, ocr_code(code), "", code, [])
                cached_ms = (time.perf_counter() - t) * 1000
                assert str(first) == str(second) and first.regions == second.regions
                placements = [box for line, words in first.regions for _, box in positioned_segments(line, words, code) if box]
                inserted = [box for box in placements if box[1] >= 100]
                in_bounds = bool(placements) and all(-85 <= l < r <= 740 and 20 <= top < b < 105 for l,top,r,b in placements)
                clean = lambda line: "".join(c.casefold() for c in line if c.isalpha())
                outputs.append(dict(code=code, line=target, output=str(first), exact=str(first)==target,
                                    letters=clean(str(first)) == clean(target), english_boxes=len(inserted),
                                    fits=in_bounds, covers=bool(getattr(first,"glyph_covers",None)), warm=bool(idx),
                                    read_ms=round(recognized_ms,2), cached_ms=round(cached_ms,2)))
report = BASE / "qa-screen-results.json"
report.write_text(json.dumps(outputs,ensure_ascii=False,indent=2),encoding="utf-8")
for code in [*LATIN, *CJK]:
    group = [r for r in outputs if r["code"]==code]
    print(code, len(group), "text/letters/boxes/english",*(sum(bool(r[k]) for r in group) for k in ("exact","letters","fits","english_boxes")),
          "warm/cached ms", *(round(statistics.median(r[k] for r in group if r["warm"]),1) for k in ("read_ms","cached_ms")))

negatives = [
    ["Press any key to continue.", "Loading", "Menu", "Open settings", "Help"],
    ["Invoice overdue", "Save all changes", "Exit", "Voice chat", "Main menu"],
    ["The microphone has been muted.", "Repeat the previous sentence.", "Check for updates", "OK", "NO"],
    ["The quick brown fox jumps over the lazy dog.", "Forest adventure", "Learn more", "Pause", "Choose your character"],
]
wrong = []
for code in [*LATIN, *CJK]:
    with engine.watch_models():
        for rows in negatives:
            image=Image.new("RGB",(820,276),"white")
            draw=ImageDraw.Draw(image)
            for i, word in enumerate(rows):
                draw.text((20,5+i*52),word,font=regular,fill="black")
            gray=image.convert("L").resize((1640,552), Image.Resampling.LANCZOS)
            gray.info["desktop_map"]=(0,0,.5,.5)
            gray.info["glyph_source"]=(image,0,0)
            rect=dict(left=0,top=0,width=820,height=276)
            with patch.object(engine,"_capture",return_value=gray):
                result=engine.recognize_watched(rect,ocr_code(code),"",code,[])
            if result:
                wrong.append((code,rows,str(result)))
print("English challenge:", len(negatives)*len(rows)*(len(LATIN)+len(CJK)), "label/source combinations", "false positive screens", len(wrong))
(BASE/"qa-screen-english.json").write_text(json.dumps(wrong,ensure_ascii=False,indent=2),encoding="utf8")
