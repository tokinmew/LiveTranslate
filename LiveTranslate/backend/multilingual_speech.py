"""Translate additional Whisper languages locally, after independent source checks."""
from functools import lru_cache
import re
import unicodedata


# Language tokens in the multilingual Base/Small tokenizer. English is excluded
# from capture choices. Large-v3 has one additional language token, Cantonese.
BASE_SPEECH_LANGUAGES = frozenset("""
zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da
hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is
hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz
fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su
""".split())
SPOKEN_LANGUAGES = BASE_SPEECH_LANGUAGES | {"yue"}
CJK_SPEECH = frozenset(("zh", "ja", "ko"))
DIRECT_SPEECH = SPOKEN_LANGUAGES - CJK_SPEECH

# Most languages use a single writing system. Permit a second script when a
# language commonly uses both. Other language tokens use Latin script.
_SCRIPT_GROUPS = {
    "ARABIC": "ar az fa ha kk pa ps sd ur uz",
    "ARMENIAN": "hy", "BENGALI": "as bn", "CJK": "yue", "CYRILLIC": "az ba be bg bs kk mk mn ru sr tg tt uk uz",
    "DEVANAGARI": "hi mr ne sa sd", "ETHIOPIC": "am", "GEORGIAN": "ka", "GREEK": "el",
    "GUJARATI": "gu", "GURMUKHI": "pa", "HEBREW": "he yi", "KANNADA": "kn",
    "KHMER": "km", "LAO": "lo", "MALAYALAM": "ml", "MONGOLIAN": "mn",
    "MYANMAR": "my", "SINHALA": "si", "TAMIL": "ta", "TELUGU": "te",
    "THAI": "th", "TIBETAN": "bo",
}
_SCRIPTS = {code: {script for script, languages in _SCRIPT_GROUPS.items() if code in languages.split()}
            for code in DIRECT_SPEECH}
for _code, _scripts in _SCRIPTS.items():
    if not _scripts or _code in {"az", "bs", "ha", "kk", "sr", "tt", "uz"}:
        _scripts.add("LATIN")

_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?。！？।]+(?:[”’\"])?(?:\s+|$)")
_ENGLISH_REPLIES = frozenset("""
ah bye cool done fine good great hello hey hi no oh ok okay right sure thanks way welcome
well wow yeah yep yes
""".split())
# Short greetings are often too brief for the written-language classifier.
# These entries establish source identity only. Whisper still translates them.
_SHORT_REPLIES = {
    "af": {"dankie", "baie dankie"}, "br": {"trugarez"}, "bs": {"hvala"},
    "ca": {"gràcies", "bon dia"}, "cs": {"děkuji", "ahoj"}, "cy": {"diolch"},
    "da": {"tak", "hej"},
    "de": {"danke", "bitte", "hallo", "nein", "tschüss"},
    "es": {"gracias", "hola", "adiós", "sí"}, "fi": {"kiitos"},
    "fr": {"merci", "bonjour", "bonsoir", "salut"}, "hu": {"köszönöm"},
    "et": {"aitäh", "tere"}, "fo": {"takk"}, "gl": {"grazas"}, "ha": {"na gode"},
    "haw": {"mahalo", "aloha"}, "hr": {"hvala"}, "ht": {"mèsi", "bonjou"},
    "id": {"bukan", "iya", "makasih", "terima kasih", "tidak", "tolong"},
    "is": {"takk", "halló"}, "it": {"grazie", "ciao", "prego"},
    "jw": {"matur nuwun"}, "la": {"gratias tibi ago"}, "lb": {"moien"},
    "ln": {"mbote"}, "lt": {"ačiū"}, "lv": {"paldies"}, "mg": {"misaotra"},
    "mi": {"kia ora"}, "ms": {"terima kasih"}, "mt": {"grazzi"}, "nn": {"takk"},
    "nl": {"bedankt", "hallo"}, "no": {"takk", "hei"}, "pl": {"dziękuję", "cześć"},
    "oc": {"mercés", "mercés plan"}, "pt": {"obrigado", "obrigada", "olá"}, "ro": {"mulțumesc"},
    "sk": {"ďakujem", "ahoj"}, "sl": {"hvala"}, "sn": {"mazvita"}, "so": {"mahadsanid"},
    "sq": {"faleminderit"}, "sr": {"hvala"}, "su": {"hatur nuhun"},
    "sv": {"tack", "hej"}, "sw": {"asante", "asante sana"}, "tl": {"opo", "salamat", "sige"},
    "tr": {"merhaba", "teşekkürler"}, "uz": {"rahmat"}, "vi": {"chào", "cảm ơn", "dạ", "không", "vâng"},
}


@lru_cache(maxsize=1)
def _text_identifier():
    try:
        from multilingual_text import local_identifier
        return local_identifier()
    except (ImportError, OSError, ValueError):
        return None


def _identified(text):
    identifier = _text_identifier()
    return identifier.classify(text) if identifier is not None else ("", 0.0)


@lru_cache(maxsize=4096)
def _script(char):
    return unicodedata.name(char, "").partition(" ")[0]


def _source_supported(text, language):
    from multilingual_text import english_words, short_foreign
    text = unicodedata.normalize("NFC", text)
    parts = [piece for piece in _SENTENCE_END.split(text) if _WORDS.search(piece)]
    if len(parts) > 1:
        # These share one timestamp. Including either side would feed both
        # languages to the translator, so ambiguous mixed turns stay silent.
        return all(_source_supported(piece, language) for piece in parts)
    words = _WORDS.findall(text.casefold())
    if not words:
        return False
    letters = [char for char in text if char.isalpha()]
    scripts = _SCRIPTS[language]
    native = sum(_script(char) in scripts for char in letters)
    if not native or native * 2 < len(letters):
        return False
    if any(_script(char) not in {"LATIN", ""} and _script(char) in scripts for char in letters):
        return True
    if english_words(words) or all(word in _ENGLISH_REPLIES for word in words):
        return False
    if short_foreign(text, language) or " ".join(words) in _SHORT_REPLIES.get(language, ()):
        return True
    label, confidence = _identified(text)
    if not label or label == "en":
        return False
    equivalent = {"jw": "jv", "nn": "no"}.get(language, language)
    agrees = label in (language, equivalent)
    if agrees:
        return len(words) > 1 or confidence >= .60
    # Short Latin-script fragments frequently resemble an English name or
    # label. When text identification supports the acoustic language, require
    # the two to agree for short fragments and for strong conflicting reads.
    identifier = _text_identifier()
    known = equivalent in identifier.nb_classes if identifier is not None else False
    return len(words) >= (4 if known else 2) and (not known or confidence < .80)


def _english_translation(text, original, language):
    from multilingual_text import english_words, short_foreign
    words = _WORDS.findall(text.casefold())
    if not words or words == _WORDS.findall(original.casefold()):
        return False
    letters = [c for c in text if c.isalpha()]
    if sum(_script(c) == "LATIN" for c in letters) < len(letters) * .70:
        return False
    if english_words(words) or all(word in _ENGLISH_REPLIES for word in words):
        return True
    if short_foreign(text, language) or " ".join(words) in _SHORT_REPLIES.get(language, ()):
        return False
    label, confidence = _identified(text)
    if label == language and confidence >= .70:
        return False
    if len(words) >= 2 and label and label != "en" and confidence >= .90:
        return False
    return True


def _language_confident(info, selection, short):
    if selection not in ("auto", info.language):
        return False
    alternatives = dict(info.all_language_probs or ())
    probability = info.language_probability
    runner_up = max((p for code, p in alternatives.items() if code != info.language), default=0.0)
    return (probability >= (.67 if short else .55) and probability - runner_up >= .18
            and probability - alternatives.get("en", 0.0) >= .28)


def translate_spans(model, clip, source, info, selection, short, memory, options, cancelled, confident_segment):
    """Check per-segment source evidence and translate only the approved time ranges."""
    from speech_memory import SpeechCaptionMemory
    if cancelled() or not _language_confident(info, selection, short):
        return
    language = info.language
    segments = []
    for seg in source:
        if cancelled():
            return
        segments.append(seg)
    groups = []
    current = []
    for seg in segments:
        if (confident_segment(seg) and seg.no_speech_prob <= .60 and _source_supported(seg.text, language)):
            current.append(seg)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    for group in groups:
        if cancelled():
            return
        original = " ".join(seg.text.strip() for seg in group)
        english = memory.lookup(original, language) if isinstance(memory, SpeechCaptionMemory) else None
        if english is None:
            # Keep padded boundaries for a brief isolated reply. Elsewhere the
            # rejected segment's audio must never enter the translation window.
            if len(group) == len(segments):
                audio = clip
            else:
                start = max(0, round(group[0].start * 16000))
                end = min(len(clip), round(group[-1].end * 16000))
                audio = clip[start:end]
            if not len(audio):
                continue
            translated, _ = model.transcribe(audio, task="translate", language=language,
                                             without_timestamps=True, **options)
            parts = []
            for seg in translated:
                if cancelled():
                    return
                if not confident_segment(seg) or seg.no_speech_prob > .65:
                    parts = []
                    break
                parts.append(seg.text.strip())
            english = " ".join(parts)
            if not _english_translation(english, original, language):
                continue
        if not cancelled():
            yield {"text": english, "original": original, "language": language}
