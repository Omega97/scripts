#!/usr/bin/env python3
"""
PasGen 2026
Generate a deterministic password from a keyword and PASGEN_SALT.

Scheme v1. Spaces are removed from the keyword and the rest is lowercased,
then mixed with the salt and the length. The same keyword, salt, and length
always produce the same password. Length must be from 4 through 100.
"""
import sys
import argparse
import random
from pathlib import Path

# Alphabet without similar characters
ALPHA = [
    "234679",
    "+-.?!",
    "ACDEFGHJKLMNPQRTWXYZ",
    "abcdefghijkmnopqrstwxyz"
]

# Resolve paths relative to the script's location for reliability.
# PasGen_2026.py lives in Programs/, so the repo root (and .env) is its parent.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / '.env'
SALT_KEY = 'PASGEN_SALT'


def gen_string(length, rng):
    """Generate string of random char using alphabet"""
    types = [i % len(ALPHA) for i in range(length)]
    chars = [ALPHA[i][rng.randrange(len(ALPHA[i]))] for i in types]
    rng.shuffle(chars)
    return ''.join(chars)


def get_password(key, salt, length: int, max_length=100):
    """Generate password given nickname and key"""
    if not key:
        raise ValueError('Key is empty')
    if not salt:
        raise ValueError('salt is empty')
    if length < len(ALPHA):
        raise ValueError(f'Length is less than {len(ALPHA)}')
    if length > max_length:
        raise ValueError(f'Length is more than {max_length}')

    s = salt + key + str(length)
    s = s.replace(' ', '').lower()
    rng = random.Random()
    rng.seed(s, version=2)
    return gen_string(length, rng)


def load_salt():
    """Load salt from PASGEN_SALT in the root .env file"""
    if not ENV_FILE.exists():
        print(f"Error: {ENV_FILE} not found.", file=sys.stderr)
        print(
            f"Add a line '{SALT_KEY}=<your secret>' to it and run the script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    salt = None
    with open(ENV_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if line.startswith('export '):
                line = line[len('export '):].lstrip()
            if line.startswith(SALT_KEY + '='):
                salt = line[len(SALT_KEY) + 1:].strip().strip('"').strip("'")
                break

    if not salt:
        print(f"Error: '{SALT_KEY}' not set in {ENV_FILE}.", file=sys.stderr)
        print(
            f"Add a line '{SALT_KEY}=<your secret>' and run the script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    return salt


def main():
    parser = argparse.ArgumentParser(
        description="PasGen 2026 - Generate password given username and keyword"
    )
    parser.add_argument("key", help="Username/keyword to base the password on")
    parser.add_argument("length", nargs="?", type=int, default=20,
                        help="Length of the generated password (default: 20)")

    args = parser.parse_args()

    salt = load_salt()

    try:
        print(get_password(args.key, salt, args.length))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
