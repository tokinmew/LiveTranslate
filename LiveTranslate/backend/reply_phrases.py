"""Prepared practice replies for a fresh install. Other wording uses the local model."""
import unicodedata


_JAPANESE = {
    "hello": ("こんにちは。", "Konnichiwa."),
    "thank you": ("ありがとうございます。", "Arigatō gozaimasu."),
    "please say that again": ("もう一度言ってください。", "Mō ichido itte kudasai."),
    "i don't understand": ("わかりません。", "Wakarimasen."),
    "can you speak more slowly": ("もう少しゆっくり話してもらえますか？",
                                  "Mō sukoshi yukkuri hanashite moraemasu ka?"),
}

_KOREAN = {
    "hello": ("안녕하세요.", "Annyeonghaseyo."),
    "thank you": ("감사합니다.", "Gamsahamnida."),
    "please say that again": ("다시 한 번 말해 주세요.", "Dasi han beon malhae juseyo."),
    "i don't understand": ("이해가 안 돼요.", "Ihaega an dwaeyo."),
    "can you speak more slowly": ("조금 더 천천히 말해 주실 수 있나요?",
                                  "Jogeum deo cheoncheonhi malhae jusil su innayo?"),
}

# The two written forms use the same Mandarin reading for each of these phrases.
_MANDARIN = {
    "hello": ("你好。", "你好。", "Nǐ hǎo."),
    "thank you": ("谢谢。", "謝謝。", "Xièxie."),
    "please say that again": ("请再说一遍。", "請再說一遍。", "Qǐng zài shuō yí biàn."),
    "i don't understand": ("我不明白。", "我不明白。", "Wǒ bù míngbai."),
    "can you speak more slowly": ("可以说慢一点吗？", "可以說慢一點嗎？", "Kěyǐ shuō màn yìdiǎn ma?"),
}

# English sound cues are intentionally approximate. Keep the language's reading
# beside them, especially the Mandarin tones and the long vowels in Japanese.
_SOUND_CUES = {
    "ja": {
        "hello": "kohn-nee-chee-wah",
        "thank you": "ah-ree-gah-toh goh-zah-ee-mahss",
        "please say that again": "moh ee-chee-doh eet-teh koo-dah-sah-ee",
        "i don't understand": "wah-kah-ree-mah-sen",
        "can you speak more slowly": "moh soo-koh-shee yook-koo-ree hah-nah-shee-teh moh-rah-eh-mahss kah",
    },
    "ko": {
        "hello": "ahn-nyuhng-hah-seh-yoh",
        "thank you": "gahm-sah-hahm-nee-dah",
        "please say that again": "dah-shee hahn buhn mahl-heh joo-seh-yoh",
        "i don't understand": "ee-heh-gah ahn dweh-yoh",
        "can you speak more slowly": "joh-geum duh chuhn-chuhn-hee mahl-heh joo-shil soo een-nah-yoh",
    },
    "zh": {
        "hello": "nee how",
        "thank you": "shyeh-shyeh",
        "please say that again": "ching dzeye shwoh ee byen",
        "i don't understand": "waw boo ming-bye",
        "can you speak more slowly": "kuh-yee shwoh mahn ee-dyen mah",
    },
}


def lookup(text, target):
    key = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    key = " ".join(key.strip().rstrip(".!?").split())
    if target in ("zh", "zt") and key in _MANDARIN:
        simplified, traditional, reading = _MANDARIN[key]
        translated = simplified if target == "zh" else traditional
        scheme = "Mandarin Pinyin"
        note = "Tone marks show the Mandarin tones."
        if key in ("hello", "can you speak more slowly"):
            note += " When two third tones meet, the first usually rises."
    elif target == "ja" and key in _JAPANESE:
        translated, reading = _JAPANESE[key]
        scheme = "Japanese rōmaji (Hepburn)"
        note = "A bar over a vowel means to hold it longer."
    elif target == "ko" and key in _KOREAN:
        translated, reading = _KOREAN[key]
        scheme = "Korean romanization"
        note = "The spellings eo and eu each represent one Korean vowel."
    else:
        return None
    cue = _SOUND_CUES["zh" if target == "zt" else target][key]
    return {"text": translated, "pronunciation": reading, "pronunciation_scheme": scheme,
            "pronunciation_note": f"Approximate sound: {cue}. {note}"}
