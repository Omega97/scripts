import os
import sys
import time
from pathlib import Path
from collections import defaultdict

# ===== Hyperparameters =====
DEFAULT_TOP_N = 30
DEFAULT_MAX_TIME = 30.0
DEFAULT_MAX_DEPTH = 50


class FolderAnalyzer:
    """
    Finds the top-N folders ranked by file count.

    recursive=False → count only files directly in folder
    recursive=True  → include subfolders
    """

    def __init__(
        self,
        root_path: Path,
        top_n: int = DEFAULT_TOP_N,
        recursive: bool = False,
        max_time: float = DEFAULT_MAX_TIME,
        max_depth: int | None = DEFAULT_MAX_DEPTH,
    ):
        self.root_path = root_path.resolve()
        self.top_n = top_n
        self.recursive = recursive
        self.max_time = max_time
        self.max_depth = max_depth

        self.start_time = time.time()
        self.folder_counts = defaultdict(int)

    def analyze(self) -> list[tuple[Path, int]]:
        try:
            for root, dirs, files in os.walk(self.root_path):
                current_path = Path(root)
                current_depth = len(current_path.relative_to(self.root_path).parts)

                if self.max_depth is not None and current_depth > self.max_depth:
                    dirs.clear()
                    continue

                file_count = len(files)

                if self.recursive:
                    # Propagate upward (bottom-up aggregation)
                    path = current_path
                    while True:
                        self.folder_counts[path] += file_count
                        if path == self.root_path:
                            break
                        path = path.parent
                else:
                    # Count only files directly in this folder
                    self.folder_counts[current_path] = file_count

                if self.max_time and (time.time() - self.start_time) > self.max_time:
                    print(f"\n⚠ Timeout reached ({self.max_time}s)")
                    break

        except OSError as e:
            print(f"Access error: {e}")

        ranked = sorted(
            self.folder_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        return ranked[:self.top_n]


def main():
    args = sys.argv[1:]

    # Parse arguments
    top_n = DEFAULT_TOP_N
    recursive = False

    for arg in args:
        if arg == "-r":
            recursive = True
        else:
            try:
                top_n = int(arg)
            except ValueError:
                print("Usage: python biggest_folders.py [n] [-r]")
                return

    root_path = Path.cwd()

    mode = "recursive" if recursive else "direct-only"

    print(f"Scanning current directory: {root_path}")
    print(f"Mode: {mode}")
    print(f"Ranking top {top_n} folders...\n")

    analyzer = FolderAnalyzer(
        root_path=root_path,
        top_n=top_n,
        recursive=recursive,
    )

    results = analyzer.analyze()

    print("📂 Top folders:\n")

    for i, (folder, count) in enumerate(results, start=1):
        rel_path = folder.relative_to(root_path)
        rel_str = "." if rel_path == Path(".") else str(rel_path)
        print(f"{i:2d}. {count:8,} files  |  {rel_str}")


if __name__ == "__main__":
    main()
  