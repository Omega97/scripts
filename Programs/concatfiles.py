#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import re
import subprocess
import platform

class ConcatFilesApp:
    # Default Values
    DEFAULT_LINES_LIM = 1000
    DEFAULT_TRUNCATED_MARKER = "\n[... TRUNCATED ...]\n"
    DEFAULT_OUTPUT_DIR = Path(r"C:\scripts\data\summaries")
    CONFIRM_THRESHOLD = 1000
    
    # ANSI Color Codes
    CLR_HEADER = '\033[95m'
    CLR_OKBLUE = '\033[94m'
    CLR_OKCYAN = '\033[96m'
    CLR_OKGREEN = '\033[92m'
    CLR_WARNING = '\033[93m'
    CLR_FAIL = '\033[91m'
    CLR_BOLD = '\033[1m'
    CLR_END = '\033[0m'
    
    # Text-like extensions
    TEXT_EXTENSIONS = {
        '.txt', '.md', '.py', '.js', '.json', '.html', '.css', '.java',
        '.cpp', '.c', '.ts', '.sh', '.xml', '.yaml', '.yml', '.go',
        '.rb', '.php', '.sql', '.rs', '.ipynb'
    }

    def __init__(
        self,
        extensions=None,
        output: str | None = None,
        sep: str = "=" * 64,
        max_lines_per_file: int = 1000,
        truncate_marker: str | None = None,
        ignore_empty_files: bool = False,
        force: bool = False,
    ):
        self.dir_path = Path.cwd()
        self.extensions = {f".{str(ext).lstrip('.')}" for ext in extensions} if extensions else self.TEXT_EXTENSIONS
        
        if output:
            self.output = Path(output).resolve()
        else:
            # Ensure the default directory exists
            out_dir = self.DEFAULT_OUTPUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename based on current folder name to avoid conflicts
            folder_name = self.dir_path.name
            self.output = out_dir / f"combined_{folder_name}.txt"
            
        self.separator = sep
        self.max_lines_per_file = max_lines_per_file
        # Fallback to class constant if no custom marker is provided
        self.truncate_marker = truncate_marker if truncate_marker is not None else self.DEFAULT_TRUNCATED_MARKER
        self.ignore_empty_files = ignore_empty_files
        self.force = force

    @classmethod
    def from_cli(cls):
        """Parse command line arguments."""
        args = sys.argv[1:]
        if any(arg in ('-h', '--help') for arg in args):
            print(f"{cls.CLR_BOLD}{cls.CLR_OKBLUE}Usage:{cls.CLR_END} concatfiles [ext1 ext2 ...] [-o output.txt] [--max-lines N] [--force]")
            print()
            print(f"{cls.CLR_BOLD}Options:{cls.CLR_END}")
            print(f"  -o <path>          Output file path (Default: {cls.DEFAULT_OUTPUT_DIR})")
            print(f"  --max-lines <N>    Limit lines per file (Default: {cls.CLR_OKGREEN}{cls.DEFAULT_LINES_LIM}{cls.CLR_END})")
            print(f"  --ignore-empty     Skip files with 0 bytes")
            print(f"  --force            Skip confirmation for >{cls.CONFIRM_THRESHOLD} files")
            print()
            print(f"{cls.CLR_BOLD}Examples:{cls.CLR_END}")
            print("  concatfiles                     # Process text files")
            print("  concatfiles md py               # Process only .md and .py")
            print(f"  concatfiles --max-lines 50      # Limit to 50 lines")
            print()
            print(f"{cls.CLR_OKCYAN}Default text extensions:{cls.CLR_END}")
            print(f"  {', '.join(sorted(cls.TEXT_EXTENSIONS))}")
            return

        # Parse arguments
        extensions = []
        output = None
        max_lines = cls.DEFAULT_LINES_LIM
        force = False
        ignore_empty = False
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == '-o' and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            elif arg == '--max-lines' and i + 1 < len(args):
                try:
                    max_lines = int(args[i + 1])
                except ValueError:
                    print(f"{cls.CLR_FAIL}Error: --max-lines requires a number{cls.CLR_END}")
                    sys.exit(1)
                i += 2
            elif arg == '--force':
                force = True
                i += 1
            elif arg == '--ignore-empty':
                ignore_empty = True
                i += 1
            elif arg.startswith('-'):
                print(f"{cls.CLR_FAIL}Unknown option: {arg}{cls.CLR_END}")
                sys.exit(1)
            else:
                extensions.append(arg)
                i += 1

        app = cls(
            extensions=extensions if extensions else None,
            output=output,
            max_lines_per_file=max_lines,
            force=force,
            ignore_empty_files=ignore_empty,
        )
        return app.run()

    def _count_files_fast(self) -> int:
        count = 0
        for root, dirs, files in os.walk(self.dir_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('__')]
            for fname in files:
                if Path(fname).suffix.lower() in self.extensions:
                    count += 1
                    if count > self.CONFIRM_THRESHOLD: 
                        return count
        return count

    def _collect_files(self) -> tuple[list[Path], set[str]]:
        file_count = self._count_files_fast()
        if file_count > self.CONFIRM_THRESHOLD and not self.force:
            print(f"\n{self.CLR_WARNING}⚠️  Found {file_count} files to process.{self.CLR_END}")
            response = input(f"Are you sure? (y/N): ").strip().lower()
            if response not in ('y', 'yes'):
                print(f"{self.CLR_FAIL}Operation cancelled.{self.CLR_END}")
                sys.exit(0)

        matched_files = []
        ignored_empty = 0
        all_extensions = set()  # Track ALL extensions found
        
        for root, dirs, files in os.walk(self.dir_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('__')]
            for fname in files:
                p = Path(root) / fname
                ext = p.suffix.lower()
                all_extensions.add(ext)  # Collect all extensions
                
                if ext in self.extensions:
                    if self.ignore_empty_files and p.stat().st_size == 0:
                        ignored_empty += 1
                        continue
                    matched_files.append(p)
                    
        matched_files.sort(key=self._natural_sort_key)
        
        if ignored_empty:
            print(f'{self.CLR_OKCYAN}❔ Ignored empty files: {ignored_empty}{self.CLR_END}')
            
        return matched_files, all_extensions

    def _read_with_optional_truncation(self, file_path: Path) -> tuple[str, bool]:
        if self.max_lines_per_file <= 0:
            with file_path.open("r", encoding="utf-8", errors="replace") as infile:
                return infile.read(), False
                
        truncated = False
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as infile:
                lines = []
                for i, line in enumerate(infile):
                    if i >= self.max_lines_per_file:
                        truncated = True
                        break
                    lines.append(line)
                content = "".join(lines)
                if truncated: 
                    content += self.truncate_marker
                return content, truncated
        except Exception as e:
            return f"{self.CLR_FAIL}[Error reading file: {e}]{self.CLR_END}\n", False

    @staticmethod
    def _open_folder(file_path: Path):
        """Opens the folder containing the given file in the system's file explorer."""
        folder = file_path.parent
        try:
            if platform.system() == "Windows":
                os.startfile(str(folder))
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", str(folder)])
            else:  # Linux and other Unix-like
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            # Fixed: Referenced class attribute correctly instead of undefined global variable
            print(f"{ConcatFilesApp.CLR_WARNING}⚠️  Could not open folder automatically: {e}{ConcatFilesApp.CLR_END}")

    def run(self) -> None:
        print(f"\n{self.CLR_BOLD}Processing:{self.CLR_END} {self.dir_path}")
        matched_files, all_extensions = self._collect_files()
        
        if not matched_files:
            print(f"{self.CLR_WARNING}No files found with selected extensions.{self.CLR_END}")
            return
            
        found_exts = sorted({f.suffix for f in matched_files})
        ignored_exts = sorted(all_extensions - set(found_exts))  # Calculate ignored
        
        print(f"{self.CLR_OKGREEN}🔎 Found extensions:{self.CLR_END} {', '.join(found_exts)}")
        
        # Display ignored extensions in yellow
        if ignored_exts:
            print(f"{self.CLR_WARNING}⚠️ Ignored extensions:{self.CLR_END} {', '.join(ignored_exts)}")
            
        print(f"{self.CLR_BOLD}☑️ Processing {len(matched_files)} files...{self.CLR_END}")
        
        truncated_count = 0
        try:
            with self.output.open("w", encoding="utf-8") as outfile:
                outfile.write(f'Directory: {self.dir_path}\nExtensions: {", ".join(found_exts)}\n')
                for file_path in matched_files:
                    rel_path = file_path.relative_to(self.dir_path)
                    outfile.write(f"{self.separator}\n{rel_path}\n{self.separator}\n")
                    content, was_truncated = self._read_with_optional_truncation(file_path)
                    truncated_count += int(was_truncated)
                    outfile.write(content + ("\n" if not content.endswith("\n") else "") + "\n")
                    
            if truncated_count:
                print(f"{self.CLR_WARNING}✂️  Truncated {truncated_count} files (limit: {self.max_lines_per_file} lines){self.CLR_END}")
                
            print(f"{self.CLR_OKGREEN}✅ Success! Output written to:{self.CLR_END}")
            print(f"Output: {self.output}")
            
            # Open the folder containing the output file
            self._open_folder(self.output)
            
        except KeyboardInterrupt:
            print(f"\n{self.CLR_FAIL}⚠️  Operation interrupted.{self.CLR_END}")
            sys.exit(1)
        except Exception as e:
            print(f"{self.CLR_FAIL}❌ Error: {e}{self.CLR_END}")
            sys.exit(1)

    @staticmethod
    def _natural_sort_key(path: Path):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(path))]

if __name__ == "__main__":
    ConcatFilesApp.from_cli()
