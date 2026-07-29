"""
Log Utility: A lightweight CLI tool for persistent message logging.

Usage:
    python log.py              - Start interactive logging mode.
    python log.py show         - Display non-empty logs with their row indices.
    python log.py del [index]  - Clear a specific entry by index (maintains row order).
    python log.py where        - Display the file path of the log file.
    python log.py -h           - Show available commands and help.

Logs are stored in data/log.txt relative to the project root.
"""

import os
import datetime
import sys


# Repo root is parent of Programs/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_FILE = os.path.join(_PROJECT_ROOT, "data", "log.txt")


def get_log_file():
    return DEFAULT_DATA_FILE

def log_message(message):
    log_file = get_log_file()
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}: {message}\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)

def show_log():
    log_file = get_log_file()
    if not os.path.exists(log_file):
        print("Log file is empty.")
        return
    
    print(f"\033[94m--- Log file content ---\033[0m")
    with open(log_file, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if line.strip():
                print(f"[{idx}] {line}", end="")

def delete_log_entry(index):
    log_file = get_log_file()
    if not os.path.exists(log_file):
        return

    try:
        idx_to_del = int(index)
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if 0 <= idx_to_del < len(lines):
            lines[idx_to_del] = "\n"
            with open(log_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"Entry {idx_to_del} deleted.")
        else:
            print(f"Error: Index {idx_to_del} out of range.")
    except ValueError:
        print("Error: Index must be a number.")

def print_help():
    print("""
\033[94mLog Utility Help\033[0m
Usage:
  python log.py              - Start interactive logging mode.
  python log.py show         - Display all logs with their indices.
  python log.py del [index]  - Delete a specific log entry by index.
  python log.py where        - Show path to the log file.
  python log.py -h / --help  - Show this help message.
    """)

def main():
    args = sys.argv[1:]

    if len(args) > 0:
        cmd = args[0]
        
        if cmd == "show":
            show_log()
        elif cmd == "del" and len(args) == 2:
            delete_log_entry(args[1])
        elif cmd == "where":
            print(f"Log file location: \033[92m{get_log_file()}\033[0m")
        elif cmd in ["-h", "--help"]:
            print_help()
        else:
            print(f"Unknown command: {' '.join(args)}")
            print_help()
        return

    print(f"\033[94mLog utility\033[0m – press Enter on an empty line to quit.")
    while True:
        try:
            user_input = input("> ").strip()
            if not user_input:
                print("Goodbye!")
                break
            log_message(user_input)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break

if __name__ == "__main__":
    main()
