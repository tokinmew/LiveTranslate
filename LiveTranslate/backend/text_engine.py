"""Offline English text translation using compatible Argos model files.

Only catalog()/install() access the internet. Runtime translation uses
CTranslate2 + SentencePiece directly, avoiding Torch and downloaded sentence
splitters. Supports direct source-to-English SentencePiece Argos packs.
"""
from __future__ import annotations

import json
from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.request
import zipfile

from foreign_text import PRIORITY, foreign_segments, script
from language_catalog import canonical_code, LANGUAGE_NAMES, NLLB_TAGS
from multilingual_text import local_identifier, model_files_present, resolve_line, standalone_translation


INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MAX_DOWNLOAD = 1024 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_FILES = 4096
MAX_SOURCE_TOKENS = 160
MAX_OUTPUT_TOKENS = 1024
CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")
RESERVED = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)),
            *("LPT" + str(i) for i in range(1, 10))}


def _valid_code(value):
    return isinstance(value, str) and bool(CODE_RE.fullmatch(value))


def _metadata(value):
    if not isinstance(value, dict) or not _valid_code(value.get("from_code")):
        raise ValueError("The language pack has invalid source-language metadata.")
    if value.get("to_code") != "en" or value.get("type", "translate") != "translate":
        raise ValueError("Choose a translation pack whose destination language is English (en).")
    if value["from_code"] == "en":
        raise ValueError("English does not need a translation pack.")
    if not isinstance(value.get("target_prefix", ""), str):
        raise ValueError("The language pack has an invalid target prefix.")
    return value


def _safe_members(archive):
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(x.file_size for x in members) > MAX_EXPANDED:
        raise ValueError("The language archive exceeds the supported size limit.")
    seen = set()
    for member in members:
        name = member.filename
        parts = PurePosixPath(name).parts
        if (not parts or name.startswith(("/", "\\")) or "\\" in name
                or any(p in (".", "..") or ":" in p or p.endswith((".", " "))
                       or p.split(".")[0].upper() in RESERVED for p in parts)):
            raise ValueError("The language archive contains an unsafe file path.")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError("Language archives may contain only normal files and folders.")
        normalized = "/".join(parts).casefold()
        if normalized in seen:
            raise ValueError("The language archive contains duplicate file paths.")
        seen.add(normalized)
        if member.flag_bits & 1:
            raise ValueError("Encrypted language archives are not supported.")
    return members


def _bounded_read(url, maximum):
    if not url.startswith("https://"):
        raise ValueError("Language files must use an HTTPS download link.")
    request = urllib.request.Request(url, headers={"User-Agent": "LiveTranslate-Prototype/0.1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("An insecure language download redirect was refused.")
        value = response.read(maximum + 1)
        if len(value) > maximum:
            raise ValueError("The downloaded language file exceeds the supported size limit.")
        return value


def _sentence_parts(text):
    """Split after common sentence endings without dropping any input text."""
    return [p for p in re.split(r"(?<=[.!?。！？])\s+|(?<=[。！？])(?=\S)", text) if p]


def _has_vocabulary(names):
    """Recognize both old TXT and current JSON CTranslate2 vocabularies."""
    return (any("shared_vocabulary." + ext in names for ext in ("txt", "json"))
            or (any("source_vocabulary." + ext in names for ext in ("txt", "json"))
                and any("target_vocabulary." + ext in names for ext in ("txt", "json"))))


def _decode_target(tokenizer, pieces):
    """Recover SentencePiece word boundaries for target-only vocabulary entries.

    The 1.9 Chinese packs can emit English model vocabulary pieces that the
    input SentencePieceProcessor does not know. Its native decoder returns
    those pieces verbatim, including their U+2581 word-space marker. Keep the
    native decoder for byte fallback, specials, and all known pieces.
    """
    decoded = tokenizer.decode(pieces)
    marker = "\u2581"
    if marker in decoded and any(marker in p and tokenizer.piece_to_id(p) == tokenizer.unk_id()
                                 for p in pieces):
        return decoded.replace(marker, " ")
    return decoded


def _japanese_sentence(text):
    """Restore omitted terminal punctuation for complete polite Japanese clauses."""
    value = text.rstrip()
    if value.endswith(("ですか", "ますか", "でしょうか", "ませんか")):
        return value + "？"
    if value.endswith(("です", "ます", "ました", "でした", "ません", "ください", "でしょう")):
        return value + "。"
    return text


def _short_script_language(text):
    """Recognize short kana/Hangul snippets without guessing from Han alone.

    Only letters from a single script family (plus shared Han characters) are
    accepted. Latin, kana+Hangul, or longer passages go to the full detector.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters or len(letters) > 40:
        return None
    def han(c):
        return (0x3400 <= ord(c) <= 0x4DBF or 0x4E00 <= ord(c) <= 0x9FFF
                or 0xF900 <= ord(c) <= 0xFAFF or 0x20000 <= ord(c) <= 0x2FA1F)
    def kana(c):
        return (0x3040 <= ord(c) <= 0x30FF or 0x31F0 <= ord(c) <= 0x31FF
                or 0xFF66 <= ord(c) <= 0xFF9D)
    def hangul(c):
        return (0x1100 <= ord(c) <= 0x11FF or 0x3130 <= ord(c) <= 0x318F
                or 0xA960 <= ord(c) <= 0xA97F or 0xAC00 <= ord(c) <= 0xD7AF
                or 0xD7B0 <= ord(c) <= 0xD7FF)
    if any(kana(c) for c in letters) and all(kana(c) or han(c) for c in letters):
        return "ja"
    if any(hangul(c) for c in letters) and all(hangul(c) or han(c) for c in letters):
        return "ko"
    return None


def _token_chunks(text, tokenizer, maximum=MAX_SOURCE_TOKENS):
    """Split long source sentences on character boundaries before encoding.

    No source is sliced off at the model's token limit. Boundary choices can
    reduce translation quality compared with a full document model.
    """
    chunks = []
    remaining = text
    while remaining:
        # Bound repeated encoder work on long pasted paragraphs. A short
        # window already holds many times the usual 160-token chunk.
        window = remaining[:maximum * 24]
        tokens = tokenizer.encode(window, out_type=str)
        if len(tokens) <= maximum:
            if tokens:
                chunks.append(tokens)
            remaining = remaining[len(window):]
            continue
        low, high = 1, len(window)
        while low < high:
            middle = (low + high + 1) // 2
            if len(tokenizer.encode(remaining[:middle], out_type=str)) <= maximum:
                low = middle
            else:
                high = middle - 1
        cut = low
        # Prefer a word boundary, while guaranteeing progress for CJK text.
        boundary = max(remaining.rfind(" ", cut // 2, cut),
                       remaining.rfind("\t", cut // 2, cut))
        if boundary > 0:
            cut = boundary + 1
        part = tokenizer.encode(remaining[:cut], out_type=str)
        if not part or len(part) > maximum:
            raise ValueError("This text contains a character sequence the language tokenizer cannot split safely.")
        chunks.append(part)
        remaining = remaining[cut:]
    return chunks


class TextEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.pack_dir = self.data_dir / "text-packs"
        self.pack_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "text-pack-index.json"
        self._loaded = {}
        self._active_model = None
        self._identifier = None
        self._recent_language_scores = lru_cache(maxsize=256)(self._score_language)
        self._chinese_converters = None

    def _packs(self):
        values = {}
        for folder in self.pack_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith(".") or folder.is_symlink():
                continue
            try:
                meta = _metadata(json.loads((folder / "metadata.json").read_text(encoding="utf-8")))
                if ((folder / "sentencepiece.model").is_file()
                        and (folder / "model" / "model.bin").is_file()
                        and _has_vocabulary({p.name for p in (folder / "model").iterdir() if p.is_file()})):
                    values[meta["from_code"]] = (folder, meta)
            except (ValueError, OSError, KeyError):
                continue
        return values

    def installed(self):
        return sorted([{"code": code, "name": LANGUAGE_NAMES.get(code) or meta.get("from_name") or code,
                        "version": str(meta.get("package_version", ""))}
                       for code, (_, meta) in self._packs().items()], key=lambda p: p["name"])

    def catalog(self):
        """Explicit online setup action: refresh the official pack catalog."""
        raw = _bounded_read(INDEX_URL, 5 * 1024 * 1024)
        index = json.loads(raw.decode("utf-8"))
        if not isinstance(index, list):
            raise ValueError("The language catalog has an unexpected format.")
        packages = self._catalog_entries(index)
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.index_path)
        return packages

    @staticmethod
    def _catalog_entries(index):
        values = {}
        for meta in index:
            try:
                _metadata(meta)
            except ValueError:
                continue
            links = meta.get("links", [])
            if not isinstance(links, list):
                continue
            link = next((x for x in links if isinstance(x, str) and x.startswith("https://")), None)
            if link:
                values[meta["from_code"]] = {
                    "code": meta["from_code"], "name": str(LANGUAGE_NAMES.get(meta["from_code"]) or meta.get("from_name") or meta["from_code"]),
                    "version": str(meta.get("package_version", "")), "url": link,
                }
        return sorted(values.values(), key=lambda p: p["name"])

    def install(self, code):
        if not _valid_code(code):
            raise ValueError("Choose a language from the text language catalog.")
        if self.index_path.is_file():
            catalog = self._catalog_entries(json.loads(self.index_path.read_text(encoding="utf-8")))
        else:
            catalog = self.catalog()
        pack = next((p for p in catalog if p["code"] == code), None)
        if pack is None:
            raise ValueError("No direct English translation pack is available for this language. Refresh the catalog.")
        # Stream to disk so a large model need not be duplicated in memory.
        request = urllib.request.Request(pack["url"], headers={"User-Agent": "LiveTranslate-Prototype/0.1"})
        with tempfile.TemporaryDirectory(prefix=".download-", dir=self.data_dir) as scratch:
            path = Path(scratch) / "download.argosmodel"
            with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as output:
                if not response.geturl().startswith("https://"):
                    raise ValueError("An insecure language download redirect was refused.")
                size = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_DOWNLOAD:
                        raise ValueError("This language download exceeds the 1 GiB supported limit.")
                    output.write(block)
            return self.import_pack(path, expected_code=code)

    def import_pack(self, path, expected_code=None):
        """Install a complete .argosmodel file without any network requests."""
        path = Path(path)
        if not path.is_file() or path.stat().st_size > MAX_DOWNLOAD:
            raise ValueError("Choose a language archive smaller than 1 GiB.")
        with zipfile.ZipFile(path) as archive:
            members = _safe_members(archive)
            metadata_files = [m for m in members if PurePosixPath(m.filename).name == "metadata.json"]
            if len(metadata_files) != 1 or metadata_files[0].file_size > 256 * 1024:
                raise ValueError("The archive must contain exactly one language metadata.json file.")
            metadata_file = metadata_files[0]
            meta = _metadata(json.loads(archive.read(metadata_file).decode("utf-8")))
            code = meta["from_code"]
            if expected_code is not None and code != expected_code:
                raise ValueError("The downloaded pack does not match the selected language.")
            prefix = PurePosixPath(metadata_file.filename).parent
            if len(prefix.parts) > 1:
                raise ValueError("The language archive has an unsupported directory layout.")
            names = {m.filename for m in members}
            def entry(name):
                return str(prefix / name) if str(prefix) != "." else name
            if entry("sentencepiece.model") not in names:
                raise ValueError("This prototype supports SentencePiece Argos packs. BPE-only packs are not supported.")
            # config.json was introduced after early Argos releases and is
            # optional in CTranslate2. Do not reject the legacy 1.1 packs.
            for required in ("model/model.bin",):
                if entry(required) not in names:
                    raise ValueError("The archive is missing a required CTranslate2 model file: " + required)
            if not _has_vocabulary({PurePosixPath(n).name for n in names
                                    if PurePosixPath(n).parent == prefix / "model"}):
                raise ValueError("The archive is missing the CTranslate2 shared or source/target vocabulary files.")
            target = self.pack_dir / (code + "_en")
            if target.exists():
                raise ValueError("That English translation pack is already installed.")
            with tempfile.TemporaryDirectory(prefix=".import-", dir=self.pack_dir) as scratch:
                staging = Path(scratch) / "pack"
                staging.mkdir()
                for member in members:
                    member_path = PurePosixPath(member.filename)
                    try:
                        relative = member_path.relative_to(prefix)
                    except ValueError:
                        raise ValueError("All language files must be inside the pack's root folder.")
                    if not relative.parts:
                        continue
                    destination = staging.joinpath(*relative.parts)
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, destination.open("xb") as output:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                staging.rename(target)
        return code

    def _load(self, code):
        if code == self._active_model:
            return self._loaded[code]
        if code not in self._loaded:
            packs = self._packs()
            if code not in packs:
                raise ValueError("No " + code + " → English text pack is installed. Open Language packs to download or import it.")
        # Each native Translator creates a CPU worker pool. Recreating these
        # on each language switch accumulates native memory on Windows.
        # Retain each pool, keeping only the active model weights resident.
        if self._active_model is not None:
            self._loaded[self._active_model][0].unload_model()
            self._active_model = None
        if code in self._loaded:
            translator = self._loaded[code][0]
            if not translator.model_is_loaded:
                translator.load_model()
        else:
            try:
                import ctranslate2
                import sentencepiece
            except (ImportError, OSError) as exc:
                raise RuntimeError("The local translation runtime could not load. Run Setup.cmd to repair dependencies. " + str(exc)) from exc
            folder, meta = packs[code]
            # Python opens Unicode Windows paths natively. Passing model bytes
            # also works when SentencePiece's C++ file loader expects ANSI.
            tokenizer = sentencepiece.SentencePieceProcessor(model_proto=(folder / "sentencepiece.model").read_bytes())
            threads = max(1, min(4, os.cpu_count() or 1))
            translator = ctranslate2.Translator(str(folder / "model"), device="cpu", compute_type="int8",
                                               intra_threads=threads, inter_threads=1)
            self._loaded[code] = (translator, tokenizer, meta.get("target_prefix", ""))
        self._active_model = code
        return self._loaded[code]

    def _classifier(self):
        if self._identifier is None:
            try:
                # Modern py3langid replaces langid 1.1.6 and supports NumPy 2.
                self._identifier = local_identifier()
            except (ImportError, OSError) as exc:
                raise RuntimeError("Language detection could not load. Run Setup.cmd or select a source language manually. " + str(exc)) from exc
        return self._identifier

    def _detect(self, text):
        hint = _short_script_language(text)
        if hint:
            return hint
        code, probability = self._classifier().classify(text)
        if probability < 0.6:
            raise ValueError("The text language is uncertain. Select its source language manually.")
        if code == "zh":
            return self._chinese_script(text)
        return code

    def _score_language(self, line):
        ranked = self._classifier().rank(line)
        top, score = ranked[0]
        return top, score, ranked[1][1], next(p for code, p in ranked if code == "en")

    def _classify_line(self, value, source):
        return resolve_line(value, source, self._recent_language_scores,
                            lambda: set(self._classifier().nb_classes))

    def accepts_source_line(self, text, source):
        source = canonical_code(source)
        if source in PRIORITY:
            return bool(foreign_segments(text, source))
        return bool(self._classify_line(text, source))

    def translate_multilingual(self, text, source, quality_callback, priority_callback):
        """Route each line to its installed text pack or the checked shared model.

        Quality and priority callbacks share models with the screen and speech
        workers. A repeated line in this request is inferred only once.
        """
        if not isinstance(text, str) or len(text) > 50000:
            raise ValueError("Translate at most 50,000 characters at a time.")
        raw_source = str(source).strip().lower()
        source = canonical_code(raw_source)
        if not _valid_code(source) and source != "auto":
            raise ValueError("Choose a valid source language or Auto.")
        installed = None
        if raw_source != source and _valid_code(raw_source):
            installed = {row["code"] for row in self.installed()}
            if raw_source in installed:
                source = raw_source
        segments = []
        for line in text.splitlines():
            if source in PRIORITY or source == "auto" and any(script(c) for c in line):
                for hint, value in foreign_segments(line, source):
                    code = self.caption_han_language(value) if hint == "han" else hint
                    segments.append((code, value))
            else:
                code = self._classify_line(line, source)
                if code:
                    segments.append((code, line.strip()))
        found = {}
        if segments and installed is None:
            installed = {row["code"] for row in self.installed()}
        for code, value in dict.fromkeys(segments):
            conventional = standalone_translation(value, code)
            if conventional and (code in installed or model_files_present(self.data_dir / "speech-translation")):
                result = {"text": conventional}
            elif code in installed:
                result = (priority_callback(value, code) if code in PRIORITY else self.translate(value, code))
            elif code in NLLB_TAGS:
                result = quality_callback([value], code)
                if result is None:
                    raise ValueError("Install the checked multilingual quality model or import a direct "
                                     f"{LANGUAGE_NAMES[code]}-to-English text pack to translate this source.")
            else:
                raise ValueError(f"No installed {code}-to-English text pack was found for this source.")
            if result and result.get("text"):
                found[(code, value)] = result["text"].strip()
        if not found:
            return {"text": "", "language": source, "ignored": True}
        codes = {code for code, value in found}
        return {"text": "\n".join(found[key] for key in segments if key in found),
                "language": next(iter(codes)) if len(codes) == 1 else "mul"}

    def convert_chinese(self, text, target):
        """Convert between writing systems without changing the spoken source."""
        if self._chinese_converters is None:
            try:
                from opencc import OpenCC
                self._chinese_converters = OpenCC("s2t"), OpenCC("t2s")
            except (ImportError, OSError) as exc:
                raise RuntimeError("Chinese script detection could not load. Select Chinese (Simplified) or Chinese (Traditional) manually, or run Setup.cmd. " + str(exc)) from exc
        return self._chinese_converters[0 if target == "zt" else 1].convert(text)

    def _chinese_script(self, text):
        """Identify a written script from its direction of conversion.

        Short or shared Han-only labels can require an explicit user choice.
        Source text is preserved when the user supplies written input.
        """
        simplified_evidence = self.convert_chinese(text, "zt") != text
        traditional_evidence = self.convert_chinese(text, "zh") != text
        if simplified_evidence and not traditional_evidence:
            return "zh"
        if traditional_evidence and not simplified_evidence:
            return "zt"
        raise ValueError("Chinese was detected, but its script is mixed or ambiguous. Select Chinese (Simplified) or Chinese (Traditional) manually.")

    def caption_han_language(self, text):
        """Choose a supported pack for Han-only signs while monitoring a screen."""
        han = "".join(char for char in text if script(char) == "han")
        try:
            detected = self._detect(han[:8000])
            if detected in PRIORITY:
                return detected
        except ValueError:
            # Brief UI labels are frequently shared between Chinese and Japanese.
            # An uncertain language or Chinese-script decision must not end a watch.
            pass
        try:
            return self._chinese_script(han)
        except ValueError:
            # Shared/mixed characters can be processed by the Chinese model.
            # Choosing Japanese in the UI explicitly resolves Han-only kanji.
            return "zh"

    def translate_imported(self, text, source):
        """For an explicitly imported pack, skip English and uncertain lines."""
        if not _valid_code(source):
            raise ValueError("Choose a valid source language or Auto.")
        translated = []
        for line in text.splitlines():
            if not any(c.isalpha() for c in line):
                continue
            try:
                language = self._detect(line[:8000])
            except ValueError:
                continue
            # Brazilian Portuguese packs use Argos 'pb', while the detector
            # uses ISO 'pt'. Shared primary language also covers regional packs.
            expected = {"pb": "pt"}.get(source, source).split("-")[0]
            if language != "en" and language == expected:
                value = self.translate(line, source)["text"].strip()
                if value:
                    translated.append(value)
        if not translated:
            return {"text": "", "language": source, "ignored": True}
        return {"text": "\n".join(translated), "language": source}

    def translate(self, text, source="auto"):
        if not isinstance(text, str) or len(text) > 50000:
            raise ValueError("Translate at most 50,000 characters at a time.")
        if not text.strip():
            return {"text": "", "language": source if source != "auto" else "unknown"}
        if source in PRIORITY and not any(script(char) for char in text):
            return {"text": "", "language": source}
        if source == "auto":
            source = self._detect(text[:8000])
        elif not _valid_code(source):
            raise ValueError("Choose a valid source language or Auto.")
        if source == "en":
            return {"text": "", "language": "en"}
        translator, tokenizer, prefix = self._load(source)
        output_lines = []
        for line in re.split(r"(\r\n|\n|\r)", text):
            if not line.strip():
                output_lines.append(line)
                continue
            # Subtitles and UI labels often omit final punctuation. Supplying
            # it for a complete predicate helps the Japanese model retain its
            # subject and object. The original shown in the UI stays intact.
            model_line = _japanese_sentence(line) if source == "ja" else line
            tokens = [chunk for sentence in _sentence_parts(model_line)
                      for chunk in _token_chunks(sentence, tokenizer)]
            results = translator.translate_batch(
                tokens, target_prefix=[[prefix]] * len(tokens) if prefix else None,
                # This Japanese pack drops essential words from short UI labels
                # with the more aggressive short-output preference.
                replace_unknowns=True, beam_size=4, length_penalty=0.6 if source == "ja" else 0.2,
                max_batch_size=512, batch_type="tokens", max_input_length=0,
                max_decoding_length=MAX_OUTPUT_TOKENS)
            translated = []
            for result in results:
                hypothesis = list(result.hypotheses[0])
                if len(hypothesis) >= MAX_OUTPUT_TOKENS:
                    raise ValueError("A translation reached the output limit. Translate shorter text to avoid incomplete output.")
                value = _decode_target(tokenizer, hypothesis)
                if prefix and value.startswith(prefix):
                    value = value[len(prefix):]
                translated.append(value.strip())
            output_lines.append(" ".join(translated))
        return {"text": "".join(output_lines), "language": source}
