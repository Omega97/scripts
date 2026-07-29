#!/usr/bin/env python3
"""
PasGen 2026
Generate password given username and keyword
"""
import sys
import os
import argparse
from random import randrange, seed, shuffle

# Alphabet without similar characters
ALPHA = [
    "234679",
    "+-.?!",
    "ACDEFGHJKLMNPQRTWXYZ",
    "abcdefghijkmnopqrstwxyz"
]

# Resolve path relative to the script's location for reliability
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data')
KEY_FILE = os.path.join(DATA_DIR, 'Key.txt')


def gen_string(length):
    """Generate string of random char using alphabet"""
    types = [i % len(ALPHA) for i in range(length)]
    chars = [ALPHA[i][randrange(len(ALPHA[i]))] for i in types]
    shuffle(chars)
    return ''.join(chars)


def get_password(key, master_key, length: int, max_length=100):
    """Generate password given nickname and key"""
    if not key:
        raise ValueError('Key is empty')
    if not master_key:
        raise ValueError('master_key is empty')
    if length < len(ALPHA):
        raise ValueError(f'Length is less than {len(ALPHA)}')
    if length > max_length:
        raise ValueError(f'Length is more than {max_length}')
        
    s = master_key + key
    s = s.replace(' ', '').lower()
    seed(s)
    return gen_string(length=length)


def load_master_key():
    """Load master key from Key.txt, create file/dir if missing, validate content"""
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, 'w', encoding='utf-8') as f:
            pass  # Creates empty file
        print(f"File not found: {KEY_FILE}")
        print("An empty 'Key.txt' has been created.")
        print("Please fill it with your master key and run the script again.")
        sys.exit(1)

    with open(KEY_FILE, 'r', encoding='utf-8') as f:
        master_key = f.read().strip()

    if not master_key:
        print(f"Error: {KEY_FILE} is empty.")
        print("Please fill the file with your master key and run the script again.")
        sys.exit(1)

    return master_key


def main():
    parser = argparse.ArgumentParser(
        description="PasGen 2026 - Generate password given username and keyword"
    )
    parser.add_argument("key", help="Username/keyword to base the password on")
    parser.add_argument("length", nargs="?", type=int, default=20, 
                        help="Length of the generated password (default: 20)")

    args = parser.parse_args()

    master_key = load_master_key()

    try:
        print(get_password(args.key, master_key, args.length))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()