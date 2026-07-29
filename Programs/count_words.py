#!/usr/bin/env python3
"""
Word Counter - Counts words in text/code files, optionally recursive.
Hyphens and most non-alphanumeric characters are treated as word separators.

Usage:
    python count_words.py                     # Count words in CWD (default)
    python count_words.py path/to/dir         # Count words in specific directory
    python count_words.py file.py             # Count words in single file
    python count_words.py -v                  # Verbose output
    python count_words.py --exclude .git node_modules
    python count_words.py --extensions txt py md
"""
import re
import sys
import argparse
from pathlib import Path


def clean_text(text):
    """
    Replace all characters that aren't letters, numbers, or apostrophes
    with a space. Treats hyphens, underscores, and punctuation as separators.
    """
    return re.sub(r"[^a-zA-Z0-9']", ' ', text)


def count_words(text):
    """
    Count words after cleaning text.
    """
    if not text or not text.strip():
        return 0
    
    cleaned_text = clean_text(text)
    words = cleaned_text.split()
    return len(words)


def read_from_file(filename):
    """
    Read text from a file with robust encoding fallback.
    """
    try:
        file_path = Path(filename)
        # Try UTF-8 first, then fallback to latin-1 for legacy files
        try:
            return file_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            return file_path.read_text(encoding='latin-1')
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.", file=sys.stderr)
        return None
    except PermissionError:
        print(f"Error: Permission denied reading '{filename}'.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error reading file '{filename}': {e}", file=sys.stderr)
        return None


def is_binary_file(file_path):
    """
    Heuristic to detect binary files by checking for null bytes in first 1KB.
    Prevents accidentally processing images, executables, etc.
    """
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\x00' in chunk  # Null byte suggests binary content
    except Exception:
        return False


def get_files_to_process(filepath, exclude, extensions):
    """
    Get list of files to process, excluding directories starting with specified strings,
    filtering by extensions, and skipping likely binary files.
    """
    filepath = Path(filepath)
    files_to_process = []
    extensions = {ext.lower() for ext in extensions}  # Use set for O(1) lookup

    if filepath.is_file():
        # Skip binary files even if extension matches
        if not is_binary_file(filepath):
            if not extensions or filepath.suffix.lower().lstrip('.') in extensions:
                files_to_process.append(filepath)
    elif filepath.is_dir():
        for file_path in filepath.rglob('*'):
            if file_path.is_file():
                # Skip if in excluded directory
                if any(
                    parent.name.startswith(exclude_str)
                    for parent in file_path.parents
                    for exclude_str in exclude
                ):
                    continue
                
                # Skip binary files
                if is_binary_file(file_path):
                    continue
                
                # Filter by extension if specified
                if not extensions or file_path.suffix.lower().lstrip('.') in extensions:
                    files_to_process.append(file_path)
    else:
        print(f"Error: '{filepath}' is neither a file nor a directory.", file=sys.stderr)
        return []

    return files_to_process


def main():
    """Main function to handle command-line arguments and execution."""
    parser = argparse.ArgumentParser(
        description="Counts words in text/code files (recursive by default). "
                    "Skips binary files and hidden directories automatically."
    )
    parser.add_argument(
        'filepath',
        nargs='?',  # Make argument optional
        default='.',
        help="Path to file/directory to process (default: current directory '.')."
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Show detailed output including sample text for each file."
    )
    parser.add_argument(
        '--exclude',
        nargs='*',
        default=['.', '__', '.git', '.venv', 'venv', 'node_modules', '.idea', '.vscode'],
        help="Exclude directories starting with these strings (default includes hidden dirs and common tool dirs)."
    )
    parser.add_argument(
        '--extensions',
        nargs='*',
        default=[],
        help="Only process files with these extensions (case-insensitive). "
             "If omitted, processes all likely text/code files (txt, py, md, js, java, cpp, html, json, yaml, etc.)."
    )

    args = parser.parse_args()

    # Default extensions for text/code files (only used when --extensions not specified)
    DEFAULT_EXTENSIONS = {
        'txt', 'md', 'markdown', 'rst', 'tex', 'org',       # Documentation
        'py', 'pyw', 'pyx', 'pxd', 'pxi',                   # Python
        'js', 'ts', 'jsx', 'tsx', 'mjs', 'cjs',             # JavaScript/TypeScript
        'java', 'kt', 'kts', 'scala',                       # JVM languages
        'cpp', 'cc', 'cxx', 'c', 'h', 'hpp', 'hxx', 'ino',  # C/C++
        'cs', 'fs',                                         # .NET
        'go', 'rs', 'swift', 'dart',                        # Modern systems
        'rb', 'gemspec', 'rake',                            # Ruby
        'php', 'phtml',                                     # PHP
        'lua', 'pl', 'pm', 't',                             # Scripting
        'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd',   # Shell scripts
        'html', 'htm', 'xml', 'xhtml',                      # Markup
        'css', 'scss', 'less', 'sass',                      # Stylesheets
        'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env', 'properties',  # Config
        'sql', 'sqlite', 'pgsql',                           # SQL
        'r', 'rmd', 'rkt',                                  # R/Scheme
        'csv', 'tsv', 'log', 'out', 'err'                   # Data/logs
    }

    # Use default extensions only if user didn't specify any
    extensions = args.extensions if args.extensions else DEFAULT_EXTENSIONS

    # Get list of files to process
    files_to_process = get_files_to_process(args.filepath, args.exclude, extensions)
    
    if not files_to_process:
        print("No text/code files found to process.", file=sys.stderr)
        print("Hint: Use --extensions to specify custom file types, or check --exclude patterns.", file=sys.stderr)
        sys.exit(1)

    total_word_count = 0
    for file_path in sorted(files_to_process):
        # Read the text from the file
        text = read_from_file(file_path)
        if text is None:
            continue

        # Count the words
        word_count = count_words(text)
        total_word_count += word_count

        # Display results for each file
        if args.verbose:
            cleaned = clean_text(text)
            words = cleaned.split()
            rel_path = file_path.relative_to(Path(args.filepath).resolve()) if Path(args.filepath).is_dir() else file_path.name
            print(f"\n--- {rel_path} ({word_count:,} words) ---")
            print(f"Size: {file_path.stat().st_size:,} bytes")
            print(f"Sample: \"{text[:100].replace(chr(10), ' ').replace(chr(13), '').strip()}...\"")
            if words:
                print(f"First words: {words[:8]}")
        else:
            # Compact output: relative path + count
            try:
                rel_path = file_path.relative_to(Path.cwd())
            except ValueError:
                rel_path = file_path
            print(f"{word_count:>8,}  {rel_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"Total files processed: {len(files_to_process):,}")
    print(f"Total words:           {total_word_count:,}")
    print(f"{'='*60}")


if __name__ == "__main__":
    sys.exit(main())
