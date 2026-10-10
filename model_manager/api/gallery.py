"""
The Gallery tab's endpoints (#209): the Civitai images stored for the models in
the library, in an order a seed picks, one by one or in groups.

The seed is kept in schema_info, as `gallery_seed`: shared by two WebUIs that
share the database, and made the first time it is asked for. The images'
order is the database's (db/gallery_ops.py); the groups' order is worked out
here, each group scored from the seed and the group itself, as SQLite cannot
hash a name. A grouping's list is kept in memory until its images change,
so a scroll does not pay for it again: 270 to 910 ms on 119,731 images.
"""
import hashlib
import random
import threading
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

from ..db import get_models_db
from ..db.gallery_ops import GROUPINGS
from ..gallery import gallery_page_size
from ..model_dirs import held_here
from ..nsfw import stamp_levels
from .common import failed, gate
from .images import gallery_switches

SEED_KEY = "gallery_seed"
MAX_SEED = 2 ** 31 - 1
# How many images a group's tile shows.
PREVIEWS = 4
# Group lists kept: one per grouping, seed and switch is plenty.
_KEPT = 8

_lock = threading.Lock()
_groups_kept: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}


def gallery_seed(db) -> int:
    """The seed kept, or a new one, kept, if there is none or it cannot be read."""
    try:
        seed = int(db.get_info(SEED_KEY))
        if 1 <= seed <= MAX_SEED:
            return seed
    except (TypeError, ValueError):
        pass
    return keep_seed(db, random.randint(1, MAX_SEED))


def keep_seed(db, seed: int) -> int:
    """Keep `seed`, held to 1 .. MAX_SEED."""
    seed = min(max(int(seed), 1), MAX_SEED)
    db.set_info(SEED_KEY, str(seed))
    return seed


def group_rank(seed: int, group: str, key: Any) -> bytes:
    """
    A group's place, from the seed and the group itself. Placed by its
    lowest-scoring image, a group of 45,389 images came first over one of 11
    for almost every seed (#209).
    """
    return hashlib.blake2b(f"{seed}:{group}:{key}".encode("utf-8"), digest_size=8).digest()


def ordered_groups(db, seed: int, group: str, hide_nsfw: bool) -> List[Dict[str, Any]]:
    """A grouping's groups in the seed's order, kept until the images change."""
    kept = (group, seed, bool(hide_nsfw), db.gallery_signature())
    with _lock:
        if kept in _groups_kept:
            return _groups_kept[kept]
    groups = db.gallery_groups(seed, group, hide_nsfw)
    groups.sort(key=lambda g: (group_rank(seed, group, g["key"]), str(g["key"])))
    with _lock:
        if len(_groups_kept) >= _KEPT:
            _groups_kept.pop(next(iter(_groups_kept)))
        _groups_kept[kept] = groups
    return groups


def _library_entries(db, version_ids) -> Dict[int, Dict[str, Any]]:
    """
    Each version's file, as Send needs it - a file this WebUI loads first,
    else any - with what the file is: Send sets Forge up for the gallery's
    file as it does from a model's gallery.
    """
    chosen: Dict[int, str] = {}
    for row in db.library_files(version_ids=list(version_ids)):
        version_id, path = row.get("version_id"), row.get("file_path")
        if version_id is None or not path:
            continue
        if version_id not in chosen or (held_here(path) and not held_here(chosen[version_id])):
            chosen[version_id] = path
    entries = {}
    for version_id, path in chosen.items():
        entries[version_id] = db.get_version(path) or {"file_path": path}
    return entries


def image_tiles(db, keys) -> List[Dict[str, Any]]:
    """The tiles of images: each image, stamped, with its model and version for Send."""
    found = db.gallery_images(keys)
    files = _library_entries(db, {entry["version_id"] for entry in found})
    stamp_levels([entry["image"] for entry in found])
    tiles = []
    for entry in found:
        file = files.get(entry["version_id"]) or {}
        file_type = file.get("file_type")
        tiles.append({
            "kind": "image",
            "image": entry["image"],
            "model": {"id": entry["model_id"], "name": entry["model_name"] or "",
                      "civitai_type": entry["model_type"], "model_type": file_type or entry["model_type"],
                      "base_model": entry["base_model"]},
            "version": {"id": entry["version_id"], "name": entry["version_name"] or "",
                        "file_path": file.get("file_path"), "file_type": file_type,
                        "base_model": entry["base_model"]},
        })
    return tiles


def browse_page(db, seed: int, hide_nsfw: bool, page: int, group: str = "",
                in_group: str = "") -> Dict[str, Any]:
    """
    Part `page` of a level: every image, a grouping's groups, or one group's
    images. With what the banner counts, and whether there is more.
    """
    size = gallery_page_size()
    page = max(int(page or 1), 1)
    offset = (page - 1) * size
    group = group if group in GROUPINGS else ""
    groups = ordered_groups(db, seed, group, hide_nsfw) if group else []

    if group and in_group == "":
        level = groups[offset:offset + size]
        previews = image_tiles(db, [pair for g in level for pair in g["previews"]])
        by_key = {}
        for tile in previews:
            by_key.setdefault((tile["image"]["id"], tile["version"]["id"]), tile)
        tiles = [{
            "kind": "group",
            "group": {"key": g["key"], "value": g["name"], "by": group, "count": g["count"]},
            "images": [by_key[pair]["image"] for pair in g["previews"] if pair in by_key],
            "matching_count": g["count"] - (g["nsfw"] if hide_nsfw else 0),
        } for g in level]
        counts = db.gallery_counts()
        return {"seed": seed, "tiles": tiles, "more": offset + size < len(groups),
                "state": _state(counts["total"], counts["nsfw"], hide_nsfw),
                "scope": {"count": counts["total"], "groups": len(groups)}}

    key: Any = None
    if group:
        key = int(in_group) if group == "model" else in_group
        entry = next((g for g in groups if str(g["key"]) == str(in_group)), None)
        total, explicit = (entry["count"], entry["nsfw"]) if entry else (0, 0)
    else:
        counts = db.gallery_counts()
        total, explicit = counts["total"], counts["nsfw"]
    keys = db.gallery_image_keys(seed, hide_nsfw, offset, size + 1, group or None, key)
    # The level's count is what it shows, as its group's tile says it.
    shown = total - (explicit if hide_nsfw else 0)
    return {"seed": seed, "tiles": image_tiles(db, keys[:size]), "more": len(keys) > size,
            "state": _state(total, explicit, hide_nsfw), "scope": {"count": shown}}


def _state(total: int, explicit: int, hide_nsfw: bool) -> Dict[str, int]:
    """What the banner counts, in the meanings every gallery's switch keeps (gallery.switch_counts)."""
    hidden = explicit if hide_nsfw else 0
    return {"total": total, "filtered": total - hidden, "hidden_nsfw": hidden, "nsfw_count": explicit}


def register(app: FastAPI) -> None:
    """Register the Gallery tab's endpoints."""

    @app.get("/model-manager/gallery/browse")
    @gate("gallery")
    def get_gallery_page(page: int = 1, group: str = "", in_group: str = "",
                         hide_nsfw_images: Optional[bool] = None):
        """
        Part `page` of a level of the Gallery, in the seed's order, through
        the NSFW switch - which starts as the Model Manager gallery's setting
        says, as every gallery of Civitai's images does.

        Args:
            group: what the images are grouped by (db/gallery_ops.GROUPINGS), or none.
            in_group: the group opened, by its key.
        """
        try:
            db = get_models_db()
            hide_nsfw, _ = gallery_switches(hide_nsfw_images, None)
            return JSONResponse({"success": True, **browse_page(
                db, gallery_seed(db), bool(hide_nsfw), page, group, in_group)})
        except Exception as e:
            return failed(e, "Gallery page error")

    @app.post("/model-manager/gallery/seed")
    @gate("gallery")
    def post_gallery_seed(seed: Optional[int] = Form(default=None)):
        """
        Keep a seed: the one given, or, given none, a new one. Answers the
        seed kept, from 1 to 2,147,483,647.
        """
        try:
            db = get_models_db()
            kept = keep_seed(db, seed if seed is not None else random.randint(1, MAX_SEED))
            return JSONResponse({"success": True, "seed": kept})
        except Exception as e:
            return failed(e, "Gallery seed error")
