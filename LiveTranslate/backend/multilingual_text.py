"""Offline source validation for written text, independent of capture hardware."""
from collections import Counter
from functools import lru_cache
import re
import threading
import unicodedata

from language_catalog import NLLB_TAGS, canonical_code

_ID_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _load_identifier(model_type, model_file):
    return model_type.from_model_file(model_file, norm_probs=True)


def local_identifier():
    from py3langid.langid import LanguageIdentifier, MODEL_FILE
    with _ID_LOCK:
        return _load_identifier(LanguageIdentifier, MODEL_FILE)


def model_files_present(directory):
    from speech_translation import verified_folder
    try:
        return verified_folder(directory) is not None
    except (OSError, ValueError):
        return False


# Unicode character names cover supplementary blocks and presentation forms.
# Japanese and Chinese share ideographs and are disambiguated by the CJK router.
_SCRIPT_NAMES = dict(row.split() for row in """
ARABIC Arab
ARMENIAN Armn
BENGALI Beng
CYRILLIC Cyrl
DEVANAGARI Deva
ETHIOPIC Ethi
GEORGIAN Geor
GREEK Grek
GUJARATI Gujr
GURMUKHI Guru
HANGUL Hang
HEBREW Hebr
KANNADA Knda
KHMER Khmr
LAO Laoo
LATIN Latn
MALAYALAM Mlym
MYANMAR Mymr
ORIYA Orya
SINHALA Sinh
TAMIL Taml
TELUGU Telu
THAI Thai
TIBETAN Tibt
TIFINAGH Tfng
""".strip().splitlines())


@lru_cache(maxsize=4096)
def _script(char):
    name = unicodedata.name(char, '')
    if name.startswith(('CJK ', 'BOPOMOFO ')):
        return 'Hani'
    if name.startswith(('KATAKANA ', 'HIRAGANA ', 'HALFWIDTH KATAKANA ')):
        return 'Jpan'
    return _SCRIPT_NAMES.get(name.partition(' ')[0], '')


@lru_cache(maxsize=1024)
def dominant_script(text):
    counts = Counter(_script(char) for char in text if char.isalpha())
    if not counts:
        return ''
    script, count = counts.most_common(1)[0]
    return script if count * 3 >= sum(counts.values()) * 2 else ''


def _words(text):
    return re.findall(r"[^\W\d_]+", text.casefold())


# A language classifier has little evidence on one-word buttons or names.
# Only accept short Latin captions with known, distinctive wording or enough
# evidence. Ordinary English UI vocabulary and ambiguous labels stay hidden.
_ENGLISH = frozenset("""
a about accept account achievement achievements active add advanced after again all allow am an and any
app apply are as at audio auto available back background before best black blue both browse build button
by cancel capture change chat check choose clear click close closed color come confirm connect connected
connection continue control controls copy could create current custom customize dark data default delete
detect details device devices did directory disable disabled display do does done down download drag drop
edit effects enable enabled end english enter error escape exit failed fast favorite favorites file files
filter find first for found free friend friends from full game games general get go graphics green group
had has have he headset help here hide high history home how i if ignore image in input install installed
into is it item items join joined just keep key keyboard label language languages last left level library
light like line list listen listening live load loading local lock log login long look loud low main make
map match me menu message mic microphone mode model models more move music mute my name network new next
no none normal now of off offline ok okay on once one online only open opening option options or original
other our out output overlay panel party pass password paste pause paused personal photo play player players
playing please press preview previous privacy profile progress quality quit read ready recent record red refresh
region release releases remove render repair repeat replay report reset resolution restart restore resume retry
return right room run running save saved scan scanning scene screen search second select selected server
session set settings setup share she short should show sign size skip slow small so some sound source space
speaker speakers speech speed start starting status stay stop stopped store stream submit subtitle subtitles
success support switch system tab test text than thank thanks that the their them then there these they this
those time title to tool tools top track translate translated translation translations try turn two type unmute
up update updated updates upload use user username version video view voice volume wait waiting want warn
was watch we welcome well were what when where which while white who why will window windows with would
wrong yes you your exit continue multiplayer singleplayer fullscreen launch quit headphones render resolution
""".split())
_SHORT_FOREIGN = {
    'de': {'danke':'Thank you.', 'vielen dank':'Thank you very much.', 'guten tag':'Good day.',
           'guten morgen':'Good morning.', 'auf wiedersehen':'Goodbye.'},
    'fr': {'bonjour':'Hello.', 'merci':'Thank you.', 'merci beaucoup':'Thank you very much.',
           'au revoir':'Goodbye.', 'bonsoir':'Good evening.'},
    'es': {'hola':'Hello.', 'gracias':'Thank you.', 'muchas gracias':'Thank you very much.',
           'hasta luego':'See you later.', 'buenos días':'Good morning.'},
    'it': {'grazie':'Thank you.', 'buongiorno':'Good morning.', 'arrivederci':'Goodbye.', 'buonasera':'Good evening.'},
    'pt': {'obrigado':'Thank you.', 'obrigada':'Thank you.', 'bom dia':'Good morning.',
           'muito obrigado':'Thank you very much.'},
    'nl': {'bedankt':'Thank you.', 'goedemorgen':'Good morning.', 'dank je wel':'Thank you.'},
    'vi': {'xin chào':'Hello.', 'chào':'Hello.', 'cảm ơn':'Thank you.', 'tạm biệt':'Goodbye.', 'vâng':'Yes.'},
    'id': {'selamat pagi':'Good morning.', 'selamat malam':'Good evening.',
           'terima kasih':'Thank you.', 'tidak':'No.'},
    'ms': {'selamat pagi':'Good morning.', 'selamat malam':'Good evening.',
           'terima kasih':'Thank you.', 'tidak':'No.'},
    'tl': {'salamat':'Thank you.', 'magandang umaga':'Good morning.', 'opo':'Yes.'},
    'tr': {'teşekkürler':'Thank you.', 'günaydın':'Good morning.', 'merhaba':'Hello.'},
    'pl': {'dziękuję':'Thank you.', 'dzień dobry':'Good morning.'}, 'cs': {'děkuji':'Thank you.', 'dobrý den':'Good day.'},
    'sv': {'tack så mycket':'Thank you very much.'}, 'fi': {'kiitos':'Thank you.', 'hyvää huomenta':'Good morning.'},
    'ro': {'mulțumesc':'Thank you.'}, 'hu': {'köszönöm':'Thank you.'}, 'eu': {'eskerrik asko':'Thank you.'},
}
_UNIQUE_SHORT = {}
for _lang, _phrases in _SHORT_FOREIGN.items():
    for _phrase in _phrases:
        _UNIQUE_SHORT[_phrase] = None if _phrase in _UNIQUE_SHORT else _lang


def english_words(words):
    if not words:
        return True
    hits = sum(w in _ENGLISH for w in words)
    return hits == len(words) or (hits >= 3 and hits / len(words) >= .65)


def short_foreign(phrase, source):
    words = ' '.join(_words(phrase))
    return words in _SHORT_FOREIGN.get(canonical_code(source), ())


def standalone_translation(text, source):
    """Conventional translations for complete greetings, without matching a longer sentence."""
    source = canonical_code(source)
    phrase = unicodedata.normalize('NFKC', text).strip().casefold().rstrip('.!').strip()
    return _SHORT_FOREIGN.get(source, {}).get(' '.join(phrase.split()))


@lru_cache(maxsize=256)
def _script_candidates(script):
    return tuple(code for code, tag in NLLB_TAGS.items() if tag.endswith('_' + script))


def resolve_line(text, source, classify, supported_detector_codes):
    """Return a real source code or None when language evidence is insufficient."""
    text = unicodedata.normalize('NFKC', text.strip())
    if not text or source in ('en', 'unknown') or re.fullmatch(r'(?:https?://|www\.)\S+', text, re.I):
        return None
    kind = dominant_script(text[:1200])
    if not kind:
        return None
    expected = NLLB_TAGS.get(source, '').partition('_')[2]
    expected = {'Hans': 'Hani', 'Hant': 'Hani'}.get(expected, expected)
    if source != 'auto' and expected and expected != kind:
        return None
    if source == 'yue' and kind == 'Hani':
        return source
    if kind not in ('Latn', 'Hani', 'Jpan', 'Hang'):
        # Letters in the selected writing system cannot be purely English.
        # A selected source is authoritative where multiple languages share it.
        if expected == kind:
            return source
        unique = _script_candidates(kind)
        if source == 'auto' and len(unique) == 1:
            return unique[0]
    words = _words(text)
    if kind == 'Latn':
        if english_words(words):
            return None
        phrase = ' '.join(words)
        if source == 'auto' and phrase in _UNIQUE_SHORT:
            return _UNIQUE_SHORT[phrase]
        if source != 'auto' and phrase in _SHORT_FOREIGN.get(source, ()):
            return source
        if len(words) < 2 and (text.isascii() or len(phrase) < 5):
            return None
    detected, probability, runner_up, english_probability = classify(text[:2048])
    detected = canonical_code(detected)
    if detected in ('en', 'und'):
        return None
    if kind == 'Latn':
        # Related languages can split most of the probability mass (e.g.
        # Malay/Indonesian) even when the detector rules out English. An
        # explicit matching source resolves that ambiguity without forcing
        # English through the translator.
        if english_probability > .025 or probability < max(.20, english_probability * 25):
            return None
        if source == 'auto' and probability < .65 and probability < runner_up * 1.33:
            return None
    elif probability < .65:
        return None
    if source == 'auto':
        actual = NLLB_TAGS.get(detected, '').partition('_')[2]
        return detected if not actual or actual == kind or actual in ('Hans', 'Hant', 'Jpan') else None
    wanted = {'pb': 'pt', 'nn': 'no'}.get(source, source).split('-')[0]
    if detected == wanted:
        return source
    # For explicitly selected, low-resource Latin languages outside the ID
    # model, a substantial, confidently non-English sample can still translate.
    if (kind == 'Latn' and source in NLLB_TAGS and wanted not in supported_detector_codes()
            and len(words) >= 4 and sum(map(len, words)) >= 14 and english_probability < .005):
        return source
    return None

