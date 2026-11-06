"""Turn the public PokerBench tables into trainer spots.

PokerBench (Apache-2.0) is 6-max no-limit hold'em. Preflop labels come from
solver charts and postflop labels from a postflop solver. Each row names one
chosen action, not the rest of the mix, so that action is stored at 100% and
every other listed action at 0%.

Source: https://huggingface.co/datasets/RZ412/PokerBench
"""

from __future__ import annotations

import ast
import csv
import re
import sqlite3
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from engine import SpotLibrary, default_library_path

FILES = (
    (
        "preflop",
        "pre-train",
        "https://huggingface.co/datasets/RZ412/PokerBench/resolve/main/preflop_60k_train_set_game_scenario_information.csv",
    ),
    (
        "preflop",
        "pre-test",
        "https://huggingface.co/datasets/RZ412/PokerBench/resolve/main/preflop_1k_test_set_game_scenario_information.csv",
    ),
    (
        "postflop",
        "post-train",
        "https://huggingface.co/datasets/RZ412/PokerBench/resolve/main/postflop_500k_train_set_game_scenario_information.csv",
    ),
    (
        "postflop",
        "post-test",
        "https://huggingface.co/datasets/RZ412/PokerBench/resolve/main/postflop_10k_test_set_game_scenario_information.csv",
    ),
)

POSITIONS = {"UTG", "HJ", "CO", "BTN", "SB", "BB"}
RANKS = set("23456789TJQKA")
SUITS = set("shdc")
_BET = re.compile(r"(?i)^bet\s+([0-9]+(?:\.[0-9]+)?)$")
_RAISE = re.compile(r"(?i)^raise\s+([0-9]+(?:\.[0-9]+)?)$")
_SIZE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)bb$")


def pretty_number(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text


def split_cards(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    cards = []
    index = 0
    while index < len(raw):
        rank = raw[index]
        suit = raw[index + 1] if index + 1 < len(raw) else ""
        if rank not in RANKS or suit not in SUITS:
            raise ValueError(f"Bad card in {raw!r}.")
        cards.append(rank + suit)
        index += 2
    return cards


def _classify(move: str) -> tuple[str, str, tuple]:
    raw = move.strip()
    low = raw.lower()
    if low == "fold":
        return "fold", "Fold", (0, 0.0)
    if low == "check":
        return "check", "Check", (1, 0.0)
    if low == "call":
        return "call", "Call", (2, 0.0)
    if low in {"allin", "all-in", "jam"}:
        return "jam", "Jam", (5, 0.0)
    bet = _BET.match(raw)
    if bet:
        number = pretty_number(bet.group(1))
        return f"bet-{number}", f"Bet {number}bb", (3, float(number))
    raised = _RAISE.match(raw)
    if raised:
        number = pretty_number(raised.group(1))
        return f"raise-{number}", f"Raise {number}bb", (4, float(number))
    size = _SIZE.match(low)
    if size:
        number = pretty_number(size.group(1))
        return f"raise-{number}", f"Raise {number}bb", (4, float(number))
    raise ValueError(f"Unknown action {raw!r}.")


def build_menu(moves, correct: str) -> tuple[list[dict], dict] | None:
    correct = str(correct).strip()
    listed = [str(move).strip() for move in moves]
    if correct not in listed:
        listed.append(correct)
    seen = {}
    correct_key = None
    for move in listed:
        key, label, rank = _classify(move)
        if key not in seen:
            seen[key] = (rank, key, label)
        if move == correct:
            correct_key = key
    if correct_key is None or len(seen) < 2 or correct_key not in seen:
        return None
    ordered = sorted(seen.values(), key=lambda item: (item[0], item[2]))
    actions = [{"key": key, "label": label} for _rank, key, label in ordered]
    gto = {action["key"]: (100 if action["key"] == correct_key else 0) for action in actions}
    return actions, gto


def _hero_clause(position: str) -> str:
    names = {
        "IP": "Hero is in position",
        "OOP": "Hero is out of position",
        "BTN": "Hero is on the button",
        "SB": "Hero is in the small blind",
        "BB": "Hero is in the big blind",
        "UTG": "Hero is under the gun",
        "HJ": "Hero is in the hijack",
        "CO": "Hero is in the cutoff",
    }
    return names.get(position, f"Hero is in {position}")


def _preflop_phrases(line: str) -> list[str]:
    if not line:
        return []
    tokens = line.split("/")
    if len(tokens) % 2:
        raise ValueError("The preflop line is uneven.")
    phrases = []
    raised = False
    for index in range(0, len(tokens), 2):
        position, action = tokens[index], tokens[index + 1]
        if position not in POSITIONS:
            raise ValueError(f"Unknown seat {position}.")
        low = action.lower()
        if low == "fold":
            phrases.append(f"{position} folds")
        elif low == "call":
            phrases.append(f"{position} calls")
        elif low == "check":
            phrases.append(f"{position} checks")
        elif low == "allin":
            phrases.append(f"{position} jams")
            raised = True
        elif low.endswith("bb"):
            size = pretty_number(low[:-2]) + "bb"
            verb = "raises to" if raised else "opens to"
            phrases.append(f"{position} {verb} {size}")
            raised = True
        else:
            raise ValueError(f"Unknown preflop action {action}.")
    return phrases


def _side_name(side: str) -> str:
    if side == "OOP":
        return "Out of position"
    if side == "IP":
        return "In position"
    return side


def _postflop_events(action: str) -> list[tuple]:
    if not action:
        return []
    parts = action.split("/")
    events = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "dealcards":
            if index + 1 >= len(parts):
                raise ValueError("A dealt card is missing.")
            events.append(("card", split_cards(parts[index + 1])))
            index += 2
            continue
        side, sep, rest = token.partition("_")
        if not sep:
            raise ValueError(f"Bad postflop token {token}.")
        who = _side_name(side)
        if rest == "CHECK":
            events.append(("act", f"{who} checks"))
        elif rest == "CALL":
            events.append(("act", f"{who} calls"))
        elif rest == "FOLD":
            events.append(("act", f"{who} folds"))
        elif rest.startswith("BET_"):
            events.append(("act", f"{who} bets {pretty_number(rest[4:])}bb"))
        elif rest.startswith("RAISE_"):
            events.append(("act", f"{who} raises to {pretty_number(rest[6:])}bb"))
        elif rest in {"ALLIN", "JAM"}:
            events.append(("act", f"{who} jams"))
        else:
            raise ValueError(f"Bad postflop action {token}.")
        index += 1
    return events


def _sentences(parts: list[str]) -> str:
    lines = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        lines.append(text[0].upper() + text[1:])
    return " ".join(lines)


def spot_from_preflop(row: dict) -> dict | None:
    hero = split_cards(row["hero_holding"])
    if len(hero) != 2:
        raise ValueError("Hero needs two cards.")
    menu = build_menu(ast.literal_eval(row["available_moves"]), row["correct_decision"])
    if menu is None:
        return None
    actions, gto = menu
    position = row["hero_pos"]
    phrases = _preflop_phrases(row.get("prev_line") or "")
    parts = ["6-max cash, 100bb deep"]
    if phrases:
        parts.extend(phrases)
    else:
        parts.append(f"{_hero_clause(position)} and is first to act")
    parts.append(f"{_hero_clause(position)} and holds {hero[0]} {hero[1]}")
    players = int(float(row["num_players"]))
    pot = pretty_number(row["pot_size"])
    if players > 1:
        parts.append(f"{players} players are still in. The pot is {pot}bb")
    else:
        parts.append(f"The pot is {pot}bb")
    return {
        "phase": "preflop",
        "title": f"Preflop · {position} · {hero[0]} {hero[1]}",
        "text": _sentences(parts),
        "hero": hero,
        "board": [],
        "actions": actions,
        "gto": gto,
    }


def spot_from_postflop(row: dict) -> dict | None:
    phase = (row.get("evaluation_at") or "").strip().lower()
    if phase not in {"flop", "turn", "river"}:
        raise ValueError("Unknown street.")
    hero = split_cards(row["holding"])
    if len(hero) != 2:
        raise ValueError("Hero needs two cards.")
    flop = split_cards(row["board_flop"])
    if len(flop) != 3:
        raise ValueError("The flop needs three cards.")
    menu = build_menu(ast.literal_eval(row["available_moves"]), row["correct_decision"])
    if menu is None:
        return None
    actions, gto = menu
    board = list(flop)
    street = "flop"
    street_actions: list[str] = []
    parts = ["6-max cash, 100bb deep"]
    parts.extend(_preflop_phrases(row.get("preflop_action") or ""))
    names = {"flop": "flop", "turn": "turn", "river": "river"}

    def flush() -> None:
        shown = " ".join(board if street == "flop" else board[-1:])
        if street == "flop":
            shown = " ".join(flop)
        parts.append(f"The {names[street]} is {shown}")
        parts.extend(street_actions)

    for kind, payload in _postflop_events(row.get("postflop_action") or ""):
        if kind == "card":
            flush()
            dealt = payload
            if len(dealt) != 1:
                raise ValueError("One card is dealt at a time.")
            board.extend(dealt)
            street = "turn" if len(board) == 4 else "river"
            street_actions = []
        else:
            street_actions.append(payload)
    flush()
    parts.append(f"{_hero_clause(row['hero_position'])} and holds {hero[0]} {hero[1]}")
    parts.append(f"The pot is {pretty_number(row['pot_size'])}bb")
    label = phase.capitalize() if phase != "flop" else "Flop"
    if phase == "turn":
        label = "Turn"
    elif phase == "river":
        label = "River"
    return {
        "phase": phase,
        "title": f"{label} · {row['hero_position']} · {hero[0]} {hero[1]}",
        "text": _sentences(parts),
        "hero": hero,
        "board": board,
        "actions": actions,
        "gto": gto,
    }


def _download(url: str, dest: Path) -> None:
    """Save a complete file. A failed transfer leaves the previous file untouched."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".part")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": "learn-poker"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
            expected = response.headers.get("Content-Length")
            written = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
        if expected is not None and written != int(expected):
            raise OSError(f"Incomplete download of {dest.name}: {written} of {expected} bytes.")
        temporary.replace(dest)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def library_ready(path: Path) -> bool:
    """True when spots.sqlite has at least one indexed spot."""
    target = Path(path)
    if not target.is_file() or target.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(target)
        try:
            rows = conn.execute("SELECT phase, COUNT(*) AS n FROM spots GROUP BY phase").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return sum(row[1] for row in rows) > 0


def _rows(path: Path, kind: str, prefix: str):
    convert = spot_from_preflop if kind == "preflop" else spot_from_postflop
    kept = 0
    skipped = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            try:
                spot = convert(row)
            except (ValueError, SyntaxError, KeyError, IndexError):
                skipped += 1
                continue
            if spot is None:
                skipped += 1
                continue
            spot["id"] = f"{prefix}-{index}"
            kept += 1
            if kept % 50000 == 0:
                print(f"{prefix}: {kept:,} spots", flush=True)
            yield spot
    print(f"{prefix}: kept {kept:,}, skipped {skipped:,}", flush=True)


def ensure_library(dest: Path | None = None) -> Path | None:
    """Download the 6-max library when spots.sqlite is missing or unusable."""
    target = Path(dest or default_library_path())
    if library_ready(target):
        return target
    print(f"Dataset missing. Downloading 6-max 100bb spots into {target}", flush=True)
    try:
        return import_pokerbench(dest=target)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError, sqlite3.Error):
        traceback.print_exc()
        print("Could not download the 6-max dataset. Starting without it.", file=sys.stderr)
        return None


def import_pokerbench(dest: Path | None = None, cache: Path | None = None) -> Path:
    """Download the four PokerBench tables and write the spot library."""
    target = Path(dest or default_library_path())
    folder = cache or target.parent / "_pokerbench_csv"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for _kind, _prefix, url in FILES:
        name = url.rsplit("/", 1)[-1]
        path = folder / name
        if not path.exists() or path.stat().st_size == 0:
            print(f"Downloading {name}", flush=True)
            _download(url, path)
        paths.append(path)

    def spots():
        for (kind, prefix, url), path in zip(FILES, paths):
            yield from _rows(path, kind, prefix)

    print(f"Writing {target}", flush=True)
    SpotLibrary.build(target, spots())
    return target


if __name__ == "__main__":
    library = import_pokerbench()
    print(library)
