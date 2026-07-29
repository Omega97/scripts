#!/usr/bin/env python3
"""
search - Fast case-insensitive exact word search with safety limits.

Usage:
    search word1 word2 ...          # Search CWD recursively (default limits)
    search -d 3 foo bar             # Max depth 3
    search -n 1000 error warning    # Stop after 1000 files
    search -t 5 *.py                # 5-second timeout

Safety limits (prevent runaway searches):
    • Time: 10 seconds (hard cutoff)
    • Depth: 5 directories deep
    • Files: 5,000 files max
"""
import re
import sys
import time
import argparse
from pathlib import Path
from typing import List, Set


def is_binary_file(path: Path) -> bool:
    """Heuristic: files with null bytes in first 1KB are likely binary."""
    try:
        with open(path, 'rb') as f:
            return b'\x00' in f.read(1024)
    except Exception:
        return True  # Treat unreadable files as binary


def should_skip_dir(path: Path, max_depth: int) -> bool:
    """Skip hidden dirs (.git), cache dirs, and respect depth limit."""
    parts = path.parts
    if len(parts) > max_depth + 1:  # +1 for root
        return True
    return any(
        part.startswith(('.', '__')) or part in {
            '.git', '.venv', 'venv', 'node_modules', '.idea', 
            '.vscode', '__pycache__', 'dist', 'build', '.mypy_cache'
        }
        for part in parts
    )


def search_file(
    path: Path, 
    patterns: List[re.Pattern], 
    start_time: float, 
    timeout: float
) -> List[tuple]:
    """Search single file for all patterns. Returns (line_num, line, matches) tuples."""
    results = []
    try:
        # Quick timeout check before expensive read
        if time.time() - start_time > timeout:
            return results
        
        # Skip obvious binaries by extension first (fast path)
        if path.suffix.lower() in {
            '.exe', '.dll', '.so', '.dylib', '.bin', '.zip', '.gz', '.tar', 
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.mp3', '.mp4', '.pdf'
        }:
            return results
        
        # Confirm with content check
        if is_binary_file(path):
            return results
        
        # Read with encoding fallback
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            try:
                text = path.read_text(encoding='latin-1', errors='ignore')
            except Exception:
                return results
        
        # Search line-by-line for better context and early timeout exit
        for line_num, line in enumerate(text.splitlines(), 1):
            if time.time() - start_time > timeout:
                return results
            
            matches = set()
            for pattern in patterns:
                if pattern.search(line):
                    matches.add(pattern.pattern.strip(r'\b'))
            
            if matches:
                # Clean line for display (truncate long lines)
                display_line = line.strip()
                if len(display_line) > 120:
                    display_line = display_line[:117] + "..."
                results.append((line_num, display_line, matches))
    
    except Exception as e:
        # Silent failure on individual files (don't crash entire search)
        pass
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Case-insensitive exact word search with safety limits",
        epilog="Defaults: 10s timeout, depth=5, max-files=5000. Skips binaries/hidden dirs automatically."
    )
    parser.add_argument('words', nargs='+', help='Words to search for (exact matches)')
    parser.add_argument('-t', '--timeout', type=float, default=10.0,
                        help='Maximum search time in seconds (default: 10)')
    parser.add_argument('-d', '--depth', type=int, default=5,
                        help='Maximum directory depth (default: 5)')
    parser.add_argument('-n', '--max-files', type=int, default=5000,
                        help='Maximum files to scan (default: 5000)')
    parser.add_argument('--path', default='.', help='Root directory to search (default: .)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show skipped files')
    
    args = parser.parse_args()
    
    # Precompile regex patterns with word boundaries for exact matches
    patterns = [
        re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
        for word in args.words
    ]
    
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Error: Path '{args.path}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    start_time = time.time()
    files_processed = 0
    total_matches = 0
    files_with_matches = 0
    
    def get_depth(path: Path) -> int:
        """Get depth relative to root."""
        try:
            return len(path.relative_to(root).parts)
        except ValueError:
            return 0
    
    def should_skip_directory(dir_path: Path) -> bool:
        """Check if directory should be skipped (hidden, cache, or too deep)."""
        depth = get_depth(dir_path)
        if depth > args.depth:
            return True
        parts = dir_path.relative_to(root).parts
        return any(
            part.startswith(('.', '__')) or part in {
                '.git', '.venv', 'venv', 'node_modules', '.idea', 
                '.vscode', '__pycache__', 'dist', 'build', '.mypy_cache'
            }
            for part in parts
        )
    
    def walk_directory(current_path: Path, current_depth: int):
        """Manually walk directory tree with depth control."""
        nonlocal files_processed, total_matches, files_with_matches
        
        try:
            entries = list(current_path.iterdir())
        except PermissionError:
            if args.verbose:
                print(f"Permission denied: {current_path}", file=sys.stderr)
            return
        except Exception:
            return
        
        for entry in entries:
            # Timeout check
            if time.time() - start_time > args.timeout:
                return
            
            # File count limit
            if files_processed >= args.max_files:
                return
            
            try:
                if entry.is_dir():
                    if not should_skip_directory(entry):
                        walk_directory(entry, current_depth + 1)
                elif entry.is_file():
                    files_processed += 1
                    matches = search_file(entry, patterns, start_time, args.timeout)
                    if matches:
                        rel_path = entry.relative_to(root)
                        files_with_matches += 1
                        for line_num, line, words in matches:
                            
                            # print match
                            print() 
                            print(f"\033[94m{rel_path}\033[0m line {line_num}")
                            print(line)  
                           
                            total_matches += 1
            except (PermissionError, OSError):
                if args.verbose:
                    print(f"Error accessing: {entry}", file=sys.stderr)
                continue
    
    try:
        walk_directory(root, 0)
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Search interrupted by user", file=sys.stderr)
    
    # Print summary
    print()
    if total_matches == 0:
        print(f"No matches found for: {', '.join(args.words)}")
        sys.exit(0)
    
    elapsed = min(time.time() - start_time, args.timeout)
    print(f"\n{'─'*70}")
    print(f"✓ Searched {files_processed:,} files in {elapsed:.2f}s")
    print(f"✓ Found {total_matches:,} match{'es' if total_matches != 1 else ''} "
          f"for {len(args.words)} word{'s' if len(args.words) != 1 else ''} "
          f"across {files_with_matches} file{'s' if files_with_matches != 1 else ''}")
    print(f"{'─'*70}")


if __name__ == "__main__":
    main()
