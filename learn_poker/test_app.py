"""Checks for frequency scoring, saved attempts, and one local HTTP session."""

from __future__ import annotations

import json
import random
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import engine
import server
import pokerbench


def _write_spot_library(path: Path) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE spots (phase TEXT)")
    conn.execute("INSERT INTO spots (phase) VALUES ('preflop')")
    conn.commit()
    conn.close()
from engine import (
    DATASET_HEADS_UP,
    DATASET_SIX_MAX,
    Engine,
    NeedHistory,
    SpotLibrary,
    default_db_path,
    default_library_path,
    label_for,
    load_spots,
    read_study,
    score_guess,
    situation_rows,
)
from pokerbench import spot_from_postflop, spot_from_preflop


class RulesTest(unittest.TestCase):
    def test_spot_file_is_complete(self):
        spots = load_spots()
        phases = {phase: 0 for phase in engine.PHASES}
        for spot in spots:
            phases[spot["phase"]] += 1
            self.assertEqual(sum(spot["gto"].values()), 100)
        for phase, count in phases.items():
            self.assertGreaterEqual(count, 4, phase)
        facing = [spot for spot in spots if spot["line"] == "facing"]
        checked = [spot for spot in spots if spot["line"] == "checked"]
        self.assertTrue(facing)
        self.assertTrue(checked)
        for spot in facing:
            labels = [action["label"] for action in spot["actions"]]
            self.assertEqual(labels[:2], ["Fold", "Call"])
            self.assertGreaterEqual(sum(1 for label in labels if "Raise" in label or label == "Jam"), 2)
        for spot in checked:
            labels = [action["label"] for action in spot["actions"]]
            self.assertEqual(labels[0], "Check")
            self.assertGreaterEqual(sum(1 for label in labels if label.startswith("Bet") or label == "Jam"), 3)
        opens = [spot for spot in spots if spot["line"] == "open"]
        self.assertTrue(all(spot["actions"][0]["label"] == "Fold" for spot in opens))

    def test_perfect_guess_scores_one(self):
        gto = {"fold": 20, "call": 50, "raise": 30}
        distance, norm = score_guess(gto, {"fold": 2, "call": 5, "raise": 3})
        self.assertAlmostEqual(norm, 1.0, places=6)
        self.assertAlmostEqual(distance, 0.0, places=6)

    def test_points_are_shares_of_any_total(self):
        pure = score_guess({"fold": 0, "call": 100}, {"fold": 1, "call": 0})
        self.assertAlmostEqual(pure[0], 1.0, places=6)
        mixed = score_guess({"fold": 75, "call": 25}, {"fold": 3, "call": 1})
        self.assertAlmostEqual(mixed[1], 1.0, places=6)
        _distance, close = score_guess(
            {"fold": 5, "call": 35, "raise": 60},
            {"fold": 0, "call": 36, "raise": 64},
        )
        self.assertAlmostEqual(close, 0.95, places=6)
        self.assertEqual(label_for(close), "Perfect")

    def test_missing_a_real_action_is_the_share_that_moved(self):
        _distance, norm = score_guess({"fold": 20, "call": 50, "raise": 30}, {"fold": 10, "call": 0, "raise": 0})
        self.assertAlmostEqual(norm, 0.2, places=6)

    def test_empty_guess_is_rejected(self):
        with self.assertRaises(ValueError):
            score_guess({"fold": 50, "call": 50}, {"fold": 0, "call": 0})


class PlayTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = Engine(Path(self.folder.name) / "poker_trainer.db", rng=random.Random(4))

    def tearDown(self):
        self.folder.cleanup()

    def test_hand_hides_the_answer(self):
        hand = self.engine.next_hand("flop")
        self.assertEqual(hand["phase"], "flop")
        self.assertNotIn("gto", json.dumps(hand))
        self.assertGreaterEqual(len(hand["actions"]), 2)
        self.assertTrue(hand["rows"])
        self.assertTrue(hand["text"].startswith(hand["rows"][0]["text"].rstrip(".")))

    def test_submit_updates_stats_and_grind(self):
        misses = self.engine.by_id["pf-22-btn"]
        hits = self.engine.by_id["pf-k9o-bb"]
        bad = self.engine.submit(misses["id"], {"fold": 10})
        good_points = {key: value for key, value in hits["gto"].items()}
        good = self.engine.submit(hits["id"], good_points)
        self.assertLess(bad["norm_score"], 0.2)
        self.assertAlmostEqual(good["norm_score"], 1.0, places=6)
        self.assertEqual(sum(good["user"].values()), 100)
        board = self.engine.dashboard()
        preflop = next(row for row in board["phases"] if row["id"] == "preflop")
        self.assertEqual(preflop["total_hands"], 2)
        self.assertAlmostEqual(preflop["avg_score"], (bad["norm_score"] + good["norm_score"]) / 2)
        worst = self.engine._worst_ids()
        self.assertEqual(worst, [misses["id"]])
        replay = self.engine.next_hand("grind")
        self.assertEqual(replay["id"], misses["id"])

    def test_grind_needs_history(self):
        with self.assertRaises(NeedHistory):
            self.engine.next_hand("grind")

    def test_points_cannot_be_negative(self):
        with self.assertRaises(ValueError):
            self.engine.submit("pf-kto-jam", {"fold": 12, "jam": -2})

    def test_old_cross_entropy_rows_are_rescored(self):
        path = Path(self.folder.name) / "poker_trainer.db"
        conn = engine.sqlite3.connect(path)
        conn.execute(
            """
            INSERT INTO attempts (
                timestamp, phase, situation_hash, user_answers, true_answers, ce_score, norm_score, dataset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t",
                "preflop",
                "pf-22-btn",
                json.dumps({"fold": 0, "limp": 36, "raise": 64}),
                json.dumps({"fold": 5, "limp": 25, "raise": 70}),
                12.0,
                0.0,
                DATASET_HEADS_UP,
            ),
        )
        conn.commit()
        conn.close()
        reopened = Engine(path, spots=self.engine.spots, rng=random.Random(1))
        preflop = next(row for row in reopened.dashboard()["phases"] if row["id"] == "preflop")
        self.assertEqual(preflop["total_hands"], 1)
        self.assertAlmostEqual(preflop["avg_score"], 0.89, places=2)


class HttpTest(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            server.ENGINE = Engine(Path(folder) / "poker_trainer.db", rng=random.Random(2))
            handler = server.make_handler(BaseHTTPRequestHandler)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
                self.assertIn("Learn Poker", page)
                script = urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js").read().decode("utf-8")
                self.assertIn("LOCK IN", script)
                self.assertIn("Settings", script)
                css = urllib.request.urlopen(f"http://127.0.0.1:{port}/style.css").read().decode("utf-8")
                self.assertIn("--bg", css)
                board = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dashboard"))
                self.assertEqual(board["dataset"]["id"], DATASET_HEADS_UP)
                self.assertIn("mixed", board["dataset"]["name"].lower())
                self.assertEqual([mode["id"] for mode in board["modes"]], ["preflop", "flop", "turn", "river", "mix", "grind"])
                hand = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hand?mode=preflop"))
                self.assertNotIn("gto", hand)
                points = {action["key"]: 0 for action in hand["actions"]}
                short = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/submit",
                    data=json.dumps({"id": hand["id"], "points": points}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(short)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
                spot = server.ENGINE.by_id[hand["id"]]
                answered = json.load(urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/submit",
                    data=json.dumps({"id": hand["id"], "points": spot["gto"]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )))
                self.assertAlmostEqual(answered["norm_score"], 1.0, places=6)
                grind = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hand?mode=grind")
                replay = json.load(grind)
                self.assertEqual(replay["id"], hand["id"])
                switched = json.load(urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/settings",
                    data=json.dumps({"dataset": DATASET_HEADS_UP}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )))
                self.assertEqual(switched["dataset"]["name"], board["dataset"]["name"])
                missing = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/settings",
                    data=json.dumps({"dataset": DATASET_SIX_MAX}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    urllib.request.urlopen(missing)
                self.assertEqual(blocked.exception.code, 400)
                blocked.exception.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


class SituationRowTest(unittest.TestCase):
    def test_preflop_rows_show_chips_added_and_the_pot(self):
        text = (
            "6-max cash, 100bb deep. "
            "UTG opens to 2bb. "
            "BTN raises to 7.5bb. "
            "SB raises to 20bb. "
            "BB calls. "
            "UTG folds. "
            "BTN jams. "
            "Hero is in the small blind and holds As Ac. "
            "4 players are still in. "
            "The pot is 142bb."
        )
        rows = {row["text"]: row for row in situation_rows(text)}
        self.assertEqual(rows["6-max cash, 100bb deep."]["pot"], "1.5bb")
        self.assertEqual(rows["UTG opens to 2bb."]["actor"], "UTG")
        self.assertEqual(rows["UTG opens to 2bb."]["bet"], "2bb")
        self.assertEqual(rows["UTG opens to 2bb."]["pot"], "3.5bb")
        self.assertEqual(rows["BTN jams."]["actor"], "BTN")
        self.assertEqual(rows["UTG folds."]["actor"], "UTG")
        self.assertEqual(rows["The pot is 142bb."]["actor"], "")
        self.assertEqual(rows["BTN raises to 7.5bb."]["bet"], "7.5bb")
        self.assertEqual(rows["SB raises to 20bb."]["bet"], "19.5bb")
        self.assertEqual(rows["SB raises to 20bb."]["pot"], "30.5bb")
        self.assertEqual(rows["BB calls."]["bet"], "19bb")
        self.assertEqual(rows["BB calls."]["pot"], "49.5bb")
        self.assertEqual(rows["UTG folds."]["bet"], "")
        self.assertEqual(rows["UTG folds."]["pot"], "")
        self.assertEqual(rows["BTN jams."]["bet"], "92.5bb")
        self.assertEqual(rows["BTN jams."]["pot"], "142bb")
        self.assertEqual(rows["The pot is 142bb."]["pot"], "")

    def test_postflop_rows_follow_bets_and_calls(self):
        spot = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/call",
            "board_flop": "6s8d7c",
            "board_turn": "9s",
            "board_river": "2c",
            "aggressor_position": "IP",
            "postflop_action": "OOP_CHECK/IP_CHECK/dealcards/9s/OOP_BET_5/IP_RAISE_16",
            "evaluation_at": "Turn",
            "available_moves": "['Fold', 'Call']",
            "pot_size": "27",
            "hero_position": "OOP",
            "holding": "Tc9c",
            "correct_decision": "Call",
        })
        rows = situation_rows(spot["text"])
        money = [(row["text"], row["actor"], row["bet"], row["pot"]) for row in rows if row["actor"] or row["bet"] or row["pot"]]
        self.assertEqual(money, [
            ("6-max cash, 100bb deep.", "", "", "1.5bb"),
            ("SB opens to 3bb.", "SB", "2.5bb", "4bb"),
            ("BB calls.", "BB", "2bb", "6bb"),
            ("Out of position checks.", "OOP", "", ""),
            ("In position checks.", "IP", "", ""),
            ("Out of position bets 5bb.", "OOP", "5bb", "11bb"),
            ("In position raises to 16bb.", "IP", "16bb", "27bb"),
        ])

    def test_a_folded_small_blind_stays_out_when_the_stated_pot_omits_it(self):
        text = (
            "6-max cash, 100bb deep. "
            "HJ opens to 2bb. "
            "BB calls. "
            "The flop is Jc Jh 4s. "
            "Out of position checks. "
            "In position bets 1bb. "
            "The pot is 5bb."
        )
        rows = {row["text"]: row for row in situation_rows(text)}
        self.assertEqual(rows["6-max cash, 100bb deep."]["pot"], "1bb")
        self.assertEqual(rows["HJ opens to 2bb."]["pot"], "3bb")
        self.assertEqual(rows["BB calls."]["bet"], "1bb")
        self.assertEqual(rows["BB calls."]["pot"], "4bb")
        self.assertEqual(rows["In position bets 1bb."]["bet"], "1bb")
        self.assertEqual(rows["In position bets 1bb."]["pot"], "5bb")
        self.assertEqual(rows["Out of position checks."]["actor"], "OOP")
        self.assertEqual(rows["Out of position checks."]["bet"], "")
        self.assertEqual(rows["Out of position checks."]["pot"], "")
        self.assertEqual(rows["In position bets 1bb."]["actor"], "IP")

    def test_study_rows_keep_the_size_written_in_the_sentence(self):
        text = "50bb effective. Hero faces a 33% c-bet into a 5.5bb pot and holds 7s 6s."
        rows = situation_rows(text)
        self.assertEqual(rows[0]["bet"], "")
        self.assertEqual(rows[0]["pot"], "")
        self.assertEqual(rows[1]["actor"], "Villain")
        self.assertEqual(rows[1]["bet"], "33%")
        self.assertEqual(rows[1]["pot"], "5.5bb")


class PokerBenchTest(unittest.TestCase):
    def test_preflop_menu_uses_the_listed_sizes(self):
        spot = spot_from_preflop({
            "prev_line": "",
            "hero_pos": "SB",
            "hero_holding": "QdJc",
            "correct_decision": "3.0bb",
            "num_players": "1",
            "num_bets": "0",
            "available_moves": "['3.0bb', 'call', 'fold']",
            "pot_size": "1.5",
        })
        self.assertEqual([action["label"] for action in spot["actions"]], ["Fold", "Call", "Raise 3bb"])
        self.assertEqual(spot["gto"]["raise-3"], 100)
        self.assertEqual(spot["hero"], ["Qd", "Jc"])
        self.assertEqual(sum(spot["gto"].values()), 100)

    def test_a_single_legal_action_is_not_a_spot(self):
        spot = spot_from_preflop({
            "prev_line": "SB/call/BB/5.0bb",
            "hero_pos": "SB",
            "hero_holding": "5s5c",
            "correct_decision": "fold",
            "num_players": "2",
            "num_bets": "1",
            "available_moves": "['fold']",
            "pot_size": "5.0",
        })
        self.assertIsNone(spot)

    def test_future_board_cards_stay_hidden(self):
        flop = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/call",
            "board_flop": "5c5dAh",
            "board_turn": "3h",
            "board_river": "Kh",
            "aggressor_position": "OOP",
            "postflop_action": "OOP_BET_2",
            "evaluation_at": "Flop",
            "available_moves": "['Fold', 'Call', 'Raise 9']",
            "pot_size": "8",
            "hero_position": "IP",
            "holding": "Ad4h",
            "correct_decision": "Call",
        })
        self.assertEqual(flop["board"], ["5c", "5d", "Ah"])
        self.assertNotIn("3h", flop["text"])
        self.assertNotIn("Kh", flop["text"])
        self.assertEqual(flop["gto"]["call"], 100)

        turn = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/10.0bb/SB/call",
            "board_flop": "Ks7h2d",
            "board_turn": "Jc",
            "board_river": "7c",
            "aggressor_position": "IP",
            "postflop_action": "OOP_CHECK/IP_BET_10/OOP_CALL/dealcards/Jc/OOP_CHECK/IP_BET_44/OOP_RAISE_80",
            "evaluation_at": "Turn",
            "available_moves": "['Fold', 'Call']",
            "pot_size": "164",
            "hero_position": "IP",
            "holding": "AhQd",
            "correct_decision": "Call",
        })
        self.assertEqual(turn["board"], ["Ks", "7h", "2d", "Jc"])
        self.assertNotIn("7c", turn["text"])
        self.assertIn("The turn is Jc.", turn["text"])

    def test_library_serves_spots_without_loading_the_answer(self):
        flop = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/call",
            "board_flop": "5c5dAh",
            "board_turn": "3h",
            "board_river": "Kh",
            "aggressor_position": "OOP",
            "postflop_action": "OOP_BET_2",
            "evaluation_at": "Flop",
            "available_moves": "['Fold', 'Call', 'Raise 9']",
            "pot_size": "8",
            "hero_position": "IP",
            "holding": "Ad4h",
            "correct_decision": "Call",
        })
        flop["id"] = "flop-1"
        pre = spot_from_preflop({
            "prev_line": "",
            "hero_pos": "SB",
            "hero_holding": "QdJc",
            "correct_decision": "3.0bb",
            "num_players": "1",
            "available_moves": "['3.0bb', 'call', 'fold']",
            "pot_size": "1.5",
        })
        pre["id"] = "pre-1"
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / "spots.sqlite"
            self.assertEqual(SpotLibrary.build(library, [flop, pre]), 2)
            trainer = Engine(Path(folder) / "attempts.sqlite", library=library, rng=random.Random(1))
            hand = trainer.next_hand("flop")
            self.assertEqual(hand["board"], ["5c", "5d", "Ah"])
            self.assertNotIn("gto", json.dumps(hand))
            stored = trainer.library.get(hand["id"])
            scored = trainer.submit(hand["id"], stored["gto"])
            self.assertAlmostEqual(scored["norm_score"], 1.0, places=6)
            board = trainer.dashboard()
            self.assertEqual(board["kicker"], "6-max")
            flop_mode = next(mode for mode in board["modes"] if mode["id"] == "flop")
            self.assertEqual(flop_mode["detail"], "1 spots")
            trainer.library.close()


class DatasetTest(unittest.TestCase):
    def test_study_answers_are_frequency_mixes(self):
        spots, meta = read_study()
        self.assertIn("Heads-up", meta["name"])
        self.assertIn("BTN", meta["name"])
        self.assertIn("mixed", meta["name"].lower())
        mixed = [
            spot for spot in spots
            if sum(1 for value in spot["gto"].values() if value > 0) >= 2
        ]
        self.assertEqual(mixed, spots)

    def test_six_max_library_is_one_action_and_can_be_switched_off(self):
        flop = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/call",
            "board_flop": "5c5dAh",
            "board_turn": "3h",
            "board_river": "Kh",
            "aggressor_position": "OOP",
            "postflop_action": "OOP_BET_2",
            "evaluation_at": "Flop",
            "available_moves": "['Fold', 'Call', 'Raise 9']",
            "pot_size": "8",
            "hero_position": "IP",
            "holding": "Ad4h",
            "correct_decision": "Call",
        })
        flop["id"] = "flop-mix-check"
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / "spots.sqlite"
            self.assertEqual(SpotLibrary.build(library, [flop]), 1)
            db = Path(folder) / "poker_trainer.db"
            trainer = Engine(db, library=library, rng=random.Random(1))
            try:
                self.assertEqual(trainer.dataset_id, DATASET_SIX_MAX)
                self.assertIn("6-max", trainer.dashboard()["dataset"]["name"])
                self.assertIn("100bb", trainer.dashboard()["dataset"]["name"])
                pure = trainer._get(trainer.next_hand("flop")["id"])
                self.assertEqual(sum(1 for value in pure["gto"].values() if value > 0), 1)
                board = trainer.set_dataset(DATASET_HEADS_UP)
                self.assertEqual(board["dataset"]["id"], DATASET_HEADS_UP)
                mixed = trainer._get(trainer.next_hand("preflop")["id"])
                self.assertGreater(sum(1 for value in mixed["gto"].values() if value > 0), 1)
                trainer.submit(mixed["id"], mixed["gto"])
                self.assertEqual(trainer.dashboard()["overall"]["total_hands"], 1)
                trainer.set_dataset(DATASET_SIX_MAX)
                self.assertEqual(trainer.dashboard()["overall"]["total_hands"], 0)
                reopened = Engine(db, library=library, rng=random.Random(2))
                try:
                    self.assertEqual(reopened.dataset_id, DATASET_SIX_MAX)
                finally:
                    reopened.library.close()
            finally:
                trainer.library.close()

    def test_old_attempts_remain_on_the_six_max_dataset(self):
        flop = spot_from_postflop({
            "preflop_action": "SB/3.0bb/BB/call",
            "board_flop": "5c5dAh",
            "board_turn": "3h",
            "board_river": "Kh",
            "aggressor_position": "OOP",
            "postflop_action": "OOP_BET_2",
            "evaluation_at": "Flop",
            "available_moves": "['Fold', 'Call']",
            "pot_size": "8",
            "hero_position": "IP",
            "holding": "Ad4h",
            "correct_decision": "Call",
        })
        flop["id"] = "flop-old"
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / "spots.sqlite"
            SpotLibrary.build(library, [flop])
            path = Path(folder) / "poker_trainer.db"
            conn = engine.sqlite3.connect(path)
            conn.execute(
                """
                CREATE TABLE attempts (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    situation_hash TEXT NOT NULL,
                    user_answers TEXT NOT NULL,
                    true_answers TEXT NOT NULL,
                    ce_score REAL NOT NULL,
                    norm_score REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE user_stats (
                    phase TEXT PRIMARY KEY,
                    total_hands INTEGER NOT NULL,
                    avg_score REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO attempts (
                    timestamp, phase, situation_hash, user_answers, true_answers, ce_score, norm_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("t", "flop", "flop-old", "{}", "{}", 0.0, 1.0),
            )
            conn.commit()
            conn.close()
            trainer = Engine(path, library=library, rng=random.Random(1))
            try:
                self.assertEqual(trainer.dataset_id, DATASET_SIX_MAX)
                self.assertEqual(trainer.dashboard()["overall"]["total_hands"], 1)
                trainer.set_dataset(DATASET_HEADS_UP)
                self.assertEqual(trainer.dashboard()["overall"]["total_hands"], 0)
            finally:
                trainer.library.close()

    def test_saved_data_lives_beside_the_program(self):
        folder = Path(engine.__file__).resolve().parent
        self.assertEqual(default_db_path(), folder / "poker_trainer.db")
        self.assertEqual(default_library_path(), folder / "spots.sqlite")

    def test_a_missing_library_is_downloaded_once(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "spots.sqlite"
            calls = []

            def fake_import(dest=None, cache=None):
                calls.append(Path(dest))
                _write_spot_library(Path(dest))
                return Path(dest)

            with patch("pokerbench.import_pokerbench", fake_import):
                first = pokerbench.ensure_library(target)
                second = pokerbench.ensure_library(target)
            self.assertEqual(first, target)
            self.assertEqual(second, target)
            self.assertEqual(calls, [target])
            self.assertTrue(pokerbench.library_ready(target))

    def test_a_corrupt_library_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "spots.sqlite"
            target.write_bytes(b"not a database")

            def fake_import(dest=None, cache=None):
                _write_spot_library(Path(dest))
                return Path(dest)

            with patch("pokerbench.import_pokerbench", fake_import):
                found = pokerbench.ensure_library(target)
            self.assertEqual(found, target)
            self.assertTrue(pokerbench.library_ready(target))

    def test_missing_library_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            trainer = Engine(Path(folder) / "poker_trainer.db", rng=random.Random(1))
            with self.assertRaises(ValueError):
                trainer.set_dataset(DATASET_SIX_MAX)


if __name__ == "__main__":
    unittest.main()
