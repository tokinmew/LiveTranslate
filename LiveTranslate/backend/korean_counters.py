"""Restore a Korean unit only when a single English question and its referent line up."""
import re


_COUNTER = re.compile(
    r"몇\s*(권|명|마리|병|켤레)(?=(?:까지|이나|씩|쯤|인지|입니까|이에요)?"
    r"(?:으로|부터|를|을|이|가|은|는|도|의)?(?:\s|[.,?!]|$))"
)
_BARE_COUNT = re.compile(
    r"\b(how many(?: more)?)(?=\s+(?:(?:can|could|do|did|will|would|should|may|must|have|has|are|were)"
    r"\s+(?:I|we|you|he|she|they|there|the|a|an|left|available)\b|at a time\b)|\s*[?!.,]?$)",
    re.I,
)
_HOW_MANY = re.compile(r"\bhow many\b", re.I)
_PERSON_COPULA = re.compile(r"^\s+(?:are|were)\s+(?:you|we|they)(?:\s+(?:in|at|here|there|today|altogether)\b|\s*[?!.]*$)", re.I)
_CLAUSE_END = re.compile(r"[.,!?;:，。！？；…\n]+")
_UNITS = {"명": "people", "마리": "animals", "병": "bottles", "켤레": "pairs"}
_NEUTRAL = frozenset("한 두 세 네 보통 최대 최소 총 대략 약 대충 모두 지금 현재 그러면 그럼 혹시 대체 도대체 한꺼번에 한꺼번에는 함께 동시에".split())
_OPENERS = frozenset("근데 그런데 하지만 그러나 그리고 그러면 그럼 그러니까".split())
_REPLIES = frozenset("네 예 응 아니요 아뇨".split())
_CIRCUMSTANCE = re.compile(r"(?:[가-힣]+(?:에서|마다|당)(?:는|도)?|(?:여기|거기|저기)서(?:는|도)?|(?:[가-힣]*(?:번|달|날|년|주|시|분)|하루|여기|거기|저기)에(?:는|도)?)")
_GENERIC_NOUN = {"권": re.compile(r"(?:책|도서)(?:들)?(?:을|를|은|는|이|가|도|만)?"),
                 "명": re.compile(r"사람(?:들)?(?:을|를|은|는|이|가|도|만)?"),
                 "마리": re.compile(r"동물(?:들)?(?:을|를|은|는|이|가|도|만)?")}
_BORROW_KO = re.compile(r"빌(?:리|릴|린|려|렸|립)|대출")
_BORROW_EN = re.compile(r"\b(?:borrow(?:s|ed|ing)?|check(?:s|ed|ing)?\s+(?:[a-z]+\s+)?out)\b", re.I)
_POSTPOSITIONS = re.compile(r"^(?:까지|이나|씩|쯤|인지|입니까|이에요)?(?:으로|부터|를|을|이|가|은|는|도|의)?(?=\s|$)")
_ADVERBS = frozenset("더 덜 남짓 가량 정도 또 아직 이미 정말 보통 지금 함께 모두 총 미리 최대 각각 따로 직접 한번 한꺼번에".split())
_ENDING = re.compile(r"(?:요|죠|니|나|까|지|냐|어|아|야|네|오|다)$")


def simple_predicate(after):
    # A bare head can follow the counter with or without a case particle,
    # e.g. 몇 병 우유 샀어요. Limit unit insertion to uncomplicated predicates.
    tail = _POSTPOSITIONS.sub("", after).strip()
    words = [w for w in tail.split() if w not in _ADVERBS]
    if not words:
        return True
    if len(words) == 1:
        return bool(_ENDING.search(words[0]))
    if not _ENDING.search(words[-1]):
        return False
    if len(words) == 3 and words[1] == "수" and re.match(r"있|없", words[2]):
        return True
    if len(words) == 2 and re.match(r"있|없|주|드|싶", words[1]):
        return bool(re.search(r"(?:아|어|여|려|해|고)$", words[0]))
    return False


def final_clause(text):
    clauses = [part.strip() for part in _CLAUSE_END.split(text) if part.strip()]
    return clauses[-1] if clauses else ""


def counted_unit(source):
    if source.count("몇") != 1:
        return None
    clause = final_clause(source)
    match = _COUNTER.search(clause)
    if not match:
        return None
    before, after = clause[:match.start()], clause[match.end():]
    # A counted genitive introduces an explicit head (몇 권의 잡지). A second
    # quantity or a conjoined/embedded clause can concern another referent.
    if (re.match(r"\s*의(?:\s|[가-힣])", after)
            or re.search(r"얼마|어느|무엇|누구|누가|어디|어떻|언제", clause)
            or re.search(r"[가-힣](?:는데|지만|다가|더니|으며|면서|고서|고|는지|었는지|았는지)(?=\s|$)", after)
            or re.search(r"(?:^|\s)[가-힣]+(?:을|를)(?=\s|$)", after)):
        return None
    if not simple_predicate(after):
        return None
    counter = match[1]
    named = False
    prefix = before.split()
    if len(prefix) >= 2 and prefix[0] in _REPLIES and prefix[1] in _OPENERS:
        prefix = prefix[1:]
    if prefix and prefix[0] in _OPENERS:
        prefix = prefix[1:]
    for token in prefix:
        if token in _NEUTRAL or _CIRCUMSTANCE.fullmatch(token):
            continue
        noun = _GENERIC_NOUN.get(counter)
        if noun is None or not noun.fullmatch(token) or named:
            return None
        named = True
    if counter == "권":
        return "books" if named else ("volumes" if _BORROW_KO.search(after) else None)
    return _UNITS[counter]


def preserve_counted_unit(source, english, language):
    if language != "ko" or len(_HOW_MANY.findall(english)) != 1:
        return english
    clause = final_clause(english)
    match = _BARE_COUNT.search(clause)
    unit = counted_unit(source)
    if not match or not unit or _PERSON_COPULA.search(clause[match.end():]):
        return english
    if unit == "volumes" and not _BORROW_EN.search(clause):
        return english
    end = english.rindex(clause) + match.end()
    return english[:end] + " " + unit + english[end:]
