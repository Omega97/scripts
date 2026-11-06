"""Checks for the quiz rules and one local HTTP session."""

from __future__ import annotations

import json
import random
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import build_deck
import content
import engine
import server
import srs
from content import CONTENT, choice_valid, deck_file_ready, kanji_hard_valid, parse_ruby
from engine import Engine, default_data_path, missed_day_to_freeze, streak_count
from srs import blank_stat, performance_skill, quotas, romaji_match, schedule, select_queue, stroke_weight


def noon(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, current):
        self.current = current

    def __call__(self):
        return self.current


class RulesTest(unittest.TestCase):
    def test_kana_deck_and_variants(self):
        hira = [item for item in CONTENT["kana"] if item["category"] == "HIRAGANA"]
        kata = [item for item in CONTENT["kana"] if item["category"] == "KATAKANA"]
        self.assertEqual(len(hira), 105)
        self.assertEqual(len(kata), 106)
        shi = next(item for item in hira if item["kana"] == "し")
        self.assertTrue(romaji_match("si", shi["romaji_variants"]))
        self.assertTrue(romaji_match("SHI", shi["romaji_variants"]))
        self.assertFalse(romaji_match("ka", shi["romaji_variants"]))
        wo = next(item for item in hira if item["kana"] == "を")
        self.assertTrue(romaji_match("o", wo["romaji_variants"]))
        self.assertTrue(romaji_match("wo", wo["romaji_variants"]))
        bar = next(item for item in kata if item["kana"] == "ー")
        self.assertTrue(romaji_match("-", bar["romaji_variants"]))
        self.assertTrue(romaji_match("chouon", bar["romaji_variants"]))

    def test_ruby_joins_extra_pipes(self):
        parts = parse_ruby("毎日、{学校|がっ|こう}に行きます。")
        school = next(part for part in parts if part.get("kanji") == "学校")
        self.assertEqual(school["reading"], "がっこう")
        self.assertGreaterEqual(len(CONTENT["kanji"]), 600)
        self.assertGreater(len(CONTENT["phrases"]), 1000)
        sun = CONTENT["kanji_by_char"]["日"]
        self.assertEqual(sun["id"], "kj_65e5")
        self.assertEqual(sun["gloss"], "Day / Sun")
        self.assertEqual(sun["audio"], "ひ")
        self.assertIn("OpenJLPT", CONTENT["source"])

    def test_schedule_sm2(self):
        now = noon(2026, 10, 20)
        first = schedule(blank_stat(), True, 1200, now)
        self.assertEqual(first["interval_days"], 1.0)
        self.assertEqual(first["streak"], 1)
        self.assertEqual(first["correct_attempts"], 1)
        slow = schedule(blank_stat(), True, 3000, now)
        self.assertAlmostEqual(slow["ease_factor"], 2.55)
        wrong = schedule(blank_stat(), False, 1000, now)
        self.assertEqual(wrong["interval_days"], 0.0)
        self.assertEqual(wrong["streak"], -1)
        self.assertAlmostEqual(wrong["ease_factor"], 2.3)
        self.assertEqual(srs.parse_time(wrong["next_review_at"]), now)

    def test_pools_spill_back_to_new_items(self):
        self.assertEqual(quotas(10), {"new": 4, "weak": 4, "review": 2})
        self.assertEqual(quotas(1), {"new": 1, "weak": 0, "review": 0})
        now = noon(2026, 10, 20)
        items = [{"id": f"n{i}"} for i in range(8)]
        picked = select_queue(items, {}, 5, now, random.Random(1))
        self.assertEqual(len(picked), 5)
        self.assertEqual(len({item["id"] for item in picked}), 5)
        future = (now + timedelta(days=9)).isoformat()
        rested = {
            "total_attempts": 4,
            "correct_attempts": 4,
            "streak": 2,
            "next_review_at": future,
        }
        only_rest = [{"id": "a"}, {"id": "b"}]
        filled = select_queue(only_rest, {"a": rested, "b": dict(rested)}, 2, now, random.Random(0))
        self.assertEqual({item["id"] for item in filled}, {"a", "b"})

    def test_kanji_strokes_follow_recent_accuracy(self):
        easy = {"id": "easy", "stroke_count": 2}
        hard = {"id": "hard", "stroke_count": 24}
        span = (2, 24)
        self.assertGreater(stroke_weight(easy, 0.1, span), stroke_weight(hard, 0.1, span))
        self.assertGreater(stroke_weight(hard, 0.9, span), stroke_weight(easy, 0.9, span))
        self.assertEqual(stroke_weight({"id": "kana"}, 0.9, span), 1.0)
        self.assertEqual(performance_skill([]), 0.25)
        self.assertGreater(performance_skill([{"category": "KANJI", "is_correct": True}] * 40), 0.8)
        self.assertLess(performance_skill([{"category": "KANJI", "is_correct": False}] * 40), 0.15)
        self.assertEqual(performance_skill([{"category": "HIRAGANA", "is_correct": True}] * 10), 0.25)

        now = noon(2026, 10, 21)
        deck = [{"id": f"k{strokes}", "stroke_count": strokes} for strokes in (2, 4, 6, 8, 12, 16, 20, 24)]
        low = []
        high = []
        for seed in range(30):
            weak = select_queue(deck, {}, 4, now, random.Random(seed), skill=0.05)
            strong = select_queue(deck, {}, 4, now, random.Random(seed), skill=0.95)
            low.append(sum(item["stroke_count"] for item in weak) / len(weak))
            high.append(sum(item["stroke_count"] for item in strong) / len(strong))
        self.assertLess(sum(low) / len(low), sum(high) / len(high))

    def test_school_grade_and_phrase_level(self):
        sun = CONTENT["kanji_by_char"]["日"]
        front = CONTENT["kanji_by_char"]["前"]
        self.assertEqual(sun["school_grade"], 1)
        self.assertEqual(front["school_grade"], 2)
        self.assertLess(sun["difficulty"], front["difficulty"])
        self.assertGreaterEqual(sun["difficulty"], 0.0)
        self.assertLessEqual(front["difficulty"], 1.0)
        grade_one = [item for item in CONTENT["kanji"] if item["school_grade"] == 1]
        fewest = min(grade_one, key=lambda item: item["stroke_count"])
        most = max(grade_one, key=lambda item: item["stroke_count"])
        self.assertLess(fewest["difficulty"], most["difficulty"])
        phrases = CONTENT["phrases"]
        n5 = max(item["difficulty"] for item in phrases if item["jlpt_level"] == 5)
        n4_low = min(item["difficulty"] for item in phrases if item["jlpt_level"] == 4)
        n4_high = max(item["difficulty"] for item in phrases if item["jlpt_level"] == 4)
        n3 = min(item["difficulty"] for item in phrases if item["jlpt_level"] == 3)
        self.assertLess(n5, n4_low)
        self.assertLess(n4_high, n3)
        shown = CONTENT["by_id"]["p_884e0bc7d7"]
        part = next(piece for piece in shown["ruby"] if piece.get("kanji") == "前")
        self.assertEqual(part["reading"], "まえ")
        self.assertNotIn("#", shown["sentence_jp"])

        now = noon(2026, 10, 21)
        with tempfile.TemporaryDirectory() as folder:
            def mean_difficulty(correct: bool) -> float:
                app = Engine(Path(folder) / f"p{correct}.json", rng=random.Random(1), now_fn=lambda: now)
                app.store.data["attempts"] = [{"category": "PHRASE", "is_correct": correct} for _ in range(40)]
                started = app.start_session("PHRASE", "HARD", 20, False)
                queue = app.sessions[started["session_id"]]["queue"]
                values = [CONTENT["by_id"][item_id]["difficulty"] for item_id in queue]
                return sum(values) / len(values)

            self.assertGreater(mean_difficulty(True), mean_difficulty(False))

        with tempfile.TemporaryDirectory() as folder:
            def mean_strokes(correct: bool) -> float:
                app = Engine(Path(folder) / f"{correct}.json", rng=random.Random(1), now_fn=lambda: now)
                app.store.data["attempts"] = [{"category": "KANJI", "is_correct": correct} for _ in range(40)]
                started = app.start_session("KANJI", "EASY", 20, False)
                strokes = [CONTENT["by_id"][item_id]["stroke_count"] for item_id in app.sessions[started["session_id"]]["queue"]]
                return sum(strokes) / len(strokes)

            self.assertGreater(mean_strokes(True), mean_strokes(False))

    def test_streak_and_freeze(self):
        today = noon(2026, 10, 22).date()
        real = {noon(2026, 10, 20).date()}
        self.assertEqual(streak_count(real, set(), today), 0)
        self.assertEqual(missed_day_to_freeze(real, today, 1), noon(2026, 10, 21).date())
        self.assertIsNone(missed_day_to_freeze(real, today, 0))
        frozen = {noon(2026, 10, 21).date()}
        self.assertEqual(streak_count(real | {today}, frozen, today), 3)

    def test_every_mode_and_srs_update(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock(noon(2026, 10, 17))
            app = Engine(Path(folder) / "state.json", rng=random.Random(2), now_fn=clock)
            hard = app.start_session("HIRAGANA", "HARD", 5, False, item_ids=["h_shi", "h_wo"])
            question = hard["question"]
            self.assertEqual(question["prompt"], "し")
            self.assertNotIn("correct_key", question)
            wrong = app.answer(hard["session_id"], question["qid"], None, "nope", 800)
            self.assertFalse(wrong["correct"])
            self.assertEqual(wrong["insight"]["jp"], "七転び八起き")
            stat = app.store.data["items"]["h_shi"]
            self.assertEqual(stat["streak"], -1)
            nxt = wrong["next"]
            variant = app.answer(hard["session_id"], nxt["qid"], None, "o" if nxt["prompt"] == "を" else "si", 500)
            self.assertTrue(variant["correct"])

            easy = app.start_session("HIRAGANA", "EASY", 5, False, item_ids=["h_ka"])
            q = easy["question"]
            key = next(option["key"] for option in q["options"] if option["text"] == "か")
            done = app.answer(easy["session_id"], q["qid"], key, "", 400)
            self.assertTrue(done["correct"])
            self.assertIsNone(done["next"])
            self.assertEqual(done["summary"]["answered"], 1)
            self.assertTrue(any(item["id"] == "first_step" for item in done["unlocks"]))

            kana_hard = app.start_session("KATAKANA", "HARD", 5, False, item_ids=["k_a"])
            self.assertEqual(kana_hard["question"]["input"], "text")
            self.assertEqual(kana_hard["question"]["prompt"], "ア")

            sun_id = CONTENT["kanji_by_char"]["日"]["id"]
            for mode, expect_input in (("EASY", "choice"), ("MEDIUM", "choice"), ("HARD", "text")):
                started = app.start_session("KANJI", mode, 5, False, item_ids=[sun_id])
                q = started["question"]
                self.assertEqual(q["input"], expect_input)
                self.assertNotIn("correct_text", q)
                if mode == "EASY":
                    self.assertEqual(q["prompt"], "日")
                    self.assertTrue(any(option["text"] == "Day / Sun" for option in q["options"]))
                elif mode == "MEDIUM":
                    self.assertEqual(q["prompt"], "Day / Sun")
                    self.assertTrue(any(option["text"] == "日" for option in q["options"]))
                else:
                    self.assertEqual(q["audio"], "ひ")
                    self.assertNotEqual(q["prompt"], "日")
                    graded = app.answer(started["session_id"], q["qid"], None, "日", 900)
                    self.assertTrue(graded["correct"])
                    self.assertIn("mnemonic", graded)

            nearby = [item for item in CONTENT["phrases"] if item["skeleton"] == "この近くに□はありますか。"]
            cinema = next(item for item in nearby if item["target"] == "映画館")
            cloze = app.start_session("PHRASE", "HARD", 5, False, item_ids=[cinema["id"]])
            ruby = cloze["question"]["ruby"]
            self.assertEqual(sum(1 for part in ruby if part.get("blank")), 1)
            self.assertFalse(any(part.get("kanji") == "映画館" for part in ruby))
            self.assertEqual(len(cloze["question"]["options"]), 4)
            listen = app.start_session("PHRASE", "LISTENING", 5, False, item_ids=[cinema["id"]])
            self.assertEqual(listen["question"]["audio"], cinema["sentence_clean"])
            self.assertIsNone(listen["question"]["ruby"])
            self.assertEqual(len(listen["question"]["options"]), 4)

            clock.current = noon(2026, 10, 20)
            later = app.start_session("HIRAGANA", "HARD", 5, False, item_ids=["h_a"])
            back = app.answer(later["session_id"], later["question"]["qid"], None, "a", 300)
            self.assertTrue(any(item["id"] == "perseverance" for item in back["unlocks"]))

            found = app.search("し")
            self.assertTrue(any(card["title"] == "し" for card in found["results"]))
            sun = app.search("ニチ")
            self.assertTrue(any(card["title"] == "日" for card in sun["results"]))
            board = app.dashboard()
            self.assertIn("heatmap", board)
            self.assertIn("weekly", board)
            self.assertGreaterEqual(board["streak"], 1)

    def test_ambiguous_answers_are_accepted(self):
        someone = CONTENT["kanji_by_char"]["者"]
        self.assertTrue(choice_valid("KANJI", "EASY", someone, "Person"))
        self.assertFalse(choice_valid("KANJI", "EASY", someone, "Fire"))
        person = CONTENT["kanji_by_char"]["人"]
        self.assertTrue(choice_valid("KANJI", "MEDIUM", person, "者"))
        self.assertFalse(choice_valid("KANJI", "MEDIUM", person, "火"))
        sun = CONTENT["kanji_by_char"]["日"]
        think = CONTENT["kanji_by_char"]["思"]
        self.assertTrue(kanji_hard_valid(sun, "日"))
        self.assertFalse(kanji_hard_valid(sun, "火"))
        self.assertTrue(kanji_hard_valid(think, "想"))

        with tempfile.TemporaryDirectory() as folder:
            app = Engine(Path(folder) / "state.json", rng=random.Random(4), now_fn=lambda: noon(2026, 10, 20))
            easy = app.start_session("KANJI", "EASY", 5, False, item_ids=[someone["id"]])
            live = app.sessions[easy["session_id"]]["live"]
            other_key = next(key for key, text in live["option_text"].items() if text != someone["gloss"])
            live["option_text"][other_key] = "Person"
            accepted = app.answer(easy["session_id"], easy["question"]["qid"], other_key, "", 400)
            self.assertTrue(accepted["correct"])
            self.assertIn(other_key, accepted["accepted_keys"])

            easy_bad = app.start_session("KANJI", "EASY", 5, False, item_ids=[someone["id"]])
            live = app.sessions[easy_bad["session_id"]]["live"]
            other_key = next(key for key, text in live["option_text"].items() if text != someone["gloss"])
            live["option_text"][other_key] = "Fire"
            rejected = app.answer(easy_bad["session_id"], easy_bad["question"]["qid"], other_key, "", 400)
            self.assertFalse(rejected["correct"])

            medium = app.start_session("KANJI", "MEDIUM", 5, False, item_ids=[person["id"]])
            live = app.sessions[medium["session_id"]]["live"]
            other_key = next(key for key, text in live["option_text"].items() if text != "人")
            live["option_text"][other_key] = "者"
            swapped = app.answer(medium["session_id"], medium["question"]["qid"], other_key, "", 400)
            self.assertTrue(swapped["correct"])

            heard = app.start_session("KANJI", "HARD", 5, False, item_ids=[think["id"]])
            alternate = app.answer(heard["session_id"], heard["question"]["qid"], None, "想", 500)
            self.assertTrue(alternate["correct"])
            self.assertIn("想", alternate["note"])

            nearby = [item for item in CONTENT["phrases"] if item["skeleton"] == "この近くに□はありますか。"]
            cinema = next(item for item in nearby if item["target"] == "映画館")
            hospital = next(item for item in nearby if item["target"] == "病院")
            self.assertNotIn(hospital["target"], cinema["distractors"])
            cloze = app.start_session("PHRASE", "HARD", 5, False, item_ids=[cinema["id"]])
            live = app.sessions[cloze["session_id"]]["live"]
            other_key = next(key for key, text in live["option_text"].items() if text != "映画館")
            live["option_text"][other_key] = "病院"
            filled = app.answer(cloze["session_id"], cloze["question"]["qid"], other_key, "", 400)
            self.assertTrue(filled["correct"])
            self.assertIn("病院", filled["note"])

    def test_http_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Engine(Path(folder) / "state.json", rng=random.Random(3), now_fn=lambda: noon(2026, 10, 20))
            server.ENGINE = app
            handler = server.make_handler(BaseHTTPRequestHandler)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
                self.assertIn("Learn Japanese", page)
                script = urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js").read().decode("utf-8")
                self.assertIn("startSession", script)
                css = urllib.request.urlopen(f"http://127.0.0.1:{port}/style.css").read().decode("utf-8")
                self.assertIn("--bg", css)
                boot = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bootstrap"))
                self.assertEqual(len(boot["categories"]), 4)
                modes = {row["id"]: [mode["id"] for mode in row["modes"]] for row in boot["categories"]}
                self.assertEqual(modes["HIRAGANA"], ["EASY", "HARD"])
                self.assertEqual(modes["KATAKANA"], ["EASY", "HARD"])
                self.assertEqual(modes["KANJI"], ["EASY", "MEDIUM", "HARD"])
                self.assertEqual(modes["PHRASE"], ["HARD", "LISTENING"])
                self.assertIn("OpenJLPT", boot["source"])
                self.assertGreaterEqual(next(row["count"] for row in boot["categories"] if row["id"] == "KANJI"), 600)
                payload = json.dumps({"category": "KATAKANA", "mode": "EASY", "length": 5, "focus": False}).encode("utf-8")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/session",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                started = json.load(urllib.request.urlopen(request))
                question = started["question"]
                glyph = next(item["kana"] for item in CONTENT["kana"] if item["category"] == "KATAKANA" and item["romaji"] == question["prompt"])
                key = next(option["key"] for option in question["options"] if option["text"] == glyph)
                answer_body = json.dumps({
                    "session_id": started["session_id"],
                    "qid": question["qid"],
                    "option_key": key,
                    "text": "",
                    "response_ms": 450,
                }).encode("utf-8")
                answered = json.load(urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/answer",
                    data=answer_body,
                    headers={"Content-Type": "application/json"},
                )))
                self.assertTrue(answered["correct"])
                dashboard = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dashboard"))
                self.assertGreaterEqual(dashboard["solved"], 1)
                bad = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/session",
                    data=json.dumps({"category": "HIRAGANA", "mode": "LISTENING", "length": 10}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(bad)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


class DatasetTest(unittest.TestCase):
    def test_progress_lives_beside_the_program(self):
        folder = Path(engine.__file__).resolve().parent
        self.assertEqual(default_data_path(), folder / "state.json")

    def test_a_missing_deck_is_downloaded_once(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "deck.json"
            calls = []

            ready = json.dumps({"kanji": [{"kanji": "日"}], "phrases": [{"id": "p"}]})

            def fake_build(dest=None):
                calls.append(Path(dest))
                Path(dest).write_text(ready, encoding="utf-8")
                return Path(dest)

            with patch("build_deck.build_deck", fake_build):
                first = build_deck.ensure_deck(target)
                second = build_deck.ensure_deck(target)
            self.assertEqual(first, target)
            self.assertEqual(second, target)
            self.assertEqual(calls, [target])
            self.assertTrue(deck_file_ready(target))

    def test_an_empty_deck_object_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "deck.json"
            target.write_text("{}", encoding="utf-8")
            ready = json.dumps({"kanji": [{"kanji": "日"}], "phrases": [{"id": "p"}]})

            def fake_build(dest=None):
                Path(dest).write_text(ready, encoding="utf-8")
                return Path(dest)

            with patch("build_deck.build_deck", fake_build):
                found = build_deck.ensure_deck(target)
            self.assertEqual(found, target)
            self.assertTrue(deck_file_ready(target))

    def test_build_deck_keeps_the_output_path(self):
        kanji = [{
            "character": "日",
            "meanings": ["day", "sun"],
            "kunyomi": ["ひ"],
            "onyomi": ["ニチ"],
            "strokes": 4,
            "grade": 1,
            "radical": "日",
        }]
        vocab = [
            {"word": "日本", "reading": "にほん", "jmdict_id": "1", "examples": [{"furigana": "あ{日本|にほん}です", "en": "It is Japan"}]},
            {"word": "今日", "reading": "きょう", "jmdict_id": "2", "examples": [{"furigana": "い{今日|きょう}です", "en": "It is today"}]},
            {"word": "人", "reading": "ひと", "jmdict_id": "3", "examples": [{"furigana": "う{人|ひと}です", "en": "That is a person"}]},
            {"word": "水", "reading": "みず", "jmdict_id": "4", "examples": [{"furigana": "え{水|みず}です", "en": "This is water"}]},
        ]

        def fake_fetch(path):
            if path.startswith("kanji/"):
                return kanji if path.endswith("n5.json") else []
            return vocab if path.endswith("n5.json") else []

        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "nested" / "deck.json"
            with patch("build_deck.fetch", fake_fetch):
                written = build_deck.build_deck(dest)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(written, dest)
            self.assertEqual(data["kanji"][0]["kanji"], "日")
            self.assertTrue(any(phrase["target"] == "日本" for phrase in data["phrases"]))


if __name__ == "__main__":
    unittest.main()
