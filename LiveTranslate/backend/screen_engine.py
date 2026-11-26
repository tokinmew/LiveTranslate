"""Explicit screen-region OCR with a bundled native engine and local models.

A manual Tesseract executable and installed Windows OCR packs can also be used.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager, nullcontext
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time
from windows_ocr import WindowsOCR, WindowsWatch
from screen_lines import LATIN_FALLBACKS, accepted_regions
from ocr_guard import (DESKTOP_ICON_CONFUSABLE, EnglishGuard, combine_row_results, corroborate_lines, filter_words, has_target_script,
                       filter_desktop_fragments,
                       join_vertical_glyphs, observe_english, overlapping_text_lines, plain_horizontal_rows,
                       plausible_band_repair, prefer_korean_row, prefer_single_line,
                       single_foreign_band, uncertain_korean_row, vertical_verifier_image, weak_foreign_line)

OCR_CODES = frozenset("afr amh ara asm aze aze_cyrl bel ben bod bos bre bul cat ceb ces ckb chi_sim chi_sim_vert chi_tra chi_tra_vert chr cos cym dan deu div dzo ell eng enm epo est eus fao fas fil fin fra frk frm fry gla gle glg grc guj hat heb hin hrv hun hye iku ind isl ita ita_old jav jpn jpn_vert kan kat kat_old kaz khm kir kmr kor kor_vert lao lat lav lit ltz mal mar mkd mlt mon mri msa mya nep nld nor oci ori osd pan pol por pus que ron rus san sin slk slv snd spa spa_old sqi srp srp_latn sun swa swe syr tam tat tel tgk tha tir ton tur uig ukr urd uzb uzb_cyrl vie yid yor".split())
AUTO_OCR_ORDER = ("chi_tra", "chi_sim", "kor", "jpn", "eng")
PRIORITY_OCR = frozenset(("chi_tra", "chi_sim", "kor", "jpn", "jpn_vert"))
_CAPTURE_LOCK = threading.Lock()
_CAPTURE_INTENT = threading.local()

class ScreenCaptureUnavailable(RuntimeError):
    """Screen pixels temporarily unavailable after desktop/display changes."""


def _tesseract_data_path(directory: Path) -> str:
    """Give the Windows native reader an ASCII spelling of the real model folder."""
    original = str(directory)
    if os.name != "nt" or (original.isascii() and len(original) < 240):
        return original
    # The app starts its worker in the installation directory. This also works
    # on systems where NTFS short names are disabled. Never change process cwd.
    try:
        relative = os.path.relpath(directory)
        if relative.isascii() and len(relative) < 240:
            return relative
    except ValueError:
        pass  # Different Windows drives do not share a relative path.
    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_short.restype = wintypes.DWORD
    length = get_short(original, None, 0)
    if length:
        result = ctypes.create_unicode_buffer(length)
        copied = get_short(original, result, length)
        if 0 < copied < length and result.value.isascii():
            return result.value
    return original


def page_segmentation_mode(language: str, full_monitor: bool = False) -> int:
    # Tesseract PSM 5: one vertical block; PSM 6: one ordinary text block.
    # https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
    if any(code.endswith("_vert") for code in language.split("+")):
        return 5
    # Full desktops contain unrelated menus, subtitles and sidebars.
    return 11 if full_monitor else 6


def confirm_desktop_labels(frame, positions, language, read, *, state=None, include_long=False):
    """Reread short labels at their actual pixels, with bounded work per frame."""
    import math
    import unicodedata
    from PIL import Image, ImageOps
    from ocr_guard import Word, parse_tsv
    from screen_geometry import union
    if not isinstance(frame, Image.Image):
        return []
    mapping = frame.info.get("desktop_map")
    if not mapping:
        return []
    x, y, sx, sy = mapping
    if sx <= 0 or sy <= 0:
        return []
    def compact(value):
        return "".join(unicodedata.normalize("NFKC", value).split())
    state = state if state is not None else {}
    attempted = state.setdefault("attempted", set())
    saved = state.setdefault("anchors", {})
    retry_at = state.setdefault("retry_at", {})
    state["complete"] = True
    candidates = []
    for line, spans in positions:
        if sum(has_target_script(ch) for ch in line) <= 2:
            for start, end, box in spans:
                candidates.append((line[start:end], box))
        if spans:
            candidates.append((line, union([box for _, _, box in spans])))
    candidates.sort(key=lambda item: (compact(item[0]), tuple(item[1])) in retry_at)
    seen, reads = set(), 0
    deadline = time.monotonic() + 1.5
    for text, box in candidates:
        source = compact(text)
        glyphs = "".join(ch for ch in source if has_target_script(ch))
        # A square, plus or minus is indistinguishable from some single Han
        # characters. Such symbols need neighboring text or an explicit region.
        if not glyphs or (len(glyphs) > 2 and not include_long) or (len(glyphs) == 1 and glyphs in DESKTOP_ICON_CONFUSABLE):
            continue
        identity = source, tuple(box)
        if identity in seen or identity in attempted:
            continue
        seen.add(identity)
        if time.monotonic() < retry_at.get(identity, 0):
            state["complete"] = False
            continue
        if reads >= 6 or time.monotonic() >= deadline - .05:
            state["complete"] = False
            break
        left, top, right, bottom = box
        h = max(bottom - top, (right - left) / max(1, len(source)))
        pad = max(3, math.ceil(h * .28))
        crop_box = (max(0, math.floor((left - x - pad) / sx)),
                    max(0, math.floor((top - y - pad) / sy)),
                    min(frame.width, math.ceil((right - x + pad) / sx)),
                    min(frame.height, math.ceil((bottom - y + pad) / sy)))
        l, t, r, b = crop_box
        if l >= r or t >= b or (r-l)*(b-t) > 160000:
            attempted.add(identity)
            continue
        crop = frame.crop(crop_box)
        scale = max(1, min(3, 54 / crop.height))
        if scale > 1:
            crop = crop.resize((round(crop.width*scale), round(crop.height*scale)), Image.Resampling.LANCZOS)
        background = max(range(256), key=crop.convert("L").histogram().__getitem__)
        crop = ImageOps.expand(crop, border=10, fill=background)
        reads += 1
        checked = read(crop, language, 7, min(.6, deadline-time.monotonic()))
        if not checked:
            # A timeout is not evidence against the text. Put fresh candidates
            # first on the next pass, then retry this area after a short delay.
            retry_at[identity] = time.monotonic() + 1
            state["complete"] = False
            continue
        attempted.add(identity)
        retry_at.pop(identity, None)
        observed = compact(checked[0])
        observed_glyphs = "".join(ch for ch in observed if has_target_script(ch))
        if (observed != source if len(glyphs) <= 2 else observed_glyphs != glyphs):
            continue
        words = [word for word in parse_tsv(checked[1]) if has_target_script(word.text)]
        scored_glyphs = "".join(ch for word in words for ch in unicodedata.normalize("NFKC", word.text) if has_target_script(ch))
        scores = [word.confidence for word in words for char in word.text if has_target_script(char)]
        if scored_glyphs != observed_glyphs or len(scores) != len(glyphs):
            continue
        confident = (scores and min(scores) >= 75 and sum(scores)/len(scores) >= 88
                     if len(glyphs) <= 2 else scores and sum(scores)/len(scores) >= 65)
        if confident:
            saved[identity] = Word(text, tuple(box), sum(scores)/len(scores))
    return list(saved.values())


class ScreenEngine:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "tessdata"
        self.root.mkdir(parents=True, exist_ok=True)
        self.native_data_path = _tesseract_data_path(self.root)
        self.english_guard = EnglishGuard()
        self.windows = WindowsOCR()
        self.accepts_source_line = None
        self._last_frame = None
        self._desktop_proof_state = None
        self._external_cache = None
        self._watch = threading.local()

    @contextmanager
    def watch_models(self):
        """Keep OCR weights on this watcher thread until its session finishes."""
        previous = getattr(self._watch, 'models', None)
        previous_windows = getattr(self._watch, 'windows', None)
        windows = WindowsWatch()
        readers = {}
        self._watch.models = readers
        self._watch.windows = windows
        try:
            yield
        finally:
            self._watch.models = previous
            self._watch.windows = previous_windows
            windows.close()
            for _, api in readers.values():
                api.End()

    @contextmanager
    def _reader(self, native, codes, mode, primary):
        readers = getattr(self._watch, 'models', None)
        if readers is None:
            with native.PyTessBaseAPI(path=self.native_data_path, lang=codes, psm=mode) as api:
                yield api
            return

        # Reserve one slot for the selected languages and one for independent
        # verification. A temporary verifier cannot evict the active main reader.
        cached = readers.get(primary)
        if cached is None or cached[0] != codes:
            if cached is not None:
                del readers[primary]
                cached[1].End()
            api = native.PyTessBaseAPI(path=self.native_data_path, lang=codes, psm=mode)
            readers[primary] = codes, api
        else:
            api = cached[1]
        try:
            api.SetPageSegMode(mode)
            yield api
            # Release screen pixels and learned page state after each read.
            # Only immutable language data should carry into the next frame.
            api.Clear()
            api.ClearAdaptiveClassifier()
        except BaseException:
            del readers[primary]
            api.End()
            raise

    @staticmethod
    def _native_engine():
        try:
            import tesserocr
            return tesserocr
        except (ImportError, OSError):
            return None

    def resolve_engine(self, executable: str = "") -> str:
        """Empty string selects the bundled engine; a path selects the CLI."""
        if executable:
            return self.find_tesseract(executable)
        if self._native_engine() is not None:
            return ""
        try:
            return self.find_tesseract()
        except RuntimeError:
            if self.windows.packs():
                return ""
            raise RuntimeError("The screen OCR engine is missing. Run Set up again to install the bundled free OCR engine, or Browse to a separate Tesseract tesseract.exe.") from None

    def engine_ready(self, executable: str = "") -> bool:
        try:
            self.resolve_engine(executable)
            return True
        except (OSError, RuntimeError):
            return False

    def find_tesseract(self, executable: str = "") -> str:
        if executable:
            candidate = Path(executable)
            if not candidate.is_file():
                raise RuntimeError("The chosen Tesseract executable does not exist.")
            return str(candidate)
        found = shutil.which("tesseract")
        if found:
            return found
        for base in (os.environ.get("ProgramFiles", "C:\\Program Files"), os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")):
            for suffix in ("Tesseract-OCR/tesseract.exe", "Programs/Tesseract-OCR/tesseract.exe"):
                candidate = Path(base) / suffix
                if candidate.is_file():
                    return str(candidate)
        raise RuntimeError("Screen translation needs an OCR engine. Run Set up selected, or use Settings to choose an installed Tesseract tesseract.exe.")

    def languages(self, executable: str = "") -> list[str]:
        return sorted(self.ocr_sources(executable))

    def ocr_sources(self, executable: str = "") -> dict[str, str]:
        packs = {} if executable else self.windows.packs()
        sources = {code: "Windows OCR (Latin fallback)" for code in LATIN_FALLBACKS if "eng" in packs}
        # CJK's layout verification uses Tesseract. List Windows recognizers
        # only when the matching reading path can actually consume them.
        sources.update((code, "Windows OCR") for code in packs if code not in PRIORITY_OCR)
        sources.update((code, "Tesseract") for code in self.external_languages(executable))
        if executable or self._native_engine() is not None or any(v == "Tesseract" for v in sources.values()):
            sources.update((code, "Tesseract") for code in self.local_languages())
        return sources

    def external_languages(self, executable: str = "") -> list[str]:
        cached = self._external_cache
        if cached and cached[0] == executable and time.monotonic() < cached[1]:
            return list(cached[2])
        result = set()
        try:
            import subprocess
            command = self.find_tesseract(executable)
            process = subprocess.run([command, "--list-langs"], capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if process.returncode == 0:
                for line in process.stdout.splitlines():
                    if re.fullmatch(r"[a-z_]+", line.strip()):
                        result.add(line.strip())
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        ordered = sorted(result)
        self._external_cache = executable, time.monotonic() + 30, ordered
        return list(ordered)

    def auto_language(self, executable: str = "") -> str:
        """Use installed horizontal priority data from one usable data folder.

        Never combine files that live in incompatible app/CLI data directories,
        and never include vertical models in automatic horizontal OCR.
        """
        groups = [set(self.local_languages())]
        external = set(self.external_languages(executable))
        if external:
            groups.append(external)
        choices = []
        for group in groups:
            selected = [code for code in AUTO_OCR_ORDER[:-1] if code in group]
            if selected and "eng" in group:
                selected.append("eng")
            choices.append(selected)
        selected = max(choices, key=lambda choice: (len(set(choice) - {"eng"}), len(choice)))
        if not selected:
            raise RuntimeError("Screen reading needs installed Chinese, Japanese or Korean OCR data. Use Install all four to prepare the checked models.")
        return "+".join(selected)

    @staticmethod
    def validate_region(region: dict) -> dict:
        if not isinstance(region, dict):
            raise ValueError("Select a screen rectangle first.")
        if "window" in region:
            from window_capture import validate_target
            return validate_target(region)
        if region == {"monitor": "primary"}:
            return {"monitor": "primary"}
        rect = {}
        for key in ("left", "top", "width", "height"):
            value = region.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Screen rectangle coordinates must be whole numbers.")
            rect[key] = value
        if "full_display" in region:
            if not isinstance(region["full_display"], bool):
                raise ValueError("Full-display capture must be true or false.")
            rect["full_display"] = region["full_display"]
        if (abs(rect["left"]) > 100000 or abs(rect["top"]) > 100000
                or not 5 <= rect["width"] <= 16384 or not 5 <= rect["height"] <= 16384
                or rect["width"] * rect["height"] > 40_000_000):
            raise ValueError("Select a valid screen rectangle of at least 5 by 5 pixels (at most 40 million pixels).")
        return rect

    def local_languages(self) -> list[str]:
        """Installed app-owned files, without importing OCR or finding its engine."""
        return sorted(file.stem for file in self.root.glob("*.traineddata")
                      if file.stem in OCR_CODES and file.is_file() and file.stat().st_size > 1000)

    def install_ocr_language(self, code: str) -> str:
        if code not in OCR_CODES:
            raise ValueError("Unknown OCR language code. Use a Tesseract language code such as jpn, spa, deu or chi_sim.")
        target = self.root / (code + ".traineddata")
        if target.is_file() and target.stat().st_size > 1000:
            return str(target)
        raise RuntimeError("Use checked model setup for the four priority languages, or select an already installed OCR language.")

    def recognize_watched(self, region, language, executable, profile, tracked_boxes, **options):
        return self.recognize(region, language, executable, tracking=(profile, tracked_boxes), source=profile, **options)

    @staticmethod
    @contextmanager
    def manual_capture():
        """A user-requested sample may briefly clear our own dashboard pixels."""
        previous = getattr(_CAPTURE_INTENT, "manual", False)
        _CAPTURE_INTENT.manual = True
        try:
            yield
        finally:
            _CAPTURE_INTENT.manual = previous

    def recognize(self, region: dict, language: str = "auto", executable: str = "", exclude_windows=(), tracking=None, source="auto", _frame=None) -> str:
        if language == "auto":
            language = self.auto_language(executable)
        selected = language.split("+")
        extended = source not in ("auto", "zh", "zt", "ko", "ja")
        if extended:
            from language_routes import ocr_code
            if (source == "en" or len(selected) != 1 or language not in OCR_CODES or
                    language == "eng" or ocr_code(source) != language or self.accepts_source_line is None):
                raise ValueError("Select a foreign language with a matching installed OCR reader.")
        elif not PRIORITY_OCR.intersection(selected) or any(code not in PRIORITY_OCR | {"eng"} for code in selected):
            raise ValueError("Choose a specific source language to read this OCR language.")
        rect = self.validate_region(region)
        full_display = rect.get("monitor") == "primary" or rect.get("full_display",False) or "window" in rect
        psm = page_segmentation_mode(language, full_display)
        available = set(self.local_languages())
        local_ready = set(selected).issubset(available)
        native = None if executable else self._native_engine()
        command = ""
        tag = ""
        if extended and not executable and (native is None or not local_ready):
            packs = self.windows.packs()
            if language not in self.external_languages():
                tag = packs.get(language, "")
                if not tag and language in LATIN_FALLBACKS:
                    tag = packs.get("eng", "")
        if not tag and (native is None or not local_ready):
            try:
                command = self.find_tesseract(executable)
            except RuntimeError:
                if native is not None:
                    missing = set(selected) - set(self.local_languages())
                    raise RuntimeError("Missing OCR files: " + ", ".join(sorted(missing))) from None
                self.resolve_engine(executable)
                raise
            if not local_ready:
                available = set(self.external_languages(command))
                missing = set(selected) - available
                if missing:
                    raise RuntimeError("Missing OCR languages in the selected engine: " + ", ".join(sorted(missing)))
        try:
            image = _frame if _frame is not None else self._capture(rect, exclude_windows) if exclude_windows else self._capture(rect)
        except OSError as exc:
            raise ScreenCaptureUnavailable("Windows could not capture this display. Reconnect the display and try again.") from exc
        from screen_geometry import LocatedText, capture_map, line_regions, union
        from screen_tracking import sample_frame
        capture_map(image, rect)
        cover_frame = image
        frame_info = image.info if isinstance(getattr(image, "info", None), dict) else {}
        capture_info = dict(frame_info.get("capture_info", {}))
        raw_reads = []
        rgb_source = frame_info.get("glyph_source")
        signature_frame = rgb_source[0] if rgb_source is not None else image
        # Skip both OCR engines on unchanged pixels. Store only a digest and
        # the filtered result. Temporary image objects remain confined to a frame.
        geometry = image.info.get("desktop_map") if isinstance(getattr(image, "info", None), dict) else None
        signature = (source, language, command, tag, local_ready, frozenset(available), psm, tuple(sorted(rect.items())), tuple(exclude_windows),
                     image.size, geometry,
                       hashlib.blake2b(signature_frame.tobytes(), digest_size=16).digest())
        if (self._last_frame is not None and self._last_frame[0] == signature
                and time.monotonic() < self._last_frame[2]):
            cached = sample_frame(self._last_frame[1], rgb_source, tracking)
            cached.capture_info = capture_info
            return cached
        def read(frame, codes, mode, timeout, shared=None):
            if command:
                try:
                    value = self._recognize_cli(command,frame,codes,mode,local_ready,timeout)
                    if codes == language and value and len(raw_reads) < 8:
                        raw_reads.append(value[0][:2000])
                    return value
                except subprocess.TimeoutExpired:
                    return None
            ctx = nullcontext(shared) if shared is not None else self._reader(native, codes, mode, codes == language)
            with ctx as api:
                api.SetImage(frame)
                if not api.Recognize(timeout=round(timeout*1000)):
                    return None
                text=api.GetUTF8Text().strip()
                if codes == language and text and len(raw_reads) < 8:
                    raw_reads.append(text[:2000])
                return text, api.GetTSVText(0) if extended or has_target_script(text) else ""

        def read_row(frame, budget, shared=None):
            deadline = time.monotonic() + budget
            row = read(frame,language,7,budget,shared)
            if row and 'kor' in selected and len(selected) > 1 and uncertain_korean_row(row[1]):
                remaining = min(1.5, deadline - time.monotonic())
                if remaining > 0.08:
                    korean = read(frame,'kor',7,remaining)
                    if korean and prefer_korean_row(row[1], korean[1]):
                        return korean
            return row

        vertical_text = ''
        vertical_positions = []
        horizontal_regions = []
        partial_vertical = False
        partial_desktop = False
        def finish(text, retry=None):
            regions = horizontal_regions + [(value, [(0,len(value),box)] if box else [])
                                            for value, box in vertical_positions]
            text = LocatedText(text, regions)
            text.capture_info = capture_info
            text.raw_ocr = "\n".join(dict.fromkeys(raw_reads))[:4000]
            if extended:
                text.verified_source = source
            if regions and rgb_source is not None:
                from glyph_cover import collect_covers
                text.glyph_covers = collect_covers(cover_frame, text)
            expires = retry if retry is not None else self.english_guard.retry_after
            now = time.monotonic()
            expires = expires if expires > now else float('inf')
            if partial_vertical:
                expires = min(expires, now + 5)
            if partial_desktop:
                expires = min(expires, now + .75)
            self._last_frame = signature, text, expires
            return sample_frame(text, rgb_source, tracking)

        if extended:
            from ocr_guard import parse_tsv
            if tag:
                words = self.windows.read(image, tag, getattr(self._watch, "windows", None))
                raw_reads.append(" ".join(word.text for word in words)[:4000])
            else:
                primary = read(image, language, psm, 8)
                if primary is None:
                    return finish("", time.monotonic()+3)
                words = parse_tsv(primary[1])
            horizontal_regions = accepted_regions(image, words, source, self.accepts_source_line, self.english_guard)
            return finish("\n".join(line for line, _ in horizontal_regions))

        auto_vertical = psm == 11 and 'jpn' in selected and len(selected) > 1
        explicit_vertical = psm == 5 and full_display
        if (auto_vertical or explicit_vertical) and {'jpn','jpn_vert'} <= available:
            from vertical_layout import read_columns, upright_columns
            columns = upright_columns(image)
            if columns:
                codes = '+'.join(c for c in ('jpn','chi_sim','kor','chi_tra','eng') if c in available)
                image,lines,partial_vertical = read_columns(image,columns,codes,read,self.english_guard,vertical_positions)
                vertical_text = '\n'.join(lines)
                low, high = image.getextrema()
                if explicit_vertical or low == high:
                    return finish(vertical_text)
            elif explicit_vertical:
                from scene_text import _textured
                if _textured(image):
                    return finish('')

        bands = []
        scene_bands = None
        if psm in (6, 11):
            from scene_text import confirmed_scene_row, textured_rows
            scene_bands = textured_rows(image, self.english_guard.detect)
            if scene_bands == []:
                return finish(vertical_text)
        if scene_bands is not None or psm == 11 or (psm == 6 and len(selected) > 1):
            bands = scene_bands if scene_bands is not None else plain_horizontal_rows(image)
            if len(bands) == 1:
                image, psm = bands[0], 7

        if len(bands) > 1:
            # All physical rows use the same bounded recognizer. This avoids
            # splitting a Korean or Japanese subtitle into unrelated phrases
            # while keeping unrelated English menu rows independently vetoable.
            limit = time.monotonic() + 8
            passes = []
            ctx = nullcontext(None) if command else self._reader(native, language, 7, True)
            with ctx as api:
                for band in bands:
                    remaining = limit - time.monotonic()
                    if remaining <= 0.05:
                        break
                    row = read_row(band,min(remaining,3),api)
                    if scene_bands is not None:
                        row = confirmed_scene_row(row)
                    if row is not None:
                        passes.append(row)
                    else:
                        break
            if len(passes) == len(bands):
                image,raw,tsv = combine_row_results(bands,passes)
                primary,psm = (raw,tsv),6
            else:
                primary = None
        else:
            primary = read_row(image,8) if psm == 7 else read(image,language,psm,8)
            if scene_bands is not None:
                primary = confirmed_scene_row(primary)
        if primary is None:
            return finish(vertical_text, time.monotonic()+5)
        raw,tsv = primary
        if psm == 6 and "jpn" in selected and overlapping_text_lines(tsv):
            candidate=read(image,language,13,2.4)
            if candidate and prefer_single_line(raw,tsv,*candidate):
                raw,tsv=candidate
        elif psm == 11 and has_target_script(raw):
            crop=single_foreign_band(image,tsv)
            if crop is not None:
                candidate=read_row(crop,2.4)
                if candidate and plausible_band_repair(raw,*candidate):
                    raw,tsv=candidate
                    image,psm=crop,7
        label = None
        if (not full_display and not bands and scene_bands is None and psm == 6
                and {"chi_tra", "chi_sim"}.intersection(selected) and has_target_script(raw)):
            from chinese_label import confirm_label
            label = confirm_label(image, (raw, tsv), language, read)
        observations = observe_english(self.english_guard,image,tsv) if has_target_script(raw) else []
        if label is not None and not observations:
            # Retain the original frame's English veto before testing the
            # independently confirmed label in its tighter coordinate system.
            image, (raw, tsv) = label
            psm = 7
            observations = observe_english(self.english_guard, image, tsv)
        if 'kor' in selected and len(selected) > 1 and observations:
            from ocr_guard import verify_hangul_suffixes
            observations = verify_hangul_suffixes(image,raw,tsv,observations,read)
        positions = []
        # A language selection narrows the recognizer; it is not evidence that
        # toolbar strokes or English UI are foreign text. Keep full-scene proof
        # for both Auto and selected CJK, while explicit crops retain label mode.
        if full_display:
            result = filter_words(raw, tsv, observations, image, positions, desktop_auto=True)
        else:
            result = filter_words(raw, tsv, observations, image, positions)
        if ("jpn_vert" in selected and result and weak_foreign_line(result) and
                image.width > 1.25*image.height and len(plain_horizontal_rows(image)) >= 2):
            # A few guessed kana from a page made entirely of horizontal rows
            # are not evidence of a vertical Japanese caption.
            result = ""
        if full_display and result:
            if self._desktop_proof_state is None or self._desktop_proof_state[0] != signature:
                self._desktop_proof_state = (signature, {})
            proof_state = self._desktop_proof_state[1]
            anchors = confirm_desktop_labels(cover_frame, positions, language, read, state=proof_state,
                                            include_long=scene_bands is not None)
            partial_desktop = not proof_state["complete"]
            if scene_bands is not None:
                # Prepared scenery rows can turn repeated fabric strokes into
                # fluent-looking text. Require the original pixels to reproduce
                # each longer source row before it can become a translation.
                from screen_geometry import union
                proven = {(anchor.text, tuple(anchor.box)) for anchor in anchors}
                positions[:] = [(line, spans) for line, spans in positions
                                if sum(has_target_script(ch) for ch in line) <= 2 or
                                (spans and (line, tuple(union([box for _, _, box in spans]))) in proven)]
                located = {line for line, _ in positions}
                result = "\n".join(line for line in result.splitlines() if line in located)
            result = filter_desktop_fragments(result, positions, anchors)
        local_short = {line for line in result.splitlines() if full_display
                       and sum(has_target_script(ch) for ch in line) <= 2}
        weak = {line for line in result.splitlines() if weak_foreign_line(line) and line not in local_short}
        if result and ((observations is None and any(line not in local_short for line in result.splitlines())) or weak):
            # Standalone CJK models can force plausible Korean/Japanese output
            # from English. A differently ordered multilingual read independently
            # checks for foreign glyphs when Windows' English OCR is unavailable.
            order = [code for code in ("jpn","chi_sim","kor","chi_tra") if code in available]
            if len(order) >= 2:
                if "+".join(order) == language:
                    order = order[1:] + order[:1]
                check_language = "+".join(order)
                verifier_image = vertical_verifier_image(image) if "jpn_vert" in selected else image
                # Sparse page layout can ignore a genuine standalone sign
                # such as 口 that both recognizers read correctly as one line.
                tight_label = (len(result.strip()) <= 2 and
                               image.width * image.height <= 100000 and image.width <= 3*image.height)
                verify_psm = 7 if "jpn_vert" in selected or psm == 7 or tight_label else 11
                checked = read(verifier_image,check_language,verify_psm,5) if verifier_image is not None else None
                alternate = checked[0] if checked else ""
                result = "\n".join(line for line in result.splitlines()
                                   if line in local_short or (observations is not None and line not in weak) or
                                   corroborate_lines(line, alternate))
        accepted_lines = set(result.splitlines())
        for line, words in positions:
            if line not in accepted_lines:
                continue
            for fragment, spans in line_regions(line, words) if words else [(line, [])]:
                if "jpn_vert" in selected:
                    joined = join_vertical_glyphs(fragment)
                    if joined != fragment and spans:
                        spans = [(0,len(joined),union([span[2] for span in spans]))]
                    fragment = joined
                horizontal_regions.append((fragment, spans))
        if "jpn_vert" in selected:
            result = join_vertical_glyphs(result)
        return finish('\n'.join(part for part in (result,vertical_text) if part))

    def _recognize_cli(self, executable, image, language, psm, local_ready, timeout):
        # Use a pipe so a capture never becomes a temporary screenshot on disk.
        command = [executable, "stdin", "stdout", "-l", language, "--psm", str(psm)]
        if local_ready:
            command += ["--tessdata-dir", self.native_data_path]
        # Set the variable directly. The checked model directory contains no
        # external Tesseract "configs/tsv" file.
        command += ["-c", "tessedit_create_tsv=1"]
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        process = subprocess.run(command, input=encoded.getvalue(), capture_output=True, timeout=timeout,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.returncode:
            raise RuntimeError("The chosen Tesseract executable failed to recognize this screen area.")
        tsv = process.stdout.decode("utf-8", "replace")
        lines = {}
        for row in tsv.splitlines():
            cols = row.split("\t", 11)
            if len(cols) == 12 and cols[0] == "5":
                lines.setdefault(tuple(cols[1:5]), []).append(cols[-1])
        return "\n".join(" ".join(line) for line in lines.values()), tsv

    @staticmethod
    def primary_region(monitors):
        monitors = list(monitors[1:])  # Index zero is the entire virtual desktop.
        primary = next((m for m in monitors if m.get("is_primary")), None)
        if primary is None:
            # Older MSS versions omit the flag. Windows defines the primary
            # monitor's top-left corner as the desktop origin.
            primary = next((m for m in monitors if m["left"] == 0 and m["top"] == 0), None)
        if primary is None:
            raise ScreenCaptureUnavailable("Windows did not report a primary monitor. Reconnect the display or select an area.")
        return ScreenEngine.validate_region({key: primary[key] for key in ("left", "top", "width", "height")})

    @staticmethod
    def _visible_bounds(handles, include_source_windows=True):
        if not handles or os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        boxes = []
        # Caption and practice windows can open after watching starts.
        # Discover marked windows on the dashboard's UI thread each capture.
        handles = list(handles)
        threads = set()
        for handle in handles:
            pid = wintypes.DWORD()
            thread = user32.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(pid))
            if thread and pid.value in (os.getppid(), os.getpid()):
                threads.add(thread)
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def collect(hwnd, _):
            if (user32.GetPropW(wintypes.HWND(hwnd), "LiveTranslate.VrCaption") or
                    user32.GetPropW(wintypes.HWND(hwnd), "LiveTranslate.ReplyPractice") or
                    user32.GetPropW(wintypes.HWND(hwnd), "LiveTranslate.CapturePreview") or
                    include_source_windows and user32.GetPropW(wintypes.HWND(hwnd), "LiveTranslate.SourceCaption")):
                handles.append(hwnd)
            return True
        for thread in threads:
            user32.EnumThreadWindows(thread, collect, 0)
        for handle in dict.fromkeys(handles):
            hwnd = wintypes.HWND(handle)
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in (os.getppid(), os.getpid()):
                continue
            if user32.GetPropW(hwnd, "LiveTranslate.ManualSampleHidden.v1"):
                continue  # The coordinated manual sample temporarily clears this app-owned window.
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                continue
            cloaked = wintypes.DWORD(0)
            if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                continue
            affinity = wintypes.DWORD(0)
            if user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)) and affinity.value == 0x11:
                continue  # The compositor already excludes this window's pixels.
            rect = wintypes.RECT()
            if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    continue
            boxes.append((rect.left, rect.top, rect.right, rect.bottom))
        return boxes

    @staticmethod
    def _mask_bounds(image, rect, bounds):
        fill = (255, 255, 255) if image.mode == "RGB" else 255
        for left, top, right, bottom in bounds:
            box = (max(0, left-rect["left"]), max(0, top-rect["top"]),
                   min(image.width, right-rect["left"]), min(image.height, bottom-rect["top"]))
            if box[2] > box[0] and box[3] > box[1]:
                image.paste(fill, box)

    @staticmethod
    def _masked_percent(rect, bounds):
        """Measure a union, not a sum: overlapping app windows count once."""
        right, bottom = rect["left"] + rect["width"], rect["top"] + rect["height"]
        boxes = [(max(rect["left"], l), max(rect["top"], t), min(right, r), min(bottom, b))
                 for l, t, r, b in bounds]
        boxes = [box for box in boxes if box[0] < box[2] and box[1] < box[3]]
        edges = sorted({edge for box in boxes for edge in (box[0], box[2])})
        area = 0
        for left, edge in zip(edges, edges[1:]):
            intervals = sorted((t, b) for l, t, r, b in boxes if l < edge and r > left)
            end = None
            total = 0
            for top, bottom in intervals:
                if end is None or top > end:
                    total += bottom - top
                    end = bottom
                elif bottom > end:
                    total += bottom - end
                    end = bottom
            area += (edge - left) * total
        return round(100 * area / (rect["width"] * rect["height"]), 1)

    @staticmethod
    def _sample_messages(handles):
        """Locate only our dashboard and send bounded capture-lease messages."""
        if not handles or os.name != "nt":
            return None
        api = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = wintypes.HWND(handles[0])
        pid = wintypes.DWORD()
        if (not api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or pid.value != os.getppid()
                or not api.GetPropW(hwnd, "LiveTranslate.ScreenSample.v1")):
            return None
        send = api.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send.restype = wintypes.LPARAM
        def exchange(message, token):
            result = ctypes.c_size_t()
            # SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT
            return bool(send(hwnd, message, token, os.getpid(), 0x23, 1200, ctypes.byref(result))
                        and result.value == 1)
        return exchange

    @staticmethod
    @contextmanager
    def _sample_lease(handles, manual=False):
        exchange = ScreenEngine._sample_messages(handles)
        if exchange is None:
            yield False
            return
        token = secrets.randbelow(0x7fffffff) + 1
        begin = 0x8243 if manual else 0x8241
        end = 0x8242
        if not exchange(begin, token):
            exchange(end, token)  # A slow UI may have received Begin after the timeout.
            raise ScreenCaptureUnavailable("The caption overlay could not prepare a clean screen frame.")
        completed = False
        try:
            yield True
            completed = True
        finally:
            # Never OCR pixels from a frame whose hide/show lease expired.
            released = exchange(end, token)
            if completed and not released:
                raise ScreenCaptureUnavailable("The display changed while sampling the text. Retry the screen read.")

    @staticmethod
    def _capture(rect, exclude_windows=()):
        # Read once, preview and watching can arrive on different worker threads.
        # Keep each capture lease intact until its frame has been returned.
        with _CAPTURE_LOCK:
            return ScreenEngine._capture_frame(rect, exclude_windows, manual=bool(getattr(_CAPTURE_INTENT, "manual", False)))

    @staticmethod
    def _capture_frame(rect, exclude_windows=(), manual=False):
        if "window" in rect:
            from window_capture import capture_application
            from PIL import ImageOps, Image
            try:
                original, bounds = capture_application(rect)
            except (OSError, RuntimeError) as exc:
                raise ScreenCaptureUnavailable(str(exc)) from exc
            # The client frame contains only the chosen app. Masking dashboard
            # rectangles here would erase genuine target text while it is behind
            # the dashboard on a single monitor.
            image = ImageOps.grayscale(original)
            if image.width < 1200 and image.height < 1000:
                image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
            from screen_geometry import capture_map
            capture_map(image, bounds)
            image.info["glyph_source"] = (original, bounds["left"], bounds["top"])
            image.info["capture_info"] = dict(source="application", width=original.width, height=original.height, masked_percent=0)
            return image
        import mss
        from mss.exception import ScreenShotError
        from PIL import Image, ImageOps
        try:
            with mss.mss() as capture:
                if rect.get("monitor") == "primary":
                    rect = ScreenEngine.primary_region(capture.monitors)
                with ScreenEngine._sample_lease(exclude_windows, manual=manual) as coordinated:
                    # The dashboard guards current and newly-created source labels
                    # until End. An uncoordinated legacy UI still needs its masks.
                    def visible_bounds():
                        if coordinated:
                            return ScreenEngine._visible_bounds(exclude_windows, include_source_windows=False)
                        return ScreenEngine._visible_bounds(exclude_windows)
                    bounds = visible_bounds()
                    covered = ScreenEngine._masked_percent(rect, bounds)
                    if covered >= 95:
                        raise ScreenCaptureUnavailable(
                            "The selected area is covered by a LiveTranslate window. Minimize the dashboard, choose Application window, or use Read once for a clean manual sample.")
                    shot = capture.grab({key: rect[key] for key in ("left", "top", "width", "height")})
                    if exclude_windows:
                        bounds.extend(visible_bounds())
                original = Image.frombytes("RGB", shot.size, shot.rgb)
        except ScreenShotError as exc:
            raise ScreenCaptureUnavailable("Screen capture is temporarily unavailable. Check the display or switch to the interactive desktop.") from exc
        ScreenEngine._mask_bounds(original, rect, bounds)
        image = ImageOps.grayscale(original)
        if image.width < 1200 and image.height < 1000:
            image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
        from screen_geometry import capture_map
        capture_map(image, rect)
        image.info["glyph_source"] = (original, rect["left"], rect["top"])
        image.info["capture_info"] = dict(source="display", width=original.width, height=original.height,
                                           masked_percent=ScreenEngine._masked_percent(rect, bounds), manual=manual)
        return image

    def preview(self, region, exclude_windows=(), language=None, executable="", source="auto"):
        """Explicit, bounded in-memory view of precisely the chosen OCR source."""
        import base64
        from PIL import Image
        rect = self.validate_region(region)
        if (not isinstance(exclude_windows, (list, tuple)) or len(exclude_windows) > 16
                or any(type(handle) is not int or not 0 < handle < 2**64 for handle in exclude_windows)):
            raise ValueError("Invalid window exclusions for capture preview.")
        with self.manual_capture():
            image = self._capture(rect, exclude_windows)
        original = image.info.get("glyph_source", (image,))[0]
        width, height = original.size
        thumb = original.convert("RGB")
        thumb.thumbnail((960, 540), Image.Resampling.LANCZOS)
        data = io.BytesIO()
        thumb.save(data, format="JPEG", quality=80)
        details = dict(image.info.get("capture_info", {}))
        if language is not None:
            try:
                observed = self.recognize(rect, language, executable, source=source, _frame=image)
                details.update(raw_ocr=getattr(observed, "raw_ocr", ""), accepted_ocr=str(observed)[:4000],
                               ocr_language=language, selected_language=source)
            except (OSError, RuntimeError, ValueError) as exc:
                details["recognition_error"] = str(exc)[:1000]
        return dict(image=base64.b64encode(data.getvalue()).decode("ascii"), width=width, height=height,
                    source="application" if "window" in rect else "display", diagnostics=details)
