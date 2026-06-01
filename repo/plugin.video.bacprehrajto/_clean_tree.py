#!/usr/bin/env python3
"""
_clean_tree.py - Enhanced recursive cleaner
Handles permission errors better (especially __pycache__)
"""

import os
import shutil
import argparse
import time
import sys

def parse_arguments():
    parser = argparse.ArgumentParser(description="Clean directory tree")
    parser.add_argument('--folders', nargs='*', default=['__pycache__', '.idea'],
                        help='Folders to delete (default: __pycache__ .idea)')
    parser.add_argument('--files', nargs='*', default=[],
                        help='Files to delete')
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

def find_items_to_delete(root_dir, target_folders, target_files):
    to_delete = {'folders': [], 'files': []}
    
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        for dirname in dirnames:
            if dirname in target_folders:
                rel_path = os.path.relpath(os.path.join(dirpath, dirname), root_dir)
                to_delete['folders'].append(rel_path)
        
        for filename in filenames:
            if filename in target_files:
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
    root_dir = os.getcwd()
    
    print(f"Cleanup started in: {root_dir}\n")

    to_delete = find_items_to_delete(root_dir, args.folders, args.files)
    
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

    # Delete files first
    for f in to_delete['files']:
        delete_with_retry(f, is_folder=False)

    # Delete folders
    for d in to_delete['folders']:
        delete_with_retry(d, is_folder=True)

    print("\n=== Cleanup finished ===")

if __name__ == "__main__":
    main()