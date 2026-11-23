"""Replay six previously generated response strings through the worker and local reading code."""
import argparse
import json
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate/backend"))
from worker import Worker


def replay(source):
    raw = json.loads(source.read_text("utf8"))
    draft = raw["freeform_english"]
    samples = raw["samples"]
    worker = Worker.__new__(Worker)
    worker.closing = threading.Event()
    worker.speech_translation_lock = threading.Lock()
    worker.control_lock = threading.RLock()
    worker.text_lock = threading.RLock()
    worker.jobs = queue.Queue(maxsize=1)
    # Chinese script conversion was already applied to the recorded native outputs.
    worker.text = SimpleNamespace(convert_chinese=lambda text, code: text)
    responses = []
    worker.send = responses.append
    def recorded_translation(phrases, *, target):
        assert phrases == [("en", draft)]
        return [samples[target]["text"]]
    worker._quality_engine = lambda request: SimpleNamespace(translate_many=recorded_translation)
    checked = {}
    for request_id, code in enumerate(samples, 1):
        worker.execute(dict(command="practice_reply", text=draft, target=code, id=request_id))
        message = responses.pop()
        assert message["id"] == request_id and message["type"] == "practice_reply"
        assert message["method"] == "model" and message["target"] == code
        assert message["text"] == samples[code]["text"] and message["pronunciation_note"]
        if code in {"zh","zt","ja","ko"}:
            assert message["pronunciation"] and message["pronunciation_scheme"]
        else:
            assert message["pronunciation"] == ""
        checked[code] = message
    assert checked["zh"]["pronunciation"] == checked["zt"]["pronunciation"]
    with patch("reply_reading.pronunciation", side_effect=OSError("Synthetic provider error")):
        worker.execute(dict(command="practice_reply", target="ja", text=draft, id=7))
        fallback = responses.pop()
        assert fallback["text"] == samples["ja"]["text"] and not fallback["pronunciation"]
        assert fallback["pronunciation_note"]
    worker.jobs.put_nowait({})
    worker.dispatch(dict(command="practice_reply", target="ja", text=draft, id=8))
    assert responses.pop()["id"] == 8
    worker.jobs.get_nowait()
    worker.dispatch(dict(command="practice_reply", target="ja", text="Thank you.", id=9))
    worker.execute(worker.jobs.get_nowait())
    assert responses.pop()["method"] == "phrasebook"
    return dict(source="Previously recorded six model responses, no model inference", samples=checked,
                provider_failure_preserves_translation=True, queue_rejection_id_and_retry=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = replay(args.source)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(result, ensure_ascii=True))
