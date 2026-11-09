"""Spot selection, frequency scoring, and the local attempt database."""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PHASES = ("preflop", "flop", "turn", "river")
LINES = {
    "open": ("fold", "limp", "raise2", "raise25", "raise3", "jam"),
    "vs-open": ("fold", "call", "three7", "three9", "three12", "jam"),
    "vs-3bet": ("fold", "call", "four18", "four22", "jam"),
    "vs-limp": ("check", "iso3", "iso4", "jam"),
    "checked": ("check", "bet33", "bet50", "bet75", "betpot", "jam"),
    "facing": ("fold", "call", "raise25", "raisepot", "jam"),
}
MODES = PHASES + ("mix", "grind")
PHASE_LABELS = {
    "preflop": "Pre-Flop",
    "flop": "Flop",
    "turn": "Turn",
    "river": "River",
}
MIN_POINTS = 1
SITUATIONS = Path(__file__).resolve().parent / "situations.json"
DATASET_SIX_MAX = "six-max-100bb"
DATASET_HEADS_UP = "heads-up-mixes"
SIX_MAX_NAME = "6-max 100bb, solver's chosen action"
SIX_MAX_DETAIL = (
    "Six-max cash, 100bb deep. Each answer is the one action a solver chose, at 100%."
)
HEADS_UP_NAME = "Heads-up BTN vs BB, mixed frequencies"
HEADS_UP_DETAIL = (
    "Heads-up button versus big blind. Each answer is a frequency mix across the menu, "
    "not a single action. The numbers are practice targets, not a solver export."
)


class NeedHistory(ValueError):
    """The Grind has no saved attempts to draw from."""


def default_db_path() -> Path:
    return Path(__file__).resolve().parent / "poker_trainer.db"


def default_library_path() -> Path:
    return default_db_path().parent / "spots.sqlite"


class SpotLibrary:
    """Read-only catalog of solver spots, indexed for one random draw."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        with self._conn() as conn:
            rows = conn.execute("SELECT phase, COUNT(*) AS n FROM spots GROUP BY phase").fetchall()
        self.counts = {phase: 0 for phase in PHASES}
        for row in rows:
            if row["phase"] in self.counts:
                self.counts[row["phase"]] = row["n"]
        self.total = sum(self.counts.values())

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def has(self, spot_id: str) -> bool:
        row = self._conn().execute("SELECT 1 FROM spots WHERE id = ?", (spot_id,)).fetchone()
        return row is not None

    def get(self, spot_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        return _spot_from_row(row) if row else None

    def pick(self, phase: str | None, rng: random.Random, exclude: str | None) -> dict | None:
        count = self.total if phase is None else self.counts.get(phase, 0)
        if count <= 0:
            return None
        chosen = None
        for _ in range(8):
            seq = rng.randrange(count)
            chosen = self._at(phase, seq)
            if chosen and chosen["id"] != exclude:
                return chosen
        return chosen

    def _at(self, phase: str | None, seq: int) -> dict | None:
        if phase is None:
            row = self._conn().execute("SELECT * FROM spots WHERE global_seq = ?", (seq,)).fetchone()
        else:
            row = self._conn().execute(
                "SELECT * FROM spots WHERE phase = ? AND seq = ?",
                (phase, seq),
            ).fetchone()
        return _spot_from_row(row) if row else None

    @staticmethod
    def build(path: Path, spots) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".building")
        if temporary.exists():
            temporary.unlink()
        conn = sqlite3.connect(temporary)
        try:
            conn.execute("PRAGMA journal_mode = OFF")
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute(
                """
                CREATE TABLE spots (
                    global_seq INTEGER PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    phase TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    hero TEXT NOT NULL,
                    board TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    gto TEXT NOT NULL
                )
                """
            )
            counts = {phase: 0 for phase in PHASES}
            batch = []
            total = 0

            def flush() -> None:
                if batch:
                    conn.executemany(
                        """
                        INSERT INTO spots (
                            global_seq, id, phase, seq, title, text, hero, board, actions, gto
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        batch,
                    )
                    batch.clear()

            for spot in spots:
                phase = spot.get("phase")
                if phase not in counts:
                    continue
                batch.append(
                    (
                        total,
                        spot["id"],
                        phase,
                        counts[phase],
                        spot.get("title") or spot["id"],
                        spot["text"],
                        json.dumps(spot["hero"], separators=(",", ":")),
                        json.dumps(spot["board"], separators=(",", ":")),
                        json.dumps(spot["actions"], separators=(",", ":")),
                        json.dumps(spot["gto"], separators=(",", ":")),
                    )
                )
                counts[phase] += 1
                total += 1
                if len(batch) >= 2000:
                    flush()
            flush()
            conn.execute("CREATE UNIQUE INDEX spots_phase_seq ON spots(phase, seq)")
            conn.commit()
        except Exception:
            conn.close()
            if temporary.exists():
                temporary.unlink()
            raise
        conn.close()
        if total == 0:
            temporary.unlink()
            raise ValueError("No spots were imported.")
        temporary.replace(path)
        return total


def _spot_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "phase": row["phase"],
        "title": row["title"],
        "text": row["text"],
        "hero": json.loads(row["hero"]),
        "board": json.loads(row["board"]),
        "actions": json.loads(row["actions"]),
        "gto": json.loads(row["gto"]),
    }


def read_study(path: Path | None = None) -> tuple[list[dict], dict]:
    """Load the heads-up study file and the name shown in Settings."""
    payload = json.loads((path or SITUATIONS).read_text(encoding="utf-8"))
    spots = payload["spots"] if isinstance(payload, dict) else payload
    if not isinstance(spots, list) or not spots:
        raise ValueError("The spot file is empty.")
    seen = set()
    for spot in spots:
        _validate_spot(spot)
        if spot["id"] in seen:
            raise ValueError(f"Duplicate spot {spot['id']}.")
        seen.add(spot["id"])
    if isinstance(payload, dict):
        meta = {
            "name": str(payload.get("name") or HEADS_UP_NAME),
            "detail": str(payload.get("note") or HEADS_UP_DETAIL),
        }
    else:
        meta = {"name": HEADS_UP_NAME, "detail": HEADS_UP_DETAIL}
    return spots, meta


def load_spots(path: Path | None = None) -> list[dict]:
    spots, _meta = read_study(path)
    return spots


def _validate_spot(spot: dict) -> None:
    if spot.get("phase") not in PHASES:
        raise ValueError(f"Spot {spot.get('id')} has a bad phase.")
    actions = spot.get("actions") or []
    expected = LINES.get(spot.get("line"))
    if expected is None:
        raise ValueError(f"Spot {spot.get('id')} has no action line.")
    keys = [action["key"] for action in actions]
    if tuple(keys) != expected:
        raise ValueError(f"Spot {spot.get('id')} is missing a live action.")
    if len(keys) != len(set(keys)):
        raise ValueError(f"Spot {spot.get('id')} repeats an action.")
    gto = spot.get("gto") or {}
    if set(gto) != set(keys):
        raise ValueError(f"Spot {spot.get('id')} frequencies do not match its actions.")
    total = 0
    for key in keys:
        value = gto[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Spot {spot.get('id')} has a bad frequency.")
        total += value
    if total != 100:
        raise ValueError(f"Spot {spot.get('id')} frequencies sum to {total}.")


def variation_score(truth: dict, guess: dict) -> tuple[float, float]:
    """Return total variation distance and a 0–1 score.

    Distance is half the L1 gap between the two mixes, so it stays between 0
    and 1. A guess of 0% on an action that is only 5% of the target moves the
    score by 0.05, instead of collapsing it through a logarithm.
    """
    gap = sum(abs(float(truth[key]) - float(guess[key])) for key in truth)
    distance = gap / 200.0
    return distance, max(0.0, min(1.0, 1.0 - distance))


def score_guess(gto: dict[str, int], points: dict[str, int]) -> tuple[float, float]:
    """Score point shares against target percentages."""
    actions = list(gto)
    total = sum(points[action] for action in actions)
    if total < MIN_POINTS:
        raise ValueError("Add at least one point.")
    if len(actions) < 2:
        raise ValueError("A spot needs at least two actions.")
    guess = {action: points[action] / total * 100 for action in actions}
    return variation_score(gto, guess)


def label_for(norm: float) -> str:
    if norm >= 0.9:
        return "Perfect"
    if norm >= 0.75:
        return "Great"
    if norm >= 0.55:
        return "Close"
    if norm >= 0.35:
        return "Off"
    return "Miss"


def percent_map(points: dict[str, int], actions: list[str]) -> dict[str, float]:
    total = sum(points[action] for action in actions)
    rounded = [round(points[action] / total * 100, 1) for action in actions]
    rounded[-1] = round(rounded[-1] + (100 - sum(rounded)), 1)
    return {action: rounded[index] for index, action in enumerate(actions)}


_SEAT = r"(?:UTG|HJ|CO|BTN|SB|BB)"
_AMOUNT = r"([0-9]+(?:\.[0-9]+)?)"
_OPEN = re.compile(rf"^({_SEAT}) (?:opens|raises) to {_AMOUNT}bb$")
_CALL = re.compile(rf"^({_SEAT}) calls$")
_JAM = re.compile(rf"^({_SEAT}) jams$")
_QUIET = re.compile(rf"^({_SEAT}) (?:folds|checks)$")
_POST = re.compile(
    rf"^(Out of position|In position) "
    rf"(checks|folds|calls|jams|bets {_AMOUNT}bb|raises to {_AMOUNT}bb)$"
)
_SIDE_ACTOR = {"Out of position": "OOP", "In position": "IP"}
_BOARD = re.compile(r"^The (?:flop|turn|river) is ")
_POT_LINE = re.compile(rf"^The pot is {_AMOUNT}bb$")
_STUDY_BET = re.compile(
    r"(?:to ([0-9]+(?:\.[0-9]+)?)x)|([0-9]+%)|(bets pot|bet pot)|(limps)",
    re.IGNORECASE,
)
_STUDY_POT = re.compile(
    r"([0-9]+(?:\.[0-9]+)?)bb pot|[Pp]ot is ([0-9]+(?:\.[0-9]+)?)bb"
)


def _bb(amount: float) -> str:
    amount = round(amount, 2)
    if amount.is_integer():
        text = str(int(amount))
    else:
        text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"{text}bb"


def _bare(sentence: str) -> str:
    return sentence[:-1] if sentence.endswith(".") else sentence


def _split_situation(text: str) -> list[str]:
    parts = [part for part in (text or "").split(". ") if part]
    return [f"{part}." if index < len(parts) - 1 else part for index, part in enumerate(parts)]


def _stated_pot(sentences: list[str]) -> float | None:
    for sentence in reversed(sentences):
        match = _POT_LINE.match(_bare(sentence))
        if match:
            return float(match.group(1))
    return None


def _seat_acted(sentences: list[str]) -> set[str]:
    acted = set()
    for sentence in sentences:
        bare = _bare(sentence)
        for pattern in (_OPEN, _CALL, _JAM, _QUIET):
            match = pattern.match(bare)
            if match:
                acted.add(match.group(1))
    return acted


def _replay_cash(sentences: list[str], drop_dead_sb: bool) -> tuple[list[dict[str, str]], float]:
    """Replay a 6-max line into chips added and the pot after each change."""
    if drop_dead_sb:
        invested = {"BB": 1.0}
        pot = 1.0
    else:
        invested = {"SB": 0.5, "BB": 1.0}
        pot = 1.5
    level = 1.0
    post = {"Out of position": 0.0, "In position": 0.0}
    post_level = 0.0
    shown: float | None = None
    rows: list[dict[str, str]] = []

    def emit(
        sentence: str,
        bet: float | None = None,
        new_pot: float | None = None,
        actor: str = "",
    ) -> None:
        nonlocal pot, shown
        bet_text = ""
        pot_text = ""
        if bet is not None and bet > 0.001:
            bet_text = _bb(bet)
        if new_pot is not None:
            pot = round(new_pot, 2)
            if shown is None or abs(pot - shown) > 0.001:
                pot_text = _bb(pot)
                shown = pot
        rows.append({"text": sentence, "actor": actor, "bet": bet_text, "pot": pot_text})

    for sentence in sentences:
        bare = _bare(sentence)
        if bare == "6-max cash, 100bb deep":
            emit(sentence, new_pot=pot)
            continue
        opened = _OPEN.match(bare)
        if opened:
            seat, to = opened.group(1), float(opened.group(2))
            added = to - invested.get(seat, 0.0)
            invested[seat] = to
            level = to
            emit(sentence, added, pot + added, seat)
            continue
        called = _CALL.match(bare)
        if called:
            seat = called.group(1)
            added = level - invested.get(seat, 0.0)
            invested[seat] = level
            emit(sentence, added, pot + added, seat)
            continue
        jammed = _JAM.match(bare)
        if jammed:
            seat = jammed.group(1)
            added = 100.0 - invested.get(seat, 0.0)
            invested[seat] = 100.0
            level = max(level, 100.0)
            emit(sentence, added, pot + added, seat)
            continue
        quiet = _QUIET.match(bare)
        if quiet:
            emit(sentence, actor=quiet.group(1))
            continue
        if _BOARD.match(bare):
            post = {"Out of position": 0.0, "In position": 0.0}
            post_level = 0.0
            emit(sentence)
            continue
        acted = _POST.match(bare)
        if acted:
            side, kind = acted.group(1), acted.group(2)
            actor = _SIDE_ACTOR[side]
            if kind in {"checks", "folds"}:
                emit(sentence, actor=actor)
            elif kind == "calls":
                added = post_level - post[side]
                post[side] = post_level
                emit(sentence, added, pot + added, actor)
            elif kind == "jams":
                rows.append({"text": sentence, "actor": actor, "bet": "Jam", "pot": ""})
            elif kind.startswith("bets"):
                amount = float(acted.group(3))
                post[side] = amount
                post_level = amount
                emit(sentence, amount, pot + amount, actor)
            else:
                amount = float(acted.group(4))
                added = amount - post[side]
                post[side] = amount
                post_level = amount
                emit(sentence, added, pot + added, actor)
            continue
        emit(sentence)
    return rows, pot


def _study_actor(bare: str) -> str:
    if re.match(r"Hero faces\b", bare):
        return "Villain"
    lead = re.match(r"(Hero|Villain)\b", bare)
    if lead:
        return lead.group(1)
    seat = re.search(rf"\b({_SEAT})\b", bare)
    return seat.group(1) if seat else ""


def situation_rows(text: str) -> list[dict[str, str]]:
    """One display row per sentence, with the actor, chips added, and the pot when it moves."""
    sentences = _split_situation(text)
    if not sentences:
        return []
    if _bare(sentences[0]) == "6-max cash, 100bb deep":
        rows, pot = _replay_cash(sentences, drop_dead_sb=False)
        stated = _stated_pot(sentences)
        if stated is not None and "SB" not in _seat_acted(sentences):
            trimmed, trimmed_pot = _replay_cash(sentences, drop_dead_sb=True)
            if abs(trimmed_pot - stated) < abs(pot - stated):
                rows, pot = trimmed, trimmed_pot
        return rows
    rows = []
    for sentence in sentences:
        bare = _bare(sentence)
        bet = ""
        found = _STUDY_BET.search(bare)
        if found:
            if found.group(1):
                bet = f"{_bb(float(found.group(1)))[:-2]}x"
            elif found.group(2):
                bet = found.group(2)
            elif found.group(3):
                bet = "Pot"
            else:
                bet = "1bb"
        pot = ""
        found_pot = _STUDY_POT.search(bare)
        if found_pot:
            pot = _bb(float(found_pot.group(1) or found_pot.group(2)))
        rows.append({"text": sentence, "actor": _study_actor(bare), "bet": bet, "pot": pot})
    return rows


def public_hand(spot: dict) -> dict:
    return {
        "id": spot["id"],
        "phase": spot["phase"],
        "phase_label": PHASE_LABELS[spot["phase"]],
        "text": spot["text"],
        "rows": situation_rows(spot["text"]),
        "hero": list(spot["hero"]),
        "board": list(spot["board"]),
        "actions": [{"key": action["key"], "label": action["label"]} for action in spot["actions"]],
    }


class Engine:
    def __init__(
        self,
        db_path: Path,
        spots: list[dict] | None = None,
        rng: random.Random | None = None,
        library: Path | None = None,
    ):
        self.db_path = Path(db_path)
        self.rng = rng or random.Random()
        self.library = None
        self.study_meta = {"name": HEADS_UP_NAME, "detail": HEADS_UP_DETAIL}
        if spots is not None:
            self.spots = spots
        else:
            self.spots, self.study_meta = read_study()
        if library is not None and Path(library).exists():
            self.library = SpotLibrary(Path(library))
        self.by_id = {spot["id"]: spot for spot in self.spots}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        saved = None
        with self._conn() as conn:
            self._schema(conn)
            row = conn.execute("SELECT value FROM settings WHERE key = 'dataset'").fetchone()
            saved = row["value"] if row else None
        self.dataset_id = self._choose_dataset(saved)
        if saved != self.dataset_id:
            with self._conn() as conn:
                self._save_dataset(conn, self.dataset_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _conn(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                phase TEXT NOT NULL,
                situation_hash TEXT NOT NULL,
                user_answers TEXT NOT NULL,
                true_answers TEXT NOT NULL,
                ce_score REAL NOT NULL,
                norm_score REAL NOT NULL,
                dataset TEXT NOT NULL DEFAULT 'six-max-100bb'
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(attempts)")}
        if "dataset" not in columns:
            conn.execute(
                "ALTER TABLE attempts ADD COLUMN dataset TEXT NOT NULL DEFAULT 'six-max-100bb'"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats (
                phase TEXT PRIMARY KEY,
                total_hands INTEGER NOT NULL,
                avg_score REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._rescore(conn)

    def _rescore(self, conn: sqlite3.Connection) -> None:
        """Rewrite attempts saved under the old cross-entropy score."""
        rows = conn.execute(
            "SELECT id, user_answers, true_answers, ce_score, norm_score FROM attempts"
        ).fetchall()
        changed = False
        for row in rows:
            try:
                truth = json.loads(row["true_answers"])
                guess = json.loads(row["user_answers"])
                distance, norm = variation_score(truth, guess)
            except (TypeError, KeyError, json.JSONDecodeError, ValueError):
                continue
            if abs(row["norm_score"] - norm) > 1e-6 or abs(row["ce_score"] - distance) > 1e-6:
                conn.execute(
                    "UPDATE attempts SET ce_score = ?, norm_score = ? WHERE id = ?",
                    (distance, norm, row["id"]),
                )
                changed = True
        if not changed:
            return
        conn.execute("DELETE FROM user_stats")
        for phase, average, count in conn.execute(
            "SELECT phase, AVG(norm_score), COUNT(*) FROM attempts GROUP BY phase"
        ):
            conn.execute(
                "INSERT INTO user_stats (phase, total_hands, avg_score) VALUES (?, ?, ?)",
                (phase, count, average),
            )

    def _library_active(self) -> bool:
        return self.dataset_id == DATASET_SIX_MAX and self.library is not None

    def _available_datasets(self) -> set[str]:
        available = set()
        if self.spots:
            available.add(DATASET_HEADS_UP)
        if self.library is not None and self.library.total:
            available.add(DATASET_SIX_MAX)
        return available

    def _choose_dataset(self, saved: str | None) -> str:
        available = self._available_datasets()
        if saved in available:
            return saved
        if DATASET_SIX_MAX in available:
            return DATASET_SIX_MAX
        if DATASET_HEADS_UP in available:
            return DATASET_HEADS_UP
        raise ValueError("No spots are available.")

    def _save_dataset(self, conn: sqlite3.Connection, dataset_id: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('dataset', ?)",
            (dataset_id,),
        )

    def datasets(self) -> list[dict]:
        library_total = self.library.total if self.library is not None else 0
        six_max_ready = library_total > 0
        rows = [
            {
                "id": DATASET_SIX_MAX,
                "name": SIX_MAX_NAME,
                "detail": SIX_MAX_DETAIL if six_max_ready else "The 6-max library is not in the learn_poker folder.",
                "spots": library_total,
                "available": six_max_ready,
            },
            {
                "id": DATASET_HEADS_UP,
                "name": self.study_meta["name"],
                "detail": self.study_meta["detail"],
                "spots": len(self.spots),
                "available": bool(self.spots),
            },
        ]
        for row in rows:
            row["active"] = row["id"] == self.dataset_id
        return rows

    def set_dataset(self, dataset_id: str) -> dict:
        dataset_id = str(dataset_id or "")
        known = {row["id"]: row for row in self.datasets()}
        choice = known.get(dataset_id)
        if choice is None:
            raise ValueError("Unknown dataset.")
        if not choice["available"]:
            raise ValueError("That dataset is not available.")
        self.dataset_id = dataset_id
        with self._conn() as conn:
            self._save_dataset(conn, dataset_id)
        return self.dashboard()

    def dashboard(self) -> dict:
        with self._conn() as conn:
            stats = {
                row["phase"]: {"total_hands": row["total_hands"], "avg_score": row["avg_score"]}
                for row in conn.execute(
                    """
                    SELECT phase, COUNT(*) AS total_hands, AVG(norm_score) AS avg_score
                    FROM attempts
                    WHERE dataset = ?
                    GROUP BY phase
                    """,
                    (self.dataset_id,),
                )
            }
            overall = conn.execute(
                "SELECT COUNT(*) AS n, AVG(norm_score) AS avg_score FROM attempts WHERE dataset = ?",
                (self.dataset_id,),
            ).fetchone()
            recent_rows = conn.execute(
                """
                SELECT id, timestamp, phase, situation_hash, norm_score
                FROM attempts
                WHERE dataset = ?
                ORDER BY id DESC
                LIMIT 8
                """,
                (self.dataset_id,),
            ).fetchall()
        phases = []
        for phase in PHASES:
            row = stats.get(phase, {"total_hands": 0, "avg_score": None})
            phases.append({
                "id": phase,
                "label": PHASE_LABELS[phase],
                "total_hands": row["total_hands"],
                "avg_score": row["avg_score"],
            })
        datasets = self.datasets()
        current = next(row for row in datasets if row["active"])
        if self._library_active():
            counts = self.library.counts
            kicker = "6-max"
        else:
            counts = {phase: 0 for phase in PHASES}
            for spot in self.spots:
                counts[spot["phase"]] += 1
            kicker = "Heads-up"
        modes = [
            {"id": phase, "label": PHASE_LABELS[phase], "detail": f"{counts[phase]:,} spots"}
            for phase in PHASES
        ]
        modes.append({"id": "mix", "label": "Random Mix", "detail": "All streets"})
        modes.append({"id": "grind", "label": "The Grind", "detail": "Bottom 5%"})
        recent = []
        for row in recent_rows:
            spot = self._get(row["situation_hash"])
            recent.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "phase": row["phase"],
                "phase_label": PHASE_LABELS.get(row["phase"], row["phase"]),
                "title": (spot.get("title") or spot["text"]) if spot else row["situation_hash"],
                "norm_score": row["norm_score"],
            })
        return {
            "phases": phases,
            "overall": {"total_hands": overall["n"] or 0, "avg_score": overall["avg_score"]},
            "recent": recent,
            "modes": modes,
            "note": current["detail"],
            "kicker": kicker,
            "dataset": {
                "id": current["id"],
                "name": current["name"],
                "detail": current["detail"],
            },
            "datasets": datasets,
        }

    def _get(self, spot_id: str) -> dict | None:
        if self._library_active():
            return self.library.get(spot_id)
        return self.by_id.get(spot_id)

    def next_hand(self, mode: str, exclude: str | None = None) -> dict:
        if mode not in MODES:
            raise ValueError("Unknown mode.")
        if mode == "grind":
            pool = [spot for spot in (self._get(spot_id) for spot_id in self._worst_ids()) if spot]
        elif self._library_active():
            spot = self.library.pick(None if mode == "mix" else mode, self.rng, exclude)
            if spot is None:
                raise ValueError("No spots in that mode.")
            return public_hand(spot)
        elif mode == "mix":
            pool = list(self.spots)
        else:
            pool = [spot for spot in self.spots if spot["phase"] == mode]
        if exclude and len(pool) > 1:
            filtered = [spot for spot in pool if spot["id"] != exclude]
            pool = filtered or pool
        if not pool:
            raise ValueError("No spots in that mode.")
        return public_hand(self.rng.choice(pool))

    def _worst_ids(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT situation_hash AS id, AVG(norm_score) AS avg_score
                FROM attempts
                WHERE dataset = ?
                GROUP BY situation_hash
                """,
                (self.dataset_id,),
            ).fetchall()
        known = [row for row in rows if self._get(row["id"])]
        if not known:
            raise NeedHistory("Play a few hands first. The Grind uses your worst spots.")
        known.sort(key=lambda row: (row["avg_score"], row["id"]))
        keep = max(1, math.ceil(len(known) * 0.05))
        return [row["id"] for row in known[:keep]]

    def submit(self, situation_id: str, raw_points: dict) -> dict:
        spot = self._get(situation_id)
        if spot is None:
            raise KeyError(situation_id)
        actions = [action["key"] for action in spot["actions"]]
        points = _parse_points(raw_points, actions)
        ce, norm = score_guess(spot["gto"], points)
        user_answers = percent_map(points, actions)
        true_answers = {action: spot["gto"][action] for action in actions}
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO attempts (
                    timestamp, phase, situation_hash, user_answers, true_answers,
                    ce_score, norm_score, dataset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    spot["phase"],
                    spot["id"],
                    json.dumps(user_answers),
                    json.dumps(true_answers),
                    ce,
                    norm,
                    self.dataset_id,
                ),
            )
            _update_stats(conn, spot["phase"], norm)
            attempt_id = cursor.lastrowid
        xp = round(norm * 100)
        return {
            "attempt_id": attempt_id,
            "situation_id": spot["id"],
            "phase": spot["phase"],
            "phase_label": PHASE_LABELS[spot["phase"]],
            "ce_score": ce,
            "norm_score": norm,
            "label": label_for(norm),
            "xp": xp,
            "actions": [{"key": action["key"], "label": action["label"]} for action in spot["actions"]],
            "user": user_answers,
            "gto": true_answers,
        }


def _parse_points(raw: dict, actions: list[str]) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("Points must be an object.")
    unknown = set(raw) - set(actions)
    if unknown:
        raise ValueError("Unknown action.")
    points = {}
    for action in actions:
        value = raw.get(action, 0)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Points must be whole numbers.")
        if value < 0:
            raise ValueError("Points cannot go below 0.")
        if value > 10000:
            raise ValueError("Points are too large.")
        points[action] = value
    if sum(points.values()) < MIN_POINTS:
        raise ValueError("Add at least one point.")
    return points


def _update_stats(conn: sqlite3.Connection, phase: str, norm: float) -> None:
    row = conn.execute("SELECT total_hands, avg_score FROM user_stats WHERE phase = ?", (phase,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO user_stats (phase, total_hands, avg_score) VALUES (?, 1, ?)",
            (phase, norm),
        )
        return
    count = row["total_hands"] + 1
    average = (row["avg_score"] * row["total_hands"] + norm) / count
    conn.execute(
        "UPDATE user_stats SET total_hands = ?, avg_score = ? WHERE phase = ?",
        (count, average, phase),
    )
