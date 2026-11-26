"""Identify source speech before translating it. Audio and models stay local."""
from __future__ import annotations

from difflib import SequenceMatcher
import math
import re

from multilingual_speech import CJK_SPEECH, DIRECT_SPEECH, SPOKEN_LANGUAGES, translate_spans
from audio_chunks import SPEECH_PAUSE_MS

_HAN = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef"
_SCRIPTS = {
    "zh": re.compile("[" + _HAN + "]"),
    "ja": re.compile("[" + _HAN + r"\u3041-\u3096\u30a1-\u30fa\uff66-\uff9d]"),
    "ko": re.compile(r"[\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3]"),
}

# Common standalone conversational replies often have a different meaning
# from a menu label or a fragment of a written sentence. These are complete
# utterances; never replace a substring inside another sentence.
_SPOKEN_REPLIES = {
    "zh": {
        "你好": "Hello.", "您好": "Hello.", "大家好": "Hello, everyone.",
        "谢谢": "Thank you.", "謝謝": "Thank you.", "不客气": "You're welcome.",
        "不客氣": "You're welcome.", "对不起": "I'm sorry.", "對不起": "I'm sorry.",
        "没关系": "It's okay.", "沒關係": "It's okay.", "再见": "Goodbye.",
        "再見": "Goodbye.", "等一下": "Wait a moment.", "知道了": "Got it.",
    },
    "ja": {
        "はい": "Yes.", "いいえ": "No.", "こんにちは": "Hello.",
        "こんばんは": "Good evening.", "おはよう": "Good morning.",
        "おはようございます": "Good morning.", "ありがとう": "Thank you.",
        "ありがとうございます": "Thank you.", "どういたしまして": "You're welcome.",
        "ごめん": "Sorry.", "ごめんなさい": "I'm sorry.", "さようなら": "Goodbye.",
        "ちょっと待って": "Wait a moment.", "わかった": "Got it.", "分かった": "Got it.",
    },
    "ko": {
        "네": "Yes.", "예": "Yes.", "아니요": "No.", "아니에요": "No, it isn't.",
        "안녕하세요": "Hello.", "감사합니다": "Thank you.", "고맙습니다": "Thank you.",
        "고마워": "Thanks.", "죄송합니다": "I'm sorry.", "미안해": "I'm sorry.",
        "저기요": "Excuse me.", "아저기요": "Oh, excuse me.", "잠깐만요": "One moment.",
        "알겠어요": "Got it.", "알겠습니다": "Understood.", "안녕히가세요": "Goodbye.",
    },
}


def downmix(samples):
    """Preserve speech in multichannel and phase-inverted playback devices."""
    import numpy as np
    if samples.shape[1] == 1:
        return samples[:, 0]
    channels = samples.shape[1]
    if channels in (6, 8):
        # WASAPI 5.1/7.1 order starts with FL FR FC LFE. Dialogue is commonly
        # in FC. Downweight surrounds and exclude the subwoofer.
        audible = samples[:, [0, 1, 2, *range(4, channels)]]
        mono = samples[:, 2] * 0.50 + (samples[:, 0] + samples[:, 1]) * 0.22
        mono += samples[:, 4:].mean(axis=1) * 0.06
    else:
        audible = samples
        mono = samples.mean(axis=1)
    if len(samples) >= 128:
        energy = np.mean(audible * audible, axis=0, dtype=np.float64)
        strongest = int(np.argmax(energy))
        # If speech was carried in one quiet channel or FL/FR have opposite
        # polarity, averaging can annihilate it. Use the intact channel.
        if np.mean(mono * mono, dtype=np.float64) < energy[strongest] * 0.08:
            mono = audible[:, strongest]
    return mono


def mono_16k(samples, rate):
    import numpy as np
    if rate != 16000:
        from scipy.signal import resample_poly
        factor = math.gcd(rate, 16000)
        samples = resample_poly(samples, 16000 // factor, rate // factor)
    return np.ascontiguousarray(samples, dtype=np.float32)


def fixture_samples(path):
    """Use the same downmix and resampling as a live callback."""
    import numpy as np
    from scipy.io.wavfile import read
    rate, raw = read(path)
    samples = raw.astype(np.float32)
    if raw.dtype.kind == "u":
        samples = (samples - 128) / 128
    elif raw.dtype.kind == "i":
        samples /= 2 ** (8 * raw.dtype.itemsize - 1)
    if samples.ndim == 2:
        samples = downmix(samples)
    return mono_16k(samples, rate)


def _speech_spans(samples):
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    # Loopback can stop the moment a word ends. Give the recurrent detector a
    # little release time, then return offsets into the original recording.
    tail = 3200
    options = VadOptions(threshold=0.40, min_speech_duration_ms=48,
                         min_silence_duration_ms=SPEECH_PAUSE_MS, speech_pad_ms=150)
    lead = 0
    spans = get_speech_timestamps(np.pad(samples, (lead, tail)), options)
    if not spans and len(samples) <= 35200:
        # After WASAPI idles, the first callback can start right on the
        # consonant. Warm up the recurrent detector with the same silence
        # it would have seen on a continuously ticking device.
        lead = 3840
        spans = get_speech_timestamps(np.pad(samples, (lead, tail)), options)
    return [{"start": max(0, s["start"] - lead), "end": min(len(samples), s["end"] - lead)}
            for s in spans if lead < s["end"] and s["start"] < len(samples) + lead]


def _accepted_language(info, selection):
    language = info.language
    if language not in CJK_SPEECH or selection not in ("auto", language):
        return False
    prob = float(info.language_probability)
    alternatives = dict(info.all_language_probs or [])
    return prob >= (0.48 if selection == "auto" else 0.40) and prob - alternatives.get("en", 0.0) >= 0.12


def _short_candidates(info, selection):
    """Only reconsider a plausible target with positive evidence against English."""
    probs = dict(info.all_language_probs or [])
    if info.language == "en" or (info.language not in CJK_SPEECH and info.language_probability >= .45):
        return set()
    english = probs.get("en", 0.0)
    allowed = CJK_SPEECH if selection == "auto" else (selection,)
    return {lang for lang in allowed if lang in CJK_SPEECH and
            probs.get(lang, 0) >= max(.20, english + .14, info.language_probability * .65)}


def _confirmed_short(first, second, selection):
    lang = second.language
    if _accepted_language(second, selection):
        return True
    if lang != first.language or second.language_probability < .26:
        return False
    for info in (first, second):
        probs = dict(info.all_language_probs or [])
        rival = max((p for code, p in probs.items() if code != lang), default=0)
        if probs.get("en", 0.0) > .09 or info.language_probability - rival < .07:
            return False
    return (first.language_probability + second.language_probability) / 2 >= (.36 if selection == "auto" else .30)


def _looks_like_title(text):
    # A spoken sentence rendered as two or more title-case words may be a
    # web or menu heading from the text model's training material.
    return bool(re.fullmatch(r"[A-Z][a-z]+(?:['’][a-z]+)?(?: [A-Z][a-z]+(?:['’][a-z]+)?){1,4}", text))


def _same_short_word(left, right):
    if not left or not right:
        return False
    shorter, longer = sorted((left, right), key=len)
    return left == right or (len(shorter) >= 2 and len(shorter) >= .65 * len(longer) and shorter in longer)


def _repeated_phrase(text):
    """Recover one utterance from a decoder pass over three copies of the same audio."""
    indices = [i for i, ch in enumerate(text) if ch.isalnum()]
    letters = "".join(text[i] for i in indices)
    for copies in (3, 2):
        width, remainder = divmod(len(letters), copies)
        if width and not remainder and letters[:width] * copies == letters:
            return text[indices[0]:indices[width-1]+1].strip()
    return ""


def _recheck_short(model, recorded, first, selection, cancelled):
    """Corroborate weak native speech by repeating the acoustic evidence with pauses."""
    import numpy as np
    from dataclasses import replace
    probs = dict(first.all_language_probs or [])
    lang = first.language if selection == "auto" else selection
    if lang not in CJK_SPEECH or len(recorded) > 32000:
        return None
    english = probs.get("en", 0.0)
    prob = probs.get(lang, 0.0)
    if english > .16 or prob < (.14 if selection == "auto" else .055) or prob < english + .045:
        return None
    if first.language != lang and first.language_probability >= .46:
        return None
    if cancelled():
        return None
    audio = np.tile(np.concatenate((recorded, np.zeros(6000, np.float32))), 3)
    # With a fixed profile, require independent detection on the repeated audio
    # unless the original read already named the selected language.
    hints = {"ja": "聞こえた単語：", "ko": "단어나 문장:", "zh": "说出的词："}
    choose = None if first.language != lang else lang
    segments, second = model.transcribe(audio, language=choose, task="transcribe", initial_prompt=hints[lang],
                                        temperature=0.0, beam_size=5, vad_filter=False, max_new_tokens=96,
                                        condition_on_previous_text=False, without_timestamps=True)
    if choose is None and (second.language != lang or not _accepted_language(second, selection)):
        return None
    segments = list(segments)
    if cancelled() or len(segments) != 1:
        return None
    segment = segments[0]
    phrase = _repeated_phrase(segment.text)
    if not phrase or not _SCRIPTS[lang].search(phrase) or segment.avg_logprob < -.80 or segment.no_speech_prob > .42:
        return None
    # Translation fallback refers to the original single utterance.
    return lang, replace(segment, text=phrase, start=0.0, end=len(recorded) / 16000.0)


def _confident_segment(segment):
    return (bool(segment.text.strip()) and segment.compression_ratio <= 2.6
            and segment.avg_logprob >= -1.1 and
            not (segment.no_speech_prob > 0.65 and segment.avg_logprob < -0.55))


def _largely_untranslated(text, language):
    # A proper name in an otherwise English sentence is valid. Reconsider
    # only a result still dominated by its source script.
    letters = sum(c.isalpha() for c in text)
    native = len(_SCRIPTS[language].findall(text))
    return native > 0 and (native == letters or (native >= 3 and native * 2 > letters))


def _independent_transcript(model, audio, first, selection):
    recognizer = getattr(model, "sensevoice", None)
    if recognizer is None or first.language == "en":
        return None
    result = recognizer.transcribe(audio)
    candidate = _native_candidate(result, first, selection)
    if candidate or not isinstance(result, dict):
        return candidate
    # Leading loopback silence can change the independent language estimate
    # on a single syllable. Only accept stronger evidence on this extra pass.
    second = recognizer.transcribe_trimmed(audio)
    candidate = _native_candidate(second, first, selection, trimmed=True)
    if candidate or not isinstance(second, dict):
        return candidate
    lang = second.get("language")
    if first.language in CJK_SPEECH and first.language != lang:
        agreed = _cross_language_consensus(result, second, selection)
        if agreed:
            repeated = recognizer.transcribe_repeated(audio)
            if isinstance(repeated, dict) and repeated.get("language") == lang and repeated.get("probs", {}).get(lang, 0) >= .99:
                phrase = _repeated_phrase(repeated.get("text", ""))
                if phrase and _source_key(phrase) == _source_key(agreed):
                    return lang, agreed
            return None
    if (first.language_probability >= .70 or lang not in CJK_SPEECH or
            selection not in ("auto",lang) or second["probs"].get(lang,0) < .60 or
            "<|Speech|>" not in second.get("tags", ())):
        return None
    repeated = recognizer.transcribe_repeated(audio)
    repeated_candidate = _native_candidate(repeated, first, selection, trimmed=True)
    if repeated_candidate and repeated_candidate[0] == lang:
        phrase = _repeated_phrase(repeated_candidate[1])
        if phrase and _source_key(phrase) == _source_key(second["text"]):
            return lang, phrase
    return None


def _source_key(text):
    return "".join(ch for ch in text if ch.isalnum())


def _cross_language_consensus(original, trimmed, selection):
    """Resolve conflicting target-language IDs only if both views agree on every source word."""
    lang = original.get("language")
    if lang not in CJK_SPEECH or lang != trimmed.get("language") or selection not in ("auto", lang):
        return None
    for view in (original, trimmed):
        if view.get("probs", {}).get(lang, 0) < .985 or "<|Speech|>" not in view.get("tags", ()):
            return None
    source = original.get("text", "").strip()
    key = _source_key(source)
    if not key or any(not _SCRIPTS[lang].fullmatch(ch) for ch in key):
        return None
    return source if _source_key(trimmed.get("text", "")) == key else None


def _corroborated_reply(original, language, source):
    """Repair one duplicated Hangul syllable only when the second recognizer independently agrees."""
    parts = original.split()
    if parts and parts[0] in _SPOKEN_REPLIES[language] and len(parts) > 1:
        # Retain a separate spoken acknowledgment if both engines agree on
        # the remaining phrase. Negative and other qualifiers stay verbatim.
        prefix = parts[0] if _SPOKEN_REPLIES[language][parts[0]] == "Yes." else ""
    else:
        prefix = ""
    word = _source_key(" ".join(parts[1:]) if prefix else original)
    variants = {word[:i]+word[i+1:] for i in range(1,len(word)) if word[i] == word[i-1]}
    if not variants.intersection(_SPOKEN_REPLIES[language]):
        return original
    segments = list(source)
    if len(segments) == 1 and _confident_segment(segments[0]):
        alternate = _source_key(segments[0].text)
        for value in variants:
            if value in _SPOKEN_REPLIES[language] and alternate in (value,prefix+value):
                return (prefix+", " if prefix else "") + value
    return original


def _question_ending(original, reference):
    """Reuse a heard question contour when both reads agree on the phrase ending."""
    if original.endswith(("?", "？")) or not reference.rstrip().endswith(("?", "？")):
        return original
    first, second = _source_key(original), _source_key(reference)
    if len(first) >= 5 and first[-2:] == second[-2:] and SequenceMatcher(None,first,second).ratio() >= .68:
        return original.rstrip("。.!！、, ") + "?"
    return original


def _alternative_words(recognizer, audio, lang, original, single, cancelled, trim=None):
    """Correct a heard word only when independent acoustic readings support the change."""
    if cancelled():
        return original
    raw_key = _source_key(original)
    heard = _source_key(single)
    # Both models heard exactly this short word. In particular, keep a
    # correct native noun when a forced formatted pass could invent one.
    if len(raw_key) <= 4 and raw_key == heard:
        return original
    formatted = recognizer.transcribe_formatted(audio, lang)
    if not isinstance(formatted, dict) or "<|Speech|>" not in formatted.get("tags", ()):
        return original
    value = formatted.get("text", "").strip()
    key = _source_key(value)
    if not key or any(not (_SCRIPTS[lang].fullmatch(ch) or ch.isdecimal()) for ch in key):
        return original
    if key == raw_key:
        return _question_ending(original, value)
    if cancelled():
        return original
    if trim is None:
        trim = recognizer.transcribe_trimmed(audio)
    trimmed = ""
    if (isinstance(trim, dict) and trim.get("language") == lang and "<|Speech|>" in trim.get("tags", ())
            and trim.get("probs", {}).get(lang, 0) >= .75):
        trimmed = _source_key(trim.get("text", ""))
    if key == heard and key == trimmed:
        return value
    if len(key) < 2 or cancelled():
        return original
    repeated = recognizer.transcribe_repeated(audio)
    if (not isinstance(repeated, dict) or repeated.get("language") != lang
            or "<|Speech|>" not in repeated.get("tags", ()) or repeated.get("probs", {}).get(lang, 0) < .85):
        return original
    repeat_key = _source_key(repeated.get("text", ""))
    if key in (heard, trimmed) and key in repeat_key:
        return value
    # When the raw pass dropped native syllables, require the inserted
    # syllables with a neighbouring word or character in another acoustic read.
    diff = SequenceMatcher(None, raw_key, key, autojunk=False)
    if diff.ratio() < .65:
        return original
    changes = [op for op in diff.get_opcodes() if op[0] != "equal"]
    if not changes or any(op[0] != "insert" for op in changes):
        return original
    for _, _, _, begin, end in changes:
        witnesses = []
        if begin:
            witnesses.append(key[begin-1:end])
        if end < len(key):
            witnesses.append(key[begin:end+1])
        if not any(w in evidence for w in witnesses for evidence in (heard, trimmed, repeat_key)):
            return original
    return value


def _native_candidate(result, first, selection, trimmed=False):
    if not isinstance(result, dict):
        return None
    lang = result.get("language")
    if lang not in CJK_SPEECH or selection not in ("auto",lang):
        return None
    if "<|Speech|>" not in result.get("tags", ()):
        return None
    source = result.get("text","").strip()
    if not _SCRIPTS[lang].search(source):
        return None
    # English embedded in an otherwise foreign utterance still goes through
    # the segmented Whisper path, where each eligible span has its own times.
    if re.search(r"[A-Za-z]{2,}", source):
        return None
    score = result.get("probs",{}).get(lang,0)
    if first.language != lang:
        if first.language_probability >= .70 or score < (.94 if trimmed else .88):
            return None
    elif score < (.76 if trimmed else .60):
        return None
    return lang, source


def _caption_for_source(model, original, language, audio, short, translate_source, options, cancelled,
                        acoustic_translation=False):
    from spoken_lexicon import lexical_reply
    from speech_memory import SpeechCaptionMemory
    if cancelled():
        return None
    # The caller has already checked source language and script. A repeated
    # source needs neither another text-model call nor another direct translation.
    if isinstance(translate_source, SpeechCaptionMemory):
        first = translate_source.lookup(original, language)
        if first is not None:
            return {"text": first, "original": original, "language": language}
    reply = None
    if short:
        key = re.sub(r"[\s\W]+", "", original)
        reply = _SPOKEN_REPLIES[language].get(key)
        if reply is None:
            reply = lexical_reply(original, language, _SPOKEN_REPLIES[language])
    if reply is None:
        result = translate_source(original, language) if translate_source is not None else None
        if cancelled() or (result is not None and result.get("ignored")):
            return None
        reply = str(result.get("text", "")).strip() if result is not None else ""
        title = short and _looks_like_title(reply)
        assess_direct = (acoustic_translation and result is not None and result.get("engine") == "nllb"
                         and len(_SCRIPTS[language].findall(original)) >= 4)
        if len(audio) and (assess_direct or result is None or _largely_untranslated(reply, language) or title):
            translated, _ = model.transcribe(audio, task="translate", language=language,
                                             without_timestamps=short, **options)
            direct = list(translated)
            candidate = " ".join(s.text.strip() for s in direct if _confident_segment(s)
                                 and (not title or (s.avg_logprob >= -.85 and s.no_speech_prob <= .30)))
            if assess_direct and (len(direct) != 1 or direct[0].avg_logprob < -.60 or direct[0].no_speech_prob > .35):
                candidate = ""
            if re.search(r"[A-Za-z]{2}|\b[IA]\b", candidate) and not _largely_untranslated(candidate, language):
                reply = candidate
    source_only = bool(_SCRIPTS[language].search(reply)) and not re.search(r"[A-Za-z]", reply)
    if not source_only and any(c.isalnum() for c in reply) and not cancelled():
        from speech_fidelity import preserve_clock_precision
        reply = preserve_clock_precision(original, reply, language)
        return {"text": reply, "original": original, "language": language}
    return None


def speech_captions(model, samples, selection="auto", translate_source=None, cancelled=lambda: False,
                    observe_language=None):
    """Yield English for identified foreign speech that matches the selected profile."""
    import numpy as np
    if cancelled() or len(samples) < 960:
        return
    raw_samples = samples
    power = float(np.sqrt(np.mean(samples * samples, dtype=np.float64)))
    if not math.isfinite(power) or power == 0:
        return
    # A brief reply surrounded by silence has a much lower overall RMS than
    # the voiced frames. Keep quiet channels audible to the neural speech gate.
    if power < 0.032:
        peak = float(np.max(np.abs(samples)))
        if peak < 0.00018:
            return
        samples = samples * max(1.0, min(160.0, 0.032 / power, 0.95 / peak))
    options = dict(beam_size=5, best_of=1, temperature=0.0, vad_filter=False,
                   condition_on_previous_text=False)
    from mixed_spans import partition
    if selection == "auto" or selection in CJK_SPEECH:
        spans = partition(model, samples, _speech_spans, cancelled, _SCRIPTS)
    else:
        spans = _speech_spans(samples)
    for span in spans:
        if cancelled():
            return
        recorded = samples[span["start"]:span["end"]]
        # Keep the first consonant away from the boundary of Whisper's first
        # analysis window. Isolated words do not need sub-segment timestamps.
        short = len(recorded) <= 35200
        clip = np.pad(recorded, (2560, 3200)) if short else recorded
        source, info = model.transcribe(clip, task="transcribe", language=None,
                                        without_timestamps=short, **options)
        if observe_language is not None:
            observe_language(info.language, float(info.language_probability))
        if info.language in DIRECT_SPEECH:
            if selection == "auto" or selection not in CJK_SPEECH:
                yield from translate_spans(model, clip, source, info, selection, short, translate_source,
                                           options, cancelled, _confident_segment)
                continue
        elif selection != "auto" and selection not in CJK_SPEECH:
            continue
        if getattr(model,"dialogue_model",None) is not None and not cancelled():
            from korean_dialogue import accurate_turn
            from dialogue_acceleration import DialogueUnavailable
            isolated = len(spans) == 1 and not span.get("partitioned") and len(raw_samples) <= 112000
            audio = raw_samples if isolated else raw_samples[span["start"]:span["end"]]
            try:
                upgraded = accurate_turn(model,audio,recorded,selection,info,cancelled,translate_source)
            except DialogueUnavailable:
                upgraded = None
            if cancelled():
                return
            if upgraded is not None:
                yield upgraded
                continue
        if short and not cancelled():
            standalone = len(spans) == 1 and not span.get("partitioned") and len(raw_samples) <= 48000
            acoustic_span = raw_samples if standalone else raw_samples[span["start"]:span["end"]]
            independent = _independent_transcript(model, acoustic_span, info, selection)
            if independent:
                if cancelled():
                    return
                language, original = independent
                corroborated = False
                review = info.language == language and info.language_probability >= .48
                trim = None
                if review and len(_source_key(original)) < 4:
                    # Two agreeing reads of a short word need no Whisper beam
                    # search. A changing word still gets independent review.
                    trim = model.sensevoice.transcribe_trimmed(acoustic_span)
                    if (isinstance(trim, dict) and trim.get("language") == language
                            and "<|Speech|>" in trim.get("tags", ())
                            and trim.get("probs", {}).get(language, 0) >= .85
                            and _source_key(trim.get("text", "")) == _source_key(original)):
                        review = False
                if review and not cancelled():
                    source = list(source)
                    if language == "ko":
                        original = _corroborated_reply(original, language, source)
                    if len(source) == 1 and _confident_segment(source[0]):
                        heard = source[0].text
                        revised = _alternative_words(model.sensevoice, acoustic_span, language, original, heard, cancelled, trim)
                        changed = _source_key(revised) != _source_key(original)
                        original = _question_ending(revised, heard)
                        agrees = SequenceMatcher(None, _source_key(original), _source_key(heard)).ratio()
                        corroborated = agrees >= (.99 if changed else .82)
                caption = _caption_for_source(model, original, language, clip, True,
                                              translate_source, options, cancelled, corroborated)
                if caption is not None:
                    yield caption
                    continue
        reviewed = False
        accepted = _accepted_language(info, selection)
        first = info
        conflicting_words = False
        if not accepted:
            candidates = _short_candidates(info, selection) if short else set()
            # A consonant in a different analysis window can settle an otherwise
            # ambiguous short word. Keep the second detection unconstrained too.
            if candidates and not cancelled():
                clip = np.pad(recorded, (0, 3200))
                second, check = model.transcribe(clip, task="transcribe", language=None,
                                                 without_timestamps=True, **options)
                if observe_language is not None:
                    observe_language(check.language, float(check.language_probability))
                if check.language in candidates and _confirmed_short(info, check, selection):
                    source, info = second, check
                    reviewed = accepted = True
        language = info.language
        if short and accepted and not reviewed:
            source = list(source)
            # The timestamp/no-timestamp decoder can score the same single
            # word differently. Salvage a marginal word only when both
            # readings agree and the timed reading passes the usual filters.
            if (len(source) == 1 and not _confident_segment(source[0])
                    and source[0].avg_logprob >= -1.4 and source[0].no_speech_prob <= .60
                    and _SCRIPTS[language].search(source[0].text) and not cancelled()):
                first_word = "".join(_SCRIPTS[language].findall(source[0].text))
                timed, _ = model.transcribe(clip, task="transcribe", language=language,
                                            without_timestamps=False, **options)
                alternatives = list(timed)
                if len(alternatives) == 1 and _confident_segment(alternatives[0]):
                    second_word = "".join(_SCRIPTS[language].findall(alternatives[0].text))
                    if _same_short_word(first_word, second_word):
                        source = alternatives
                    else:
                        conflicting_words = True
        # A full English segment inside a mostly foreign utterance still has
        # no qualifying source script. Keep its time out of the fallback too.
        groups = []
        current = []
        native_evidence = not accepted
        for seg in source if accepted else ():
            if cancelled():
                return
            native_evidence |= bool(_SCRIPTS[language].search(seg.text))
            sure = not reviewed or (seg.avg_logprob >= -.72 and seg.no_speech_prob <= .40)
            if sure and _confident_segment(seg) and _SCRIPTS[language].search(seg.text):
                current.append(seg)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        if short and not groups and native_evidence and not conflicting_words:
            recovered = _recheck_short(model, recorded, first, selection, cancelled)
            if recovered is not None:
                language, segment = recovered
                groups.append([segment])
                clip = recorded
        for group in groups:
            if cancelled():
                return
            original = " ".join(seg.text.strip() for seg in group)
            start = max(0, round(group[0].start * 16000))
            end = min(len(clip), round(group[-1].end * 16000))
            caption = _caption_for_source(model, original, language, clip[start:end], short and len(group) == 1,
                                          translate_source, options, cancelled,
                                          acoustic_translation=short and _accepted_language(info, selection))
            if caption is not None:
                yield caption
