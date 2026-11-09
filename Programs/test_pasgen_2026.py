#!/usr/bin/env python3
"""Characterization tests for PasGen 2026 scheme v1."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import PasGen_2026 as pasgen

SALT = "stand-in-salt"


class PasswordTests(unittest.TestCase):
    def test_known_passwords(self):
        expected = {
            ("google", 21): "4fwE.H7o+3n3P-C?3i7P?",
            ("google1", 21): "-67ho6?K3dqyJ.M.2QE!4",
            ("My Key", 20): "i-64D4X.g-+M+y6h2DKm",
            ("alpha", 4): "!Tf2",
        }
        for (key, length), password in expected.items():
            self.assertEqual(pasgen.get_password(key, SALT, length), password)

    def test_same_length_keywords_differ(self):
        first = pasgen.get_password("google", SALT, 21)
        second = pasgen.get_password("google1", SALT, 21)
        self.assertNotEqual(first, second)

    def test_space_and_case_folding(self):
        folded = pasgen.get_password("My Key", SALT, 20)
        self.assertEqual(folded, pasgen.get_password("mykey", SALT, 20))

    def test_shared_seed_string_still_differs_by_length(self):
        longer = pasgen.get_password("google", SALT, 15)
        shorter = pasgen.get_password("google1", SALT, 5)
        self.assertEqual(longer, "4!d--tK2Q6?QxG2")
        self.assertEqual(shorter, "t24Q!")
        self.assertNotEqual(longer, shorter)

    def test_length_bounds(self):
        self.assertEqual(len(pasgen.get_password("alpha", SALT, 4)), 4)
        self.assertEqual(len(pasgen.get_password("alpha", SALT, 100)), 100)
        with self.assertRaises(ValueError):
            pasgen.get_password("alpha", SALT, 3)
        with self.assertRaises(ValueError):
            pasgen.get_password("alpha", SALT, 101)

    def test_empty_key_or_salt(self):
        with self.assertRaises(ValueError):
            pasgen.get_password("", SALT, 20)
        with self.assertRaises(ValueError):
            pasgen.get_password("alpha", "", 20)


class SaltLoadTests(unittest.TestCase):
    def setUp(self):
        self._env_file = pasgen.ENV_FILE
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore_env_file)

    def _restore_env_file(self):
        pasgen.ENV_FILE = self._env_file

    def _write(self, name, text=None, data=None):
        path = Path(self.tmp.name) / name
        if data is not None:
            path.write_bytes(data)
        else:
            path.write_text(text, encoding="utf-8")
        pasgen.ENV_FILE = path
        return path

    def _assert_exit(self, code=1):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as caught:
                pasgen.load_salt()
        self.assertEqual(caught.exception.code, code)
        self.assertIn(pasgen.SALT_KEY, buf.getvalue())
        self.assertTrue(buf.getvalue())

    def test_missing_file(self):
        pasgen.ENV_FILE = Path(self.tmp.name) / "missing.env"
        self._assert_exit()

    def test_missing_key(self):
        self._write("salt.env", "OTHER=value\n")
        self._assert_exit()

    def test_empty_value(self):
        self._write("salt.env", "PASGEN_SALT=\n")
        self._assert_exit()

    def test_quoted_value(self):
        self._write("salt.env", 'PASGEN_SALT="quoted-secret"\n')
        self.assertEqual(pasgen.load_salt(), "quoted-secret")

    def test_export_prefix(self):
        self._write("salt.env", "export PASGEN_SALT=from-export\n")
        self.assertEqual(pasgen.load_salt(), "from-export")

    def test_first_line_wins(self):
        self._write("salt.env", "PASGEN_SALT=first\nPASGEN_SALT=second\n")
        self.assertEqual(pasgen.load_salt(), "first")

    def test_utf8_bom(self):
        self._write("salt.env", data=b"\xef\xbb\xbfPASGEN_SALT=bom-salt\n")
        self.assertEqual(pasgen.load_salt(), "bom-salt")

    def test_example_shape(self):
        self._write(
            "salt.env",
            "# comment\nPASGEN_SALT=example-salt-change-me\n",
        )
        self.assertEqual(pasgen.load_salt(), "example-salt-change-me")

    def test_inline_comment_stays_in_value(self):
        self._write("salt.env", "PASGEN_SALT=abc # comment\n")
        self.assertEqual(pasgen.load_salt(), "abc # comment")


if __name__ == "__main__":
    unittest.main()
