#!/usr/bin/env python3
"""
Row-parity steganography.

Each row stores three bits at one bit depth: the parity of that bit in red,
then green, then blue. Depth -1 (the default) is the least significant bit.
Depth 0 is the most significant bit. Depths -8 and 0 are the same plane, and
-1 and 7 are the same plane. A message at one depth does not change another.

Bits are grouped into Latin-1 bytes, high bit first. Leftover bits are
discarded, and trailing spaces are removed on decode. Encode pads the message
with spaces so it fills every usable byte.
"""
import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError


def bit_shift(depth):
    """Map a depth to a bit index. -1 and 7 are the least significant bit."""
    if not -8 <= depth <= 7:
        raise ValueError("Depth must be from -8 to 7")
    return 7 - (depth % 8)


def parity_bits(image, depth=-1):
    """Return one parity bit per channel per row at this bit depth."""
    shift = bit_shift(depth)
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 1 or height < 1:
        raise ValueError("Image has no pixels")

    pixels = rgb.load()
    bits = []
    for y in range(height):
        for channel in range(3):
            count = 0
            for x in range(width):
                count += (pixels[x, y][channel] >> shift) & 1
            bits.append(count & 1)
    return bits


def bits_to_text(bits):
    """Pack complete bytes, high bit first, and drop trailing spaces."""
    usable = len(bits) - (len(bits) % 8)
    data = bytearray()
    for start in range(0, usable, 8):
        value = 0
        for bit in bits[start:start + 8]:
            value = (value << 1) | (bit & 1)
        data.append(value)
    return data.decode("latin-1").rstrip(" ")


def text_to_bits(text):
    """Expand a Latin-1 string into bits, high bit first."""
    try:
        data = text.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError("Message must be Latin-1 (includes àèéìòù)") from exc

    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def usable_bytes(height):
    """How many Latin-1 bytes fit in an image of this height."""
    return (height * 3) // 8


def report_capacity(height, depth=-1):
    """Print how many Latin-1 bytes this image can store at this depth."""
    print(f"capacity: {usable_bytes(height)} (depth {depth})", file=sys.stderr)


def colorize(text, code, stream):
    """Wrap text in an ANSI color when the stream is a terminal."""
    if stream.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def print_message(text):
    """Print the decoded message in blue when stdout is a terminal."""
    print(colorize(text, "94", sys.stdout))


def print_encoded(destination):
    """Confirm a successful encode in green when stdout is a terminal."""
    print(colorize(f"Encoded {destination}", "92", sys.stdout))


def print_warning(text):
    """Print a warning in yellow when stderr is a terminal."""
    print(colorize(text, "93", sys.stderr), file=sys.stderr)


def encode_into(image, message, depth=-1):
    """Return an RGB image whose row parities at this depth store message.

    A mismatch flips that bit of one pixel in that row. The column is chosen
    from a generator seeded with the image width, so a later message at the
    same depth edits that same set of pixels. Other depths are left alone.
    """
    shift = bit_shift(depth)
    mask = 1 << shift
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 1 or height < 1:
        raise ValueError("Image has no pixels to edit")

    text_to_bits(message)
    capacity = usable_bytes(height)
    if len(message) > capacity:
        raise ValueError(
            f"Message is {len(message)} bytes; this image fits {capacity}"
        )

    padded = message + (" " * (capacity - len(message)))
    desired_bits = text_to_bits(padded)
    columns = random.Random(width)
    pixels = rgb.load()
    for index, desired in enumerate(desired_bits):
        y, channel = divmod(index, 3)
        x = columns.randrange(width)
        parity = 0
        for column in range(width):
            parity = (parity + ((pixels[column, y][channel] >> shift) & 1)) & 1
        if parity == desired:
            continue
        pixel = list(pixels[x, y])
        pixel[channel] ^= mask
        pixels[x, y] = tuple(pixel)
    return rgb


def decode_image(image, as_bits=False, depth=-1):
    """Read one depth's parities as a bit string or as stripped Latin-1."""
    bits = parity_bits(image, depth)
    if as_bits:
        return "".join(str(bit) for bit in bits)
    return bits_to_text(bits)


def kept_output(source):
    """PNG written beside the source when --keep is set."""
    path = Path(source)
    return path.with_name(path.stem + ".steg.png")


def replacement_output(source):
    """Path that replaces the source. JPEG and other non-PNG files become PNG."""
    path = Path(source)
    if path.suffix.lower() == ".png":
        return path
    return path.with_name(path.stem + ".png")


def save_png(image, destination):
    """Write a PNG, replacing destination only after the save succeeds."""
    destination = Path(destination)
    descriptor, name = tempfile.mkstemp(
        prefix=".steg-",
        suffix=".png",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        image.save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def add_depth_argument(command):
    """Add the shared bit-plane selector. -1 is the lowest bit."""
    command.add_argument(
        "-d",
        "--depth",
        type=int,
        default=-1,
        choices=range(-8, 8),
        metavar="DEPTH",
        help="Bit plane from -8 to 7. -1 (default) is the lowest bit; 0 is the highest",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="steg",
        description="Hide a Latin-1 message in image row parities",
        epilog=(
            "examples:\n"
            '  steg encode photo.png "Hello World"\n'
            '  steg encode photo.png "second" --depth -2\n'
            "  steg decode photo.png\n"
            "  steg decode photo.png --depth -2"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="mode", required=True)

    decode_cmd = commands.add_parser("decode", help="Read a message from an image")
    decode_cmd.add_argument("image", help="Image to read")
    decode_cmd.add_argument(
        "--bits",
        action="store_true",
        help="Print every parity bit, including bits left over from the last byte",
    )
    add_depth_argument(decode_cmd)

    encode_cmd = commands.add_parser("encode", help="Hide a message in an image")
    encode_cmd.add_argument(
        "image",
        help="Image to encode. Replaced with the encoded PNG unless --keep or -o is set",
    )
    encode_cmd.add_argument("message", help="Latin-1 message to hide (includes àèéìòù)")
    encode_cmd.add_argument(
        "-o",
        "--output",
        help="Write this PNG and leave the source image in place",
    )
    encode_cmd.add_argument(
        "--keep",
        action="store_true",
        help="Leave the source image and write <name>.steg.png",
    )
    add_depth_argument(encode_cmd)

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help()
        return

    args = parser.parse_args(argv)
    try:
        if args.mode == "decode":
            with Image.open(args.image) as image:
                text = decode_image(image, as_bits=args.bits, depth=args.depth)
            if args.bits:
                print(text)
            else:
                print_message(text)
            return

        source = Path(args.image)
        if args.output:
            destination = Path(args.output)
            delete_source = False
        elif args.keep:
            destination = kept_output(source)
            delete_source = False
        else:
            destination = replacement_output(source)
            delete_source = destination.resolve() != source.resolve()
            if delete_source and destination.exists():
                raise ValueError(f"{destination} already exists")

        with Image.open(source) as image:
            report_capacity(image.size[1], args.depth)
            encoded = encode_into(image, args.message, depth=args.depth)
        save_png(encoded, destination)
        if delete_source:
            source.unlink()
        if source.suffix.lower() != ".png":
            print_warning(
                f"Warning: converted {source.name} to PNG ({destination.name})."
            )
        print_encoded(destination)
    except (ValueError, OSError, UnidentifiedImageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
