"""This program downloads pictures from the web in parallel."""
import requests
import argparse
import re
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Constants
EXTENSIONS = ['.jpg', '.png', '.jpeg', '.webp']
NUMBER_OF_PROCESSES = 8  # Number of parallel workers
MAX_RETRIES = 3          # Maximum retry attempts for failed downloads

# Default User-Agent to prevent 403 Forbidden errors on some sites
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/91.0.4472.124 Safari/537.36'
}

def sanitize_filename(name: str) -> str:
    r"""Remove characters that are invalid for Windows filenames."""
    return re.sub(r'[<>:"\/?*]', '_', name)

def generate_url_cascade(url: str, img_type: str = None) -> list[dict]:
    """Generate the urls of the images in the gallery."""
    if not any(url.lower().endswith(ext) for ext in EXTENSIONS):
        raise ValueError(f'Invalid url: {url} must end with one of {EXTENSIONS}')
        
    if img_type is None:
        img_type = url.split('.')[-1].lower()

    parts = url.split('/')
    if len(parts) < 2:
        raise ValueError(f'Invalid URL structure: {url}')

    gallery_raw = parts[-2]
    gallery = sanitize_filename(gallery_raw)

    try:
        n = int(parts[-1].split('.')[0])
    except ValueError:
        raise ValueError(f'Could not determine image count from URL: {url}')

    urls = []
    base_path_parts = parts[:-1]
    base_url = '/'.join(base_path_parts)

    for i in range(n):
        img_num = i + 1
        new_url = f"{base_url}/{img_num}.{img_type}"
        _id = f'{img_num:03d}'
        dct = {
            'url': new_url,
            'gallery': gallery,
            'id': _id,
            'extension': f'.{img_type}',
            'name': f'{gallery}_{_id}.{img_type}'
        }
        urls.append(dct)
    return urls

class Handler:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)

    def download_image_from_page(self, gallery: str, name: str, url: str, timeout: int = 10) -> bool:
        """Download a single image. Returns True on success, False on failure."""
        gallery_dir = self.path / gallery
        file_path = gallery_dir / name

        if file_path.exists():
            print(f"{name} already downloaded ✅")
            return True

        gallery_dir.mkdir(parents=True, exist_ok=True)

        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            with open(file_path, 'wb') as f:
                f.write(response.content)
            print(f"{name} saved successfully ✅")
            return True
        except requests.exceptions.RequestException as e:
            print(f"\nNetwork error downloading {name}: {e}")
            return False
        except OSError as e:
            print(f"\nI/O error saving {name}: {e}")
            return False

    def download_gallery(self, url: str, img_type: str = None):
        """Download the gallery from the url using parallel workers."""
        if img_type is not None:
            print(f'\nOverwriting the image type with {img_type}')

        try:
            gallery_display = sanitize_filename(url.split('/')[-2])
        except IndexError:
            gallery_display = "unknown_gallery"

        print(f'\nProcessing Gallery: {gallery_display}')
        print(f'Saving to: {self.path}')

        try:
            image_list = generate_url_cascade(url, img_type=img_type)
        except ValueError as e:
            print(f"\nError processing URL: {e}")
            return

        if not image_list:
            print("No images found in cascade.")
            return

        # Parallel download with retry tracking
        pending = image_list.copy()
        downloaded = set()
        attempt = 0

        while pending and attempt < MAX_RETRIES:
            attempt += 1
            print(f"\n--- Batch Attempt {attempt}/{MAX_RETRIES} ---")
            failed_this_batch = []

            # ThreadPoolExecutor is used because network downloads are I/O-bound.
            # Change to ProcessPoolExecutor if you later add CPU-intensive processing.
            with ThreadPoolExecutor(max_workers=NUMBER_OF_PROCESSES) as executor:
                # Map futures to their metadata for uniform task dispatch
                future_to_info = {
                    executor.submit(self.download_image_from_page, dct['gallery'], dct['name'], dct['url']): dct
                    for dct in pending
                }

                for future in as_completed(future_to_info):
                    info = future_to_info[future]
                    try:
                        success = future.result()
                        if success:
                            downloaded.add(info['name'])
                        else:
                            failed_this_batch.append(info)
                    except Exception as e:
                        failed_this_batch.append(info)
                        print(f"Unexpected exception for {info['name']}: {e}")

            pending = failed_this_batch
            if pending and attempt < MAX_RETRIES:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"\n{len(pending)} files failed. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

        # Final report
        if pending:
            print(f"\n❌ Failed to download after {MAX_RETRIES} attempts: {len(pending)} images")
            for d in pending:
                print(f"   - {d['name']}")
        else:
            print(f"\n✅ Successfully downloaded {len(downloaded)}/{len(image_list)} images!")

        print('\nDone!')

def main():
    default_path = Path.cwd() / '_downloads'
    parser = argparse.ArgumentParser(description="Download images from the web in parallel.")

    parser.add_argument("url", type=str, nargs='*',
                        help="URL(s) of the last page of the gallery (ending with the extension)")

    parser.add_argument("-t", "--type", type=str, default=None,
                        help="Image type, overwrites the one in the url (e.g., jpg, png)")

    parser.add_argument("-p", "--path", type=str, default=str(default_path),
                        help=f"Output folder path (default: {default_path})")

    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Run in interactive mode (wait for user input)")

    args = parser.parse_args()
    handler = Handler(args.path)

    urls_to_process = [u.strip() for u in args.url if u.strip()]

    if not urls_to_process or args.interactive:
        print()
        print("=" * 60)
        print("  H-Downloader - Interactive Mode (Parallel)")
        print("=" * 60)
        print(f"Download folder: {handler.path}")
        print(f"Parallel workers: {NUMBER_OF_PROCESSES}")
        print(f"Image type override: {args.type if args.type else 'Auto-detect'}")
        print("\nInstructions:")
        print("  - Enter a URL ending with an image number (e.g., .../10.jpg)")
        print("  - Press Enter to download")
        print("  - Type 'quit', 'exit', or 'q' to stop")
        print("  - Press Ctrl+C to exit anytime")
        print("=" * 60)

        while True:
            try:
                print()
                url = input("Enter URL (or 'quit' to exit):  ").strip()
                if not url:
                    print("No URL entered. Please try again.")
                    continue
                if url.lower() in ['quit', 'exit', 'q']:
                    print("\nGoodbye!")
                    break
                handler.download_gallery(url, img_type=args.type)
            except KeyboardInterrupt:
                print("\n\nInterrupted by user. Goodbye!")
                break
            except EOFError:
                print("\n\nInput stream closed. Goodbye!")
                break
    else:
        for url in urls_to_process:
            handler.download_gallery(url, img_type=args.type)

    print("\nAll done!")

if __name__ == "__main__":
    main()
    