import os
import sys
import time
from pathlib import Path

# ===== Hyperparameters =====
DEFAULT_TOP_N = 30
DEFAULT_MAX_TIME = 30.0
DEFAULT_MAX_DEPTH = 50

class FileSizeAnalyzer:
    """Finds the top-N largest files in the directory tree."""
    def __init__(
        self,
        root_path: Path,
        top_n: int = DEFAULT_TOP_N,
        max_time: float = DEFAULT_MAX_TIME,
        max_depth: int | None = DEFAULT_MAX_DEPTH,
    ):
        self.root_path = root_path.resolve()
        self.top_n = top_n
        self.max_time = max_time
        self.max_depth = max_depth
        self.start_time = time.time()
        self.file_list = []

    def format_size(self, size_bytes: int) -> str:
        """Helper to make bytes human-readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:3.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:3.1f} PB"

    def analyze(self) -> list[tuple[Path, int]]:
        try:
            for root, dirs, files in os.walk(self.root_path):
                current_path = Path(root)
                current_depth = len(current_path.relative_to(self.root_path).parts)

                # Depth check
                if self.max_depth is not None and current_depth > self.max_depth:
                    dirs.clear()
                    continue

                for name in files:
                    file_path = current_path / name
                    try:
                        # Get size (follow_symlinks=False to avoid errors/loops)
                        size = file_path.stat(follow_symlinks=False).st_size
                        self.file_list.append((file_path, size))
                    except (OSError, FileNotFoundError):
                        continue

                # Timeout check
                if self.max_time and (time.time() - self.start_time) > self.max_time:
                    print(f"\n⚠ Timeout reached ({self.max_time}s)")
                    break

        except OSError as e:
            print(f"Access error: {e}")

        # Sort by size (index 1 of the tuple) descending
        ranked = sorted(self.file_list, key=lambda x: x[1], reverse=True)
        return ranked[:self.top_n]

def main():
    args = sys.argv[1:]
    top_n = DEFAULT_TOP_N
    
    # Parse arguments (simple integer for N)
    for arg in args:
        try:
            top_n = int(arg)
        except ValueError:
            print("Usage: python big_files.py [n]")
            return

    root_path = Path.cwd()
    print(f"Scanning current directory: {root_path}")
    print(f"Ranking top {top_n} largest files...\n")

    analyzer = FileSizeAnalyzer(
        root_path=root_path,
        top_n=top_n,
    )

    results = analyzer.analyze()
    print("📄 Top files by size:\n")

    for i, (file_path, size) in enumerate(results):
        # ✅ FIX: Usa analyzer.root_path (già risolto) invece di root_path
        rel_path = file_path.relative_to(analyzer.root_path)
        readable_size = analyzer.format_size(size)

        # Check adjacent files in the sorted list for exact size matches
        prev_size = results[i-1][1] if i > 0 else None
        next_size = results[i+1][1] if i < len(results) - 1 else None

        # Print "*" if size matches previous or next, otherwise "|"
        separator = "*" if (size == prev_size or size == next_size) else "|"

        print(f"{i+1:3d}) {readable_size:>10} {separator} {rel_path}")

if __name__ == "__main__":
    main()
