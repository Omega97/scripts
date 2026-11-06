"""Session flow, SRS persistence, and dashboard stats for one local learner."""

from __future__ import annotations

import json
import random
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from content import (
    ACHIEVEMENTS,
    CONTENT,
    INSIGHTS,
    MODE_LABELS,
    MODES,
    SEASONS,
    choice_valid,
    compound_note,
    hard_alternates,
    insight_by_id,
    items_for,
    kanji_hard_valid,
    norm_en,
    season_for_month,
    shares_any,
)
from srs import blank_stat, parse_time, performance_skill, romaji_match, schedule, select_queue, utcnow

DEFAULT_SETTINGS = {
    "furigana": True,
    "sound": True,
    "theme": "seasonal",
    "daily_goal": 20,
    "reduced_motion": False,
}

CATEGORY_LABELS = {
    "HIRAGANA": "Hiragana",
    "KATAKANA": "Katakana",
    "KANJI": "Kanji",
    "PHRASE": "Phrases",
}

ATTEMPT_CAP = 8000


def fresh_state() -> dict:
    return {
        "settings": dict(DEFAULT_SETTINGS),
        "attempts": [],
        "items": {},
        "sessions": [],
        "achievements": [],
        "freezes": 0,
        "frozen_dates": [],
        "freeze_award_dates": [],
        "study_ms": 0,
    }


def default_data_path() -> Path:
    return Path(__file__).resolve().parent / "state.json"


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        base = fresh_state()
        if not self.path.exists():
            return base
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Could not read {self.path}: {exc}") from exc
        if not isinstance(saved, dict):
            raise SystemExit(f"Could not read {self.path}: expected an object")
        settings = dict(DEFAULT_SETTINGS)
        settings.update(saved.get("settings") or {})
        base["settings"] = settings
        for key in ("attempts", "items", "sessions", "achievements", "frozen_dates", "freeze_award_dates"):
            if isinstance(saved.get(key), (list, dict)):
                base[key] = saved[key]
        base["freezes"] = int(saved.get("freezes") or 0)
        base["study_ms"] = int(saved.get("study_ms") or 0)
        return base

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def as_date(value) -> date:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamp.astimezone().date()
    if isinstance(value, date):
        return value
    text = str(value)
    if "T" in text:
        return parse_time(text).astimezone().date()
    return date.fromisoformat(text[:10])


def attempt_dates(attempts: list[dict]) -> set[date]:
    return {as_date(item["timestamp"]) for item in attempts if item.get("timestamp")}


def streak_count(real: set[date], frozen: set[date], today: date) -> int:
    """Consecutive active days ending today, or yesterday if today is still open."""
    active = set(real) | set(frozen)
    cursor = today if today in active else today - timedelta(days=1)
    if cursor not in active:
        return 0
    count = 0
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count


def missed_day_to_freeze(real: set[date], today: date, freezes: int) -> date | None:
    """Cover exactly one skipped day when the learner returns and has a freeze."""
    if today in real or freezes <= 0 or not real:
        return None
    gap = (today - max(real)).days
    if gap == 2:
        return today - timedelta(days=1)
    return None


def _fold_kana(text: str) -> str:
    """Compare hiragana and katakana as the same reading."""
    chars = []
    for char in (text or "").lower():
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(char)
    return "".join(chars)


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:10]


class Engine:
    def __init__(self, path: Path, rng: random.Random | None = None, now_fn=None):
        self.store = Store(path)
        self.rng = rng or random.Random()
        self.now_fn = now_fn or utcnow
        self.sessions: dict[str, dict] = {}
        self.lock = threading.Lock()

    def now(self) -> datetime:
        current = self.now_fn()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current

    def bootstrap(self) -> dict:
        with self.lock:
            state = self.store.data
            today = as_date(self.now())
            month = today.month
            season_id = season_for_month(month)
            season = {"id": season_id, **SEASONS[season_id]}
            theme = state["settings"].get("theme") or "seasonal"
            resolved = season_id if theme == "seasonal" else theme
            real = attempt_dates(state["attempts"])
            frozen = {as_date(item) for item in state["frozen_dates"]}
            categories = []
            for category, modes in MODES.items():
                categories.append({
                    "id": category,
                    "label": CATEGORY_LABELS[category],
                    "count": len(items_for(category)),
                    "modes": [{"id": mode, "label": MODE_LABELS[(category, mode)]} for mode in modes],
                })
            motto = INSIGHTS[today.timetuple().tm_yday % len(INSIGHTS)]
            return {
                "settings": state["settings"],
                "theme": resolved,
                "season_setting": theme,
                "season": {key: season[key] for key in ("id", "jp", "romaji", "en", "particle")},
                "motto": {key: motto[key] for key in ("jp", "romaji", "en")},
                "daily": self._daily(state, today),
                "streak": streak_count(real, frozen, today),
                "freezes": int(state["freezes"]),
                "categories": categories,
                "source": CONTENT.get("source") or "",
            }

    def update_settings(self, patch: dict) -> dict:
        with self.lock:
            settings = self.store.data["settings"]
            if "furigana" in patch:
                settings["furigana"] = bool(patch["furigana"])
            if "sound" in patch:
                settings["sound"] = bool(patch["sound"])
            if "reduced_motion" in patch:
                settings["reduced_motion"] = bool(patch["reduced_motion"])
            if "theme" in patch:
                theme = str(patch["theme"])
                if theme not in {"seasonal", "light", "dark", "contrast"}:
                    raise ValueError("Theme must be seasonal, light, dark, or contrast.")
                settings["theme"] = theme
            if "daily_goal" in patch:
                goal = int(patch["daily_goal"])
                if goal < 1 or goal > 500:
                    raise ValueError("Daily goal must be between 1 and 500.")
                settings["daily_goal"] = goal
            self.store.save()
        return self.bootstrap()

    def start_session(self, category: str, mode: str, length: int, focus: bool, item_ids: list[str] | None = None) -> dict:
        with self.lock:
            category = str(category or "").upper()
            mode = str(mode or "").upper()
            if category not in MODES:
                raise ValueError("Choose hiragana, katakana, kanji, or phrases.")
            if mode not in MODES[category]:
                raise ValueError(f"{CATEGORY_LABELS[category]} does not have that mode.")
            length = int(length)
            if length not in {0, 5, 10, 20}:
                raise ValueError("Session length must be 5, 10, 20, or endless.")
            pool = items_for(category)
            if item_ids is not None:
                queue = []
                for item_id in item_ids:
                    item = CONTENT["by_id"].get(item_id)
                    if item is None or item["category"] != category:
                        raise ValueError(f"Unknown item {item_id}")
                    queue.append(item_id)
                if not queue:
                    raise ValueError("The session has no problems.")
            else:
                count = 10 if length == 0 else length
                picked = select_queue(
                    pool,
                    self.store.data["items"],
                    count,
                    self.now(),
                    self.rng,
                    skill=self._pick_skill(category),
                )
                if not picked:
                    raise ValueError("No problems are available in this category.")
                queue = [item["id"] for item in picked]
            session = {
                "id": _new_id("sess_"),
                "category": category,
                "mode": mode,
                "focus": bool(focus),
                "endless": length == 0,
                "nominal": length,
                "queue": queue,
                "cursor": 0,
                "answered": 0,
                "correct": 0,
                "combo": 0,
                "started_at": self.now(),
                "live": None,
                "closed": False,
            }
            self.sessions[session["id"]] = session
            question = self._serve(session)
            return {
                "session_id": session["id"],
                "category": category,
                "mode": mode,
                "focus": session["focus"],
                "endless": session["endless"],
                "question": question,
            }

    def answer(self, session_id: str, qid: str, option_key: str | None, text: str | None, response_ms: int) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None or session["closed"]:
                raise ValueError("That session is already finished.")
            live = session["live"]
            if live is None or live["qid"] != qid:
                raise ValueError("This question has already been answered.")
            response_ms = max(0, min(int(response_ms or 0), 180_000))
            correct = self._grade(live, option_key, text)
            now = self.now()
            state = self.store.data
            today = as_date(now)
            real_before = attempt_dates(state["attempts"])
            returned = False
            if today not in real_before:
                earlier = [day for day in real_before if day < today]
                if earlier and (today - max(earlier)).days >= 3:
                    returned = True
                missed = missed_day_to_freeze(real_before, today, int(state["freezes"]))
                if missed is not None:
                    state["freezes"] = int(state["freezes"]) - 1
                    state["frozen_dates"].append(missed.isoformat())
            item = CONTENT["by_id"][live["item_id"]]
            before = state["items"].get(item["id"])
            state["items"][item["id"]] = schedule(before or blank_stat(), correct, response_ms, now)
            selected = ""
            if live["input"] == "choice":
                selected = live["option_text"].get(option_key or "", "")
            else:
                selected = (text or "").strip()
            state["attempts"].append({
                "attempt_id": _new_id("att_"),
                "session_id": session["id"],
                "problem_id": item["id"],
                "category": session["category"],
                "difficulty": session["mode"],
                "is_correct": correct,
                "selected_option": selected,
                "response_time_ms": response_ms,
                "timestamp": now.isoformat(),
            })
            if len(state["attempts"]) > ATTEMPT_CAP:
                state["attempts"] = state["attempts"][-ATTEMPT_CAP:]
            state["study_ms"] = int(state["study_ms"]) + response_ms
            session["answered"] += 1
            if correct:
                session["correct"] += 1
                session["combo"] += 1
            else:
                session["combo"] = 0
                self._requeue(session, item["id"])
            session["cursor"] += 1
            session["live"] = None
            unlocks = self._grant(state, today, returned, session_done=False)
            self._award_freeze(state, today)
            nxt = self._serve(session)
            summary = None
            if nxt is None:
                summary = self._close(session, now)
                unlocks.extend(self._grant(state, today, False, session_done=True))
            if live["input"] == "choice":
                live["accepted_keys"] = [
                    key
                    for key, value in live["option_text"].items()
                    if choice_valid(live["category"], live["mode"], item, value)
                ]
            self.store.save()
            payload = self._feedback(item, session, live, correct, before, selected)
            payload.update({
                "correct": correct,
                "correct_key": live.get("correct_key"),
                "accepted_keys": list(live.get("accepted_keys") or []),
                "correct_text": live["correct_text"],
                "your_text": selected,
                "combo": session["combo"],
                "daily": self._daily(state, today),
                "unlocks": unlocks,
                "next": nxt,
                "summary": summary,
                "progress": {
                    "answered": session["answered"],
                    "correct": session["correct"],
                    "total": None if session["endless"] else len(session["queue"]),
                },
            })
            return payload

    def end_session(self, session_id: str) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise ValueError("That session is already finished.")
            now = self.now()
            summary = self._close(session, now)
            today = as_date(now)
            unlocks = self._grant(self.store.data, today, False, session_done=session["answered"] > 0)
            summary["unlocks"] = unlocks
            self.store.save()
            return summary

    def dashboard(self) -> dict:
        with self.lock:
            return self._dashboard()

    def zen(self, category: str) -> dict:
        category = str(category or "").upper()
        if category not in MODES:
            raise ValueError("Choose hiragana, katakana, kanji, or phrases.")
        cards = [self._zen_card(item) for item in items_for(category)]
        return {"category": category, "label": CATEGORY_LABELS[category], "cards": cards}

    def search(self, query: str) -> dict:
        needle = (query or "").strip()
        if not needle:
            return {"results": []}
        folded = _fold_kana(needle)
        results = []
        seen = set()

        def add(item):
            if item["id"] in seen:
                return
            seen.add(item["id"])
            results.append(self._dict_card(item))

        for item in CONTENT["kana"]:
            if needle == item["kana"] or folded == item["romaji"] or folded in item["romaji_variants"]:
                add(item)
        for item in CONTENT["kanji"]:
            readings = [_fold_kana(reading) for reading in item["kunyomi"] + item["onyomi"] + [item["audio"]]]
            if needle == item["kanji"] or folded in _fold_kana(item["gloss"]) or folded in readings:
                add(item)
        for item in CONTENT["phrases"]:
            blob = _fold_kana(item["meaning_en"] + item["sentence_clean"] + item["target"])
            if folded in blob or needle in item["sentence_clean"] or needle in item["target"]:
                add(item)
        return {"results": results[:30]}

    def item(self, item_id: str) -> dict:
        found = CONTENT["by_id"].get(item_id)
        if found is None:
            raise KeyError(item_id)
        return self._dict_card(found)

    def _serve(self, session: dict) -> dict | None:
        if session["cursor"] >= len(session["queue"]):
            if session["endless"]:
                self._refill(session)
            if session["cursor"] >= len(session["queue"]):
                return None
        item = CONTENT["by_id"][session["queue"][session["cursor"]]]
        public, secret = self._question(item, session)
        public["index"] = session["cursor"] + 1
        public["total"] = None if session["endless"] else len(session["queue"])
        public["combo"] = session["combo"]
        public["focus"] = session["focus"]
        public["answered"] = session["answered"]
        session["live"] = secret
        return public

    def _pick_skill(self, category: str) -> float | None:
        """Kanji and phrase sessions follow recent accuracy. Kana stay uniform."""
        if category not in {"KANJI", "PHRASE"}:
            return None
        return performance_skill(self.store.data["attempts"], category)

    def _refill(self, session: dict) -> None:
        pool = items_for(session["category"])
        picked = select_queue(
            pool,
            self.store.data["items"],
            5,
            self.now(),
            self.rng,
            skill=self._pick_skill(session["category"]),
        )
        if not picked:
            picked = [self.rng.choice(pool)]
        session["queue"].extend(item["id"] for item in picked)

    def _requeue(self, session: dict, item_id: str) -> None:
        cap = 10**6 if session["endless"] or session["nominal"] == 0 else session["nominal"] + 5
        if len(session["queue"]) >= cap:
            return
        upcoming = session["queue"][session["cursor"] + 1:]
        if item_id in upcoming:
            return
        session["queue"].append(item_id)

    def _question(self, item: dict, session: dict) -> tuple[dict, dict]:
        category = session["category"]
        mode = session["mode"]
        qid = _new_id("q_")
        secret = {
            "qid": qid,
            "item_id": item["id"],
            "category": category,
            "mode": mode,
            "input": "choice",
            "correct_key": None,
            "correct_text": "",
            "option_text": {},
            "accepted_keys": [],
            "accepted_texts": [],
            "variants": [],
            "expect": "",
        }
        public = {
            "qid": qid,
            "category": category,
            "mode": mode,
            "label": MODE_LABELS[(category, mode)],
            "input": "choice",
            "prompt": "",
            "sub": "",
            "ruby": None,
            "audio": None,
            "options": [],
            "aria": "",
            "allow_reveal": False,
        }
        if category in {"HIRAGANA", "KATAKANA"} and mode == "EASY":
            distractors = self._siblings(item, items_for(category), lambda it: it["kana"])
            options, key = self._choices(item["kana"], distractors)
            public.update(prompt=item["romaji"], sub=self._kana_sub(item, easy=True), options=options, aria=f"Romaji {item['romaji']}")
            self._finish_choice(secret, item, options, key, item["kana"])
        elif category in {"HIRAGANA", "KATAKANA"} and mode == "HARD":
            script = "hiragana" if category == "HIRAGANA" else "katakana"
            public.update(
                input="text",
                prompt=item["kana"],
                sub="Type the romaji. Hepburn variants such as shi/si are accepted.",
                aria=f"{script} prompt",
                allow_reveal=False,
            )
            secret.update(input="text", expect="romaji", correct_text=item["romaji"], variants=list(item["romaji_variants"]))
        elif category == "KANJI" and mode == "EASY":
            distractors = self._safe_distractors(
                item,
                CONTENT["kanji"],
                lambda it: it["gloss"],
                lambda other, value: shares_any(other.get("meanings"), item.get("meanings")) or choice_valid("KANJI", "EASY", item, value),
            )
            options, key = self._choices(item["gloss"], distractors)
            public.update(prompt=item["kanji"], sub="Choose the meaning", options=options, aria=item["audio"])
            self._finish_choice(secret, item, options, key, item["gloss"])
        elif category == "KANJI" and mode == "MEDIUM":
            distractors = self._safe_distractors(
                item,
                CONTENT["kanji"],
                lambda it: it["kanji"],
                lambda other, value: shares_any(item.get("displayed"), other.get("meanings")) or choice_valid("KANJI", "MEDIUM", item, value),
            )
            options, key = self._choices(item["kanji"], distractors)
            public.update(prompt=item["gloss"], sub="Choose the kanji", options=options, aria=item["gloss"])
            self._finish_choice(secret, item, options, key, item["kanji"])
        elif category == "KANJI" and mode == "HARD":
            public.update(
                input="text",
                prompt=item["gloss"],
                sub="Listen, then type the kanji.",
                audio=item["audio"],
                aria=item["gloss"],
                allow_reveal=True,
            )
            secret.update(
                input="text",
                expect="kanji",
                correct_text=item["kanji"],
                accepted_texts=[item["kanji"]] + hard_alternates(item),
            )
        elif category == "PHRASE" and mode == "HARD":
            options, key = self._choices(item["target"], item["distractors"])
            public.update(
                prompt="",
                sub="Fill in the blank",
                ruby=self._cloze(item),
                options=options,
                aria="Phrase with a blank",
            )
            mates = CONTENT["targets_by_skeleton"].get(item.get("skeleton"), set())
            secret["accepted_texts"] = [item["target"]] + sorted(target for target in mates if target != item["target"])
            self._finish_choice(secret, item, options, key, item["target"])
        elif category == "PHRASE" and mode == "LISTENING":
            allowed = CONTENT["english_by_sentence"].get(item["sentence_clean"], set())
            others = [phrase for phrase in CONTENT["phrases"] if phrase["id"] != item["id"]]
            self.rng.shuffle(others)
            safe = []
            unsafe = []
            for phrase in others:
                value = phrase["meaning_en"]
                if value in safe or value in unsafe or value == item["meaning_en"]:
                    continue
                if norm_en(value) in allowed:
                    unsafe.append(value)
                else:
                    safe.append(value)
                if len(safe) == 3:
                    break
            picked = safe[:3]
            if len(picked) < 3:
                for value in unsafe:
                    if value not in picked:
                        picked.append(value)
                    if len(picked) == 3:
                        break
            options, key = self._choices(item["meaning_en"], picked)
            public.update(
                prompt="Listen, then choose the meaning.",
                sub="Listening",
                audio=item["audio"],
                options=options,
                aria="Spoken Japanese sentence",
                allow_reveal=True,
            )
            secret["accepted_texts"] = list(CONTENT["english_forms"].get(item["sentence_clean"], [item["meaning_en"]]))
            self._finish_choice(secret, item, options, key, item["meaning_en"])
        else:
            raise ValueError("That mode is not available.")
        return public, secret

    def _kana_sub(self, item: dict, easy: bool) -> str:
        if item["group"] == "sokuon":
            return "Small tsu — the consonant doubler"
        if item["group"] == "chouon":
            return "Katakana long-vowel mark"
        script = "hiragana" if item["category"] == "HIRAGANA" else "katakana"
        return f"Choose the {script}" if easy else "Type the romaji"

    def _siblings(self, item: dict, pool: list[dict], text_of) -> list[str]:
        correct = text_of(item)
        same = [other for other in pool if other.get("group") == item.get("group") and other["id"] != item["id"]]
        self.rng.shuffle(same)
        texts: list[str] = []
        for other in same:
            value = text_of(other)
            if value != correct and value not in texts:
                texts.append(value)
            if len(texts) == 3:
                return texts
        rest = [other for other in pool if other["id"] != item["id"]]
        self.rng.shuffle(rest)
        for other in rest:
            value = text_of(other)
            if value != correct and value not in texts:
                texts.append(value)
            if len(texts) == 3:
                break
        return texts

    def _safe_distractors(self, item: dict, pool: list[dict], text_of, is_unsafe) -> list[str]:
        """Three wrong options. A meaning that is also true of the prompt is kept out when possible."""
        correct = text_of(item)
        same = [other for other in pool if other.get("group") == item.get("group") and other["id"] != item["id"]]
        rest = [other for other in pool if other["id"] != item["id"] and other.get("group") != item.get("group")]
        self.rng.shuffle(same)
        self.rng.shuffle(rest)
        safe: list[str] = []
        unsafe: list[str] = []
        seen = {correct}
        for other in same + rest:
            value = text_of(other)
            if not value or value in seen:
                continue
            seen.add(value)
            if is_unsafe(other, value):
                unsafe.append(value)
            else:
                safe.append(value)
            if len(safe) >= 3:
                break
        picked = safe[:3]
        if len(picked) < 3:
            for value in unsafe:
                if value not in picked:
                    picked.append(value)
                if len(picked) == 3:
                    break
        return picked

    def _finish_choice(self, secret: dict, item: dict, options: list[dict], correct_key: str, correct_text: str) -> None:
        secret.update(
            correct_key=correct_key,
            correct_text=correct_text,
            option_text={opt["key"]: opt["text"] for opt in options},
        )
        accepted = [
            opt["key"]
            for opt in options
            if choice_valid(secret["category"], secret["mode"], item, opt["text"])
        ]
        if correct_key not in accepted:
            accepted.append(correct_key)
        secret["accepted_keys"] = accepted

    def _choices(self, correct: str, distractors: list[str]) -> tuple[list[dict], str]:
        texts = [correct]
        for value in distractors:
            if value not in texts:
                texts.append(value)
        texts = texts[:4]
        self.rng.shuffle(texts)
        keys = "abcd"
        options = [{"key": keys[index], "text": value} for index, value in enumerate(texts)]
        correct_key = next(option["key"] for option in options if option["text"] == correct)
        return options, correct_key

    def _cloze(self, item: dict) -> list[dict]:
        parts = []
        blank_at = item.get("blank_at")
        for index, part in enumerate(item["ruby"]):
            if blank_at is not None and index == blank_at:
                parts.append({"blank": True, "width": max(1, len(item["target"]))})
            elif blank_at is None and part.get("kanji") == item["target"]:
                parts.append({"blank": True, "width": max(1, len(item["target"]))})
            else:
                parts.append(dict(part))
        return parts

    def _grade(self, live: dict, option_key: str | None, text: str | None) -> bool:
        item = CONTENT["by_id"][live["item_id"]]
        if live["input"] == "choice":
            chosen = live["option_text"].get(option_key or "", "")
            return choice_valid(live["category"], live["mode"], item, chosen)
        if live["expect"] == "romaji":
            return romaji_match(text or "", live["variants"])
        if live["expect"] == "kanji":
            return kanji_hard_valid(item, text or "")
        return False

    def _also_accepted(self, live: dict) -> str:
        texts = list(live.get("accepted_texts") or [])
        for key in live.get("accepted_keys") or []:
            value = live.get("option_text", {}).get(key, "")
            if value and value not in texts:
                texts.append(value)
        primary = live.get("correct_text") or ""
        extras = []
        for value in texts:
            if value and value != primary and value not in extras:
                extras.append(value)
        if not extras:
            return ""
        return "Also accepted: " + ", ".join(extras)

    def _feedback(self, item: dict, session: dict, live: dict, correct: bool, before: dict | None, selected: str) -> dict:
        category = session["category"]
        reading = ""
        meaning = ""
        mnemonic = ""
        note = ""
        example = None
        sentence = None
        strokes = None
        radicals: list[str] = []
        if category in {"HIRAGANA", "KATAKANA"}:
            reading = item["kana"]
            meaning = item["romaji"]
            extras = [variant for variant in item["romaji_variants"] if variant != item["romaji"]]
            if extras:
                note = "Also accepted: " + ", ".join(extras)
        elif category == "KANJI":
            reading = self._reading(item)
            meaning = item["gloss"]
            mnemonic = item["mnemonic"]
            strokes = item["stroke_count"]
            radicals = list(item["radicals"])
            example = {"jp": item["example_jp"], "kana": item["example_kana"], "en": item["example_en"]}
            note = self._also_accepted(live)
        else:
            blank_at = item.get("blank_at")
            ruby = item["ruby"]
            if isinstance(blank_at, int) and 0 <= blank_at < len(ruby):
                token = ruby[blank_at]
            else:
                token = next(part for part in ruby if part.get("kanji") == item["target"])
            reading = token.get("reading") or ""
            note = self._also_accepted(live)
            meaning = item["meaning_en"]
            linked = CONTENT["by_id"].get(item.get("target_kanji_id") or "")
            mnemonic = compound_note(item["target"])
            if linked and linked.get("mnemonic") and len(item["target"]) == 1:
                mnemonic = linked["mnemonic"]
            sentence = item["ruby"]
            example = {"jp": item["sentence_clean"], "kana": "", "en": item["meaning_en"]}
        insight = None
        if not correct:
            strong = False
            if before and int(before.get("total_attempts") or 0) >= 3:
                accuracy = int(before.get("correct_attempts") or 0) / int(before["total_attempts"])
                strong = accuracy >= 0.8 or float(before.get("interval_days") or 0) >= 7
            insight = insight_by_id("monkey" if strong else "fall")
            insight = {key: insight[key] for key in ("jp", "romaji", "en")}
        return {
            "reading": reading,
            "meaning": meaning,
            "mnemonic": mnemonic,
            "note": note,
            "example": example,
            "sentence": sentence,
            "strokes": strokes,
            "radicals": radicals,
            "insight": insight,
            "item_id": item["id"],
        }

    def _reading(self, item: dict) -> str:
        bits = []
        if item.get("kunyomi"):
            bits.append("くん " + "・".join(item["kunyomi"]))
        if item.get("onyomi"):
            bits.append("おん " + "・".join(item["onyomi"]))
        if item.get("audio"):
            bits.append(item["audio"])
        return "   ".join(bits)

    def _close(self, session: dict, now: datetime) -> dict:
        if not session["closed"]:
            session["closed"] = True
            started = session["started_at"]
            duration_ms = max(0, int((now - started).total_seconds() * 1000))
            if session["answered"] > 0:
                self.store.data["sessions"].append({
                    "session_id": session["id"],
                    "started_at": started.isoformat(),
                    "ended_at": now.isoformat(),
                    "category": session["category"],
                    "mode": session["mode"],
                    "problems_count": session["answered"],
                    "correct_count": session["correct"],
                    "duration_ms": duration_ms,
                })
            session["duration_ms"] = duration_ms
        answered = session["answered"]
        correct = session["correct"]
        accuracy = (correct / answered) if answered else 0
        phrase = self._summary_phrase(accuracy, as_date(now))
        return {
            "session_id": session["id"],
            "category": session["category"],
            "category_label": CATEGORY_LABELS[session["category"]],
            "mode": session["mode"],
            "mode_label": MODE_LABELS[(session["category"], session["mode"])],
            "answered": answered,
            "correct": correct,
            "accuracy": accuracy,
            "duration_ms": session.get("duration_ms", 0),
            "phrase": phrase,
            "endless": session["endless"],
        }

    def _summary_phrase(self, accuracy: float, today: date) -> dict:
        state = self.store.data
        real = attempt_dates(state["attempts"])
        frozen = {as_date(item) for item in state["frozen_dates"]}
        streak = streak_count(real, frozen, today)
        if streak >= 21:
            chosen = insight_by_id("stone")
        elif accuracy >= 0.999 and accuracy > 0:
            chosen = insight_by_id("continue")
        elif accuracy < 0.5:
            chosen = insight_by_id("fall")
        else:
            chosen = insight_by_id("dust")
        return {key: chosen[key] for key in ("jp", "romaji", "en")}

    def _daily(self, state: dict, today: date) -> dict:
        done = sum(1 for item in state["attempts"] if item.get("timestamp") and as_date(item["timestamp"]) == today)
        return {"done": done, "goal": int(state["settings"].get("daily_goal") or 20)}

    def _award_freeze(self, state: dict, today: date) -> None:
        real = attempt_dates(state["attempts"])
        frozen = {as_date(item) for item in state["frozen_dates"]}
        streak = streak_count(real, frozen, today)
        today_text = today.isoformat()
        if streak >= 7 and streak % 7 == 0 and today_text not in state["freeze_award_dates"]:
            state["freezes"] = int(state["freezes"]) + 1
            state["freeze_award_dates"].append(today_text)

    def _grant(self, state: dict, today: date, returned: bool, session_done: bool) -> list[dict]:
        owned = {entry["id"] for entry in state["achievements"]}
        fresh: list[str] = []

        def grant(achievement_id: str, ok: bool) -> None:
            if ok and achievement_id not in owned:
                state["achievements"].append({"id": achievement_id, "unlocked_at": self.now().isoformat()})
                owned.add(achievement_id)
                fresh.append(achievement_id)

        correct = sum(1 for item in state["attempts"] if item.get("is_correct"))
        real = attempt_dates(state["attempts"])
        frozen = {as_date(item) for item in state["frozen_dates"]}
        streak = streak_count(real, frozen, today)
        grant("first_step", session_done and any(item.get("problems_count", 0) > 0 for item in state["sessions"]))
        grant("week_streak", streak >= 7)
        grant("century", correct >= 100)
        grant("thousand", correct >= 1000)
        kana_ids = [item["id"] for item in CONTENT["kana"]]
        mastered_kana = 0
        for item_id in kana_ids:
            stat = state["items"].get(item_id)
            if stat and int(stat.get("total_attempts") or 0) >= 1 and int(stat.get("correct_attempts") or 0) == int(stat["total_attempts"]):
                mastered_kana += 1
        grant("kana_master", mastered_kana == len(kana_ids) and len(kana_ids) > 0)
        learned = sum(
            1
            for item in CONTENT["kanji"]
            if int(state["items"].get(item["id"], {}).get("correct_attempts") or 0) >= 1
        )
        grant("kanji_100", learned >= 100)
        grant("perseverance", returned)
        by_id = {item["id"]: item for item in ACHIEVEMENTS}
        return [{"id": item_id, "seal": by_id[item_id]["seal"], "name": by_id[item_id]["name"]} for item_id in fresh]

    def _dashboard(self) -> dict:
        state = self.store.data
        today = as_date(self.now())
        real = attempt_dates(state["attempts"])
        frozen = {as_date(item) for item in state["frozen_dates"]}
        attempts = state["attempts"]
        correct = sum(1 for item in attempts if item.get("is_correct"))
        solved = len(attempts)
        week_ago = today - timedelta(days=6)
        categories = []
        for category in MODES:
            pool = items_for(category)
            cat_attempts = [item for item in attempts if item.get("category") == category]
            cat_correct = sum(1 for item in cat_attempts if item.get("is_correct"))
            learned = 0
            mastered = 0
            new_week = 0
            for item in pool:
                stat = state["items"].get(item["id"])
                if not stat:
                    continue
                if int(stat.get("correct_attempts") or 0) >= 1:
                    learned += 1
                if float(stat.get("interval_days") or 0) >= 30:
                    mastered += 1
                seen = stat.get("first_seen_at")
                if seen and as_date(seen) >= week_ago:
                    new_week += 1
            categories.append({
                "id": category,
                "label": CATEGORY_LABELS[category],
                "accuracy": (cat_correct / len(cat_attempts)) if cat_attempts else None,
                "learned": learned,
                "total": len(pool),
                "new_this_week": new_week,
                "mastered": mastered,
            })
        discovery = []
        for item in CONTENT["kanji"]:
            stat = state["items"].get(item["id"])
            if not stat or not stat.get("first_seen_at"):
                continue
            discovery.append({
                "id": item["id"],
                "kanji": item["kanji"],
                "meaning": item["gloss"],
                "mnemonic": item["mnemonic"],
                "date": as_date(stat["first_seen_at"]).isoformat(),
            })
        discovery.sort(key=lambda row: row["date"], reverse=True)
        return {
            "streak": streak_count(real, frozen, today),
            "freezes": int(state["freezes"]),
            "solved": solved,
            "correct": correct,
            "accuracy": (correct / solved) if solved else None,
            "study_ms": int(state["study_ms"]),
            "daily": self._daily(state, today),
            "categories": categories,
            "discovery": discovery[:40],
            "heatmap": self._heatmap(attempts, today),
            "trend": self._trend(attempts, today),
            "srs": self._srs_pie(state),
            "times": self._times(attempts),
            "achievements": self._achievement_view(state, today),
            "weekly": self._weekly(attempts, today),
            "season": season_for_month(today.month),
        }

    def _heatmap(self, attempts: list[dict], today: date) -> dict:
        start = today - timedelta(days=364)
        start = start - timedelta(days=(start.weekday() + 1) % 7)
        counts_by_day: dict[date, int] = {}
        for item in attempts:
            if not item.get("timestamp"):
                continue
            day = as_date(item["timestamp"])
            counts_by_day[day] = counts_by_day.get(day, 0) + 1
        days = []
        counts = []
        cursor = start
        while cursor <= today:
            days.append(cursor.isoformat())
            counts.append(counts_by_day.get(cursor, 0))
            cursor += timedelta(days=1)
        return {"start": start.isoformat(), "dates": days, "counts": counts}

    def _trend(self, attempts: list[dict], today: date) -> dict:
        days = [today - timedelta(days=offset) for offset in range(29, -1, -1)]
        series = {category: [] for category in MODES}
        for day in days:
            for category in MODES:
                rows = [
                    item for item in attempts
                    if item.get("category") == category and item.get("timestamp") and as_date(item["timestamp"]) == day
                ]
                if not rows:
                    series[category].append(None)
                else:
                    hit = sum(1 for item in rows if item.get("is_correct"))
                    series[category].append(round(hit / len(rows), 3))
        return {"dates": [day.isoformat() for day in days], "series": series}

    def _srs_pie(self, state: dict) -> dict:
        buckets = {"new": 0, "learning": 0, "review": 0, "mastered": 0}
        for item in CONTENT["kana"] + CONTENT["kanji"] + CONTENT["phrases"]:
            stat = state["items"].get(item["id"])
            total = int(stat.get("total_attempts") or 0) if stat else 0
            interval = float(stat.get("interval_days") or 0) if stat else 0
            if total <= 0:
                buckets["new"] += 1
            elif interval >= 30:
                buckets["mastered"] += 1
            elif interval >= 1:
                buckets["review"] += 1
            else:
                buckets["learning"] += 1
        return buckets

    def _times(self, attempts: list[dict]) -> list[dict]:
        labels = [("under 1s", 0, 1000), ("1–3s", 1000, 3000), ("3–6s", 3000, 6000), ("6–10s", 6000, 10000), ("over 10s", 10000, 10**9)]
        rows = []
        for label, low, high in labels:
            count = sum(1 for item in attempts if low <= int(item.get("response_time_ms") or 0) < high)
            rows.append({"label": label, "count": count})
        return rows

    def _weekly(self, attempts: list[dict], today: date) -> str:
        start = today - timedelta(days=today.weekday())
        week = [item for item in attempts if item.get("timestamp") and start <= as_date(item["timestamp"]) <= today]
        if not week:
            doing = insight_by_id("doing")
            return f"{doing['jp']} — No problems yet this week. {doing['en']}"
        correct = sum(1 for item in week if item.get("is_correct"))
        accuracy = round(100 * correct / len(week))
        by_cat: dict[str, list[dict]] = {category: [] for category in MODES}
        for item in week:
            by_cat.setdefault(item.get("category"), []).append(item)
        ranked = []
        for category, rows in by_cat.items():
            if not rows or category not in CATEGORY_LABELS:
                continue
            hit = sum(1 for item in rows if item.get("is_correct"))
            ranked.append((hit / len(rows), len(rows), CATEGORY_LABELS[category]))
        strongest = max(ranked)[2] if ranked else "—"
        tally: dict[str, int] = {}
        for item in week:
            tally[item.get("problem_id")] = tally.get(item.get("problem_id"), 0) + 1
        top_id = max(tally, key=tally.get) if tally else ""
        glyph = self._glyph(top_id)
        return (
            f"今週も頑張りましたね！ — You solved {len(week)} problems this week with {accuracy}% accuracy. "
            f"Your strongest category: {strongest}. Your most-reviewed item: {glyph}. 継続は力なり。"
        )

    def _glyph(self, item_id: str) -> str:
        item = CONTENT["by_id"].get(item_id)
        if item is None:
            return "—"
        return item.get("kana") or item.get("kanji") or item.get("target") or item_id

    def _achievement_view(self, state: dict, today: date) -> list[dict]:
        unlocked = {entry["id"]: entry.get("unlocked_at") for entry in state["achievements"]}
        correct = sum(1 for item in state["attempts"] if item.get("is_correct"))
        real = attempt_dates(state["attempts"])
        frozen = {as_date(item) for item in state["frozen_dates"]}
        streak = streak_count(real, frozen, today)
        kana_total = len(CONTENT["kana"])
        kana_ok = 0
        for item in CONTENT["kana"]:
            stat = state["items"].get(item["id"])
            if stat and int(stat.get("total_attempts") or 0) >= 1 and int(stat.get("correct_attempts") or 0) == int(stat["total_attempts"]):
                kana_ok += 1
        kanji_ok = sum(
            1 for item in CONTENT["kanji"] if int(state["items"].get(item["id"], {}).get("correct_attempts") or 0) >= 1
        )
        progress = {
            "first_step": (1 if state["sessions"] else 0, 1),
            "week_streak": (min(streak, 7), 7),
            "century": (min(correct, 100), 100),
            "thousand": (min(correct, 1000), 1000),
            "kana_master": (kana_ok, kana_total),
            "kanji_100": (min(kanji_ok, 100), 100),
            "perseverance": (1 if "perseverance" in unlocked else 0, 1),
        }
        rows = []
        for spec in ACHIEVEMENTS:
            current, target = progress[spec["id"]]
            rows.append({
                **spec,
                "unlocked": spec["id"] in unlocked,
                "unlocked_at": unlocked.get(spec["id"]),
                "current": current,
                "target": target,
            })
        return rows

    def _dict_card(self, item: dict) -> dict:
        category = item["category"]
        if category in {"HIRAGANA", "KATAKANA"}:
            return {
                "id": item["id"],
                "kind": category,
                "title": item["kana"],
                "reading": item["romaji"],
                "meaning": item["romaji"],
                "mnemonic": "",
                "note": "Also accepted: " + ", ".join(v for v in item["romaji_variants"] if v != item["romaji"]),
                "example_jp": "",
                "example_kana": "",
                "example_en": "",
                "strokes": None,
                "radicals": [],
            }
        if category == "KANJI":
            return {
                "id": item["id"],
                "kind": "KANJI",
                "title": item["kanji"],
                "reading": self._reading(item),
                "meaning": item["gloss"],
                "mnemonic": item["mnemonic"],
                "note": "",
                "example_jp": item["example_jp"],
                "example_kana": item["example_kana"],
                "example_en": item["example_en"],
                "strokes": item["stroke_count"],
                "radicals": list(item["radicals"]),
            }
        return {
            "id": item["id"],
            "kind": "PHRASE",
            "title": item["target"],
            "reading": item["sentence_clean"],
            "meaning": item["meaning_en"],
            "mnemonic": compound_note(item["target"]),
            "note": "",
            "example_jp": item["sentence_clean"],
            "example_kana": "",
            "example_en": item["meaning_en"],
            "strokes": None,
            "radicals": [],
            "ruby": item["ruby"],
        }

    def _zen_card(self, item: dict) -> dict:
        card = self._dict_card(item)
        if item["category"] in {"HIRAGANA", "KATAKANA"}:
            front, front_ruby = item["kana"], None
        elif item["category"] == "KANJI":
            front, front_ruby = item["kanji"], None
        else:
            front, front_ruby = "", item["ruby"]
        card["front"] = front
        card["front_ruby"] = front_ruby
        return card
