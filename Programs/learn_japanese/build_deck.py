"""Download JLPT kanji and example sentences and write deck.json.

Source: OpenJLPT (CC BY-SA 4.0), https://github.com/evanclan/OpenJLPT
Kanji N5–N3 and vocabulary examples N5–N3.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

_PLACEHOLDER = re.compile(r"^#(\d+)$")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from content import deck_file_ready, parse_ruby, sentence_clean  # noqa: E402

CDN = "https://cdn.jsdelivr.net/gh/evanclan/OpenJLPT@main/data/json/"
LEVELS = ("n5", "n4", "n3")
OUT = HERE / "deck.json"


def fetch(path: str):
    with urllib.request.urlopen(CDN + path, timeout=120) as response:
        return json.load(response)


def kata_to_hira(text: str) -> str:
    chars = []
    for char in text or "":
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(char)
    return "".join(chars)


def reading_stem(reading: str) -> str:
    text = (reading or "").strip().lstrip("-")
    if "." in text:
        text = text.split(".", 1)[0]
    return kata_to_hira(text)


def title_phrase(text: str) -> str:
    return " ".join(part[:1].upper() + part[1:] if part else part for part in text.split(" "))


def merge_word(parts: list[dict], word: str) -> tuple[list[dict], int | None]:
    """Join consecutive ruby tokens that spell the vocabulary word."""
    if not word:
        return parts, None
    for start in range(len(parts)):
        if "kanji" not in parts[start]:
            continue
        acc = ""
        end = start
        while end < len(parts) and "kanji" in parts[end] and word.startswith(acc + parts[end]["kanji"]):
            acc += parts[end]["kanji"]
            end += 1
            if acc == word:
                reading = "".join(parts[index].get("reading") or "" for index in range(start, end))
                merged = parts[:start] + [{"kanji": word, "reading": reading}] + parts[end:]
                return merged, start
    for index, part in enumerate(parts):
        kanji = part.get("kanji") or ""
        if kanji and kanji in word:
            return parts, index
    return parts, None


def ruby_kana(parts: list[dict]) -> str:
    bits = []
    for part in parts:
        if part.get("text"):
            bits.append(part["text"])
        else:
            bits.append(part.get("reading") or part.get("kanji") or "")
    return "".join(bits)


def skeleton_of(parts: list[dict], blank_at: int) -> str:
    bits = []
    for index, part in enumerate(parts):
        if index == blank_at:
            bits.append("□")
        else:
            bits.append(part.get("text") or part.get("kanji") or "")
    return "".join(bits)


def saved_mnemonics(path: Path) -> dict[str, str]:
    """Keep mnemonics already stored in a deck that is about to be rebuilt."""
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    found = {}
    for item in data.get("kanji") or []:
        kanji = item.get("kanji")
        mnemonic = item.get("mnemonic")
        if kanji and mnemonic:
            found[str(kanji)] = str(mnemonic)
    return found


def build_deck(dest: Path | None = None) -> Path:
    """Download OpenJLPT N5–N3 and write deck.json."""
    out = Path(dest or OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    handwritten = saved_mnemonics(out)
    kanji_rows = []
    seen_chars = set()
    for level in LEVELS:
        for row in fetch(f"kanji/{level}.json"):
            char = row["character"]
            if char in seen_chars:
                continue
            seen_chars.add(char)
            kanji_rows.append((level, row))

    phrases = []
    seen_keys = set()
    vocab_rows = []
    jmdict: dict[str, tuple[str, str]] = {}
    for level in LEVELS:
        for word in fetch(f"vocab/{level}.json"):
            vocab_rows.append((level, word))
            entry_id = word.get("jmdict_id")
            if entry_id and word.get("word") and word.get("reading"):
                jmdict[str(entry_id)] = (word["word"], word["reading"])
    kanji_audio = {}
    for _level, row in kanji_rows:
        stem = reading_stem((row.get("kunyomi") or [None])[0] or "") or reading_stem((row.get("onyomi") or [None])[0] or "")
        if stem:
            kanji_audio[row["character"]] = stem

    def resolved_reading(reading: str, token: str) -> str:
        match = _PLACEHOLDER.match(reading or "")
        if not match:
            return reading or ""
        pair = jmdict.get(match.group(1))
        if pair and pair[0] == token:
            return pair[1]
        if len(token) == 1 and token in kanji_audio:
            return kanji_audio[token]
        return ""

    for level, word in vocab_rows:
        jlpt = int(level[1])
        vocab = word.get("word") or ""
        if not any("\u4e00" <= char <= "\u9fff" for char in vocab):
            continue
        for example in word.get("examples") or []:
            furigana = example.get("furigana") or ""
            english = " ".join((example.get("en") or "").split())
            if not furigana or not english or len(english) > 140 or len(english) < 3:
                continue
            parts = parse_ruby(furigana)
            for part in parts:
                if part.get("reading"):
                    part["reading"] = resolved_reading(part["reading"], part.get("kanji") or "")
            parts, blank_at = merge_word(parts, vocab)
            if blank_at is None:
                continue
            target = parts[blank_at].get("kanji") or ""
            if not target:
                continue
            clean = sentence_clean(furigana if blank_at is None else "")
            # Rebuild the annotated sentence from parts so a merged word stays one token.
            sentence = []
            for part in parts:
                if part.get("text"):
                    sentence.append(part["text"])
                else:
                    reading = part.get("reading") or ""
                    sentence.append("{" + part["kanji"] + ("|" + reading if reading else "") + "}")
            sentence_jp = "".join(sentence)
            clean = sentence_clean(sentence_jp)
            if not (4 <= len(clean) <= 48) or target not in clean:
                continue
            skeleton = skeleton_of(parts, blank_at)
            key = skeleton + "\0" + target
            if key in seen_keys:
                continue
            seen_keys.add(key)
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
            phrases.append({
                    "id": f"p_{digest}",
                    "category": "PHRASE",
                    "sentence_jp": sentence_jp,
                    "sentence_clean": clean,
                    "ruby": parts,
                    "target": target,
                    "blank_at": blank_at,
                    "skeleton": skeleton,
                    "meaning_en": english,
                    "audio": clean,
                    "jlpt_level": jlpt,
                    "group": level.upper(),
                    "vocab": vocab,
                })

    by_skeleton: dict[str, set[str]] = {}
    for phrase in phrases:
        by_skeleton.setdefault(phrase["skeleton"], set()).add(phrase["target"])

    rng = random.Random(0)
    pool_by_level: dict[str, list[dict]] = {}
    for phrase in phrases:
        pool_by_level.setdefault(phrase["group"], []).append(phrase)

    usable = []
    for phrase in phrases:
        banned = set(by_skeleton.get(phrase["skeleton"], set()))
        banned.add(phrase["target"])
        same_len = [item["target"] for item in pool_by_level[phrase["group"]] if item["target"] not in banned and len(item["target"]) == len(phrase["target"])]
        any_level = [item["target"] for item in phrases if item["target"] not in banned]
        rng.shuffle(same_len)
        rng.shuffle(any_level)
        distractors = []
        for candidate in same_len + any_level:
            if candidate not in distractors:
                distractors.append(candidate)
            if len(distractors) == 3:
                break
        if len(distractors) < 3:
            continue
        phrase["distractors"] = distractors
        usable.append(phrase)

    kanji_by_char_stub = {row["character"]: row for _level, row in kanji_rows}
    kanji_items = []
    phrase_by_char: dict[str, dict] = {}
    for phrase in usable:
        for char in phrase["target"]:
            phrase_by_char.setdefault(char, phrase)

    for level, row in kanji_rows:
        char = row["character"]
        meanings = [meaning.strip() for meaning in row.get("meanings") or [] if meaning.strip()]
        if not meanings:
            continue
        displayed = meanings[:2]
        kun = [reading_stem(reading) for reading in row.get("kunyomi") or []]
        on = [reading_stem(reading) for reading in row.get("onyomi") or []]
        kun = [reading for reading in kun if reading]
        on = [reading for reading in on if reading]
        audio = next((reading for reading in kun if reading), "") or (on[0] if on else char)
        example = phrase_by_char.get(char)
        jlpt = int(level[1])
        kanji_items.append({
            "id": "kj_" + format(ord(char), "x"),
            "category": "KANJI",
            "kanji": char,
            "group": level.upper(),
            "meanings": meanings,
            "displayed": displayed,
            "gloss": " / ".join(title_phrase(meaning) for meaning in displayed),
            "kunyomi": kun,
            "onyomi": on,
            "jlpt_level": jlpt,
            "stroke_count": int(row.get("strokes") or 0),
            "school_grade": row.get("grade") if isinstance(row.get("grade"), int) else None,
            "radicals": [row["radical"]] if row.get("radical") else [],
            "mnemonic": handwritten.get(char) or (f"Radical {row['radical']}." if row.get("radical") else ""),
            "audio": audio,
            "example_jp": example["sentence_clean"] if example else "",
            "example_kana": ruby_kana(example["ruby"]) if example else "",
            "example_en": example["meaning_en"] if example else "",
            "readings": list(dict.fromkeys(kun + on)),
        })

    # Point phrases at a kanji id when the target's first character is in the deck.
    by_char = {item["kanji"]: item["id"] for item in kanji_items}
    for phrase in usable:
        phrase["target_kanji_id"] = next((by_char[char] for char in phrase["target"] if char in by_char), None)
        phrase.pop("vocab", None)

    ambiguous_clozes = sum(1 for targets in by_skeleton.values() if len(targets) > 1)
    deck = {
        "source": "OpenJLPT CC BY-SA 4.0 — https://github.com/evanclan/OpenJLPT — kanji and Tatoeba examples, JLPT N5–N3",
        "kanji": kanji_items,
        "phrases": usable,
    }
    out.write_text(json.dumps(deck, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"kanji {len(kanji_items)} phrases {len(usable)} ambiguous clozes {ambiguous_clozes} bytes {out.stat().st_size}")
    print("unused kanji rows", len(kanji_rows) - len(kanji_items))
    return out


def ensure_deck(dest: Path | None = None) -> Path | None:
    """Download the OpenJLPT deck when deck.json is missing or unusable."""
    target = Path(dest or OUT)
    if deck_file_ready(target):
        return target
    print(f"Dataset missing. Downloading OpenJLPT N5–N3 into {target}", flush=True)
    try:
        return build_deck(target)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        traceback.print_exc()
        print("Could not download the Japanese deck.", file=sys.stderr)
        return None


def main() -> None:
    build_deck()


if __name__ == "__main__":
    main()
