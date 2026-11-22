"""Named source-language profiles shared by setup and capture commands.

Argos uses zt for Traditional Chinese text. Whisper uses zh for Chinese
speech regardless of written script; OCR has its own Tesseract codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from language_catalog import canonical_code, LANGUAGE_NAMES, REGIONS, NLLB_TAGS
from language_routes import ocr_code, speech_code


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    text_language: str
    speech_language: str
    ocr_language: str
    ocr_vertical_language: str = ""

    @property
    def ocr_languages(self) -> tuple[str, ...]:
        return tuple(code for code in (self.ocr_language, self.ocr_vertical_language) if code)


PROFILES = (
    LanguageProfile("zt", "Chinese (Traditional)", "zt", "zh", "chi_tra"),
    LanguageProfile("zh", "Chinese (Simplified)", "zh", "zh", "chi_sim"),
    LanguageProfile("ko", "Korean", "ko", "ko", "kor"),
    LanguageProfile("ja", "Japanese", "ja", "ja", "jpn", "jpn_vert"),
)
_PRIORITY = {profile.code for profile in PROFILES}
ALL_PROFILES = PROFILES + tuple(
    LanguageProfile(code, name, code if code in NLLB_TAGS else "",
                    speech_code(code), ocr_code(code))
    for code, name in LANGUAGE_NAMES.items() if code not in _PRIORITY)
PROFILE_BY_CODE = {profile.code: profile for profile in ALL_PROFILES}


def get_profile(code: str) -> LanguageProfile:
    try:
        return PROFILE_BY_CODE[canonical_code(code)]
    except (KeyError, TypeError):
        raise ValueError("Choose a source from the language list.") from None


def speech_language(code: str) -> str:
    if code == "auto":
        return code
    token = speech_code(code)
    if not token:
        raise ValueError("This source has no matching speech model language. Choose another voice language.")
    return token


def screen_languages(source: str, ocr_language: str = "auto", vertical: bool = False) -> tuple[str, str]:
    """Return explicit text source and matching OCR without script guessing."""
    profile = PROFILE_BY_CODE.get(canonical_code(source))
    if profile is None:
        if vertical:
            raise ValueError("Vertical layout is available with the Japanese profile. Select Japanese first.")
        return source, ocr_language
    if vertical:
        if not profile.ocr_vertical_language:
            raise ValueError("Vertical layout is currently available for Japanese. Select a normal horizontal layout for this profile.")
        return profile.text_language, profile.ocr_vertical_language
    # Explicit advanced choices always win over the suggested profile model.
    if ocr_language not in ("", "auto"):
        return profile.text_language, ocr_language
    return profile.text_language, profile.ocr_language


def profile_status(text_codes, ocr_codes, speech_models, tesseract_ready: bool = False, multilingual_ready=False) -> list[dict]:
    text_codes, ocr_codes, speech_models = set(text_codes), set(ocr_codes), set(speech_models)
    rows = []
    for profile in ALL_PROFILES:
        direct = profile.code in text_codes
        shared = profile.code in NLLB_TAGS and multilingual_ready
        text_ready = bool(direct or shared)
        ocr_ready = bool(profile.ocr_languages) and all(code in ocr_codes for code in profile.ocr_languages)
        speech_ready = bool(profile.speech_language and (
            "large-v3" in speech_models or
            (profile.speech_language != "yue" and {"base", "small", "medium", "tiny", "large-v2", "large-v1"} & speech_models)))
        rows.append({
            "code": profile.code, "name": profile.name,
            "region": REGIONS[profile.code], "text_model": "Argos" if direct else ("NLLB" if shared else ""),
            "text_supported": bool(profile.text_language or direct),
            "screen_supported": bool(profile.ocr_language and (profile.text_language or direct)),
            "speech_supported": bool(profile.speech_language),
            "text_language": profile.code if direct else profile.text_language, "speech_language": profile.speech_language,
            "ocr_language": profile.ocr_language, "ocr_vertical_language": profile.ocr_vertical_language,
            "text_ready": text_ready, "ocr_ready": ocr_ready, "speech_ready": speech_ready,
            "assets_ready": text_ready and ocr_ready and speech_ready,
            "ocr_engine_ready": tesseract_ready,
            "ocr_executable_ready": tesseract_ready,
            "screen_ready": text_ready and ocr_ready and tesseract_ready,
        })
    return rows
