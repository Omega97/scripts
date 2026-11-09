import os
from pathlib import Path

YELLOW = "\033[33m"
RESET = "\033[0m"
N_COLS = 3
WIDTH = 23


def _enable_windows_ansi():
    """Turn on ANSI colors in the classic Windows console."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except OSError:
        pass


def command_names(batch_dir):
    names = []
    for f in os.listdir(batch_dir):
        full_path = os.path.join(batch_dir, f)
        if os.path.isfile(full_path):
            name, ext = os.path.splitext(f)
            if ext.lower() in (".bat", ".cmd"):
                names.append(name)
    names.sort()
    return names


def print_grid(names, color=""):
    for i in range(0, len(names), N_COLS):
        row = names[i : i + N_COLS]
        line = "".join(f"{name:<{WIDTH}}" for name in row)
        if color:
            print(f"{color}{line}{RESET}")
        else:
            print(line)


def main():
    # Repo root is parent of Programs/; bats live in batch/ and batch-private/.
    root = Path(__file__).resolve().parent.parent
    _enable_windows_ansi()

    batch_dir = root / "batch"
    try:
        names = command_names(batch_dir)
    except FileNotFoundError:
        print(f"Errore: la directory '{batch_dir}' non esiste.")
        return
    print_grid(names)

    private_dir = root / "batch-private"
    try:
        private_names = command_names(private_dir)
    except FileNotFoundError:
        print(f"Errore: la directory '{private_dir}' non esiste.")
        return
    if private_names:
        print()
        print_grid(private_names, YELLOW)


if __name__ == "__main__":
    main()
