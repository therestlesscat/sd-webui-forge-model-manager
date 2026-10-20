"""
The Civitai Images tab's endpoints (#209, #283): the Civitai images stored for the
models in the library, in an order a seed picks, one by one or in groups, one
or two deep, and searched by their prompts.

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
from ..db.gallery_ops import GROUPINGS, NUMBER_KEYS, Scope
from ..db.images_ops import resource_rows
from ..gallery import gallery_page_size
from ..model_dirs import held_here
from ..nsfw import stamp_levels
from ..send import stamp_readings
from . import levels
from .common import failed, gate
from .images import gallery_switches

SEED_KEY = "gallery_seed"
MAX_SEED = 2 ** 31 - 1
# How many images a group's tile shows.
PREVIEWS = 4
# Group lists kept: one per grouping, seed and switch is plenty.
_KEPT = 8
# What an image's ⋯ menu offers of its resources, as the Generations tab's (#298).
MENU_ROLES = ("checkpoint", "lora")
# Version ids asked for at a time: the older SQLite takes 999 values a statement.
_CHUNK = 500

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


def ordered_groups(db, seed: int, group: str, scope: Scope, level) -> List[Dict[str, Any]]:
    """A grouping's groups within a level (read by `level`), in the seed's order, kept until the images change."""
    kept = (group, seed, bool(scope.hide_nsfw), tuple(scope.words), tuple(scope.opened), db.gallery_signature())
    with _lock:
        if kept in _groups_kept:
            return _groups_kept[kept]
    groups = level.groups(group)
    groups.sort(key=lambda g: (group_rank(seed, group, g["key"]), str(g["key"])))
    with _lock:
        if len(_groups_kept) >= _KEPT:
            _groups_kept.pop(next(iter(_groups_kept)))
        _groups_kept[kept] = groups
    return groups


def _held_files(db, version_ids) -> Dict[int, str]:
    """
    Each version's file, as Send takes one - a file this WebUI loads first,
    else any - for the versions the library holds. Asked 500 ids at a time:
    the older SQLite takes 999 values a statement, and one image can name
    hundreds of LoRAs (#298).
    """
    wanted = sorted({version_id for version_id in version_ids if version_id is not None})
    chosen: Dict[int, str] = {}
    for start in range(0, len(wanted), _CHUNK):
        for row in db.library_files(version_ids=wanted[start:start + _CHUNK]):
            version_id, path = row.get("version_id"), row.get("file_path")
            if version_id is None or not path:
                continue
            if version_id not in chosen or (held_here(path) and not held_here(chosen[version_id])):
                chosen[version_id] = path
    return chosen


def _library_entries(db, version_ids) -> Dict[int, Dict[str, Any]]:
    """
    Each version's file, as Send needs it, with what the file is: Send sets
    Forge up for the gallery's file as it does from a model's gallery.
    """
    entries = {}
    for version_id, path in _held_files(db, version_ids).items():
        entries[version_id] = db.get_version(path) or {"file_path": path}
    return entries


def _menu_resources(image: Dict[str, Any], own: Optional[int]) -> List[tuple]:
    """
    What an image's ⋯ menu offers (#298): each checkpoint and LoRA its record
    names, in the record's order, by the rule that fills image_resources -
    each version once, and not the version whose gallery the image is of,
    which the tile's Model button opens already.
    """
    seen = set()
    rows = []
    for row in resource_rows(image):
        version_id = row[4]
        if row[1] not in MENU_ROLES or version_id is None or version_id == own or version_id in seen:
            continue
        seen.add(version_id)
        rows.append(row)
    return rows


def image_menu(db, image_id: int, version_id: int) -> Optional[List[Dict[str, Any]]]:
    """
    An image's ⋯ menu items, read when ⋯ is pressed (#298): each resource
    with the file the library holds of it - None when it holds none. None
    for an image no longer stored under that version.
    """
    found = db.gallery_images([(image_id, version_id)])
    if not found:
        return None
    resources = _menu_resources(found[0]["image"], version_id)
    files = _held_files(db, [row[4] for row in resources])
    return [{"role": role, "type": kind, "model_id": model_id, "version_id": version,
             "name": name or "", "version_name": version_name or "", "file_path": files.get(version)}
            for _, role, kind, model_id, version, _, name, version_name in resources]


def image_tiles(db, keys) -> List[Dict[str, Any]]:
    """
    The tiles of images: each image, stamped, with its model and version for
    Send, and whether it has a ⋯ menu - its items are asked for when pressed.
    """
    found = db.gallery_images(keys)
    files = _library_entries(db, {entry["version_id"] for entry in found})
    stamp_readings(stamp_levels([entry["image"] for entry in found]))
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
            "menu": bool(_menu_resources(entry["image"], entry["version_id"])),
        })
    return tiles


def group_id(key: Any) -> str:
    """
    A group as a request names it: its key after a "v", so a group whose key
    is empty - no LoRAs, no base model - is a group still, where an empty
    in_group means none is opened. As the Generations tab names its groups.
    """
    return f"v{'' if key is None else key}"


def group_key(grouping: str, text: str) -> Any:
    """The key a group id names (group_id): a number for a model or a prompt; None for no group."""
    if not str(text).startswith("v"):
        return None
    value = str(text)[1:]
    if grouping in NUMBER_KEYS:
        try:
            return int(value)
        except ValueError:
            return None
    return value


def _lora_name(key: str, images: List[Dict[str, Any]]) -> str:
    """A LoRA group's name: its LoRAs as one of its images lists them, by name and version."""
    wanted = {part for part in str(key or "").split(",") if part}
    for image in images:
        meta = image.get("meta") if isinstance(image.get("meta"), dict) else {}
        names = {}
        for entry in meta.get("civitaiResources") or []:
            if isinstance(entry, dict) and str(entry.get("modelVersionId")) in wanted:
                name = " ".join(str(x) for x in (entry.get("name"), entry.get("modelVersionName")) if x)
                names[str(entry.get("modelVersionId"))] = name or str(entry.get("modelVersionId"))
        if len(names) == len(wanted):
            return ", ".join(sorted(names.values(), key=str.lower))
    return ", ".join(sorted(wanted))


def browse_page(db, seed: int, hide_nsfw: bool, page: int, group: str = "",
                in_group: str = "", in_subgroup: str = "", search: str = "") -> Dict[str, Any]:
    """
    Part `page` of a level: every image, a grouping's groups, or one group's
    images - one or two groupings deep, and only what the search finds. With
    what the banner counts, and whether there is more.
    """
    size = gallery_page_size()
    page = max(int(page or 1), 1)
    offset = (page - 1) * size
    chain = levels.grouping_chain(group, GROUPINGS)
    words, _ = levels.search_terms(search, tasks=False)
    opened = []
    for grouping, text in zip(chain, (in_group, in_subgroup)):
        if text == "":
            break
        opened.append((grouping, group_key(grouping, text)))
    scope = Scope(bool(hide_nsfw), words, opened)
    grouping = chain[len(opened)] if len(opened) < len(chain) else None
    # The level read once, its counts and its page or groups from it (#283).
    with db.gallery_level(seed, scope) as read:
        counts = read.counts()
        if grouping:
            groups = ordered_groups(db, seed, grouping, scope, read)
        else:
            keys = read.image_keys(offset, size + 1)

    if grouping:
        level = groups[offset:offset + size]
        previews = image_tiles(db, [pair for g in level for pair in g["previews"]])
        by_key = {}
        for tile in previews:
            by_key.setdefault((tile["image"]["id"], tile["version"]["id"]), tile)
        names = db.gallery_prompt_names([g["key"] for g in level]) if grouping == "prompt" else {}
        tiles = []
        for g in level:
            images = [by_key[pair]["image"] for pair in g["previews"] if pair in by_key]
            name = (names.get(g["key"], "") if grouping == "prompt"
                    else _lora_name(g["key"], images) if grouping == "loras" else g["name"])
            tiles.append({
                "kind": "group",
                "group": {"key": group_id(g["key"]), "value": name, "by": grouping, "count": g["count"]},
                "images": images,
                "matching_count": g["count"] - (g["nsfw"] if hide_nsfw else 0),
            })
        return {"seed": seed, "tiles": tiles, "more": offset + size < len(groups),
                "state": _state(counts["total"], counts["nsfw"], hide_nsfw),
                "scope": {"count": counts["total"], "groups": len(groups)}}

    # The level's count is what it shows, as its group's tile says it.
    shown = counts["total"] - (counts["nsfw"] if hide_nsfw else 0)
    return {"seed": seed, "tiles": image_tiles(db, keys[:size]), "more": len(keys) > size,
            "state": _state(counts["total"], counts["nsfw"], hide_nsfw), "scope": {"count": shown}}


def _state(total: int, explicit: int, hide_nsfw: bool) -> Dict[str, int]:
    """What the banner counts, in the meanings every gallery's switch keeps (gallery.switch_counts)."""
    hidden = explicit if hide_nsfw else 0
    return {"total": total, "filtered": total - hidden, "hidden_nsfw": hidden, "nsfw_count": explicit}


def register(app: FastAPI) -> None:
    """Register the Civitai Images tab's endpoints."""

    @app.get("/model-manager/gallery/browse")
    @gate("gallery")
    def get_gallery_page(page: int = 1, group: str = "", in_group: str = "", in_subgroup: str = "",
                         search: str = "", hide_nsfw_images: Optional[bool] = None):
        """
        Part `page` of a level of the Civitai Images tab, in the seed's order, through
        the NSFW switch - which starts as the Model Manager gallery's setting
        says, as every gallery of Civitai's images does.

        Args:
            group: what the images are grouped by (db/gallery_ops.GROUPINGS), one
                grouping or two, as "model>day"; or none.
            in_group: the group opened, by its id (group_id); in_subgroup, the
                group opened inside it, when grouped two deep.
            search: the words an image's prompt or negative prompt must hold.
        """
        try:
            db = get_models_db()
            hide_nsfw, _ = gallery_switches(hide_nsfw_images, None)
            return JSONResponse({"success": True, **browse_page(
                db, gallery_seed(db), bool(hide_nsfw), page, group, in_group, in_subgroup, search)})
        except Exception as e:
            return failed(e, "Gallery page error")

    @app.get("/model-manager/gallery/menu")
    @gate("gallery")
    def get_gallery_menu(image_id: int, version_id: int):
        """
        An image's ⋯ menu (#298): its checkpoints and LoRAs, each with the
        file the library holds of it, if any - asked when ⋯ is pressed, so
        what the library holds is as of the press.
        """
        try:
            items = image_menu(get_models_db(), image_id, version_id)
            if items is None:
                return JSONResponse({"success": False, "error": "This image is no longer stored"})
            return JSONResponse({"success": True, "items": items})
        except Exception as e:
            return failed(e, "Gallery menu error")

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
