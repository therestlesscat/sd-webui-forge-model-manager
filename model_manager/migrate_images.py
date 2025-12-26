"""
Migration script to move images from .images.json files to SQLite database.

Run this script once to migrate existing image data, then .images.json files
will be deleted.

Usage:
    python migrate_images.py [--dry-run]
"""
import os
import sys
import json
import argparse
from typing import List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_manager.images_cache import get_images_cache
from model_manager.storage import read_civitai_info


def find_images_json_files(root_path: str) -> List[str]:
    """Find all .images.json files recursively from root path."""
    files = []
    if not os.path.isdir(root_path):
        return files

    for root, _, filenames in os.walk(root_path):
        for filename in filenames:
            if filename.endswith(".images.json"):
                files.append(os.path.join(root, filename))
    return files


def get_models_root() -> str:
    """Get the models root directory."""
    try:
        from modules import shared
        if hasattr(shared, 'models_path'):
            return shared.models_path
    except ImportError:
        pass

    # Fallback: infer from extension location
    # extension is in webui/extensions/sd-webui-forge-model-manager.dev/
    ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    webui_dir = os.path.dirname(os.path.dirname(ext_dir))
    return os.path.join(webui_dir, "models")


def migrate_images_file(images_json_path: str, cache, dry_run: bool = False) -> Tuple[bool, str]:
    """
    Migrate a single .images.json file to SQLite.

    Returns:
        (success, message)
    """
    # Get corresponding model file path
    # .images.json -> find .civitai.info to get version_id
    base_path = images_json_path.rsplit(".images.json", 1)[0]

    # Find the model file
    model_path = None
    for ext in [".safetensors", ".ckpt", ".pt", ".pth", ".bin"]:
        if os.path.exists(base_path + ext):
            model_path = base_path + ext
            break

    if not model_path:
        return False, "No model file found"

    # Read .civitai.info to get version_id
    civitai_data = read_civitai_info(model_path)
    if not civitai_data:
        return False, "No .civitai.info file"

    # Get version_id - check both formats
    version_id = civitai_data.get("id")  # Version response format
    if not version_id:
        # Full model response format
        versions = civitai_data.get("modelVersions", [])
        if versions:
            version_id = versions[0].get("id")

    if not version_id:
        return False, "No version_id in civitai.info"

    # Read .images.json
    try:
        with open(images_json_path, "r", encoding="utf-8") as f:
            images_data = json.load(f)
    except Exception as e:
        return False, f"Failed to read: {e}"

    # Handle both formats - list or dict with 'images' key
    if isinstance(images_data, list):
        images = images_data
    elif isinstance(images_data, dict):
        images = images_data.get("images", [])
    else:
        return False, "Invalid format"

    if not images:
        # No images, just delete the file
        if not dry_run:
            os.remove(images_json_path)
        return True, "Deleted (no images)"

    if dry_run:
        return True, f"Would migrate {len(images)} images for version {version_id}"

    # Store images in SQLite
    cache.clear_version(version_id)
    cache.store_images(version_id, page=1, images=images)

    # Store pagination state
    cache.update_pagination_state(
        version_id=version_id,
        total_count=len(images),
        total_pages=1,
        fetched_pages=1
    )

    # Delete .images.json file
    os.remove(images_json_path)

    return True, f"Migrated {len(images)} images"


def main():
    parser = argparse.ArgumentParser(description="Migrate .images.json files to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    print("=" * 60)
    print("Images Migration Script")
    print("=" * 60)

    if args.dry_run:
        print("DRY RUN - No changes will be made\n")

    # Get models root
    models_root = get_models_root()
    print(f"Scanning: {models_root}\n")

    # Find .images.json files
    images_files = find_images_json_files(models_root)
    print(f"Found {len(images_files)} .images.json files\n")

    if not images_files:
        print("Nothing to migrate!")
        return

    # Get cache instance
    cache = get_images_cache()

    # Migrate each file
    success_count = 0
    error_count = 0

    for filepath in images_files:
        filename = os.path.basename(filepath)
        success, message = migrate_images_file(filepath, cache, dry_run=args.dry_run)

        status = "OK" if success else "FAIL"
        print(f"[{status}] {filename}: {message}")

        if success:
            success_count += 1
        else:
            error_count += 1

    print()
    print("=" * 60)
    print(f"Migration complete: {success_count} succeeded, {error_count} failed")

    if not args.dry_run:
        stats = cache.get_cache_stats()
        print(f"Cache stats: {stats['total_images']} images for {stats['total_versions']} versions ({stats['db_size_mb']} MB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
