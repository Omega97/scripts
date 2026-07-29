# scripts

Personal Windows toolkit: small Python utilities and launchers, exposed as named commands via `.bat` files.

Each command is a short batch wrapper in `batch/` that runs a script under `Programs/` (and optionally a dedicated virtual environment under `venvs/`). Putting `batch` on your `PATH` lets you type the command name from any directory.

## Layout

```text
scripts/                 # repo root (ROOT)
├── batch/               # command entry points (*.bat) — put this on PATH
├── Programs/            # Python scripts and other program assets
├── venvs/               # one venv per command that needs third-party packages
├── data/                # local data / outputs (gitignored)
├── _other/              # archives and one-offs (gitignored)
└── README.md
```

| Path | Role |
|------|------|
| `batch/` | Public commands. Filename without `.bat` is the command name (`md_to_pdf.bat` → `md_to_pdf`). |
| `Programs/` | Implementation scripts (usually Python). |
| `venvs/` | Isolated envs when a script needs `pip` packages. |
| `data/` | Runtime data, keys, generated summaries — not committed. |

### Path convention in batch files

Batch files live in `batch/`, so they resolve the repo root as the parent of their own folder:

```bat
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
```

All script and venv paths are then built as `%ROOT%\…`, never hardcoded as `C:\scripts\…`.

Example (no venv):

```bat
@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
python "%ROOT%\Programs\concatfiles.py" %*
```

## Prerequisites

- Windows
- Python 3 (available as `py` and/or `python` on PATH)
- `batch` on PATH so commands resolve from any working directory:

  ```text
  C:\scripts\batch
  ```

List known commands:

```bat
commands
```

## Adding a new command

Follow this checklist whenever you add a tool, the same way `md_to_pdf` was added.

### 1. Choose a command name

Use a short, stable name (e.g. `md_to_pdf`, `concatfiles`). That name becomes:

- `Programs\<name>.py` (or a clear related filename)
- `batch\<name>.bat`
- `venvs\_<name>_venv\` **only if** third-party packages are required

Aliases are fine: e.g. `cf.bat` and `concatfiles.bat` can both call the same script.

### 2. Write the script in `Programs/`

Create `Programs/<name>.py` with:

- A real CLI (`argparse` or equivalent) so the batch wrapper can pass `%*`
- Clear errors and non-zero exit codes on failure
- No hard-coded machine-specific paths when a relative or env-based path works

Prefer stdlib-only when possible so you can skip a dedicated venv.

### 3. Create a venv only if needed

If the script imports packages that are not in the standard library:

```bat
py -m venv C:\scripts\venvs\_<name>_venv
C:\scripts\venvs\_<name>_venv\Scripts\pip install <packages>
```

Naming convention used in this repo:

- `_md_to_pdf_venv`, `_genesys_venv`, `_h_downloader_venv` (leading underscore + command-ish name)
- `tags_venv` (older style without leading underscore — either is fine; stay consistent for new ones)

Keep one venv per command (or per related family of commands that share the same deps).

### 4. Add the batch file in `batch/`

**Without venv** (uses system `python`):

```bat
@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
python "%ROOT%\Programs\<name>.py" %*
```

**With venv** (preferred when packages were installed in step 3):

```bat
@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

set "VENV_DIR=%ROOT%\venvs\_<name>_venv"
set "SCRIPT=%ROOT%\Programs\<name>.py"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at "%VENV_DIR%"
    echo Please run the setup for a new venv:
    echo   py -m venv "%ROOT%\venvs\_<name>_venv"
    echo   "%ROOT%\venvs\_<name>_venv\Scripts\pip" install <packages>
    exit /b 1
)

"%VENV_DIR%\Scripts\python.exe" "%SCRIPT%" %*
```

Notes:

- Do **not** use `%~dp0Programs\…` — that points into `batch\`, not the repo root.
- Prefer no trailing `pause` unless the tool is interactive and you want the window to stay open.
- Pass through all arguments with `%*`.

### 5. Smoke-test

From any directory (with `batch` on PATH):

```bat
<name> --help
```

Or call the bat explicitly:

```bat
C:\scripts\batch\<name>.bat --help
```

For a venv-based command, confirm the bat finds `venvs\_<name>_venv\Scripts\python.exe` and does not look under `batch\venvs\`.

### 6. Example: `md_to_pdf`

| Piece | Path |
|-------|------|
| Script | `Programs\md_to_pdf.py` |
| Venv | `venvs\_md_to_pdf_venv` (`markdown`, `xhtml2pdf`, `pygments`) |
| Command | `batch\md_to_pdf.bat` |

Usage:

```bat
md_to_pdf notes.md
md_to_pdf notes.md out.pdf
md_to_pdf notes.md out.pdf --css custom.css
```

## What not to put in git

See `.gitignore`. Roughly:

- `_other/`, `data/`
- `Programs/exiftool_files/`
- `*.exe`

Virtual environments under `venvs/` may be large; recreate them with the setup lines printed by the batch file if missing.

## Related files

- `ai-feed.md` — scratch / ideas feed for new tools (local; not part of the command runtime)
- `commands` — lists every `batch\*.bat` name
- `programs` — also lists batch command names from the `batch` folder
