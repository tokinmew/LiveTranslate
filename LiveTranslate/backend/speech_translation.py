"""Local multilingual translation using verified optional model files."""
from pathlib import Path
import hashlib
from collections import OrderedDict
from functools import lru_cache
from language_catalog import NLLB_TAGS
from multilingual_text import standalone_translation

_PINS = {
    "model.bin": (622595991, "ed1beaf75134de7505315a5223162f56acff397eff6b50638a500d3936fe707b"),
    "config.json": (159, "0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c"),
    "shared_vocabulary.txt": (2568098, "a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5"),
    "sentencepiece.bpe.model": (4852054, "14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a"),
}


@lru_cache(maxsize=16)
def _verified_digest(path, size, modified, changed, inode):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_folder(directory):
    folder = Path(directory) / "nllb-600m-int8"
    if not folder.is_dir():
        return None
    for name, (length, pin) in _PINS.items():
        path = folder / name
        if not path.is_file():
            raise ValueError(f"Repair the offline speech translation files. Missing or incomplete {name}.")
        info = path.stat()
        if info.st_size != length:
            raise ValueError(f"Repair the offline speech translation files. Missing or incomplete {name}.")
        if _verified_digest(path.resolve(), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino) != pin:
            raise ValueError(f"Repair the offline speech translation files. {name} failed verification.")
    return folder


def load_local_model(directory):
    folder = verified_folder(directory)
    return NllbTranslator(folder) if folder else None


class NllbTranslator:
    name = "nllb"

    def __init__(self, path, device="cpu", threads=2):
        import ctranslate2
        import sentencepiece
        path = Path(path)
        self.model = ctranslate2.Translator(str(path), device=device, compute_type="int8",
                                            intra_threads=threads, inter_threads=1)
        # Open with Python's Unicode-aware file API. Some Windows builds of
        # SentencePiece cannot open otherwise valid non-ASCII installation paths.
        tokenizer_bytes = (path / "sentencepiece.bpe.model").read_bytes()
        self.tokens = sentencepiece.SentencePieceProcessor(model_proto=tokenizer_bytes)
        self._recent = OrderedDict()

    def translate_many(self, phrases, *, target="en"):
        """Translate source-labelled phrases to English, or English reply drafts to a target."""
        from text_engine import _token_chunks, _sentence_parts
        if target != "en" and target not in NLLB_TAGS:
            raise ValueError("Choose a supported reply language.")
        target_tag = "eng_Latn" if target == "en" else NLLB_TAGS[target]
        phrases = list(phrases)
        decoded = {}
        sources, owners = [], []
        for key in dict.fromkeys(phrases):
            lang, text = key
            if target == "en" and lang in NLLB_TAGS:
                source_tag = NLLB_TAGS[lang]
            elif target != "en" and lang == "en":
                source_tag = "eng_Latn"
            else:
                raise ValueError("This source has no multilingual text model route.")
            conventional = standalone_translation(text, lang) if target == "en" else None
            if conventional:
                decoded[key] = [conventional]
                continue
            cache_key = (lang, text, target)
            if cache_key in self._recent:
                self._recent.move_to_end(cache_key)
                decoded[key] = [self._recent[cache_key]]
                continue
            decoded[key] = []
            for sentence in _sentence_parts(text):
                for chunk in _token_chunks(sentence, self.tokens):
                    sources.append([source_tag, *chunk, "</s>"])
                    owners.append(key)
        if sources:
            limit = min(768, max(96, max(map(len, sources)) * 4 + 16))
            results = self.model.translate_batch(sources, target_prefix=[[target_tag] for _ in sources],
                                                 beam_size=4, max_batch_size=512, batch_type="tokens",
                                                 max_input_length=0, max_decoding_length=limit,
                                                 no_repeat_ngram_size=4)
            for key, result in zip(owners, results, strict=True):
                tokens = result.hypotheses[0]
                if len(tokens) >= limit:
                    raise ValueError("A translation reached the model output limit. Try a shorter sentence.")
                if tokens[:1] == [target_tag]:
                    tokens = tokens[1:]
                decoded[key].append(self.tokens.decode(tokens).strip())
        values = {key: " ".join(value).strip() for key, value in decoded.items()}
        for key, value in values.items():
            if len(key[1]) <= 2048 and value:
                self._recent[(*key, target)] = value
                if len(self._recent) > 384:
                    self._recent.popitem(last=False)
        return [values[key] for key in phrases]
