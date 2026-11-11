#!/usr/bin/env python3
"""Round-trip tests for row-parity steganography."""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import steg

SCRIPT = Path(__file__).resolve().parent / "steg.py"


class ParityTests(unittest.TestCase):
    def test_known_row(self):
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (1, 2, 4))
        image.putpixel((1, 0), (1, 0, 0))
        self.assertEqual(steg.parity_bits(image), [0, 0, 0])
        self.assertEqual(steg.parity_bits(image, depth=-1), [0, 0, 0])
        self.assertEqual(steg.parity_bits(image, depth=-2), [0, 1, 0])
        self.assertEqual(steg.parity_bits(image, depth=-3), [0, 0, 1])
        self.assertEqual(steg.parity_bits(image, depth=7), [0, 0, 0])


class RoundTripTests(unittest.TestCase):
    def test_internal_spaces(self):
        image = Image.new("RGB", (3, 30), (0, 0, 0))
        encoded = steg.encode_into(image, "hello world")
        self.assertEqual(steg.decode_image(encoded), "hello world")

    def test_leftover_bits_are_ignored(self):
        image = Image.new("RGB", (4, 17), (12, 34, 56))
        encoded = steg.encode_into(image, "google")
        self.assertEqual(len(steg.parity_bits(encoded)) % 8, 3)
        self.assertEqual(steg.decode_image(encoded), "google")

    def test_filler_spaces_are_removed(self):
        image = Image.new("RGB", (2, 17), (0, 0, 0))
        encoded = steg.encode_into(image, "hi")
        self.assertEqual(steg.decode_image(encoded), "hi")

    def test_original_trailing_space_is_removed(self):
        image = Image.new("RGB", (2, 17), (0, 0, 0))
        encoded = steg.encode_into(image, "hello ")
        self.assertEqual(steg.decode_image(encoded), "hello")

    def test_later_message_stays_on_the_same_low_bits(self):
        base = Image.new("RGB", (8, 17), (10, 20, 30))
        direct = steg.encode_into(base, "hello!")
        chained = steg.encode_into(steg.encode_into(base, "google"), "hello!")
        self.assertEqual(chained.tobytes(), direct.tobytes())
        self.assertEqual(steg.decode_image(chained), "hello!")
        for y in range(base.size[1]):
            for x in range(base.size[0]):
                before = base.getpixel((x, y))
                after = direct.getpixel((x, y))
                diffs = [abs(after[channel] - before[channel]) for channel in range(3)]
                self.assertLessEqual(max(diffs), 1)
                self.assertLessEqual(sum(value != 0 for value in diffs), 1)

    def test_depths_do_not_overwrite_each_other(self):
        base = Image.new("RGB", (4, 17), (10, 20, 30))
        low_then_next = steg.encode_into(
            steg.encode_into(base, "google", depth=-1), "secret", depth=-2
        )
        next_then_low = steg.encode_into(
            steg.encode_into(base, "secret", depth=-2), "google", depth=-1
        )
        self.assertEqual(steg.decode_image(low_then_next, depth=-1), "google")
        self.assertEqual(steg.decode_image(low_then_next, depth=-2), "secret")
        self.assertEqual(steg.decode_image(next_then_low, depth=-1), "google")
        self.assertEqual(steg.decode_image(next_then_low, depth=-2), "secret")
        replaced = steg.encode_into(low_then_next, "hello!", depth=-1)
        self.assertEqual(steg.decode_image(replaced, depth=-1), "hello!")
        self.assertEqual(steg.decode_image(replaced, depth=-2), "secret")

    def test_depth_out_of_range(self):
        image = Image.new("RGB", (4, 17), (0, 0, 0))
        for depth in (8, -9):
            with self.assertRaises(ValueError):
                steg.encode_into(image, "hi", depth=depth)

    def test_message_too_long(self):
        image = Image.new("RGB", (1, 3))
        with self.assertRaises(ValueError) as caught:
            steg.encode_into(image, "AB")
        self.assertIn("1", str(caught.exception))

    def test_latin1_round_trip(self):
        nicol = steg.encode_into(
            Image.new("RGB", (3, 30), (0, 0, 0)), "Ciao Nicolò"
        )
        vowels = steg.encode_into(
            Image.new("RGB", (2, 17), (0, 0, 0)), "àèéìòù"
        )
        self.assertEqual(steg.decode_image(nicol), "Ciao Nicolò")
        self.assertEqual(steg.decode_image(vowels), "àèéìòù")

    def test_outside_latin1_rejected(self):
        image = Image.new("RGB", (1, 8))
        with self.assertRaises(ValueError) as caught:
            steg.encode_into(image, "ō")
        self.assertIn("àèéìòù", str(caught.exception))


class MessageColorTests(unittest.TestCase):
    def test_terminal_message_is_blue(self):
        buffer = io.StringIO()
        buffer.isatty = lambda: True
        with contextlib.redirect_stdout(buffer):
            steg.print_message("Hello")
        self.assertEqual(buffer.getvalue(), "\033[94mHello\033[0m\n")

    def test_terminal_encode_is_green(self):
        buffer = io.StringIO()
        buffer.isatty = lambda: True
        with contextlib.redirect_stdout(buffer):
            steg.print_encoded("photo.png")
        self.assertEqual(buffer.getvalue(), "\033[92mEncoded photo.png\033[0m\n")

    def test_terminal_warning_is_yellow(self):
        buffer = io.StringIO()
        buffer.isatty = lambda: True
        with contextlib.redirect_stderr(buffer):
            steg.print_warning("Warning: converted photo.jpg to PNG (photo.png).")
        self.assertEqual(
            buffer.getvalue(),
            "\033[93mWarning: converted photo.jpg to PNG (photo.png).\033[0m\n",
        )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image_path = Path(self.tmp.name) / "blank.png"
        Image.new("RGB", (4, 17), (0, 0, 0)).save(self.image_path)

    def test_saved_file_round_trip_and_bit_length(self):
        output = Path(self.tmp.name) / "out.png"
        with Image.open(self.image_path) as image:
            encoded = steg.encode_into(image, "google")
        encoded.save(output, format="PNG")
        with Image.open(output) as saved:
            self.assertEqual(steg.decode_image(saved), "google")
            bits = steg.decode_image(saved, as_bits=True)
        self.assertEqual(len(bits), 17 * 3)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "decode", str(output), "--bits"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.strip()), 17 * 3)

    def test_cli_depth_round_trip(self):
        output = Path(self.tmp.name) / "deep.png"
        before = self.image_path.read_bytes()
        encoded = self._run(
            "encode", str(self.image_path), "google", "--depth", "-2", "-o", str(output)
        )
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        self.assertIn("capacity: 6 (depth -2)", encoded.stderr)
        self.assertEqual(self.image_path.read_bytes(), before)
        decoded = self._run("decode", str(output), "--depth", "-2")
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        self.assertEqual(decoded.stdout.strip(), "google")
        other = self._run("decode", str(output))
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertNotEqual(other.stdout.strip(), "google")

    def test_cli_rejects_a_message_that_does_not_fit(self):
        tiny = Path(self.tmp.name) / "tiny.png"
        Image.new("RGB", (1, 3)).save(tiny)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "encode", str(tiny), "AB"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("capacity: 1", result.stderr)
        self.assertIn("fits 1", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(tiny.exists())

    def test_no_arguments_shows_encode_and_decode_examples(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('steg encode photo.png "Hello World"', result.stdout)
        self.assertIn("steg decode photo.png", result.stdout)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_png_is_replaced_in_place(self):
        result = self._run("encode", str(self.image_path), "google")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("capacity: 6", result.stderr)
        self.assertNotIn("Warning:", result.stderr)
        self.assertEqual(result.stdout.strip(), f"Encoded {self.image_path}")
        self.assertFalse((self.image_path.parent / "blank.steg.png").exists())
        decoded = self._run("decode", str(self.image_path))
        self.assertEqual(decoded.stdout.strip(), "google")
        self.assertNotIn("capacity:", decoded.stderr)

    def test_jpeg_is_replaced_by_png(self):
        jpeg = Path(self.tmp.name) / "photo.jpg"
        Image.new("RGB", (4, 17), (8, 16, 24)).save(jpeg, format="JPEG")
        result = self._run("encode", str(jpeg), "google")
        png = jpeg.with_suffix(".png")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Warning: converted photo.jpg to PNG (photo.png).",
            result.stderr,
        )
        self.assertEqual(result.stdout.strip(), f"Encoded {png}")
        self.assertFalse(jpeg.exists())
        self.assertTrue(png.exists())
        decoded = self._run("decode", str(png))
        self.assertEqual(decoded.stdout.strip(), "google")

    def test_keep_writes_a_copy(self):
        result = self._run("encode", str(self.image_path), "google", "--keep")
        copy = self.image_path.with_name("blank.steg.png")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.image_path.exists())
        self.assertEqual(result.stdout.strip(), f"Encoded {copy}")
        decoded = self._run("decode", str(copy))
        self.assertEqual(decoded.stdout.strip(), "google")

    def test_output_flag_leaves_the_source(self):
        output = Path(self.tmp.name) / "elsewhere.png"
        before = self.image_path.read_bytes()
        result = self._run("encode", str(self.image_path), "google", "-o", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.image_path.read_bytes(), before)
        self.assertEqual(result.stdout.strip(), f"Encoded {output}")
        decoded = self._run("decode", str(output))
        self.assertEqual(decoded.stdout.strip(), "google")

    def test_existing_png_blocks_jpeg_replacement(self):
        jpeg = Path(self.tmp.name) / "photo.jpg"
        png = jpeg.with_suffix(".png")
        Image.new("RGB", (4, 17), (1, 2, 3)).save(jpeg, format="JPEG")
        Image.new("RGB", (4, 17), (4, 5, 6)).save(png)
        jpeg_bytes = jpeg.read_bytes()
        png_bytes = png.read_bytes()
        result = self._run("encode", str(jpeg), "google")
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(jpeg.read_bytes(), jpeg_bytes)
        self.assertEqual(png.read_bytes(), png_bytes)


if __name__ == "__main__":
    unittest.main()
