"""Only sample the rectangle of CaptureManualCheck's authored Japanese window."""
from pathlib import Path
import json
import sys
from unittest.mock import patch

repository, app = map(Path, sys.argv[1:3])
sys.path.insert(0, str(repository / "LiveTranslate/backend"))
from screen_engine import ScreenEngine, ScreenCaptureUnavailable

handle, left, top, width, height = map(int, sys.argv[3:])
rect = dict(left=left, top=top, width=width, height=height)
assert width == 620 and height == 180, "Only the authored source fixture may be captured"

# When the installed baseline is still 0.8.0, demonstrate its actual failure
# with the same authored windows before testing the new implementation.
baseline_file = app / "backend/screen_engine.py"
if "_CAPTURE_INTENT" not in baseline_file.read_text("utf-8-sig"):
    import importlib.util
    spec = importlib.util.spec_from_file_location("capture_published_baseline", baseline_file)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    prior = baseline.ScreenEngine._capture(rect, [handle]).info["glyph_source"][0]
    assert prior.getextrema() == ((255, 255), (255, 255), (255, 255)), prior.getextrema()
    print("PASS original 0.8.0 reproduces a blank covered capture rectangle", flush=True)
try:
    ScreenEngine._capture(rect, [handle])
except ScreenCaptureUnavailable as error:
    assert "covered" in str(error), str(error)
    print("PASS watch reports a covered area instead of blank OCR", flush=True)
else:
    raise AssertionError("Baseline dashboard obstruction was not reproduced")

with ScreenEngine.manual_capture():
    sampled = ScreenEngine._capture(rect, [handle])
source = sampled.info["glyph_source"][0]
assert source.size == (width, height)
assert source.getpixel((2, 2)) == (20, 27, 37), source.getpixel((2, 2))
assert sampled.info["capture_info"]["masked_percent"] == 0
print("PASS manual lease reveals exact authored background pixels", flush=True)

engine = ScreenEngine(app / "data")
with engine.manual_capture():
    read = engine.recognize(rect, "jpn", exclude_windows=[handle], source="ja")
assert "".join(read.split()) == "窓を開けてください。", repr(str(read))
assert "窓を開けてください。" in read.raw_ocr
assert read.capture_info["masked_percent"] == 0
print("PASS real native OCR reads the complete underlying Japanese source", flush=True)

preview = engine.preview(rect, [handle], language="jpn", source="ja")
assert "窓を開けてください。" in preview["diagnostics"]["raw_ocr"]
assert "".join(preview["diagnostics"]["accepted_ocr"].split()) == "窓を開けてください。"
print("PASS explicit preview diagnoses precisely the captured Japanese frame", flush=True)

# The lease must also release when a native grab throws after the dashboard clears.
import mss
with mss.mss() as probe:
    capture_type = type(probe)
with patch.object(capture_type, "grab", side_effect=OSError("authored failed grab")):
    try:
        with ScreenEngine.manual_capture():
            ScreenEngine._capture(rect, [handle])
    except OSError:
        pass
    else:
        raise AssertionError("Synthetic grab failure was not raised")
print("PASS failed manual grab ends its matching UI lease", flush=True)

# Deliberately leave one valid lease unfinished, as if the worker exited in the
# middle of a sample. The owning UI must restore itself through its watchdog.
exchange = ScreenEngine._sample_messages([handle])
assert exchange is not None and exchange(0x8243, 71718)
print("PASS unfinished worker lease enters the bounded UI watchdog path", flush=True)
