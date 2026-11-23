"""Check the public reply command with generated text and a local NLLB pack."""
import argparse
import json
import queue
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LiveTranslate/backend"))
from worker import Worker
from language_catalog import NLLB_TAGS
from reply_phrases import lookup


def run(model_data):
    events = queue.Queue()
    case_count = 0
    serial = 0
    def check(condition, name):
        nonlocal case_count
        if not condition:
            raise AssertionError(name)
        case_count += 1

    def request(worker, command, **fields):
        nonlocal serial
        serial += 1
        worker.dispatch({"command": command, "id": serial, **fields})
        while True:
            result = events.get(timeout=45)
            if result.get("id") == serial:
                return result
            if result["type"] != "status":
                raise AssertionError(result)

    with tempfile.TemporaryDirectory() as tmp:
        worker = Worker(Path(tmp), events.put)
        try:
            # The worker's recording methods are never requested.
            for code in ("zh", "zt", "ja", "ko"):
                for draft in ("hello", "Thank you!", "Please say that again.",
                              "I don’t understand", "Can you speak more slowly?"):
                    reply = request(worker, "practice_reply", target=code, text=draft)
                    curated = lookup(draft, code)
                    check(reply["type"] == "practice_reply" and reply["method"] == "phrasebook"
                          and reply["target"] == code and bool(reply["pronunciation"])
                          and all(reply[key] == value for key, value in curated.items()),
                          (code, draft, reply))
            check(worker.speech_translator is None, "Starter replies must not load a model")
            missing = request(worker, "practice_reply", target="ko", text="How do I get there?")
            check(missing["type"] == "error" and "Get more text languages" in missing["message"],
                  "Missing-model action")
            for code, draft in (("auto","Hello"),("en","Hello"),("unknown","Hello"),
                                ("ja","   "),("ko","x"*501),([], "Hello"),("zh", {})):
                check(request(worker, "practice_reply", target=code, text=draft)["type"] == "error",
                      "Invalid reply input")
            with patch.object(worker.jobs, "put_nowait", side_effect=queue.Full):
                busy = request(worker, "practice_reply", target="ja", text="Thank you.")
                check(busy["type"] == "error" and "pending" in busy["message"],
                      "A full worker queue returns an error tied to the draft so the user can retry")
            check(request(worker, "practice_reply", target="ja", text="Thank you.")["method"] == "phrasebook",
                  "Retry works after a queue overflow")
            worker.speech_translation_dir = model_data
            english = "Where is the library?"
            samples = {}
            for code, required in {"ja": "図書館", "ko": "도서관", "zh": "图书馆",
                                   "zt": "圖書館", "fr": "biblioth", "es": "biblioteca"}.items():
                start = perf_counter()
                reply = request(worker, "practice_reply", target=code, text=english)
                duration = perf_counter() - start
                check(reply["type"] == "practice_reply" and reply["target"] == code and
                      reply["method"] == "model" and required in reply["text"].casefold(), (code, reply))
                check({"pronunciation", "pronunciation_scheme", "pronunciation_note"} <= reply.keys(),
                      "Reading schema")
                again = request(worker, "practice_reply", target=code, text=english)
                check(reply["text"] == again["text"], "Repeated wording in same target")
                samples[code] = dict(text=reply["text"], seconds=round(duration,4),
                                     pronunciation=reply["pronunciation"], scheme=reply["pronunciation_scheme"],
                                     note=reply["pronunciation_note"])
            def broken_reader(text, target):
                raise OSError("Synthetic unavailable pronunciation provider.")
            with patch.dict(sys.modules, {"reply_reading": SimpleNamespace(pronunciation=broken_reader)}):
                fallback = request(worker, "practice_reply", target="ja", text=english)
                check(fallback["text"] == samples["ja"]["text"] and not fallback["pronunciation"]
                      and bool(fallback["pronunciation_note"]), "Unavailable reading preserves translated text")
            for source in ("auto", "en", "zh", "ko", "de"):
                received = request(worker, "translate", source=source, text=english)
                check(received["type"] == "result" and not received.get("text"),
                      ("English still suppressed for incoming route", source))
            check(not worker.audio.running and worker.screen_current is None, "Inputs stayed closed")
            vocab = worker.speech_translation_dir / "nllb-600m-int8" / "shared_vocabulary.txt"
            tokens = set(vocab.read_text("utf8").splitlines())
            check({"eng_Latn", *NLLB_TAGS.values()} <= tokens, "All 201 target tokens in on-disk vocabulary")
            return dict(checks=case_count, starter_pairs=20, freeform_english=english, samples=samples)
        finally:
            worker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_parent", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = run(args.model_parent.resolve())
    if args.output:
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(receipt, ensure_ascii=True))
