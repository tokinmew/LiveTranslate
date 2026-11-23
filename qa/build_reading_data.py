"""Rebuild reply dictionaries from the project's previously verified offline snapshots."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parent / "captions-v06"
OUT = HERE / "LiveTranslate/backend"
HAN = re.compile(r"[一-鿿]")
KANA = re.compile(r"[ぁ-ゖァ-ヺー]+")


def checked(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Unexpected bytes: {path.name}")
    return json.loads(data)


def write_rows(name, notice, mapping):
    # The incremental updater supports UTF-8 Python. Literal, sorted dictionary
    # rows keep the source readable and the asset available to older installations.
    rows = []
    for surface, values in sorted(mapping.items()):
        reading = next(iter(values)) if len(values) == 1 else "?"
        if any(c in surface + reading for c in ('\n','\t','"', '\\')):
            raise ValueError(surface)
        rows.append(surface + "\t" + reading)
    dest = OUT / ("reply_" + name + "_data.py")
    dest.write_bytes(('"""' + notice + '"""\n\nROWS = """\\\n' + '\n'.join(rows) + '\n"""\n').encode())
    print(dest.name, len(rows), dest.stat().st_size)


def chinese():
    folder = BASE / "lexical-eval/verified"
    receipts = json.loads((folder / "checks.json").read_text("utf-8-sig"))
    table = defaultdict(set)
    for row in receipts:
        if not re.fullmatch(r"zh[1-6]", row["id"]):
            continue
        for word in checked(folder / (row["id"] + ".data"), row["sha256"]):
            for form in word["f"]:
                pinyin = form["i"]["y"].lower()
                for spelling in {word["s"], form["t"]}:
                    if spelling and all(HAN.fullmatch(c) for c in spelling) and pinyin:
                        table[spelling].add(pinyin)
    write_rows("zh", """Mandarin dictionary readings adapted from CC-CEDICT, by its contributors, distributed by MDBG.
HSK selection by Yanis Zafirópulos and Complete HSK Vocabulary contributors (MIT).
Source revision 7ac65bf1a6387d35f1ade478906172a19311c7f9.
This adapted data is licensed under CC BY-SA 4.0. See WORD-DATA-LICENSES.txt for attribution, URLs and MIT notice.
Only Mandarin readings of Han headwords are retained. A question mark marks multiple readings.""", table)


def japanese():
    folder = BASE / "idiom-eval"
    digest = json.loads((folder / "checks.json").read_bytes())["member"]["sha256"]
    words = checked(folder / "reviewed.json", digest)["words"]
    table = defaultdict(set)
    for word in words:
        common = [k for k in word["kanji"] if k["common"] and HAN.search(k["text"])]
        for key in common:
            surface = key["text"]
            kana = [k for k in word["kana"] if KANA.fullmatch(k["text"])
                    and ("*" in k["appliesToKanji"] or surface in k["appliesToKanji"])]
            ordinary = [k for k in kana if k["common"]] or kana
            for item in ordinary:
                reading = item["text"]
                table[surface].add(reading)
                if surface[-1] == reading[-1] and KANA.fullmatch(surface[-1]):
                    for sense in word["sense"]:
                        if not ("*" in sense["appliesToKanji"] or surface in sense["appliesToKanji"]):
                            continue
                        if not ("*" in sense["appliesToKana"] or reading in sense["appliesToKana"]):
                            continue
                        for pos in sense["partOfSpeech"]:
                            if pos in {"adj-i", "v1", "v5u", "v5s", "v5k", "v5k-s",
                                       "v5g", "v5t", "v5m", "v5b", "v5n", "v5r"}:
                                table[surface + ":" + pos].add(reading)
    write_rows("ja", """JMdict common Japanese headwords and kana readings.
Copyright James William Breen and the Electronic Dictionary Research and Development Group (EDRDG).
Source: JMdict-simplified, scriptin, 3.6.2+20261116213322. This adaptation is CC BY-SA 4.0.
See WORD-DATA-LICENSES.txt for attribution, source URLs and license.
Filtered to common written forms; selected applicable readings and inflection classes.
A question mark marks multiple readings. A colon introduces a JMdict part-of-speech tag.""", table)


if __name__ == "__main__":
    chinese()
    japanese()
