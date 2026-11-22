"""Preserve the precision of clock times in short translated speech."""
import re


_CLOCK = {
    "ko": re.compile(r"시에|시부터|시까지|시쯤|(?:\d|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*시"),
    "ja": re.compile(r"時|(?:[0-9]|いち|に|さん|よ|ご|ろく|しち|はち|く|じゅう)\s*じ"),
    "zh": re.compile(r"[時时點点]"),
}
_DAYPART = {
    "ko": re.compile(r"오전|오후|새벽|아침|낮|정오|한낮|저녁|밤|자정|야간|해질|일출|해 뜰"),
    "ja": re.compile(r"午前|午後|早朝|朝|昼|夕|晩|夜|深更|真昼|正午|未明|日没|あさ|ひる|ゆうがた|よる"),
    "zh": re.compile(r"上午|下午|凌晨|早|晨|中午|正午|午后|午後|傍晚|晚|夜|半夜|天亮|天黑|日落|黄昏|黃昏"),
}
_LATIN_DAYPART = re.compile(r"\b[ap]\.?\s*m\b", re.I)
_TWENTY_FOUR_HOUR = re.compile(
    r"(?<!\d)(?:0{1,2}|1[3-9]|2[0-4])\s*(?=[:時时點点시])"
    r"|(?:[零〇○]|十[三四五六七八九]|二十[一二三四]?|廿[一二三四]?)\s*(?:時|时|點|点)"
    r"|(?:영|공|십[삼사오육칠팔구]|이십[일이삼사]?)\s*시"
)
_MERIDIEM = re.compile(
    r"\b(?P<hour>(?:1[0-2]|0?[1-9])(?::[0-5]\d)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s*(?P<marker>[ap]\.?\s*m\.?)(?![\w])", re.I
)


def preserve_clock_precision(source, english, language):
    """Remove an explicit English AM/PM invented for an unspecified source clock hour."""
    if language not in _CLOCK or not _MERIDIEM.search(english):
        return english
    if (not _CLOCK[language].search(source) or _DAYPART[language].search(source)
            or _LATIN_DAYPART.search(source) or _TWENTY_FOUR_HOUR.search(source)):
        return english

    def unqualified(match):
        rest = english[match.end():].lstrip()
        sentence_end = match["marker"].endswith(".") and (not rest or rest[0].isupper())
        return match["hour"] + ("." if sentence_end else "")

    return _MERIDIEM.sub(unqualified, english)
