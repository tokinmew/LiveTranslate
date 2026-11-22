"""Optional higher-accuracy acoustic pass for uninterrupted Korean conversation."""
from difflib import SequenceMatcher
import re
import numpy as np


def _key(text):
    return "".join(c for c in text if c.isalnum())


def _break(audio):
    frames = np.pad(audio, (0, -len(audio) % 160)).reshape(-1, 160)
    energy = np.sqrt(np.mean(frames ** 2, axis=1))
    threshold = max(.0018, float(energy.max()) * .035)
    quiet = np.flatnonzero(energy < threshold)
    runs = np.split(quiet, np.flatnonzero(np.diff(quiet) > 1) + 1)
    cuts = [(len(run), int((run[0] + run[-1] + 1) * 80)) for run in runs if len(run) >= 14
            and np.count_nonzero(energy[:run[0]] > threshold*2) >= 14
            and np.count_nonzero(energy[run[-1]+1:] > threshold*2) >= 14]
    return max(cuts)[1] if cuts else 0


def _options(audio):
    return dict(beam_size=5, temperature=0., condition_on_previous_text=False, vad_filter=False,
                max_new_tokens=max(32, min(128, round(len(audio)/16000*22))))


def _native(model, audio, cancelled):
    from speech_decode import _accepted_language, _confident_segment, _SCRIPTS
    if cancelled():
        return ""
    segments, info = model.transcribe(audio, language=None, task="transcribe", without_timestamps=True, **_options(audio))
    if not _accepted_language(info, "ko"):
        return ""
    parts = list(segments)
    if not parts or any(not _confident_segment(s) or re.search(r"[A-Za-z]{2,}",s.text)
                        or not _SCRIPTS["ko"].search(s.text) for s in parts):
        return ""
    return " ".join(s.text.strip() for s in parts)


def _english(model, audio, cancelled):
    from speech_decode import _confident_segment
    if cancelled():
        return ""
    segments,_ = model.transcribe(audio, language="ko", task="translate", without_timestamps=True, **_options(audio))
    expression = " ".join(s.text.strip() for s in segments if _confident_segment(s))
    return expression if re.search(r"[A-Za-z]",expression) and not re.search(r"[가-힣]",expression) else ""


def _known_clause(text, replies):
    words = _key(text)
    if words in replies:
        return replies[words]
    parts = text.strip(" .?!").split(maxsplit=1)
    if len(parts)==2 and parts[0] in replies and _key(parts[1]) in replies:
        return replies[parts[0]]+" "+replies[_key(parts[1])]
    return ""


def _clauses(model, audio, source, whole, cancelled, replies):
    """Restore independently timestamped clauses if the complete translation collapsed them."""
    if not re.search(r"[.?!]\s+\S", source) or re.search(r"[.?!]\s+\S", whole):
        return whole
    segments,_ = model.transcribe(audio, language="ko",task="transcribe",word_timestamps=True,**_options(audio))
    words = [w for segment in segments for w in segment.words or []]
    cuts=[0]
    for left,right in zip(words,words[1:]):
        if re.search(r"[.?!]$",left.word.strip()):
            boundary = round((left.end+right.start)*8000)
            if boundary-cuts[-1] >= 3200 and len(audio)-boundary >= 3200:
                cuts.append(boundary)
    if len(cuts)==1:
        return whole
    cuts.append(len(audio))
    phrases=[]
    for start,end in zip(cuts,cuts[1:]):
        group=" ".join(w.word.strip() for w in words if start <= (w.start+w.end)*8000 < end)
        part = _known_clause(group,replies) or _english(model, np.pad(audio[start:end],(1280,1280)), cancelled)
        if not part:
            return whole
        phrases.append(part)
    return " ".join(phrases)


def _counter_read(model, audio, english, expected, cancelled):
    from korean_counters import preserve_counted_unit
    from speech_decode import _confident_segment
    if cancelled():
        return False
    segments,_ = model.transcribe(audio,language="ko",task="transcribe",without_timestamps=True,beam_size=5,
                                  best_of=1,temperature=0.,condition_on_previous_text=False,vad_filter=False)
    phrase = " ".join(s.text for s in segments if _confident_segment(s) and s.avg_logprob >= -.65 and s.no_speech_prob <= .45)
    return preserve_counted_unit(phrase,english,"ko") == expected


def _confirm_quantity_question(model, recognizer, acoustic, reference, english, expected, cancelled):
    trim = np.pad(recognizer._trim(reference),(2560,3200))
    if _counter_read(model,trim,english,expected,cancelled):
        return True
    if cancelled():
        return False
    # A preceding clause can change a short classifier's decode. Anchor
    # the second reading to the quantifier and retain the complete question.
    clip = np.pad(acoustic,(2560,3200))
    segments,_=model.transcribe(clip,language="ko",task="transcribe",word_timestamps=True,beam_size=5,
                                temperature=0.,condition_on_previous_text=False,vad_filter=False)
    words = [w for s in segments for w in s.words or []]
    candidates = [i for i,w in enumerate(words) if "몇" in w.word]
    if len(candidates)!=1 or cancelled():
        return False
    first = candidates[0]
    if first >= len(words)-1:
        return False
    start = max(0,round(words[first].start*16000)-800)
    end = min(len(clip),round(words[-1].end*16000)+800)
    return _counter_read(model,np.pad(clip[start:end],(2560,3200)),english,expected,cancelled)


def accurate_turn(small, acoustic, reference_audio, selection, first, cancelled, translate_source):
    from korean_counters import counted_unit, preserve_counted_unit
    from speech_decode import _SPOKEN_REPLIES
    from speech_fidelity import preserve_clock_precision
    large = getattr(small,"dialogue_model",None)
    recognizer = getattr(small,"sensevoice",None)
    if (large is None or recognizer is None or selection not in ("auto","ko") or first.language != "ko"
            or first.language_probability < .76 or not 32000 <= len(acoustic) <= 112000 or cancelled()):
        return None
    raw = recognizer.transcribe_trimmed(acoustic)
    if (not isinstance(raw,dict) or raw.get("language") != "ko" or raw.get("probs",{}).get("ko",0) < .80
            or "<|Speech|>" not in raw.get("tags",()) or len(_key(raw.get("text",""))) < 8
            or re.search(r"[A-Za-z]{2,}",raw["text"])):
        return None
    normalized = acoustic
    rms = float(np.sqrt(np.mean(acoustic**2)))
    if 0 < rms < .032:
        normalized = acoustic * max(1., min(160., .032/rms, .95/max(float(np.max(np.abs(acoustic))),1e-5)))
    clip=np.pad(normalized, (2560,3200))
    source = _native(large,clip,cancelled)
    if not source or SequenceMatcher(None,_key(source),_key(raw["text"])).ratio() < .52:
        return None
    cut = _break(clip)
    captions = []
    sources = []
    if cut:
        for piece in (clip[:cut],clip[cut:]):
            piece = np.pad(piece,(1280,1280))
            native = _native(large,piece,cancelled)
            english = _english(large,piece,cancelled) if native else ""
            if not english:
                break
            sources.append(native)
            captions.append(english)
    split_ok = len(captions)==2 and SequenceMatcher(None,_key(source),_key("".join(sources))).ratio() >= .68
    if split_ok:
        joined = " ".join(sources)
        if _key(source) == _key(joined):
            # Keep the continuous voice and participant context when the
            # whole translation already contains both complete clauses.
            whole = _english(large,clip,cancelled)
            complete = len(re.findall(r"[.!?](?:\s|$)",whole)) >= len(captions)
            if any("?" in clause for clause in captions):
                complete = complete and "?" in whole
        else:
            whole, complete = "", False
        source, english = joined, whole if complete else " ".join(captions)
    else:
        english = _english(large,clip,cancelled)
        if english:
            english = _clauses(large,clip,source,english,cancelled,_SPOKEN_REPLIES["ko"])
    if not english or cancelled():
        return None
    if not split_ok and translate_source is not None:
        # A recovering native word should reach the text translator when
        # two independent recognizers support it over the initial read.
        formatted = recognizer.transcribe_formatted(acoustic,"ko")
        prior, candidate = _key(raw["text"]), _key(formatted.get("text",""))
        independent = _key(source)
        difference = SequenceMatcher(None,prior,candidate,autojunk=False)
        additions = [(j,k) for tag,i,h,j,k in difference.get_opcodes() if tag=="insert"]
        if additions and difference.ratio() >= .75 and all(candidate[max(0,j-1):k] in independent for j,k in additions):
            corrected = translate_source(source, "ko")
            if corrected and corrected.get("text") and not corrected.get("ignored"):
                english = corrected["text"]
    # Some Korean numerical classifiers carry the counted noun implicitly.
    # Require two unrelated acoustic recognizers to recover the same unit.
    counted = preserve_counted_unit(raw["text"],english,"ko")
    if counted != english:
        native = recognizer.transcribe(acoustic)
        if (native.get("language") != "ko" or native.get("probs",{}).get("ko",0) < .90
                or "<|Speech|>" not in native.get("tags",())
                or preserve_counted_unit(native.get("text",""),english,"ko") != counted):
            return {"text":preserve_clock_precision(source,english,"ko"),"original":source,"language":"ko"}
        if _confirm_quantity_question(small,recognizer,acoustic,reference_audio,english,counted,cancelled):
            english = counted
            if SequenceMatcher(None,_key(source),_key(raw["text"])).ratio() >= .82:
                source = raw["text"]
                if translate_source is not None:
                    # The direct pass omitted an explicit part of the question.
                    # Translate the confirmed whole question with its context.
                    result = translate_source(source.rstrip(" .?!")+"?", "ko")
                    if result and not result.get("ignored"):
                        alternative = result.get("text","")
                        grounded = preserve_counted_unit(source,alternative,"ko")
                        unit = counted_unit(source)
                        names = {"volumes","books"} if unit == "volumes" else ({unit} if unit else set())
                        expresses_unit = any(re.search(r"\b"+re.escape(word)+r"\b",grounded,re.I) for word in names)
                        if grounded != alternative or expresses_unit:
                            english = grounded
    return {"text":preserve_clock_precision(source,english,"ko"),"original":source,"language":"ko"}
