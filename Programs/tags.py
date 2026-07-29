import os
import sys
import subprocess
import shutil
import time
import tempfile

# Estensioni supportate
EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.avif', '.webp',
    '.webm', '.gif', '.mp4'
}

def get_exiftool_path():
    """Cerca exiftool nella cartella dello script o nel PATH."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_exe = os.path.join(script_dir, 'exiftool.exe')
    if os.path.isfile(local_exe):
        return local_exe
    path_exe = shutil.which('exiftool')
    if path_exe:
        return path_exe
    return None

def transform_folder_name(name: str) -> str:
    """Applica le regole di trasformazione."""
    tag = name.lower()
    tag = tag.replace(' ', '_')
    tag = tag.strip('_')
    return tag

def get_tags_for_file(filepath: str, base_dir: str) -> list:
    """
    Estrae i tag dalla struttura delle cartelle.
    Restituisce solo tag con lunghezza >= 2 caratteri.
    """
    dir_path = os.path.dirname(filepath)
    rel_dir = os.path.relpath(dir_path, base_dir)

    if rel_dir == '.':
        return []

    folders = rel_dir.split(os.sep)
    tags = []
    for folder in folders:
        tag = transform_folder_name(folder)
        # 🔹 Nuovo filtro: tag lungo almeno 2 caratteri
        if tag and len(tag) >= 2:
            tags.append(tag)

    # Rimuove duplicati mantenendo l'ordine
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)
    return unique_tags

def set_tags_exiftool(filepath: str, tags: list, exiftool_path: str):
    """Cancella i tag esistenti e imposta i nuovi, inclusi quelli per Windows."""
    # Crea una stringa con i tag separati da punto e virgola (formato preferito da Windows)
    tags_string = "; ".join(tags)

    cmd = [
        exiftool_path,
        '-overwrite_original',
        # Pulisce i campi precedenti
        '-Keywords=',
        '-IPTC:Keywords=',
        '-XMP:Subject=',
        '-EXIF:XPKeywords=',
        # Scrive i nuovi tag
        '-Keywords+=' + tags_string,
        '-IPTC:Keywords+=' + tags_string,
        '-XMP:Subject+=' + tags_string,
        '-EXIF:XPKeywords=' + tags_string,  # <--- QUESTO È IL CAMPO GIUSTO PER WINDOWS
        filepath
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✓ {os.path.basename(filepath)} → {', '.join(tags) if tags else '(nessun tag)'}")
    except subprocess.CalledProcessError as e:
        print(f"✗ Errore su {filepath}: {e.stderr.strip()}")

def main():
    # --- CARTELLA TARGET (sempre cwd) ---
    target_dir = os.getcwd()
    print(f"\n📂 Cartella target: {target_dir}\n")

    # --- EXIFTOOL ---
    exiftool = get_exiftool_path()
    if exiftool is None:
        print("❌ ERRORE: exiftool non trovato.")
        print("   Copia exiftool.exe in C:\\scripts\\Programs\\ o aggiungilo al PATH.")
        sys.exit(1)
    else:
        print(f"🔧 Usa exiftool: {exiftool}")

    # --- SCANSIONE PRELIMINARE (con filtro tag vuoti) ---
    print("⏳ Scansione dei file in corso...")
    file_list = []
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in EXTENSIONS:
                full_path = os.path.join(root, file)
                tags = get_tags_for_file(full_path, target_dir)
                # 🔹 Skip: se non ha tag, non lo includiamo nella lista
                if tags:
                    file_list.append((full_path, tags))

    if not file_list:
        print("⚠️  Nessun file trovato che riceverà dei tag (controlla che ci siano sottocartelle con nomi validi).")
        return

    # --- RIEPILOGO ---
    print(f"\n📄 Trovati {len(file_list)} file da elaborare (esclusi quelli senza tag).")
    print("\n⚠️  ATTENZIONE: Questa operazione MODIFICHERÀ i metadati (tags)")
    print("   di TUTTI questi file. I tag esistenti verranno SOSTITUITI.")
    print("   I nuovi tag verranno generati dai nomi delle cartelle.\n")

    # --- CONFERMA ---
    confirm = input("❓ Procedere con l'operazione? (s/S per confermare, qualsiasi altro tasto per annullare): ").strip().lower()
    if confirm != 's':
        print("\n❌ Operazione annullata. Nessun file è stato modificato.")
        return

    # --- ESECUZIONE IN BATCH CON MISURA DEL TEMPO ---
    print("\n🚀 Avvio dell'elaborazione in batch...\n")
    start_time = time.time()

    if not file_list:
        print("⚠️  Nessun file da elaborare.")
        return

    # --- ESECUZIONE A BLOCCHI TRAMITE ARGFILE (-@) ---
    # Non passiamo più tutti gli argomenti sulla riga di comando: su Windows la
    # riga di comando ha un limite di lunghezza (WinError 206) che con migliaia
    # di file viene superato. Scriviamo invece gli argomenti (uno per riga) in
    # un file temporaneo e lo passiamo a ExifTool con '-@'.
    #
    # Usiamo inoltre '-execute' tra un file e l'altro: senza questo separatore,
    # ExifTool applicherebbe l'INTERO set di opzioni accumulate a TUTTI i file
    # elencati in una stessa invocazione, facendo "trapelare" i tag di un file
    # su quelli successivi. Con '-execute' ogni file riceve solo i propri tag.
    CHUNK_SIZE = 300  # file per invocazione di exiftool
    total = len(file_list)
    processed = 0
    errors = 0

    for start in range(0, total, CHUNK_SIZE):
        chunk = file_list[start:start + CHUNK_SIZE]

        argfile_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.args', delete=False, encoding='utf-8'
            ) as argfile:
                argfile_path = argfile.name
                argfile.write('-overwrite_original\n')
                for filepath, tags in chunk:
                    tags_string = "; ".join(tags)
                    argfile.write('-Keywords=\n')
                    argfile.write('-IPTC:Keywords=\n')
                    argfile.write('-XMP:Subject=\n')
                    argfile.write('-EXIF:XPKeywords=\n')
                    argfile.write('-Keywords+=' + tags_string + '\n')
                    argfile.write('-IPTC:Keywords+=' + tags_string + '\n')
                    argfile.write('-XMP:Subject+=' + tags_string + '\n')
                    argfile.write('-EXIF:XPKeywords=' + tags_string + '\n')
                    argfile.write(filepath + '\n')
                    argfile.write('-execute\n')

            result = subprocess.run(
                [exiftool, '-@', argfile_path],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                errors += 1
                print(f"✗ Errore nel blocco {start + 1}-{start + len(chunk)}: {result.stderr.strip()}")
        finally:
            if argfile_path and os.path.exists(argfile_path):
                os.remove(argfile_path)

        processed += len(chunk)
        print(f"   → {processed}/{total} file elaborati...")

    if errors:
        print(f"⚠️  Elaborazione batch completata con {errors} blocco/i in errore su {total} file.")
    else:
        print(f"✅ Elaborazione batch completata per {total} file.")

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n✅ Operazione completata!")
    print(f"   Elaborati {len(file_list)} file.")
    print(f"   Tempo totale: {minutes} minuti e {seconds} secondi.")


if __name__ == "__main__":
    main()
