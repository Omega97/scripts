import os
import sys
from pathlib import Path
import time


# ===== Hyperparameters =====
ARG_EXLUDE_STARTSWITH = "-es"
ARG_NAME_CONTAINS = "-c"
ARG_HELP = "-h"
DEFAULT_MAX_FILES = 100_000
DEFAULT_MAX_TIME = 30.0
DEFAULT_MAX_DEPTH = 50
HELP_TEXT = ("\ncommands:\n"
"-es [prefix]   exclude directories that start with [prefix]\n"
"-c [str]       include only files that contain [str]")


class Parser:
    """Handles command-line argument parsing."""

    def __init__(self, args: list[str]):
        self.args = args
        self.folder_path = Path(".")
        self.extensions: list[str] = []
        self.exclude_prefixes: list[str] = []
        self.contains_word: str | None = None
        self._parse()

    def _parse(self):
        i = 0
        while i < len(self.args):
            arg = self.args[i]

            if arg == ARG_EXLUDE_STARTSWITH:
                i += 1
                while i < len(self.args) and not self.args[i].startswith("-"):
                    self.exclude_prefixes.append(self.args[i])
                    i += 1
                continue

            elif arg == ARG_NAME_CONTAINS:
                i += 1
                if i < len(self.args) and not self.args[i].startswith("-"):
                    self.contains_word = self.args[i].lower()
                    i += 1
                continue

            elif arg == ARG_HELP:
                print(HELP_TEXT)
                sys.exit(0)

            elif Path(arg).is_dir():
                self.folder_path = Path(arg)
                i += 1
                continue

            elif not arg.startswith("-"):
                # Treat as extension (without leading dot)
                ext = arg.lstrip(".").lower()
                if ext:  # avoid empty strings
                    self.extensions.append(ext)
                i += 1
                continue

            else:
                # Unknown flag → skip
                i += 1

    def get_summary(self) -> str:
        parts = []
        if self.extensions:
            parts.append(f"extensions: {', '.join(self.extensions)}")
        if self.exclude_prefixes:
            parts.append(f"exclude prefixes: {', '.join(self.exclude_prefixes)}")
        if self.contains_word:
            parts.append(f"containing: '{self.contains_word}'")
        return " | ".join(parts) or "all files"


class CountFiles:
    """Counts files in a directory with flexible filtering and limits."""

    def __init__(
        self,
        root_path: Path,
        max_files: int = 100_000,
        max_time: float = 30.0,
        max_depth: int | None = 50,
        extensions: list[str] | None = None,
        exclude_prefixes: list[str] | None = None,
        contains_word: str | None = None,
    ):
        self.root_path = root_path.resolve()
        self.max_files = max_files
        self.max_time = max_time
        self.max_depth = max_depth
        self.extensions = {e.lower() for e in (extensions or [])}
        self.exclude_prefixes = exclude_prefixes or []
        self.contains_word = contains_word.lower() if contains_word else None

        self.file_count = 0
        self.start_time = time.time()
        self.status = "complete"
        self.message = "Counting completed successfully"

    def should_include_file(self, filename: str) -> bool:
        """Check if a file should be counted based on filters."""
        name_lower = filename.lower()

        # Exclude by prefix
        if any(name_lower.startswith(p.lower()) for p in self.exclude_prefixes):
            return False

        # Extension filter
        if self.extensions:
            ext = Path(filename).suffix.lstrip(".").lower()
            if ext not in self.extensions:
                return False

        # Contains word filter
        if self.contains_word and self.contains_word not in name_lower:
            return False

        return True

    def count(self) -> dict:
        try:
            for root, dirs, files in os.walk(self.root_path):
                current_depth = len(Path(root).relative_to(self.root_path).parts)
                if self.max_depth is not None and current_depth > self.max_depth:
                    dirs.clear()
                    continue

                # Exclude directories by prefix
                if self.exclude_prefixes:
                    dirs[:] = [
                        d for d in dirs
                        if not any(d.startswith(p) for p in self.exclude_prefixes)
                    ]

                # Filter and count files
                for file in files:
                    if self.should_include_file(file):
                        self.file_count += 1

                        # Check limits
                        if self.max_files and self.file_count >= self.max_files:
                            self.status = "limit_reached"
                            self.message = f"Stopped: reached file limit ({self.max_files})"
                            return self._result()

                # Time limit check (after processing directory)
                if self.max_time and (time.time() - self.start_time) > self.max_time:
                    self.status = "timeout"
                    self.message = f"Stopped: exceeded time limit ({self.max_time}s)"
                    return self._result()

        except OSError as e:
            self.status = "error"
            self.message = f"Access error: {e}"

        return self._result()

    def _result(self) -> dict:
        return {
            "count": self.file_count,
            "status": self.status,
            "message": self.message,
        }


def main():
    
    parser = Parser(sys.argv[1:])

    print(f"Scanning : {parser.folder_path.absolute()}")
    if summary := parser.get_summary():
        print(f"Filters  : {summary}")
    print(f"Limits   : max {DEFAULT_MAX_FILES:,} files | {DEFAULT_MAX_TIME}s | depth {DEFAULT_MAX_DEPTH}")
    print("Counting...\n")

    counter = CountFiles(
        root_path=parser.folder_path,
        max_files=DEFAULT_MAX_FILES,
        max_time=DEFAULT_MAX_TIME,
        max_depth=DEFAULT_MAX_DEPTH,
        extensions=parser.extensions,
        exclude_prefixes=parser.exclude_prefixes,
        contains_word=parser.contains_word,
    )

    result = counter.count()

    color = "\033[94m" if result["status"] == "complete" else "\033[93m"
    reset = "\033[0m"

    print(f"{color}Total files counted:{reset} {result['count']:,}")

    if result["status"] != "complete":
        print(f"Status              : {result['message']}")
    if parser.contains_word:
        print(f"→ Only files containing '{parser.contains_word}' in name")
    if parser.extensions:
        print(f"→ Only files with extensions: {', '.join(parser.extensions)}")
    if parser.exclude_prefixes:
        print(f"→ Excluded prefixes: {', '.join(parser.exclude_prefixes)}")


if __name__ == "__main__":
    main()
