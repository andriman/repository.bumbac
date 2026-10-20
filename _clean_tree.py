#!/usr/bin/env python3
"""
_clean_tree.py - Clean cached and helper files from every addon under repo/.
"""

import os
import shutil
import argparse
import fnmatch
import time

DEFAULT_FOLDERS = [
    '__pycache__',
    '.idea',
    '.pytest_cache',
    '.cursor',
    '.git',
    '.github',
    'venv',
    '.venv',
]
DEFAULT_FILES = [
    '.gitignore',
    'JetBrains.gitignore',
    '.DS_Store',
    'thumbs.db',
    'Thumbs.db',
    'desktop.ini',
    'debug.log',
]
DEFAULT_PATTERNS = [
    'hs_err*.log',
    '*.pyc',
    '*.pyo',
]


def parse_arguments():
    parser = argparse.ArgumentParser(description="Clean addon directory tree under repo/")
    parser.add_argument('--folders', nargs='*', default=DEFAULT_FOLDERS,
                        help='Folders to delete')
    parser.add_argument('--files', nargs='*', default=DEFAULT_FILES,
                        help='Exact file names to delete')
    parser.add_argument('--patterns', nargs='*', default=DEFAULT_PATTERNS,
                        help='Filename globs to delete (for example hs_err*.log)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview only')
    parser.add_argument('--force', action='store_true',
                        help='Try harder to delete locked files')
    return parser.parse_args()


def remove_readonly(func, path, excinfo):
    """Error handler for shutil.rmtree to remove read-only files"""
    try:
        os.chmod(path, 0o777)
        func(path)
    except Exception:
        pass  # Ignore if it still fails


def _matches_pattern(filename, patterns):
    return any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)


def find_items_to_delete(root_dir, target_folders, target_files, target_patterns):
    to_delete = {'folders': [], 'files': []}

    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        for dirname in dirnames:
            if dirname in target_folders:
                rel_path = os.path.relpath(os.path.join(dirpath, dirname), root_dir)
                to_delete['folders'].append(rel_path)

        for filename in filenames:
            if filename in target_files or _matches_pattern(filename, target_patterns):
                rel_path = os.path.relpath(os.path.join(dirpath, filename), root_dir)
                to_delete['files'].append(rel_path)

    return to_delete


def display_deletions(to_delete):
    print("\n=== Items to be deleted ===")
    if not to_delete['folders'] and not to_delete['files']:
        print("No matching items found.")
        return False

    if to_delete['folders']:
        print(f"\nFolders ({len(to_delete['folders'])}):")
        for item in sorted(to_delete['folders']):
            print(f"  - {item}")

    if to_delete['files']:
        print(f"\nFiles ({len(to_delete['files'])}):")
        for item in sorted(to_delete['files']):
            print(f"  - {item}")

    return True


def delete_with_retry(path, is_folder=False, max_retries=3):
    for attempt in range(max_retries):
        try:
            if is_folder:
                shutil.rmtree(path, onerror=remove_readonly)
            else:
                os.remove(path)
            print(f"✓ Deleted: {path}")
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                print(f"⚠ Access denied: {path} → Retrying ({attempt+1}/{max_retries})...")
                time.sleep(0.5)
            else:
                print(f"✗ Failed (Access Denied): {path}")
        except FileNotFoundError:
            print(f"✓ Already gone: {path}")
            return True
        except Exception as e:
            print(f"✗ Error deleting {path}: {e}")
            break
    return False


def main():
    args = parse_arguments()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.join(script_dir, 'repo')

    if not os.path.isdir(root_dir):
        print(f"Addon folder not found: {root_dir}")
        return

    print(f"Cleanup started in: {root_dir}\n")

    to_delete = find_items_to_delete(root_dir, args.folders, args.files, args.patterns)

    if not display_deletions(to_delete):
        print("Nothing to clean.")
        return

    if args.dry_run:
        print("\n=== DRY RUN MODE - Nothing was deleted ===")
        return

    print("\nStarting deletion...")
    confirm = input("Proceed with deletion? (y/n): ").strip().lower()

    if confirm not in ['y', 'yes']:
        print("Operation cancelled.")
        return

    for rel in to_delete['files']:
        delete_with_retry(os.path.join(root_dir, rel), is_folder=False)

    for rel in to_delete['folders']:
        delete_with_retry(os.path.join(root_dir, rel), is_folder=True)

    print("\n=== Cleanup finished ===")


if __name__ == "__main__":
    main()
