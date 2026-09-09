from pathlib import Path

def rename_items_in_cwd():
    folder_path = Path.cwd()

    # Get items (files or directories) directly in CWD that contain spaces
    # Excludes the script itself to prevent runtime issues
    items_to_rename = [
        item for item in folder_path.iterdir()
        if ' ' in item.name and item.name != Path(__file__).name
    ]

    if not items_to_rename:
        print(f"No files or folders with spaces found in: {folder_path}")
        return

    total_items = len(items_to_rename)
    
    user_choice = input(
        f"Found {total_items} item(s) (files & top-level folders) to rename in current directory.\n"
        f"Do you want to rename 'n' ({total_items}) items? (Press Enter to confirm, or any other key to cancel): "
    )

    if user_choice.strip() != "":
        print("Operation cancelled.")
        return

    renamed_count = 0
    for item_path in items_to_rename:
        new_name = item_path.name.replace(" ", "-")
        new_item_path = item_path.parent / new_name

        try:
            item_path.rename(new_item_path)
            item_type = "Folder" if new_item_path.is_dir() else "File"
            print(f"Renamed ({item_type}): '{item_path.name}' -> '{new_name}'")
            renamed_count += 1
        except Exception as e:
            print(f"Failed to rename '{item_path.name}': {e}")

    print(f"\nDone! Successfully renamed {renamed_count} item(s).")

if __name__ == "__main__":
    rename_items_in_cwd()