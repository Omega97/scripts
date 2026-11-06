"""Hiragana, katakana, kanji, and phrase content for the local app.

Kana are generated from the gojuon, dakuten, and yoon tables so the deck stays
complete. Kanji and phrases are the vendored OpenJLPT N5–N3 deck in deck.json
(CC BY-SA 4.0, https://github.com/evanclan/OpenJLPT).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_RUBY = re.compile(r"\{([^{}]+)\}")

# vowel, or a special marker handled by the row itself
_VOWELS = ("a", "i", "u", "e", "o")

# Basic rows: key, hiragana glyphs, katakana glyphs.
_BASIC = [
    ("a", list("あいうえお"), list("アイウエオ"), {}),
    ("k", list("かきくけこ"), list("カキクケコ"), {}),
    ("s", list("さしすせそ"), list("サシスセソ"), {"i": ("shi", ["shi", "si"])}),
    ("t", list("たちつてと"), list("タチツテト"), {"i": ("chi", ["chi", "ti"]), "u": ("tsu", ["tsu", "tu"])}),
    ("n", list("なにぬねの"), list("ナニヌネノ"), {}),
    ("h", list("はひふへほ"), list("ハヒフヘホ"), {"u": ("fu", ["fu", "hu"])}),
    ("m", list("まみむめも"), list("マミムメモ"), {}),
    ("y", list("やゆよ"), list("ヤユヨ"), {"_vowels": ("a", "u", "o")}),
    ("r", list("らりるれろ"), list("ラリルレロ"), {}),
    ("w", ["わ", "を"], ["ワ", "ヲ"], {"a": ("wa", ["wa"]), "o": ("wo", ["wo", "o"]), "_vowels": ("a", "o")}),
]

_DAKU = [
    ("g", list("がぎぐげご"), list("ガギグゲゴ"), {}),
    ("z", list("ざじずぜぞ"), list("ザジズゼゾ"), {"i": ("ji", ["ji", "zi"]), "u": ("zu", ["zu", "du"])}),
    ("d", list("だぢづでど"), list("ダヂヅデド"), {"i": ("di", ["di", "ji", "dzi"]), "u": ("du", ["du", "zu"])}),
    ("b", list("ばびぶべぼ"), list("バビブベボ"), {}),
    ("p", list("ぱぴぷぺぽ"), list("パピプペポ"), {}),
]

# Yoon glyphs are stored as pairs (きゃ is two code points).
_YOON = [
    ("ky", ["きゃ", "きゅ", "きょ"], ["キャ", "キュ", "キョ"], {}),
    ("sh", ["しゃ", "しゅ", "しょ"], ["シャ", "シュ", "ショ"], {
        "a": ("sha", ["sha", "sya", "sia"]),
        "u": ("shu", ["shu", "syu", "siu"]),
        "o": ("sho", ["sho", "syo", "sio"]),
    }),
    ("ch", ["ちゃ", "ちゅ", "ちょ"], ["チャ", "チュ", "チョ"], {
        "a": ("cha", ["cha", "tya", "tia"]),
        "u": ("chu", ["chu", "tyu", "tiu"]),
        "o": ("cho", ["cho", "tyo", "tio"]),
    }),
    ("ny", ["にゃ", "にゅ", "にょ"], ["ニャ", "ニュ", "ニョ"], {}),
    ("hy", ["ひゃ", "ひゅ", "ひょ"], ["ヒャ", "ヒュ", "ヒョ"], {}),
    ("my", ["みゃ", "みゅ", "みょ"], ["ミャ", "ミュ", "ミョ"], {}),
    ("ry", ["りゃ", "りゅ", "りょ"], ["リャ", "リュ", "リョ"], {}),
    ("gy", ["ぎゃ", "ぎゅ", "ぎょ"], ["ギャ", "ギュ", "ギョ"], {}),
    ("j", ["じゃ", "じゅ", "じょ"], ["ジャ", "ジュ", "ジョ"], {
        "a": ("ja", ["ja", "jya", "zya"]),
        "u": ("ju", ["ju", "jyu", "zyu"]),
        "o": ("jo", ["jo", "jyo", "zyo"]),
    }),
    ("by", ["びゃ", "びゅ", "びょ"], ["ビャ", "ビュ", "ビョ"], {}),
    ("py", ["ぴゃ", "ぴゅ", "ぴょ"], ["ピャ", "ピュ", "ピョ"], {}),
]


def parse_ruby(sentence: str) -> list[dict]:
    """Split `{漢字|ふりがな}` tokens. Extra pipes are joined into the reading."""
    parts: list[dict] = []
    cursor = 0
    for match in _RUBY.finditer(sentence):
        if match.start() > cursor:
            parts.append({"text": sentence[cursor:match.start()]})
        segments = match.group(1).split("|")
        kanji = segments[0]
        reading = "".join(segments[1:]) if len(segments) > 1 else ""
        parts.append({"kanji": kanji, "reading": reading})
        cursor = match.end()
    if cursor < len(sentence):
        parts.append({"text": sentence[cursor:]})
    return parts


def sentence_clean(sentence: str) -> str:
    chunks = []
    for part in parse_ruby(sentence):
        chunks.append(part.get("text") or part.get("kanji") or "")
    return "".join(chunks)


def _kana_item(category: str, glyph: str, canonical: str, variants: list[str], group: str, slug: str) -> dict:
    prefix = "h" if category == "HIRAGANA" else "k"
    unique = list(dict.fromkeys(variants))
    return {
        "id": f"{prefix}_{slug}",
        "category": category,
        "type": category,
        "kana": glyph,
        "romaji": canonical,
        "romaji_variants": unique,
        "group": group,
        "jlpt_level": 5,
    }


def _expand_row(key: str, hira: list[str], kata: list[str], overrides: dict) -> list[dict]:
    vowels = overrides.get("_vowels", _VOWELS)
    if len(hira) != len(vowels) or len(kata) != len(vowels):
        raise ValueError(f"row {key} has {len(hira)} glyphs for vowels {vowels}")
    items = []
    for vowel, h_glyph, k_glyph in zip(vowels, hira, kata):
        if vowel in overrides:
            canonical, variants = overrides[vowel]
            slug = canonical
        else:
            canonical = f"{key}{vowel}" if key not in {"a"} else vowel
            if key == "a":
                canonical = vowel
            variants = [canonical]
            slug = canonical
        # Disambiguate slugs that would collide (di/du already unique on purpose).
        items.append(_kana_item("HIRAGANA", h_glyph, canonical, variants, key, slug))
        items.append(_kana_item("KATAKANA", k_glyph, canonical, variants, key, slug))
    return items


def _build_kana() -> list[dict]:
    items: list[dict] = []
    for row in _BASIC + _DAKU:
        items.extend(_expand_row(*row))
    yoon_vowels = ("a", "u", "o")
    for key, hira, kata, overrides in _YOON:
        spec = dict(overrides)
        spec["_vowels"] = yoon_vowels
        items.extend(_expand_row(key, hira, kata, spec))
    items.append(_kana_item("HIRAGANA", "っ", "ltu", ["ltu", "xtu", "ltsu", "xtsu"], "sokuon", "sokuon"))
    items.append(_kana_item("KATAKANA", "ッ", "ltu", ["ltu", "xtu", "ltsu", "xtsu"], "sokuon", "sokuon"))
    items.append(_kana_item("HIRAGANA", "ん", "n", ["n", "nn"], "n", "n"))
    items.append(_kana_item("KATAKANA", "ン", "n", ["n", "nn"], "n", "n"))
    items.append(_kana_item("KATAKANA", "ー", "-", ["-", "chouon", "ー"], "chouon", "chouon"))
    return items


def _load_study_deck() -> tuple[list[dict], list[dict], str]:
    """Kanji and phrases saved from OpenJLPT (CC BY-SA 4.0)."""
    path = Path(__file__).resolve().parent / "deck.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["kanji"]), list(data["phrases"]), str(data.get("source") or "")


def norm_en(text: str) -> str:
    cleaned = " ".join((text or "").replace("’", "'").split()).casefold()
    while cleaned and cleaned[-1] in ".!?。":
        cleaned = cleaned[:-1].strip()
    return cleaned


def _meaning_set(values) -> set[str]:
    return {str(value).casefold() for value in values or [] if str(value).strip()}


def displays_fit(displayed, meanings) -> bool:
    """True when every meaning shown to the learner is a meaning of the other item."""
    shown = _meaning_set(displayed)
    have = _meaning_set(meanings)
    return bool(shown) and shown <= have


def shares_any(left, right) -> bool:
    return bool(_meaning_set(left) & _meaning_set(right))


def choice_valid(category: str, mode: str, item: dict, text: str) -> bool:
    """Whether this option is a real answer, not only the one stored as primary."""
    text = text or ""
    if category in {"HIRAGANA", "KATAKANA"}:
        return text == item.get("kana")
    if category == "KANJI" and mode == "EASY":
        if text == item.get("gloss"):
            return True
        for owner in CONTENT["gloss_owners"].get(text, []):
            if displays_fit(owner.get("displayed"), item.get("meanings")):
                return True
        return False
    if category == "KANJI" and mode == "MEDIUM":
        other = CONTENT["kanji_by_char"].get(text)
        if other is None:
            return text == item.get("kanji")
        return displays_fit(item.get("displayed"), other.get("meanings"))
    if category == "PHRASE" and mode == "HARD":
        allowed = CONTENT["targets_by_skeleton"].get(item.get("skeleton"), set())
        return text in allowed
    if category == "PHRASE" and mode == "LISTENING":
        allowed = CONTENT["english_by_sentence"].get(item.get("sentence_clean"), set())
        return norm_en(text) in allowed
    return False


def kanji_hard_valid(item: dict, typed: str) -> bool:
    from srs import normalize_kanji

    character = normalize_kanji(typed or "")
    if not character:
        return False
    if character == item.get("kanji"):
        return True
    other = CONTENT["kanji_by_char"].get(character)
    if other is None:
        return False
    readings = set(other.get("readings") or [])
    readings.update(other.get("kunyomi") or [])
    readings.update(other.get("onyomi") or [])
    if item.get("audio") not in readings:
        return False
    return displays_fit(item.get("displayed"), other.get("meanings"))


def hard_alternates(item: dict) -> list[str]:
    found = []
    for other in CONTENT["kanji"]:
        if other["kanji"] == item["kanji"]:
            continue
        if kanji_hard_valid(item, other["kanji"]):
            found.append(other["kanji"])
    return found



INSIGHTS = [
    {"id": "fall", "jp": "七転び八起き", "romaji": "Nana korobi ya oki", "en": "Fall seven times, stand up eight.", "when": "wrong"},
    {"id": "monkey", "jp": "猿も木から落ちる", "romaji": "Saru mo ki kara ochiru", "en": "Even monkeys fall from trees.", "when": "easy_miss"},
    {"id": "continue", "jp": "継続は力なり", "romaji": "Keizoku wa chikara nari", "en": "Continuity is power.", "when": "streak"},
    {"id": "stone", "jp": "石の上にも三年", "romaji": "Ishi no ue ni mo sannen", "en": "Three years on a stone.", "when": "long"},
    {"id": "dust", "jp": "塵も積もれば山となる", "romaji": "Chiri mo tsumoreba yama to naru", "en": "Dust piled up becomes a mountain.", "when": "progress"},
    {"id": "doing", "jp": "習うより慣れよ", "romaji": "Narau yori nareyo", "en": "Learn by doing.", "when": "start"},
]

SEASONS = {
    "spring": {"months": (3, 4, 5), "jp": "花より団子", "romaji": "Hana yori dango", "en": "Dumplings over flowers — substance over style.", "particle": "sakura"},
    "summer": {"months": (6, 7, 8), "jp": "夏バテ注意", "romaji": "Natsubate chuui", "en": "Take care in the summer heat.", "particle": "firefly"},
    "autumn": {"months": (9, 10, 11), "jp": "読書の秋", "romaji": "Dokusho no aki", "en": "Autumn — the season for reading.", "particle": "momiji"},
    "winter": {"months": (12, 1, 2), "jp": "冬来りなば春遠からじ", "romaji": "Fuyu kitarinaba haru tookaraji", "en": "If winter comes, can spring be far behind?", "particle": "snow"},
}

ACHIEVEMENTS = [
    {"id": "first_step", "seal": "一歩", "name": "First Step", "detail": "Complete a session."},
    {"id": "week_streak", "seal": "一週間", "name": "7-Day Streak", "detail": "Practice seven days in a row."},
    {"id": "century", "seal": "百", "name": "Century", "detail": "Answer 100 problems correctly."},
    {"id": "thousand", "seal": "千", "name": "Thousand", "detail": "Answer 1,000 problems correctly."},
    {"id": "kana_master", "seal": "仮名達人", "name": "Kana Master", "detail": "Answer every hiragana and katakana correctly."},
    {"id": "kanji_100", "seal": "百漢字", "name": "100 Kanji", "detail": "Learn 100 different kanji."},
    {"id": "perseverance", "seal": "七転八起", "name": "Perseverance", "detail": "Come back after a break of three days or more."},
]

MODES = {
    "HIRAGANA": ("EASY", "HARD"),
    "KATAKANA": ("EASY", "HARD"),
    "KANJI": ("EASY", "MEDIUM", "HARD"),
    "PHRASE": ("HARD", "LISTENING"),
}

MODE_LABELS = {
    ("HIRAGANA", "EASY"): "Easy — romaji to kana",
    ("HIRAGANA", "HARD"): "Hard — type the romaji",
    ("KATAKANA", "EASY"): "Easy — romaji to kana",
    ("KATAKANA", "HARD"): "Hard — type the romaji",
    ("KANJI", "EASY"): "Easy — kanji to meaning",
    ("KANJI", "MEDIUM"): "Medium — meaning to kanji",
    ("KANJI", "HARD"): "Hard — listen and type the kanji",
    ("PHRASE", "HARD"): "Fill the blank",
    ("PHRASE", "LISTENING"): "Listening — pick the meaning",
}


def season_for_month(month: int) -> str:
    for name, info in SEASONS.items():
        if month in info["months"]:
            return name
    return "autumn"


def insight_by_id(insight_id: str) -> dict:
    for item in INSIGHTS:
        if item["id"] == insight_id:
            return item
    return INSIGHTS[0]


def school_year(grade) -> int:
    """Japanese school step for a KANJIDIC grade.

    Grades 1–6 are elementary school. Grade 8 is the rest of the jōyō list,
    taught in junior high, so it sorts as step 7. Anything else sorts last.
    """
    if grade in {1, 2, 3, 4, 5, 6}:
        return int(grade)
    if grade == 8:
        return 7
    return 8


def _assign_difficulty(kanji: list[dict], phrases: list[dict]) -> None:
    """Write difficulty in [0, 1]. Lower is easier. Order is the whole rank.

    Kanji: school year first, stroke count second.
    Phrases: JLPT level of the sentence first (N5, then N4, then N3), then the
    hardest school year among kanji in the blank, then the sentence length,
    then the blank length. Most fill-in items are N3, so level has to lead
    or a new learner is dropped into long examples.
    """
    ordered = sorted(
        kanji,
        key=lambda item: (school_year(item.get("school_grade")), int(item.get("stroke_count") or 0), item["kanji"]),
    )
    last = max(1, len(ordered) - 1)
    by_char = {}
    for index, item in enumerate(ordered):
        item["difficulty"] = index / last
        by_char[item["kanji"]] = item

    def phrase_key(item: dict) -> tuple:
        years = [school_year(by_char[char]["school_grade"]) for char in item["target"] if char in by_char]
        year = max(years) if years else 9
        level = int(item.get("jlpt_level") or 3)
        return (6 - level, year, len(item.get("sentence_clean") or ""), len(item.get("target") or ""), item["id"])

    ranked = sorted(phrases, key=phrase_key)
    last_phrase = max(1, len(ranked) - 1)
    for index, item in enumerate(ranked):
        item["difficulty"] = index / last_phrase


_PLACEHOLDER_READING = re.compile(r"^#\d+$")


def _repair_placeholder_readings(kanji: list[dict], phrases: list[dict]) -> None:
    """OpenJLPT sometimes stores a JMdict id (`#1392580`) where the kana belongs."""
    by_char = {item["kanji"]: item for item in kanji}

    def kana_for(token: str, reading: str) -> str:
        if not _PLACEHOLDER_READING.match(reading or ""):
            return reading or ""
        if len(token) == 1 and token in by_char:
            audio = str(by_char[token].get("audio") or "").strip("-")
            if audio and not _PLACEHOLDER_READING.match(audio):
                return audio
        return ""

    replacements: dict[str, str] = {}
    for phrase in phrases:
        for part in phrase.get("ruby") or []:
            reading = part.get("reading") or ""
            if _PLACEHOLDER_READING.match(reading):
                fixed = kana_for(part.get("kanji") or "", reading)
                replacements.setdefault(reading, fixed)
                part["reading"] = fixed
        if phrase.get("sentence_jp"):
            phrase["sentence_jp"] = _swap_placeholders(phrase["sentence_jp"], replacements)
    for item in kanji:
        for field in ("example_kana", "example_jp"):
            if item.get(field):
                item[field] = _swap_placeholders(item[field], replacements)


def _swap_placeholders(text: str, replacements: dict[str, str]) -> str:
    for placeholder, reading in replacements.items():
        if placeholder in text:
            text = text.replace(placeholder, reading)
    return text


def build_content() -> dict:
    kana = _build_kana()
    kanji, phrases, source = _load_study_deck()
    _repair_placeholder_readings(kanji, phrases)
    _assign_difficulty(kanji, phrases)
    by_char = {item["kanji"]: item for item in kanji}
    by_id = {}
    for item in kana + kanji + phrases:
        if item["id"] in by_id:
            raise ValueError(f"duplicate id {item['id']}")
        by_id[item["id"]] = item
    gloss_owners: dict[str, list[dict]] = {}
    for item in kanji:
        gloss_owners.setdefault(item["gloss"], []).append(item)
    targets_by_skeleton: dict[str, set[str]] = {}
    english_by_sentence: dict[str, set[str]] = {}
    english_forms: dict[str, list[str]] = {}
    for phrase in phrases:
        targets_by_skeleton.setdefault(phrase["skeleton"], set()).add(phrase["target"])
        cleaned = phrase["sentence_clean"]
        english_by_sentence.setdefault(cleaned, set()).add(norm_en(phrase["meaning_en"]))
        forms = english_forms.setdefault(cleaned, [])
        if phrase["meaning_en"] not in forms:
            forms.append(phrase["meaning_en"])
    content = {
        "kana": kana,
        "kanji": kanji,
        "phrases": phrases,
        "by_id": by_id,
        "kanji_by_char": by_char,
        "gloss_owners": gloss_owners,
        "targets_by_skeleton": targets_by_skeleton,
        "english_by_sentence": english_by_sentence,
        "english_forms": english_forms,
        "source": source,
    }
    validate_content(content)
    return content


def validate_content(content: dict) -> None:
    errors: list[str] = []
    seen_glyph: dict[tuple[str, str], str] = {}
    seen_romaji: dict[tuple[str, str], str] = {}
    for item in content["kana"]:
        key = (item["category"], item["kana"])
        if key in seen_glyph:
            errors.append(f"duplicate kana {key}")
        seen_glyph[key] = item["id"]
        romaji_key = (item["category"], item["romaji"])
        if romaji_key in seen_romaji:
            errors.append(f"ambiguous easy prompt {romaji_key} ({item['id']} and {seen_romaji[romaji_key]})")
        seen_romaji[romaji_key] = item["id"]
        if item["romaji"] not in item["romaji_variants"]:
            errors.append(f"{item['id']} canonical not in variants")
    chars = [item["kanji"] for item in content["kanji"]]
    if len(chars) != len(set(chars)):
        errors.append("duplicate kanji")
    for item in content["kanji"]:
        if not item.get("gloss") or not item.get("displayed"):
            errors.append(f"{item['id']} missing gloss")
    for item in content["phrases"]:
        ruby = item.get("ruby") or []
        blank_at = item.get("blank_at")
        if not isinstance(blank_at, int) or not (0 <= blank_at < len(ruby)):
            errors.append(f"{item['id']} blank is out of range")
        elif ruby[blank_at].get("kanji") != item["target"]:
            errors.append(f"{item['id']} blank does not match {item['target']!r}")
        if item["target"] in item["distractors"] or len(item["distractors"]) != 3:
            errors.append(f"{item['id']} distractors are invalid")
        allowed = content["targets_by_skeleton"].get(item["skeleton"], set())
        if any(choice in allowed for choice in item["distractors"]):
            errors.append(f"{item['id']} distractor is another valid fill")
        if not item["sentence_clean"]:
            errors.append(f"{item['id']} empty sentence")
    hira = [item for item in content["kana"] if item["category"] == "HIRAGANA"]
    kata = [item for item in content["kana"] if item["category"] == "KATAKANA"]
    if len(hira) != 105:
        errors.append(f"expected 105 hiragana, got {len(hira)}")
    if len(kata) != 106:
        errors.append(f"expected 106 katakana, got {len(kata)}")
    if len(content["kanji"]) < 600:
        errors.append(f"expected at least 600 kanji, got {len(content['kanji'])}")
    if len(content["phrases"]) < 1000:
        errors.append(f"expected at least 1000 phrases, got {len(content['phrases'])}")
    if errors:
        raise ValueError("; ".join(errors[:12]))


CONTENT = None
_DECK_PATH = Path(__file__).resolve().parent / "deck.json"


def deck_file_ready(path: Path | None = None) -> bool:
    """True when a deck file has kanji and phrase lists."""
    target = Path(path or _DECK_PATH)
    if not target.is_file() or target.stat().st_size == 0:
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    kanji = data.get("kanji")
    phrases = data.get("phrases")
    return isinstance(kanji, list) and bool(kanji) and isinstance(phrases, list) and bool(phrases)


def activate() -> dict:
    """Load deck.json into CONTENT. Startup calls this after a download."""
    global CONTENT
    CONTENT = build_content()
    return CONTENT


if _DECK_PATH.is_file() and _DECK_PATH.stat().st_size > 0:
    try:
        activate()
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        CONTENT = None


def items_for(category: str) -> list[dict]:
    if category in {"HIRAGANA", "KATAKANA"}:
        return [item for item in CONTENT["kana"] if item["category"] == category]
    if category == "KANJI":
        return list(CONTENT["kanji"])
    if category == "PHRASE":
        return list(CONTENT["phrases"])
    raise KeyError(category)


def compound_note(target: str) -> str:
    bits = []
    for char in target:
        item = CONTENT["kanji_by_char"].get(char)
        if item:
            bits.append(f"{char} {item['meanings'][0]}")
    return " + ".join(bits)
