import argparse
import os
import subprocess
import sys
import tempfile
from PIL import Image


def _explain_ffmpeg_error(stderr: str) -> list[str]:
    """Return a list of likely causes for an FFmpeg failure."""
    hints = []
    low = stderr.lower()
    if "not divisible by 2" in low or "height not divisible" in low or "width not divisible" in low:
        hints.append(
            "The frame dimensions are odd (e.g. 720x405), which libx264/yuv420p "
            "rejects. The scale filter should have fixed this, so verify FFmpeg "
            "supports the `scale` filter."
        )
    if "unknown encoder" in low or "encoder 'libx264'" in low or "could not find codec" in low:
        hints.append(
            "FFmpeg was built without the libx264 encoder. Reinstall FFmpeg with "
            "H.264 support, or switch `-c:v` to another encoder (e.g. mpeg4)."
        )
    if "invalid data found" in low or "error while decoding" in low or "could not find codec parameters" in low:
        hints.append(
            "FFmpeg could not decode the extracted PNG frames. The source WebP may "
            "be corrupt, or Pillow wrote malformed frames."
        )
    if "no such file or directory" in low:
        hints.append(
            "FFmpeg could not find a file. The temporary directory may have been "
            "removed prematurely, or the output path is not writable."
        )
    if "permission denied" in low:
        hints.append(
            "The output file could not be written due to missing permissions. Check "
            "the current directory's write access."
        )
    if not hints:
        hints.append("No known cause matched the FFmpeg output. See the error below.")
    return hints


def convert_webp_to_mp4(keep: bool):
    # Find all .webp files in the current working directory
    webp_files = [f for f in os.listdir(".") if f.lower().endswith(".webp")]

    if not webp_files:
        print("No .webp files found in the current directory.")
        return 0

    print(f"Found {len(webp_files)} WebP file(s) to process.")

    failures = 0

    for webp_file in webp_files:
        base_name = os.path.splitext(webp_file)[0]
        output_mp4 = f"{base_name}.mp4"

        print(f"\nProcessing: {webp_file} -> {output_mp4}")

        # Create a temporary directory for frames
        with tempfile.TemporaryDirectory() as temp_dir:
            frame_count = 0
            durations = []
            try:
                with Image.open(webp_file) as img:
                    # Static WebP files are images, not animations.
                    if getattr(img, "n_frames", 1) <= 1:
                        print(f"  Skipped {webp_file}: It is a static image, not an animation.")
                        continue

                    while True:
                        durations.append(img.info.get("duration", 40))
                        frame_path = os.path.join(temp_dir, f"frame_{frame_count:04d}.png")
                        frame = img.convert("RGBA")
                        bg = Image.new("RGB", frame.size, (255, 255, 255))
                        bg.paste(frame, mask=frame.split()[3])
                        bg.save(frame_path)
                        frame_count += 1
                        img.seek(frame_count)
            except EOFError:
                pass  # Reached end of animation
            except Exception as e:
                print(f"  Error reading {webp_file}: {e}")
                print("    Possible causes:")
                print("      - The WebP file is corrupt, truncated, or an unsupported variant.")
                print("      - The file was deleted/moved while processing, or is not readable.")
                failures += 1
                continue

            if frame_count == 0:
                continue

            avg_ms = sum(durations) / len(durations)
            fps = 1000 / avg_ms if avg_ms > 0 else 25

            print(f"  Extracted {frame_count} frames. Encoding to MP4...")

            # Run FFmpeg to compile frames into MP4
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",  # Overwrite output file if it exists
                "-framerate",
                str(fps),
                "-i",
                os.path.join(temp_dir, "frame_%04d.png"),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                output_mp4,
            ]

            try:
                subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
                print(f"  Successfully created: {output_mp4}")
                if keep:
                    print(f"  Kept original: {webp_file}")
                else:
                    try:
                        os.remove(webp_file)
                        print(f"  Deleted original: {webp_file}")
                    except OSError as e:
                        print(f"  Created {output_mp4}, but could not delete {webp_file}: {e}")
                        failures += 1
            except FileNotFoundError:
                print("  FFmpeg was not found on PATH. Install FFmpeg and try again.")
                return 1
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode(errors="replace") if e.stderr else str(e)
                print(f"  FFmpeg failed for {webp_file}. Error: {err.strip()}")
                for hint in _explain_ffmpeg_error(err):
                    print(f"    Possible cause: {hint}")
                failures += 1

    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert animated WebP files in the current directory to MP4."
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the original WebP files. By default they are deleted after a successful conversion.",
    )
    args = parser.parse_args()
    return convert_webp_to_mp4(keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
