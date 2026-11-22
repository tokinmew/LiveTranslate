"""Run the real screen watcher on generated panels, without acquiring any display."""
import json
import os
import sys
import threading
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "LiveTranslate/backend"))
from worker import Worker


def panel(source, font):
    rgb = Image.new("RGB", (840, 150), (221, 231, 242))
    draw = ImageDraw.Draw(rgb)
    fonts = Path(os.environ["WINDIR"]) / "Fonts"
    draw.text((28, 12), source, font=ImageFont.truetype(str(fonts / font), 33), fill=(22, 34, 44))
    draw.text((28, 85), "Press here to continue.", font=ImageFont.truetype(str(fonts / "segoeui.ttf"), 32),
              fill=(22, 34, 44))
    frame = rgb.convert("L").resize((1680, 300), Image.Resampling.LANCZOS)
    frame.info.update(desktop_map=(-100, 20, .5, .5), glyph_source=(rgb, -100, 20))
    return frame


def replay(profile, source, face, expected_language, expected_words):
    source_frame = panel(source, face)
    english_frame = panel("Open the settings menu.", "segoeui.ttf")
    events = []
    counts = Counter()
    scanned = threading.Event()
    done = threading.Event()

    def capture(*args):
        counts["scans"] += 1
        if counts["scans"] >= 4:
            scanned.set()
        return source_frame if counts["scans"] <= 3 else english_frame

    def send(event):
        events.append(event)
        if event.get("type") == "screen_clear" or event.get("state") == "error":
            done.set()

    model_data = Path(os.environ.get("LIVETRANSLATE_TEST_DATA", HERE.parents[1] / "captions-v04/qa-installed/LiveTranslate/data"))
    worker = Worker(model_data, send)
    region = dict(left=-100, top=20, width=840, height=150)
    with patch.object(worker.screen, "_capture", side_effect=capture):
        try:
            worker.dispatch(dict(command="start_screen", region=region, profile=profile, interval=.5, session_id="fixture"))
            if not done.wait(15):
                raise AssertionError((profile, counts, [(e.get("type"), e.get("message")) for e in events]))
        finally:
            worker.dispatch(dict(command="stop_screen"))
            worker.close()
            if worker.screen_thread:
                worker.screen_thread.join(5)
    assert scanned.is_set(), (profile, counts)
    captions = [e for e in events if e.get("type") == "screen"]
    assert len(captions) == 1, (profile, [(e.get("original"), e.get("text")) for e in captions])
    caption, = captions
    regions = caption["regions"]
    assert caption["language"] == expected_language and caption["original"] == source, caption
    assert all(word in caption["text"].casefold() for word in expected_words), caption["text"]
    assert regions and all(-100 <= r["left"] < r["left"]+r["width"] <= 740 and
                           20 <= r["top"] < r["top"]+r["height"] < 105 for r in regions), regions
    assert all("cover_png" in r or "background_rgb" in r for r in regions), regions
    assert "Press" not in caption["original"] and any(c.isascii() and c.isalpha() for c in caption["text"])
    assert sum(e.get("type") == "screen_clear" for e in events) == 1
    return dict(profile=profile, source=source, observed=caption["original"], english=caption["text"],
                emitted=len(captions), scans=counts["scans"], regions=len(regions),
                language=caption["language"])


if __name__ == "__main__":
    fixtures = [
        ("zh", "请把门关上。", "msyh.ttc", "zh", ("close", "door")),
        ("zt", "請把門關上。", "msjh.ttc", "zt", ("close", "door")),
        ("ja", "次の電車は何時ですか。", "YuGothM.ttc", "ja", ("next", "train")),
        ("ko", "도서관은 어디에 있나요?", "malgun.ttf", "ko", ("where", "library")),
        ("auto", "次の電車は何時ですか。", "YuGothM.ttc", "ja", ("next", "train")),
    ]
    rows = [replay(*fixture) for fixture in fixtures]
    (HERE / "screen-watch-replays.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=True))
