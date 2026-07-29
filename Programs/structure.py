#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import re
import subprocess
import platform

class FolderTreeApp:
    # Default Values
    CONFIRM_THRESHOLD = 1000
    MAX_DEPTH = 50
    DEFAULT_OUTPUT_DIR = Path(r"C:\summaries")
    
    # ANSI Color Codes (Works on Windows 10/11 Console)
    CLR_HEADER = '\033[95m'
    CLR_OKBLUE = '\033[94m'
    CLR_OKCYAN = '\033[96m'
    CLR_OKGREEN = '\033[92m'
    CLR_WARNING = '\033[93m'
    CLR_FAIL = '\033[91m'
    CLR_BOLD = '\033[1m'
    CLR_END = '\033[0m'
    
    # Tree drawing characters
    TREE_VERTICAL = '│'
    TREE_BRANCH = '├──'
    TREE_LAST = '└──'
    TREE_SPACE = '    '
    
    # Text-like extensions (for filtering)
    TEXT_EXTENSIONS = {
        '.txt', '.md', '.py', '.js', '.json', '.html', '.css', '.java',
        '.cpp', '.c', '.ts', '.sh', '.xml', '.yaml', '.yml', '.go',
        '.rb', '.php', '.sql', '.rs', '.ipynb'
    }
    
    # Folders to ignore by default
    DEFAULT_IGNORE_FOLDERS = {
        '.git', '__pycache__', 'node_modules', '.venv', 'venv',
        '.idea', '.vscode', 'build', 'dist', '.pytest_cache'
    }

    def __init__(
        self,
        extensions=None,
        output: str | None = None,
        max_depth: int = 50,
        ignore_folders=None,
        show_files: bool = True,
        show_folders: bool = True,
        show_size: bool = False,
        sort_by: str = 'name',
        force: bool = False,
    ):
        self.dir_path = Path.cwd()
        self.extensions = {f".{str(ext).lstrip('.')}" for ext in extensions} if extensions else None
        self.max_depth = max_depth
        self.ignore_folders = set(ignore_folders) if ignore_folders else self.DEFAULT_IGNORE_FOLDERS
        self.show_files = show_files
        self.show_folders = show_folders
        self.show_size = show_size
        self.sort_by = sort_by
        self.force = force
        
        if output:
            self.output = Path(output).resolve()
        else:
            # Ensure the default directory exists
            out_dir = self.DEFAULT_OUTPUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename based on current folder name to avoid conflicts
            folder_name = self.dir_path.name
            self.output = out_dir / f"tree_{folder_name}.txt"

    @classmethod
    def from_cli(cls):
        """Parse command line arguments."""
        args = sys.argv[1:]
        if any(arg in ('-h', '--help') for arg in args):
            print(f"{cls.CLR_BOLD}{cls.CLR_OKBLUE}Usage:{cls.CLR_END} foldertree [options]")
            print()
            print(f"{cls.CLR_BOLD}Options:{cls.CLR_END}")
            print(f"  -o <path>          Output file path (Default: {cls.DEFAULT_OUTPUT_DIR})")
            print(f"  --ext <ext1 ext2>  Filter by extensions (e.g., py md)")
            print(f"  --max-depth <N>    Maximum depth to traverse (Default: {cls.MAX_DEPTH})")
            print(f"  --ignore <folders> Folders to ignore (e.g., .git node_modules)")
            print(f"  --files-only       Show only files")
            print(f"  --folders-only     Show only folders")
            print(f"  --show-size        Show file sizes (Default: hidden)")
            print(f"  --sort <criteria>  Sort by: name, size, date (Default: name)")
            print(f"  --force            Skip confirmation for >{cls.CONFIRM_THRESHOLD} items")
            print()
            print(f"{cls.CLR_BOLD}Examples:{cls.CLR_END}")
            print("  foldertree                          # Show all files and folders")
            print("  foldertree --ext py md              # Show only .py and .md files")
            print("  foldertree --files-only             # Show files only")
            print("  foldertree --folders-only           # Show folders only")
            print()
            return

        # Parse arguments
        extensions = None
        output = None
        max_depth = cls.MAX_DEPTH
        ignore_folders = None
        show_files = True
        show_folders = True
        show_size = False
        sort_by = 'name'
        force = False
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == '-o' and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            elif arg == '--ext' and i + 1 < len(args):
                extensions = []
                i += 1
                while i < len(args) and not args[i].startswith('--'):
                    extensions.append(args[i])
                    i += 1
            elif arg == '--max-depth' and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except ValueError:
                    print(f"{cls.CLR_FAIL}Error: --max-depth requires a number{cls.CLR_END}")
                    sys.exit(1)
                i += 2
            elif arg == '--ignore' and i + 1 < len(args):
                ignore_folders = []
                i += 1
                while i < len(args) and not args[i].startswith('--'):
                    ignore_folders.append(args[i])
                    i += 1
            elif arg == '--files-only':
                show_folders = False
                i += 1
            elif arg == '--folders-only':
                show_files = False
                i += 1
            elif arg == '--show-size':
                show_size = True
                i += 1
            elif arg == '--no-size':
                show_size = False
                i += 1
            elif arg == '--sort' and i + 1 < len(args):
                sort_by = args[i + 1].lower()
                if sort_by not in ('name', 'size', 'date'):
                    print(f"{cls.CLR_FAIL}Error: --sort must be name, size, or date{cls.CLR_END}")
                    sys.exit(1)
                i += 2
            elif arg == '--force':
                force = True
                i += 1
            elif arg.startswith('-'):
                print(f"{cls.CLR_FAIL}Unknown option: {arg}{cls.CLR_END}")
                sys.exit(1)
            else:
                i += 1

        app = cls(
            extensions=extensions,
            output=output,
            max_depth=max_depth,
            ignore_folders=ignore_folders,
            show_files=show_files,
            show_folders=show_folders,
            show_size=show_size,
            sort_by=sort_by,
            force=force,
        )
        return app.run()

    def _count_items_fast(self) -> int:
        """Quick count of items to confirm with user."""
        count = 0
        for root, dirs, files in os.walk(self.dir_path):
            # Filter ignored and hidden folders consistently
            dirs[:] = [d for d in dirs if d not in self.ignore_folders and not d.startswith('.')]
            
            if self.show_folders:
                count += len(dirs)
            if self.show_files:
                if self.extensions:
                    count += sum(1 for f in files if Path(f).suffix.lower() in self.extensions)
                else:
                    count += len(files)
                    
            if count > self.CONFIRM_THRESHOLD:
                return count
        return count

    def _get_items(self, path: Path) -> tuple[list[Path], list[Path]]:
        """Get sorted folders and files in a directory."""
        folders = []
        files = []
        try:
            for item in path.iterdir():
                if item.is_dir():
                    # Skip ignored and hidden folders
                    if item.name in self.ignore_folders or item.name.startswith('.'):
                        continue
                    if not self.show_folders:
                        continue
                    folders.append(item)
                elif item.is_file():
                    # Filter by extension if specified
                    if self.extensions and item.suffix.lower() not in self.extensions:
                        continue
                    if not self.show_files:
                        continue
                    files.append(item)
        except PermissionError:
            pass
            
        # Sort items
        if self.sort_by == 'name':
            folders.sort(key=lambda x: x.name.lower())
            files.sort(key=lambda x: x.name.lower())
        elif self.sort_by == 'size':
            folders.sort(key=lambda x: x.name.lower())
            files.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
        elif self.sort_by == 'date':
            folders.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
            files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
            
        return folders, files

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:7.1f} {unit}"
            size /= 1024
        return f"{size:7.1f} PB"

    def _build_tree(
        self,
        path: Path,
        prefix: str = "",
        depth: int = 0,
        output_lines: list = None,
        stats: dict = None,
    ) -> None:
        """Recursively build the folder tree structure."""
        if output_lines is None:
            output_lines = []
        if stats is None:
            stats = {'folders': 0, 'files': 0, 'total_size': 0}
            
        if depth > self.max_depth:
            return
            
        folders, files = self._get_items(path)
        
        # Update stats
        stats['folders'] += len(folders)
        stats['files'] += len(files)
        
        items = folders + files
        total_items = len(items)
        
        for index, item in enumerate(items):
            is_last = (index == total_items - 1)
            connector = self.TREE_LAST if is_last else self.TREE_BRANCH
            
            # Build the line
            if item.is_dir():
                line = f"{prefix}{connector} {self.CLR_OKCYAN}📁 {item.name}/{self.CLR_END}"
            else:
                size_str = ""
                if self.show_size:
                    try:
                        size = item.stat().st_size
                        stats['total_size'] += size
                        size_str = f" {self.CLR_WARNING}({self._format_size(size)}){self.CLR_END}"
                    except Exception:
                        size_str = ""
                line = f"{prefix}{connector} {self.CLR_OKGREEN}📄 {item.name}{self.CLR_END}{size_str}"
                
            output_lines.append(line)
            
            # Recurse into folders
            if item.is_dir():
                new_prefix = prefix + (self.TREE_SPACE if is_last else self.TREE_VERTICAL + self.TREE_SPACE)
                self._build_tree(item, new_prefix, depth + 1, output_lines, stats)

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
            print(f"{FolderTreeApp.CLR_WARNING}⚠️  Could not open folder automatically: {e}{FolderTreeApp.CLR_END}")

    def run(self) -> None:
        print(f"\n{self.CLR_BOLD}Scanning:{self.CLR_END} {self.dir_path}")
        
        # Quick count for confirmation
        item_count = self._count_items_fast()
        if item_count > self.CONFIRM_THRESHOLD and not self.force:
            print(f"\n{self.CLR_WARNING}⚠️  Found approximately {item_count} items to process.{self.CLR_END}")
            response = input("Are you sure? (y/N): ").strip().lower()
            if response not in ('y', 'yes'):
                print(f"{self.CLR_FAIL}Operation cancelled.{self.CLR_END}")
                sys.exit(0)
                
        # Build the tree
        output_lines = []
        stats = {'folders': 0, 'files': 0, 'total_size': 0}
        
        # Header
        output_lines.append(f"{self.CLR_BOLD}{self.dir_path.name}/{self.CLR_END}")
        output_lines.append("")
        
        self._build_tree(self.dir_path, "", 0, output_lines, stats)
        
        # Summary
        output_lines.append("")
        output_lines.append(f"{self.CLR_OKBLUE}{'─' * 50}{self.CLR_END}")
        output_lines.append(f"{self.CLR_BOLD}Summary:{self.CLR_END}")
        output_lines.append(f"  {self.CLR_OKCYAN}📁 Folders:{self.CLR_END} {stats['folders']}")
        output_lines.append(f"  {self.CLR_OKGREEN}📄 Files:{self.CLR_END} {stats['files']}")
        if self.show_size:
            output_lines.append(f"  {self.CLR_WARNING}📊 Total Size:{self.CLR_END} {self._format_size(stats['total_size'])}")
            
        # Output to console and/or file
        tree_output = "\n".join(output_lines)
        
        try:
            # Print to console
            print("\n" + tree_output)
            
            # Also save to file
            with self.output.open("w", encoding="utf-8") as f:
                # Strip ANSI codes for file output
                ansi_escape = re.compile(r'\033\[[0-9;]*m')
                clean_output = ansi_escape.sub('', tree_output)
                f.write(clean_output)
                
            print(f"\n{self.CLR_OKGREEN}✅ Success! Output written to:{self.CLR_END}")
            print(f"Output: {self.output}")
            
            # Open the folder containing the output file
            self._open_folder(self.output)
            
        except KeyboardInterrupt:
            print(f"\n{self.CLR_FAIL}⚠️  Operation interrupted.{self.CLR_END}")
            sys.exit(1)
        except Exception as e:
            print(f"{self.CLR_FAIL}❌ Error: {e}{self.CLR_END}")
            sys.exit(1)

if __name__ == "__main__":
    FolderTreeApp.from_cli()
