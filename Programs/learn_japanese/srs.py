"""SM-2 lite scheduling, romaji checks, and session pool selection.

The rules follow the learning-app blueprint: 40/40/20 new/weak/review,
redistribute a short pool toward the next one, and never block a session.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Iterable


def normalize_romaji(text: str) -> str:
    """Fold keyboard variants so Hepburn answers compare fairly."""
    if text is None:
        return ""
    raw = unicodedata.normalize("NFKC", text).strip().lower()
    raw = raw.replace("ō", "o").replace("ū", "u").replace("ā", "a").replace("ī", "i").replace("ē", "e")
    raw = raw.replace(" ", "").replace("'", "").replace("’", "")
    return raw


def romaji_match(user: str, variants: Iterable[str]) -> bool:
    folded = normalize_romaji(user)
    if not folded:
        return False
    accepted = {normalize_romaji(v) for v in variants if normalize_romaji(v)}
    return folded in accepted


def normalize_kanji(text: str) -> str:
    if text is None:
        return ""
    return unicodedata.normalize("NFC", text).strip().replace(" ", "").replace("\u3000", "")


def quotas(n: int, weights: tuple[tuple[str, float], ...] | None = None) -> dict[str, int]:
    """Split n into weighted integer shares. Leftover units go to the largest fraction."""
    if weights is None:
        weights = (("new", 0.4), ("weak", 0.4), ("review", 0.2))
    names = [name for name, _weight in weights]
    if n <= 0:
        return {name: 0 for name in names}
    raw = [n * weight for _name, weight in weights]
    base = [int(math.floor(value)) for value in raw]
    remaining = n - sum(base)
    order = sorted(
        range(len(raw)),
        key=lambda index: (raw[index] - base[index], -index),
        reverse=True,
    )
    for index in order[:remaining]:
        base[index] += 1
    return {names[index]: base[index] for index in range(len(names))}


def classify_pool(stat: dict | None, now: datetime) -> str:
    """Return new, weak, review, or rest for one item stat."""
    if stat is None or int(stat.get("total_attempts") or 0) == 0:
        return "new"
    total = int(stat["total_attempts"])
    correct = int(stat.get("correct_attempts") or 0)
    accuracy = correct / total if total else 0
    if accuracy < 0.7 or int(stat.get("streak") or 0) < 0:
        return "weak"
    due = stat.get("next_review_at")
    if due is None:
        return "review"
    due_at = due if isinstance(due, datetime) else parse_time(due)
    if due_at <= now:
        return "review"
    return "rest"


# Difficulty prior. Each kanji and phrase already carries difficulty in [0, 1]
# (school grade, then strokes; phrases use JLPT level, then that grade).
# Items with no such number fall back to stroke count inside the deck.
# Recent accuracy is the skill. Sampling stays inside the 40/40/20 pools.
#
#   last 40 answers in that section, c correct, beginner prior 2/8
#   skill k = (c + 2) / (n + 8)                     in (0, 1)
#   no answers yet: k = 0.25
#
#   distance = difficulty - k
#   weight w = 0.12 + 0.88 * exp(-distance^2 / (2 * 0.35^2))
#
# A card at the skill has weight 1. A card at the other end has weight about
# 0.13, so it can still appear. Kana stay uniform. Due and weak cards are not
# skipped: the pool quotas still fill first.
BEGINNER_SKILL = 0.25
SKILL_WINDOW = 40
SKILL_PRIOR_CORRECT = 2.0
SKILL_PRIOR_ATTEMPTS = 8.0
STROKE_SIGMA = 0.35
STROKE_WEIGHT_FLOOR = 0.12


def performance_skill(attempts: list[dict], category: str = "KANJI") -> float:
    """Skill in (0, 1) from the latest answers in one category. Starts easy."""
    recent = [row for row in attempts if row.get("category") == category][-SKILL_WINDOW:]
    if not recent:
        return BEGINNER_SKILL
    correct = sum(1 for row in recent if row.get("is_correct"))
    return (correct + SKILL_PRIOR_CORRECT) / (len(recent) + SKILL_PRIOR_ATTEMPTS)


def _stroke_count(item: dict) -> int | None:
    value = item.get("stroke_count")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    strokes = int(value)
    if strokes <= 0:
        return None
    return strokes


def stroke_span(items: list[dict]) -> tuple[int, int] | None:
    counts = [count for item in items if (count := _stroke_count(item)) is not None]
    if len(counts) < 2:
        return None
    low, high = min(counts), max(counts)
    if high <= low:
        return None
    return low, high


def _unit_difficulty(item: dict, span: tuple[int, int] | None) -> float | None:
    """Prefer a stored 0–1 difficulty. Otherwise scale stroke count across the deck."""
    value = item.get("difficulty")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    if span is None:
        return None
    strokes = _stroke_count(item)
    if strokes is None:
        return None
    low, high = span
    return (strokes - low) / (high - low)


def stroke_weight(item: dict, skill: float | None, span: tuple[int, int] | None) -> float:
    """Relative draw weight. No skill, or no difficulty, leaves the item uniform."""
    if skill is None:
        return 1.0
    difficulty = _unit_difficulty(item, span)
    if difficulty is None:
        return 1.0
    distance = difficulty - max(0.0, min(1.0, skill))
    bell = math.exp(-(distance * distance) / (2 * STROKE_SIGMA * STROKE_SIGMA))
    return STROKE_WEIGHT_FLOOR + (1.0 - STROKE_WEIGHT_FLOOR) * bell


def _weighted_take(pool: list[dict], want: int, rng, weight_of) -> list[dict]:
    remaining = list(pool)
    picked: list[dict] = []
    while remaining and len(picked) < want:
        weights = [max(0.0, float(weight_of(item))) for item in remaining]
        if sum(weights) <= 0:
            weights = [1.0] * len(remaining)
        point = rng.random() * sum(weights)
        cursor = 0.0
        chosen_index = len(remaining) - 1
        for index, weight in enumerate(weights):
            cursor += weight
            if point <= cursor:
                chosen_index = index
                break
        picked.append(remaining.pop(chosen_index))
    return picked


def select_queue(
    items: list[dict],
    stats: dict[str, dict],
    n: int,
    now: datetime,
    rng,
    skill: float | None = None,
) -> list[dict]:
    """Pick n items using the pool weights, then difficulty inside each pool.

    Short pools spill forward (new, then weak, then review, then rested). A
    skill of None keeps every card equally likely. A skill near 0 prefers the
    easy end of the 0–1 difficulty; a skill near 1 prefers the hard end.
    """
    if n <= 0 or not items:
        return []
    pools: dict[str, list[dict]] = {"new": [], "weak": [], "review": [], "rest": []}
    for item in items:
        pools[classify_pool(stats.get(item["id"]), now)].append(item)
    span = stroke_span(items) if skill is not None else None
    weight_of = lambda item: stroke_weight(item, skill, span)

    shares = quotas(n)
    chosen: list[dict] = []
    taken: set[str] = set()
    surplus = 0
    for name in ("new", "weak", "review"):
        want = shares[name] + surplus
        available = [item for item in pools[name] if item["id"] not in taken]
        grab = _weighted_take(available, want, rng, weight_of)
        chosen.extend(grab)
        taken.update(item["id"] for item in grab)
        surplus = want - len(grab)

    if surplus > 0:
        for name in ("new", "weak", "review", "rest"):
            if surplus <= 0:
                break
            available = [item for item in pools[name] if item["id"] not in taken]
            grab = _weighted_take(available, surplus, rng, weight_of)
            chosen.extend(grab)
            taken.update(item["id"] for item in grab)
            surplus -= len(grab)

    # Interleave pools so a session does not open with only new items.
    buckets = {"new": [], "weak": [], "review": [], "rest": []}
    for item in chosen:
        buckets[classify_pool(stats.get(item["id"]), now)].append(item)
    mixed: list[dict] = []
    while any(buckets.values()):
        for name in ("new", "weak", "review", "rest"):
            if buckets[name]:
                mixed.append(buckets[name].pop(0))
    return mixed[:n]


def blank_stat(now: datetime | None = None) -> dict:
    return {
        "total_attempts": 0,
        "correct_attempts": 0,
        "streak": 0,
        "ease_factor": 2.5,
        "interval_days": 0.0,
        "last_attempted_at": None,
        "next_review_at": None,
        "first_seen_at": None,
    }


def schedule(stat: dict, correct: bool, response_ms: int, now: datetime) -> dict:
    """Apply one SM-2 lite update. Brand-new correct answers get a 1-day interval."""
    updated = dict(stat)
    first = int(updated.get("total_attempts") or 0) == 0
    ease = float(updated.get("ease_factor") or 2.5)
    interval = float(updated.get("interval_days") or 0)
    if correct:
        if first:
            interval_new = 1.0
        else:
            interval_new = max(1.0, interval * ease)
        penalty = 0.0 if response_ms < 3000 else 0.05
        ease = max(1.3, ease + 0.1 - penalty)
        updated["streak"] = int(updated.get("streak") or 0) + 1
        updated["next_review_at"] = (now + timedelta(days=interval_new)).isoformat()
        updated["interval_days"] = interval_new
    else:
        ease = max(1.3, ease - 0.2)
        updated["streak"] = -1
        updated["interval_days"] = 0.0
        updated["next_review_at"] = now.isoformat()
    updated["ease_factor"] = ease
    updated["total_attempts"] = int(updated.get("total_attempts") or 0) + 1
    updated["correct_attempts"] = int(updated.get("correct_attempts") or 0) + (1 if correct else 0)
    updated["last_attempted_at"] = now.isoformat()
    if not updated.get("first_seen_at"):
        updated["first_seen_at"] = now.isoformat()
    return updated


def parse_time(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
