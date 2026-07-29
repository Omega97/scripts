import os
from pathlib import Path


def main():
    # Repo root is parent of Programs/; bats live in batch/
    root = Path(__file__).resolve().parent.parent
    batch_dir = root / "batch"
    N_COLS = 3
    WIDTH = 23

    try:
        files = os.listdir(batch_dir)
    except FileNotFoundError:
        print(f"Errore: la directory '{batch_dir}' non esiste.")
        return

    # Filtra i file batch (.bat e .cmd)
    batch_files = []
    for f in files:
        full_path = os.path.join(batch_dir, f)
        if os.path.isfile(full_path):
            name, ext = os.path.splitext(f)
            if ext.lower() in (".bat", ".cmd"):
                batch_files.append(name)

    # Ordina alfabeticamente
    batch_files.sort()

    # Stampa in colonne
    for i in range(0, len(batch_files), N_COLS):
        row = batch_files[i : i + N_COLS]
        line = "".join(f"{name:<{WIDTH}}" for name in row)
        print(line)


if __name__ == "__main__":
    main()
