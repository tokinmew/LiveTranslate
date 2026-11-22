"""Bridge written-language codes, speech models and Tesseract training data."""
from __future__ import annotations

from language_catalog import canonical_code, REGIONS

# Keys include the direct Argos-to-English routes as well as languages that
# users may import. Each value is the Tesseract training file for that script.
_OCR = {
    "af": "afr", "ar": "ara", "az": "aze", "be": "bel", "bg": "bul",
    "bn": "ben", "bs": "bos", "ca": "cat", "cs": "ces", "cy": "cym",
    "da": "dan", "de": "deu", "el": "ell", "en": "eng", "eo": "epo",
    "es": "spa", "et": "est", "eu": "eus", "fa": "fas", "fi": "fin",
    "fr": "fra", "ga": "gle", "gl": "glg", "gu": "guj", "he": "heb",
    "hi": "hin", "hr": "hrv", "ht": "hat", "hu": "hun", "hy": "hye",
    "id": "ind", "is": "isl", "it": "ita", "ja": "jpn", "ka": "kat",
    "kk": "kaz", "km": "khm", "kn": "kan", "ko": "kor", "ky": "kir",
    "la": "lat", "lo": "lao", "lt": "lit", "lv": "lav", "mk": "mkd",
    "ml": "mal", "mn": "mon", "mr": "mar", "ms": "msa", "mt": "mlt",
    "my": "mya", "ne": "nep", "nl": "nld", "no": "nor", "or": "ori",
    "pa": "pan", "pb": "por", "pl": "pol", "ps": "pus", "pt": "por",
    "ro": "ron", "ru": "rus", "si": "sin", "sk": "slk", "sl": "slv",
    "sq": "sqi", "sr": "srp", "sv": "swe", "sw": "swa", "ta": "tam",
    "te": "tel", "th": "tha", "tl": "fil", "tr": "tur", "uk": "ukr",
    "ur": "urd", "uz": "uzb", "vi": "vie", "zh": "chi_sim", "zt": "chi_tra",
}

_OCR.update({
    "am": "amh", "as": "asm", "bo": "bod", "br": "bre", "ceb": "ceb",
    "ckb": "ckb", "dz": "dzo", "fo": "fao", "fy": "fry", "gd": "gla",
    "jv": "jav", "kmr": "kmr", "lb": "ltz", "mi": "mri", "ne": "nep",
    "oc": "oci", "qu": "que", "sa": "san", "sd": "snd", "su": "sun",
    "tg": "tgk", "ti": "tir", "tt": "tat", "ug": "uig", "yi": "yid",
    "yo": "yor",
})


def ocr_code(source):
    return _OCR.get(canonical_code(source), "")


def speech_code(source):
    from multilingual_speech import SPOKEN_LANGUAGES
    code = canonical_code(source)
    token = {"zt": "zh", "jv": "jw", "pb": "pt"}.get(code, code)
    return token if token in SPOKEN_LANGUAGES else ""

def with_source_options(languages):
    """Keep the pack's actual text code while exposing compatible capture options."""
    enriched = []
    for row in languages:
        code = row["code"]
        enriched.append({
            **row,
            "region": REGIONS.get(code, "Other"),
            "speech_language": speech_code(code),
            "ocr_language": ocr_code(code),
        })
    return enriched
