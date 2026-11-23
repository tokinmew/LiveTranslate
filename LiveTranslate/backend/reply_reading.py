"""Offline practice guides for a translated reply. Keep uncertainty out of the reading field."""
from functools import lru_cache
import unicodedata

_PUNCT = {"，": ",", "、": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";"}
_SCHEMES = {"zh": "Mandarin pinyin", "zt": "Mandarin pinyin", "ja": "Japanese romaji",
            "ko": "Korean romanization"}
_NOTES = {"zh": "Tone marks show dictionary tones. Tones can change in connected speech.",
          "zt": "Mandarin reading of Traditional Chinese. Tone marks show dictionary tones.",
          "ja": "Practice reading. Names, particles and pitch can vary with context.",
          "ko": "Approximate Seoul pronunciation. eo and eu each represent one vowel."}


def _han(char):
    return "CJK UNIFIED IDEOGRAPH" in unicodedata.name(char, "") or char == "々"


def _hira(char):
    return chr(ord(char) - 96) if "ァ" <= char <= "ヶ" else char


def _longest_entry(dictionary, text, pos, longest):
    for size in range(min(longest, len(text) - pos), 0, -1):
        key = text[pos:pos + size]
        if key in dictionary:
            return key, dictionary[key]
    return "", "?"


@lru_cache(maxsize=1)
def _chinese_dictionary():
    from reply_zh_data import ROWS
    words = dict(row.split("\t") for row in ROWS.splitlines())
    # Frequent grammatical words have several dictionary readings in isolation.
    # Use explicit phrases for their context-dependent readings.
    words.update({"对不起":"duì bu qǐ", "對不起":"duì bu qǐ", "了解":"liǎo jiě",
                  "了不起":"liǎo bu qǐ", "说得":"shuō de", "說得":"shuō de",
                  "听得懂":"tīng de dǒng", "聽得懂":"tīng de dǒng",
                  "知道了":"zhī dào le", "明白了":"míng bai le", "你好":"nǐ hǎo", "您好":"nín hǎo",
                  "大家好":"dà jiā hǎo", "喝水":"hē shuǐ", "说慢":"shuō màn", "說慢":"shuō màn",
                  "请说":"qǐng shuō", "請說":"qǐng shuō", "你说":"nǐ shuō", "你說":"nǐ shuō",
                  "我说":"wǒ shuō", "我說":"wǒ shuō", "会说":"huì shuō", "會說":"huì shuō",
                  "说中文":"shuō zhōng wén", "說中文":"shuō zhōng wén",
                  "想要":"xiǎng yào", "我要":"wǒ yào", "想玩":"xiǎng wán", "玩吧":"wán ba",
                  "玩什么":"wán shén me", "玩什麼":"wán shén me", "别担心":"bié dān xīn",
                  "別擔心":"bié dān xīn", "听到了":"tīng dào le", "聽到了":"tīng dào le"})
    return words, max(map(len, words))


def _mandarin(text):
    words, longest = _chinese_dictionary()
    pieces = []
    pos = 0
    while pos < len(text):
        word, reading = _longest_entry(words, text, pos, longest)
        if pos > 0 and pos + 1 == len(text):
            reading = {"吗":"ma", "嗎":"ma", "吧":"ba", "呢":"ne"}.get(word, reading)
        if not word or reading == "?":
            return None
        pieces.append(reading)
        pos += len(word)
    return " ".join(pieces)


_KANA_ROWS = {
    "あいうえお": "a i u e o", "かきくけこ": "ka ki ku ke ko", "がぎぐげご":"ga gi gu ge go",
    "さしすせそ": "sa shi su se so", "ざじずぜぞ":"za ji zu ze zo", "たちつてと":"ta chi tsu te to",
    "だぢづでど":"da ji zu de do", "なにぬねの":"na ni nu ne no", "はひふへほ":"ha hi fu he ho",
    "ばびぶべぼ":"ba bi bu be bo", "ぱぴぷぺぽ":"pa pi pu pe po", "まみむめも":"ma mi mu me mo",
    "やゆよ":"ya yu yo", "らりるれろ":"ra ri ru re ro", "わゐゑを":"wa i e o", "んゔ":"n vu",
}
_KANA = {c: sound for chars, sounds in _KANA_ROWS.items() for c, sound in zip(chars, sounds.split())}
for _char, _prefix in zip("きぎしじちぢにひびぴみり", ("ky","gy","sh","j","ch","j","ny","hy","by","py","my","ry")):
    for _small, _vowel in zip("ゃゅょ","auo"):
        _KANA[_char + _small] = _prefix + _vowel
_KANA.update({"ふぁ":"fa","ふぃ":"fi","ふぇ":"fe","ふぉ":"fo","てぃ":"ti","でぃ":"di","とぅ":"tu",
              "どぅ":"du","うぃ":"wi","うぇ":"we","うぉ":"wo","ちぇ":"che","しぇ":"she","じぇ":"je",
              "ゔぁ":"va","ゔぃ":"vi","ゔぇ":"ve","ゔぉ":"vo","つぁ":"tsa","つぃ":"tsi","つぇ":"tse","つぉ":"tso"})


def _romaji(kana):
    kana = "".join(map(_hira, kana))
    out = []
    pos = 0
    geminate = False
    while pos < len(kana):
        ch = kana[pos]
        if ch == "っ":
            geminate = True
            pos += 1
            continue
        if ch == "ー":
            if not out or out[-1][-1] not in "aeiou":
                return None
            out.append(out[-1][-1])
            pos += 1
            continue
        pair = kana[pos:pos + 2]
        sound = _KANA.get(pair) if len(pair) == 2 else None
        pos += 2 if sound else 1
        sound = sound or _KANA.get(ch)
        if not sound:
            return None
        if geminate:
            if sound[0] in "aeioun":
                return None
            sound = ("t" if sound.startswith("ch") else sound[0]) + sound
            geminate = False
        if out and out[-1] == "n" and sound[0] in "aeiouy":
            out.append("'")
        out.append(sound)
    return None if geminate else "".join(out)


_INFLECT = {"v5k": ("き","か","いて","いた"), "v5k-s": ("き","か","って","った"),
            "v5g": ("ぎ","が","いで","いだ"), "v5s": ("し","さ","して","した"),
            "v5t": ("ち","た","って","った"), "v5r": ("り","ら","って","った"),
            "v5u": ("い","わ","って","った"), "v5m": ("み","ま","んで","んだ"),
            "v5b": ("び","ば","んで","んだ"), "v5n": ("に","な","んで","んだ"),
            "v1": ("","","て","た")}


@lru_cache(maxsize=1)
def _japanese_dictionary():
    from reply_ja_data import ROWS
    words = {}
    derived = {}
    for line in ROWS.splitlines():
        key, reading = line.split("\t")
        if ":" not in key:
            words[key] = reading
            continue
        base, pos = key.split(":")
        if pos == "adj-i":
            ends = ("くて","く","かった","くない")
        else:
            polite, negative, te, past = _INFLECT[pos]
            ends = [te, past, negative + "ない", negative + "なかった"]
            ends.extend(polite + s for s in ("ます","ました","ません","ましょう","たい"))
            if pos != "v1":
                potential = {"き":"け","ぎ":"げ","し":"せ","ち":"て","り":"れ","い":"え",
                             "み":"め","び":"べ","に":"ね"}[polite]
                ends.extend(potential + s for s in ("る","て","た","ない","ます","ました","ません"))
        for suffix in ends:
            form = base[:-1] + suffix
            value = "?" if reading == "?" else reading[:-1] + suffix
            if form in derived and derived[form] != value:
                value = "?"
            derived[form] = value
    derived.update(words)
    # Whole expressions have stable grammatical readings even where individual
    # characters or kana particles have several readings.
    derived.update({"こんにちは":"こんにちわ","こんばんは":"こんばんわ","では":"でわ",
                    "日本語":"にほんご","私は":"わたし わ","もう一度":"もういちど","お願いします":"おねがいします",
                    "手伝って":"てつだって","聞こえます":"きこえます","分かりました":"わかりました",
                    "お疲れ様":"おつかれさま","お疲れさま":"おつかれさま","大丈夫":"だいじょうぶ",
                    "来ます":"きます","来ました":"きました","来て":"きて","来ない":"こない",
                    "行きます":"いきます","行きましょう":"いきましょう","行って":"いって",
                    "行きたい":"いきたい","何ですか":"なん です か","名前は":"なまえ わ"})
    return derived, max(map(len, derived))


def _japanese(text):
    words, longest = _japanese_dictionary()
    parts = []
    pos = 0
    while pos < len(text):
        word, reading = _longest_entry(words, text, pos, longest)
        if word == "今日は":
            # 今日は can also spell the greeting. A whole isolated token is ambiguous.
            reading = "きょう わ" if pos + len(word) < len(text) else "?"
        if not word:
            ch = text[pos]
            if _han(ch):
                return None
            if parts and ch in "はへを":
                reading = {"は":"わ","へ":"え","を":"お"}[ch]
                word = ch
            else:
                end = pos + 1
                while end < len(text) and not _han(text[end]) and not _longest_entry(words, text, end, longest)[0]:
                    end += 1
                word = reading = text[pos:end]
        latin = [_romaji(token) for token in reading.split()]
        if not latin or not all(latin):
            return None
        parts.extend(latin)
        pos += len(word)
    return " ".join(parts)


_ONSETS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_ON = dict(zip(_ONSETS, ("g","kk","n","d","tt","r","m","b","pp","s","ss","","j","jj","ch","k","t","p","h")))
_VOWELS = "a ae ya yae eo e yeo ye o wa wae oe yo u wo we wi yu eu ui i".split()
_CODAS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
_CLUSTERS = {"ㄳ":"ㄱㅅ","ㄵ":"ㄴㅈ","ㄶ":"ㄴㅎ","ㄺ":"ㄹㄱ","ㄻ":"ㄹㅁ","ㄼ":"ㄹㅂ",
             "ㄽ":"ㄹㅅ","ㄾ":"ㄹㅌ","ㄿ":"ㄹㅍ","ㅀ":"ㄹㅎ","ㅄ":"ㅂㅅ"}
_FINAL = {c:s for chars,s in (("ㄱㄲㅋㄳㄺ","k"),("ㄴㄵㄶ","n"),("ㄷㅅㅆㅈㅊㅌㅎ","t"),
          ("ㄹㄼㄽㄾㅀ","l"),("ㅁㄻ","m"),("ㅂㅍㅄㄿ","p"),("ㅇ","ng"),(" ","")) for c in chars}
_ASPIRATED = {"ㄱ":"ㅋ","ㄷ":"ㅌ","ㅈ":"ㅊ","ㅂ":"ㅍ"}


def _korean(text):
    if text == "서울역":
        return "seoullyeok"
    cells = []
    for char in text:
        code = ord(char) - 0xAC00
        if not 0 <= code < 11172:
            return None
        onset, rest = divmod(code, 588)
        vowel, coda = divmod(rest, 28)
        cells.append([_ONSETS[onset], _VOWELS[vowel], _CODAS[coda]])
    for i in range(len(cells) - 1):
        a, b = cells[i], cells[i + 1]
        tail, head = a[2], b[0]
        if tail == " ":
            continue
        if head == "ㅇ" and tail != "ㅇ":
            keeper, move = _CLUSTERS.get(tail, " " + tail)
            if b[1] == "i" and move in "ㄷㅌ":
                move = "ㅈ" if move == "ㄷ" else "ㅊ"
            b[0] = "ㅇ" if move == "ㅎ" else move
            a[2] = keeper
        elif tail in "ㅎㄶㅀ" and head in _ASPIRATED:
            a[2] = _CLUSTERS.get(tail, " ")[0]
            b[0] = _ASPIRATED[head]
        elif head == "ㅎ" and tail in _ASPIRATED:
            a[2] = " "
            b[0] = "ㅊ" if tail == "ㄷ" and b[1] == "i" else _ASPIRATED[tail]
        elif (_FINAL[tail],head) in {("n","ㄹ"),("l","ㄴ")}:
            a[2], b[0] = "ㄹ", "ㄹ"
        elif head in "ㄴㅁㄹ":
            a[2] = {"k":"ㅇ","t":"ㄴ","p":"ㅁ"}.get(_FINAL[tail], tail)
            if head == "ㄹ" and _FINAL[a[2]] in ("ng","m"):
                b[0] = "ㄴ"
    result = []
    for i, (on, vowel, tail) in enumerate(cells):
        lead = "l" if on == "ㄹ" and i and _FINAL[cells[i-1][2]] == "l" else _ON[on]
        result.append(lead + vowel + _FINAL[tail])
    return "".join(result)


def pronunciation(text, target):
    """Return a display-only reading of the exact translated text, or a reason."""
    scheme = _SCHEMES.get(target, "")
    unavailable = {"pronunciation":"", "pronunciation_scheme":scheme,
                   "pronunciation_note":"A pronunciation guide is unavailable for this language."}
    if not scheme:
        return unavailable
    unavailable["pronunciation_note"] = "No confident reading for the complete reply. Names and uncommon words may need a fluent speaker."
    text = unicodedata.normalize("NFKC", text).strip()
    if not text or len(text) > 4000:
        return unavailable
    if target in ("zh", "zt"):
        convert, eligible = _mandarin, _han
    elif target == "ko":
        convert, eligible = _korean, lambda c: "가" <= c <= "힣"
    else:
        convert, eligible = _japanese, lambda c: _han(c) or "ぁ" <= _hira(c) <= "ゖ" or c == "ー"
    out = []
    pos = 0
    has_reading = False
    retained = False
    while pos < len(text):
        if eligible(text[pos]):
            stop = pos + 1
            while stop < len(text) and eligible(text[stop]):
                stop += 1
            try:
                reading = convert(text[pos:stop])
            except (ImportError, OSError):
                reading = None
            if not reading:
                return unavailable
            if out and (out[-1][-1].isalnum() or out[-1] in (",", ";", ":", ".", "!", "?")):
                out.append(" ")
            out.append(reading)
            has_reading = True
            pos = stop
        else:
            ch = text[pos]
            if ch.isalnum():
                if not ch.isascii():
                    return unavailable
                if pos and eligible(text[pos - 1]):
                    out.append(" ")
                retained = True
            out.append(_PUNCT.get(ch, ch))
            pos += 1
    if not has_reading:
        return unavailable
    note = _NOTES[target]
    if retained:
        note += " Latin letters and digits remain as written."
    return {"pronunciation":"".join(out), "pronunciation_scheme":scheme, "pronunciation_note":note}
