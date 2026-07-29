#!/usr/bin/env python3
"""
Yu-Gi-Oh! GENESYS Card Points CLI Tool
---------------------------------------
Search and manage the official GENESYS card point list.
Usage:
genesys.py [SEARCH_TERM]          # Search cards containing SEARCH_TERM
genesys.py --update               # Force refresh card list from web
genesys.py --list                 # Show all cards
genesys.py --sort points          # Sort results by points (high to low)
genesys.py --help                 # Show help
Examples:
genesys.py ash                    # Find cards with "ash" in name
genesys.py --update dragon        # Refresh list, then search "dragon"
genesys.py --list --sort points   # List all cards sorted by points (high to low)
genesys.py ash --sort points-asc  # Search "ash", sort by points (low to high)
genesys.py ""                     # Show all cards (empty search)
"""
import argparse
import csv
import os
import sys
from pathlib import Path
from typing import List, Tuple
import requests
from bs4 import BeautifulSoup

# Repo root is parent of Programs/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = str(_PROJECT_ROOT / "data" / "genesys_cards.csv")

# Color palette for card points based on value ranges
# Format: (min_points, max_points, color_code, color_name)
COLOR_PALETTE = [
    (1, 5, '\033[92m', 'green'),      # Bright green for low cost
    (6, 16, '\033[93m', 'yellow'),    # Bright yellow for medium-low cost
    (17, 33, '\033[38;5;208m', 'orange'),  # Orange for medium-high cost
    (34, 999999, '\033[91m', 'red'),  # Bright red for high cost
]

# Enable ANSI escape code processing on Windows 10+
if os.name == 'nt':
    os.system('')


def colorize_points(points: int, width: int, use_color: bool = True) -> str:
    """Format points with color based on value thresholds.
    
    Color mapping (from COLOR_PALETTE):
      - Green  (1-5):   low cost
      - Yellow (6-16):  medium-low cost
      - Orange (17-33): medium-high cost
      - Red    (34+):   high cost
    """
    formatted = f"{points:>{width}}"
    if not use_color:
        return formatted
    
    # Find the appropriate color based on points value
    color = '\033[97m'  # Default to white if no match
    for min_val, max_val, color_code, color_name in COLOR_PALETTE:
        if min_val <= points <= max_val:
            color = color_code
            break
    
    return f"{color}{formatted}\033[0m"


class GenesysScraper:
    """Specialized scraper for Yu-Gi-Oh! GENESYS card points table."""
    URL = "https://www.yugioh-card.com/en/genesys/"
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/120.0.0.0 Safari/537.36'
    }
    TIMEOUT = 15

    def __init__(self, cache_file: str = DEFAULT_DATA_FILE):
        self.cache_file = Path(cache_file)
        self.cards: List[Tuple[str, int]] = []

    def load_from_cache(self) -> bool:
        """Load card data from local CSV cache."""
        if not self.cache_file.exists():
            return False
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.cards = [(row['Card Name'], int(row['Points'])) for row in reader]
            return True
        except Exception as e:
            print(f"Warning: Failed to load cache ({e})", file=sys.stderr)
            return False

    def save_to_cache(self) -> bool:
        """Save current card data to CSV cache."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Card Name', 'Points'])
                writer.writeheader()
                for name, points in self.cards:
                    writer.writerow({'Card Name': name, 'Points': points})
            return True
        except Exception as e:
            print(f"Error: Failed to save cache ({e})", file=sys.stderr)
            return False

    def download_from_web(self) -> bool:
        """Download and parse card data from official website."""
        try:
            response = requests.get(self.URL, headers=self.DEFAULT_HEADERS, timeout=self.TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            tables = soup.find_all('table')

            # Find table with "Card Name" and "Points" headers
            for table in tables:
                rows = table.find_all('tr')
                if not rows:
                    continue
                headers = [h.get_text(strip=True).lower() for h in rows[0].find_all(['th', 'td'])]
                if not (any('card' in h and 'name' in h for h in headers)
                        and any('point' in h for h in headers)):
                    continue
                self.cards = []
                for row in rows[1:]:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 2:
                        continue
                    card_name = ' '.join(cells[0].get_text(strip=True).split())
                    points_text = cells[1].get_text(strip=True)
                    points = int(points_text) if points_text.isdigit() else 0
                    if card_name:
                        self.cards.append((card_name, points))
                return bool(self.cards)

            # Fallback: try to find any 2-column table that looks like card data
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        cell0 = ' '.join(cells[0].get_text(strip=True).split())
                        cell1 = ' '.join(cells[1].get_text(strip=True).split())
                        if cell0 and not cell0.isdigit() and (cell1.isdigit() or not cell1):
                            points = int(cell1) if cell1.isdigit() else 0
                            self.cards.append((cell0, points))
                if self.cards:
                    return True

            print("Error: Could not find card points table on page", file=sys.stderr)
            return False

        except requests.exceptions.Timeout:
            print(f"Error: Request timed out after {self.TIMEOUT}s", file=sys.stderr)
        except requests.exceptions.ConnectionError:
            print("Error: Failed to connect to server. Check internet connection.", file=sys.stderr)
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error {e.response.status_code}: {e.response.reason}", file=sys.stderr)
        except Exception as e:
            print(f"Error: {type(e).__name__}: {str(e)}", file=sys.stderr)
        return False

    def ensure_data(self, force_update: bool = False) -> bool:
        """Ensure card data is available (load from cache or download)."""
        if not force_update and self.load_from_cache():
            return True
        print("Downloading latest card list from official website...", file=sys.stderr)
        if not self.download_from_web():
            return False
        if self.save_to_cache():
            print(f"✓ Saved {len(self.cards)} cards to {self.cache_file.name}", file=sys.stderr)
        return True

    def search(self, query: str = "") -> List[Tuple[str, int]]:
        """Search cards containing query string (case-insensitive substring match)."""
        if not query:
            return self.cards
        query_lower = query.lower()
        return [(name, points) for name, points in self.cards if query_lower in name.lower()]


def sort_results(results: List[Tuple[str, int]], sort_key: str) -> List[Tuple[str, int]]:
    """Sort card results by the chosen key.

    sort_key:
      - 'name'       : alphabetical (A-Z), case-insensitive
      - 'points'     : points high to low; ties broken alphabetically
      - 'points-asc' : points low to high; ties broken alphabetically
    """
    if sort_key == 'points':
        return sorted(results, key=lambda x: (-x[1], x[0].lower()))
    if sort_key == 'points-asc':
        return sorted(results, key=lambda x: (x[1], x[0].lower()))
    # default: alphabetical
    return sorted(results, key=lambda x: x[0].lower())


def print_colored_help():
    """Print a custom colorized help screen."""
    # ANSI escape codes (disabled if not printing to a terminal)
    is_tty = sys.stdout.isatty()
    W = '\033[97m' if is_tty else ''  # White (normal text)
    C = '\033[96m' if is_tty else ''  # Cyan (commands)
    A = '\033[93m' if is_tty else ''  # Yellow (arguments)
    M = '\033[90m' if is_tty else ''  # Gray (comments)
    R = '\033[0m'  if is_tty else ''  # Reset

    help_text = f"""
{W}\nYu-Gi-Oh! GENESYS Card Points CLI Tool{R}
{W}---------------------------------------{R}
{W}Search and manage the official GENESYS card point list.{R}

{W}Usage:{R}
  {C}genesys{R} {A}[SEARCH_TERM]{R}          {M}# Search cards containing SEARCH_TERM{R}
  {C}genesys{R} {A}--update{R}               {M}# Force refresh card list from web{R}
  {C}genesys{R} {A}--list{R}                 {M}# Show all cards{R}
  {C}genesys{R} {A}--sort{R} {A}points{R}          {M}# Sort results by points (high to low){R}
  {C}genesys{R} {A}--help{R}                 {M}# Show help{R}

{W}Examples:{R}
  {C}genesys{R} {A}ash{R}                    {M}# Find cards with "ash" in name{R}
  {C}genesys{R} {A}--update{R} {A}dragon{R}        {M}# Refresh list, then search "dragon"{R}
  {C}genesys{R} {A}--list{R} {A}--sort{R} {A}points{R}   {M}# List all cards sorted by points{R}
  {C}genesys{R} {A}""{R}                     {M}# Show all cards (empty search){R}
"""
    print(help_text.strip())
    print(f"\n{M}Hint: Provide a search term to filter cards, or use {A}--list{M} to show all{R}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Yu-Gi-Oh! GENESYS Card Points CLI Tool",
        epilog="Examples:\n"
               "  genesys.py ash                     # Search cards with 'ash'\n"
               "  genesys.py --update dragon         # Refresh list, then search 'dragon'\n"
               "  genesys.py --list --sort points    # All cards, points high to low\n"
               "  genesys.py ash --sort points-asc   # Search 'ash', points low to high\n"
               "  genesys.py ''                      # Show all cards",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'search_term',
        nargs='?',
        default=None,
        help='Search term to filter cards (case-insensitive substring match)'
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='Force download latest card list from web (ignores local cache)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='Show all cards (same as empty search term)'
    )
    parser.add_argument(
        '--sort',
        choices=['name', 'points', 'points-asc'],
        default='name',
        help='Sort order: name (alphabetical, default), '
             'points (high to low), points-asc (low to high)'
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored point output (useful when piping to a file)'
    )
    parser.add_argument(
        '--file',
        default=DEFAULT_DATA_FILE,
        help=f'CSV cache filename ({DEFAULT_DATA_FILE})'
    )
    args = parser.parse_args()

    # Determine search term
    if args.list:
        search_term = ""
    elif args.search_term is not None:
        search_term = args.search_term
    else:
        search_term = None  # No search term provided -> show help

    # Initialize scraper
    scraper = GenesysScraper(cache_file=args.file)

    # Ensure we have data (download if needed)
    if not scraper.ensure_data(force_update=args.update):
        sys.exit(1)

    # If no search term provided, show help and exit
    if search_term is None:
        print_colored_help()
        sys.exit(0)

    # Perform search
    results = scraper.search(search_term)

    # Sort results
    results = sort_results(results, args.sort)

    # Display results
    if not results:
        print(f"No cards found containing '{search_term}'")
        sys.exit(0)

    # Color is enabled only when stdout is a TTY and --no-color was not passed
    use_color = (not args.no_color) and sys.stdout.isatty()

    # Find max points width for alignment (at least 3 chars for "100")
    max_points_width = max(len(str(points)) for _, points in results) + 1
    for name, points in results:
        colored_points = colorize_points(points, max_points_width, use_color)
        print(f"{colored_points}  {name}")

    # Print summary to stderr (doesn't interfere with piping output)
    print(f"\n{len(results)} card(s) found", file=sys.stderr)


if __name__ == "__main__":
    main()
