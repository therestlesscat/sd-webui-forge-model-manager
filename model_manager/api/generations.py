"""
Your own generations: a model's gallery of them, the second tab beside its
Civitai images; and every one of them, in the Generations tab.

A gallery shows the generations that used any file of the open model's
version - as the Civitai tab shows one gallery per version - one card per
generation, a page of cards at a time, through the same two switches. What is
recorded, and how, is model_manager/generations.py's.

An image file is served by its record's id, never by a path the page sends:
only what was recorded can be opened.
"""
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse

from ..prompt_rules import MIN_PROMPT_LENGTH
from ..db import get_models_db
from ..db.generations_ops import PROMPT_GROUPINGS, Scope, group_id, group_key, tidy
from ..forge_host import setting
from ..nsfw import PG, SFW_MAX, user_level
from ..gallery import gallery_page_size, switch_counts
from .images import gallery_switches
from .common import failed, gate
from ..console import say

# The images a card shows before "Show images".
PREVIEW_IMAGES = 4


def generations_hide_nsfw() -> bool:
    """Whether the Generations tab opens with explicit images hidden: its own setting."""
    from ..generations import GENERATIONS_HIDE_NSFW
    return bool(setting(GENERATIONS_HIDE_NSFW))


def _filtered(rows: List[Dict[str, Any]], hide_nsfw: bool,
              hide_promptless: bool) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Your generations through the switches: their stored level, their prompt's length."""
    return switch_counts(
        rows,
        [r["level"] is not None and r["level"] <= SFW_MAX for r in rows],
        [r["prompt_length"] >= MIN_PROMPT_LENGTH for r in rows],
        hide_nsfw, hide_promptless)


def _hash_list(value: Any) -> Dict[str, str]:
    """Forge's "Lora hashes" / "TI hashes" line - "name: hash, name: hash" - by name."""
    found: Dict[str, str] = {}
    for part in str(value or "").strip().strip('"').split(","):
        name, _, hash_ = part.rpartition(":")
        if name.strip() and hash_.strip():
            found[name.strip()] = hash_.strip()
    return found


def image_resources(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    An image's LoRAs and embeddings as a Civitai image lists them - its meta's
    `resources`, each with a type, name, weight and hash - so Send shows their
    chips in txt2img as it does a Civitai image's, by the same code.

    The LoRAs are the record's - what Forge loaded for the image's own
    iteration, at the weight it loaded them - each with its hash from the
    infotext's "Lora hashes"; the embeddings are the infotext's "TI hashes".
    """
    meta = row.get("meta") or {}
    loras = row.get("loras") or []
    # Its checkpoint too, by the infotext's own last line - Forge's parser
    # drops `Model` when it names the checkpoint loaded at the time - so the
    # Resources dialog a send stopped for it opens can offer it (#233).
    from ..image_text import line_params
    line = line_params(row.get("infotext"))
    checkpoint = [{"type": "Checkpoint", "name": line.get("Model") or "", "weight": None,
                   "hash": line.get("Model hash") or ""}] if (line.get("Model") or line.get("Model hash")) else []
    if isinstance(loras, str):
        try:
            loras = json.loads(loras)
        except ValueError:
            loras = []
    lora_hashes = _hash_list(meta.get("Lora hashes"))
    resources, seen = [], set()
    for lora in loras:
        name = isinstance(lora, dict) and lora.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        resources.append({"type": "lora", "name": name, "weight": lora.get("te_multiplier"),
                          "hash": lora_hashes.get(name, "")})
    for name, hash_ in lora_hashes.items():
        if name not in seen:
            resources.append({"type": "lora", "name": name, "weight": None, "hash": hash_})
    for name, hash_ in _hash_list(meta.get("TI hashes")).items():
        resources.append({"type": "embedding", "name": name, "weight": None, "hash": hash_})
    return checkpoint + resources


def file_ref(path: Optional[str], known: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    A model file as the page's menus name it: by version and model where
    Civitai knows it, so another tab is asked for those, not a path - the
    path is kept only for a file it does not know, which has nothing else.
    `in_library` is False for a file the library no longer has.
    """
    if not path:
        return None
    entry = known.get(path)
    return {"path": path, "name": os.path.splitext(os.path.basename(path))[0],
            "in_library": entry is not None,
            "version_id": (entry or {}).get("version_id"), "model_id": (entry or {}).get("model_id"),
            "model_name": (entry or {}).get("model_name")}


def _image(row: Dict[str, Any]) -> Dict[str, Any]:
    """An image as the page draws one: its generation data as a Civitai
    image's meta, its level stamped as every image the page gets is."""
    level = row.get("user_nsfw_level")
    from_prompt = level is None
    if level is None:
        level = row.get("prompt_nsfw_level")
    return {
        "id": row["id"],
        "generation_id": row["generation_id"],
        "position": row["position"],
        "iteration": row.get("iteration"),
        "seed": row.get("seed"),
        "width": row.get("width"),
        "height": row.get("height"),
        "meta": {**(row.get("meta") or {}), "resources": image_resources(row)},
        "infotext": row.get("infotext"),
        "url": f"/model-manager/generations/images/{row['id']}/file",
        "exists": bool(row.get("path")) and os.path.isfile(row["path"]),
        "mm_level": level,
        # The rating a person gave it, or None: it wins over the prompt's.
        "user_level": row.get("user_nsfw_level"),
        # What set the level, for the badge's "X · prompt": nobody rates
        # these images, so it is the prompt unless the user has.
        "mm_level_from_prompt": from_prompt and level != PG,
    }


def generation_page(db, path: str, hide_nsfw: bool, hide_promptless: bool,
                    page: int = 1) -> Dict[str, Any]:
    """
    Page `page` of a gallery's generations, as every gallery pages
    (model_manager/gallery.py): the generations filed under the gallery's
    files at places (page - 1) * size + 1 to page * size, newest first,
    before the switches - which only decide which of their images are drawn.
    A generation with none left to draw has no card, and is still counted in
    its page's note. The page is picked in SQL, and only its images read.

    Returns:
        generations: the page's cards, each with its first images;
        page: its number and size, how many generations and images it holds,
            how many images are shown, what each switch hid, and whether
            more come after it;
        state: the gallery's totals, over every page, for the banner.
    """
    size = gallery_page_size()
    page = max(1, int(page or 1))
    files = db.generation_gallery_files(path)
    on_page, total = db.generation_scope_generations(Scope(files=files), (page - 1) * size, size)
    page_rows = db.generation_scope_rows(Scope(files=files, generations=on_page)) if on_page else []
    shown, page_counts = _filtered(page_rows, hide_nsfw, hide_promptless)
    counts = _switches(db.generation_scope_counts(Scope(files=files), hide_nsfw, hide_promptless))

    by_generation: Dict[int, List[Dict[str, Any]]] = {}
    for row in shown:
        by_generation.setdefault(row["generation_id"], []).append(row)
    drawn = [g for g in on_page if g in by_generation]

    generations = db.get_generations(drawn)
    previews = [r["id"] for g in drawn for r in by_generation[g][:PREVIEW_IMAGES]]
    images = db.get_generation_images(previews)
    cards = []
    for generation_id in drawn:
        card = dict(generations.get(generation_id) or {"id": generation_id})
        card["matching_count"] = len(by_generation[generation_id])
        card.update(shared_levels(by_generation[generation_id]))
        card["images"] = [_image(images[r["id"]]) for r in by_generation[generation_id][:PREVIEW_IMAGES]
                          if r["id"] in images]
        cards.append(card)

    return {
        "generations": cards,
        "page": {
            "number": page,
            "size": size,
            "generations": len(on_page),
            "count": len(page_rows),
            "shown": page_counts["filtered"],
            "hidden_nsfw": page_counts["hidden_nsfw"],
            "hidden_promptless": page_counts["hidden_promptless"],
            "hidden_both": page_counts["hidden_both"],
            "more": total > page * size,
            "error": None,
        },
        "state": {
            "generation_count": total,
            # Every generation filed here, filtered or not: the tab's label.
            "stored_generations": db.count_generations(files),
            "hide_nsfw_images": hide_nsfw,
            "hide_promptless_images": hide_promptless,
            **counts,
        },
    }


# The counts gallery.switch_counts() gives, of a scope's counts.
_SWITCH_COUNTS = ("total", "filtered", "hidden_nsfw", "hidden_both", "hidden_promptless", "hidden",
                  "nsfw_count", "promptless_count", "promptless_total")


def _switches(counts: Dict[str, Any]) -> Dict[str, int]:
    return {k: counts[k] for k in _SWITCH_COUNTS}


def shared_levels(rows: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    """
    The level every one of these images has, if they share one - what a folded
    tile or card shows selected when rating - and the rating a person gave
    them all, if they share that; else None for either.
    """
    levels = {r.get("level") for r in rows}
    users = {r.get("user_level") for r in rows}
    return {"level": next(iter(levels)) if len(levels) == 1 else None,
            "user_level": next(iter(users)) if len(users) == 1 else None}


def _delete_files(paths: List[str]) -> Tuple[List[str], List[Dict[str, str]]]:
    """Delete these image files - the ones a record's delete handed back -
    and say which went, and which could not, with why."""
    deleted, failed = [], []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            deleted.append(path)
        except OSError as e:
            failed.append({"path": path, "error": str(e)})
    return deleted, failed


def _checkpoints_by_hash(db, generation: Dict[str, Any]) -> List[str]:
    """The library's checkpoint files whose hash is the one the generation
    names - recorded, or its infotext's `Model hash` - in the library's order."""
    from ..image_text import line_params
    hashes = [h for h in (generation.get("checkpoint_hash"),
                          line_params(generation.get("infotext")).get("Model hash")) if h]
    if not hashes:
        return []
    return [row["file_path"] for row in db.versions_named_by([], hashes)
            if row.get("file_path") and row.get("file_type") in (None, "Checkpoint")]


def remember_kept(db, paths: List[str]) -> int:
    """
    Put each file a delete handed back and left on disk on the removed list -
    asked to keep it, or it could not be deleted - so Sync images does not
    bring its row back (#233). A file deleted needs no entry.

    Returns:
        How many went on the list.
    """
    entries = []
    for path in dict.fromkeys(paths):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        entries.append((path, stat.st_size, stat.st_mtime_ns))
    if entries:
        db.remember_removed_images(entries)
    return len(entries)


def send_plan(db, generation_id: int, use_version: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    What Forge is set up with before a generation of your own is sent back to
    it: the same as it was made with, from what was recorded - its checkpoint's
    UI preset, the checkpoint, and exactly the VAE / text encoder files that
    were loaded, none for a model that loaded none. The same for every kind of
    model.

    Pasting the infotext does not do it: Forge Neo ignores the checkpoint and
    the modules an infotext names unless told otherwise ("Ignore the
    Checkpoint / VAE / Text Encoder when reading infotext", both on by
    default), and a model that loaded no modules names none to clear.

    Returns:
        plan_for()'s answer, or None for no such generation.
    """
    generation = db.get_generation(generation_id)
    if not generation:
        return None
    path = generation.get("checkpoint_path") or ""
    modules = generation.get("modules") or []
    if use_version:
        # The person chose, in the Resources dialog Send opened, to send with
        # the file of the image's version the library holds - not the file the
        # image was made with (#233): the first of them Forge lists.
        from ..forge_host import checkpoint_name
        held = next((r["file_path"] for r in db.library_files(version_ids=[int(use_version)])
                     if checkpoint_name(r["file_path"])), None)
        if held:
            plan = plan_for(db, held, modules)
            plan["instead"] = os.path.basename(held)
            plan["inputs"] = bool(generation.get("inputs"))
            return plan
    plan = plan_for(db, path, modules)
    if not plan["checkpoint"]:
        # Forge does not list the file it was made with (#233). The library's
        # file with the hash the image names - a download from the Resources
        # dialog Send opened, say - is the one, if Forge lists it. Else Send
        # stops and says why, as a Civitai image's does (api/webui.py): the
        # file is in a folder this WebUI does not load - the other WebUI's -
        # or Forge has not listed it yet, or the library lacks it.
        from ..forge_host import checkpoint_name
        from ..model_dirs import loads_here
        candidates = [p for p in dict.fromkeys(([path] if path else []) + _checkpoints_by_hash(db, generation))
                      if os.path.isfile(p)]
        listed = next((p for p in candidates if checkpoint_name(p)), None)
        if listed:
            plan = plan_for(db, listed, modules)
        elif candidates:
            found = candidates[0]
            plan["checkpoint_missing"] = os.path.basename(found)
            plan["checkpoint_problem"] = {"reason": "not_listed" if loads_here(found) else "elsewhere",
                                          "name": os.path.basename(found), "path": found}
        else:
            # Synced from a folder, its text may name a checkpoint by name alone.
            name = (None if path else db.unheld_checkpoint(generation_id)) or plan["checkpoint_missing"]
            plan["checkpoint_missing"] = name
            plan["checkpoint_problem"] = {"reason": "missing", "name": name} if name else None
    # Whether its Send sets back what the press was sent (#7); a generation
    # recorded without them has Forge's paste, corrected.
    plan["inputs"] = bool(generation.get("inputs"))
    return plan


def plan_for(db, path: str, modules: List[str]) -> Dict[str, Any]:
    """
    How to set Forge up for a checkpoint file and these VAE / text encoder
    files: a generation of your own sent back (send_plan), or a queued task
    loaded into its tab (api/scheduler.py).

    Returns:
        preset (None if unknown), checkpoint (the name Forge lists it under,
        None if it does not), checkpoint_missing (its file name, then),
        target (the module labels to hold), modules_missing (the recorded
        modules Forge does not offer), embeddings (the kind of embedding the
        checkpoint loads: forge_host.embedding_kind).
    """
    from ..file_identity import identify
    from ..forge_host import checkpoint_name, embedding_kind, installed_modules
    from ..identity_store import record_architecture

    preset = None
    model_class = None
    if path:
        # Read as any checkpoint is, once, and stored; a file the library
        # does not hold is read without storing.
        spelled = db.library_spelling([path]).get(path, path)
        try:
            record_architecture(db, spelled)
        except Exception as e:
            say(f"Could not read {os.path.basename(path)}: {e}")
        row = db.get_version(spelled) or {}
        preset, model_class = row.get("architecture"), row.get("architecture_class")
        if not preset and os.path.isfile(path):
            found = identify(path)
            preset, model_class = found.preset, found.model_class

    checkpoint = checkpoint_name(path)
    installed = installed_modules()
    recorded = [os.path.basename(p) for p in modules if p]
    return {
        "preset": preset,
        "checkpoint": checkpoint,
        "checkpoint_missing": os.path.basename(path) if path and not checkpoint else None,
        "target": [m for m in recorded if m in installed],
        "modules_missing": [m for m in recorded if m not in installed],
        "embeddings": embedding_kind(model_class, preset),
    }


# What a tile needs of its generation, besides its images.
TILE_FIELDS = ("id", "created_at", "mode", "image_count", "width", "height", "checkpoint_path")


# What the Generations tab can group images by, and what each is called; what
# each groups on is GROUP_KEYS' (db/generations_ops.py). An image is in
# exactly one group of each.
GROUPINGS = {
    "prompt_written": "Prompt, as written",
    "prompt": "Prompt, as generated",
    # The checkpoint's, as the library holds it - the Model Manager's Base Model filter's.
    "base_model": "Base model",
    "model": "Model",
    "loras": "LoRA combination",
    "size": "Size",
    "day": "Day",
}


def grouping_chain(group: str) -> List[str]:
    """
    What `group` groups by, in order: one grouping ("model"), or two
    ("model>prompt_written") - a group of the first opens onto groups of the
    second. Anything else, or more than two, is no grouping at all.
    """
    keys = [k for k in str(group or "").split(">")]
    return keys if 1 <= len(keys) <= 2 and all(k in GROUPINGS for k in keys) else []


def search_terms(text: str) -> Tuple[List[str], Optional[int]]:
    """
    What a Generations search asks for: the words an image's prompt or
    negative prompt must each hold - a "quoted phrase" as one - and, with
    task:<number>, the Queue's task whose run made it. Nothing else is a key:
    a prompt's own "(red:1.2)" is searched for as typed.
    """
    words: List[str] = []
    task = None
    for quoted, plain in re.findall(r'"([^"]*)"|(\S+)', text or ""):
        found = re.fullmatch(r"task:(\d+)", plain, re.IGNORECASE)
        if found:
            task = int(found.group(1))
        elif (quoted or plain).strip():
            words.append(quoted or plain)
    return words, task


def _scope(group: str = "", in_group: str = "", generation: Optional[int] = None,
           in_subgroup: str = "", search: str = "") -> Scope:
    """
    The images a level of the Generations tab holds - inside a group, one of
    its groups when grouped twice, a generation, or these together - that the
    search finds.
    """
    chain = grouping_chain(group)
    words, task = search_terms(search)
    return Scope(generation=generation, words=words, task=task,
                 opened=[(k, g) for k, g in zip(chain, (in_group, in_subgroup)) if g])


def _group_values(db, grouping: str, keys) -> Dict[Any, str]:
    """What each group of a grouping is called: a prompt group's tidied text,
    or the value itself."""
    if grouping in PROMPT_GROUPINGS:
        texts = db.prompt_texts(k for k in keys if k)
        return {k: tidy(texts.get(k, "")) if k else "" for k in keys}
    return {k: str(k) for k in keys}


def browse_page(db, hide_nsfw: bool, page: int = 1, group: str = "",
                in_group: str = "", generation: Optional[int] = None,
                in_subgroup: str = "", search: str = "") -> Dict[str, Any]:
    """
    Part `page` of a level of the Generations tab, newest first. The top level
    is a tile per generation - its first images and how many it has - or, with
    `group`, a tile per group of images (GROUPINGS), whatever generations they
    are of. A level inside one, `in_group` (a group's id) or `generation`, is
    what that holds: a group's generations, and a generation's images, each a
    tile - so a group opens onto its batches, and a batch onto its images.
    Grouped twice ("model>prompt_written", grouping_chain()), the top level
    is the second grouping's groups in sections of the first - each tile
    carries its `section`, the page heads each with a row - so a prompt under
    its model is one click from its batches: `in_group` the section,
    `in_subgroup` the group. `in_group` alone is a section's groups.

    The tab scrolls rather than pages, so there is no page note to count what
    the NSFW switch hid on each: images are filtered first and the parts cut
    from what is left, and no part comes back emptied. The prompt switch is
    not offered here; nothing is hidden for a prompt. The part is picked in
    SQL, and only its tiles' images read (#231).

    Returns:
        tiles: each {"kind": "group" | "generation" | "image", "group",
        "generation", "images", "matching_count"}; more: whether another part
        follows; state: the level's totals, for the banner; scope: what the
        level is, for its header - how many images, from when to when, and
        the group's value or the generation's.
    """
    size = gallery_page_size()
    page = max(1, int(page or 1))
    chain = grouping_chain(group)
    scope = _scope(group, in_group, generation, in_subgroup, search)

    # The grouping this level's groups are by, if it is a level of groups:
    # the first at the top - or, grouped twice, the second, in sections of the
    # first - and the second inside a group of the first.
    by = None
    sectioned = generation is None and len(chain) == 2 and not in_group
    if generation is None:
        if sectioned:
            by = chain[1]
        elif chain and not in_group:
            by = chain[0]
        elif len(chain) == 2 and in_group and not in_subgroup:
            by = chain[1]
    if generation is not None:
        kind, unit = "image", "image"
    elif by:
        kind, unit = "group", by
    else:
        kind, unit = "generation", "generation"
    section = chain[0] if sectioned else None

    units = db.generation_scope_units(scope, unit, section, hide_nsfw, (page - 1) * size, size + 1)
    more = len(units) > size
    units = units[:size]
    part = [((u["s"],) if section else ()) + (u["u"],) for u in units]
    previews: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {key: [] for key in part}
    for row in db.generation_scope_previews(scope, unit, section, hide_nsfw, part, PREVIEW_IMAGES):
        previews[((row["s"],) if section else ()) + (row["u"],)].append(row)
    unit_loras = db.generation_scope_unit_loras(scope, unit, section, hide_nsfw, part)
    unit_checkpoints = db.generation_scope_unit_checkpoints(scope, unit, section, hide_nsfw, part)
    preview_ids = [r["id"] for rows in previews.values() for r in rows]
    images = db.get_generation_images(preview_ids)
    image_loras = db.generation_image_loras(preview_ids)
    # The files the menus name - each checkpoint and LoRA these tiles used -
    # looked up in the library once each.
    known = db.generation_library_files(
        set(unit_checkpoints.values()) | {r["checkpoint_path"] for rows in previews.values() for r in rows}
        | {p for paths in unit_loras.values() for p in paths})
    generations = db.get_generations(list(dict.fromkeys(rows[0]["generation_id"]
                                                        for rows in previews.values() if rows)))
    values = _group_values(db, by, [u["u"] for u in units]) if by else {}
    sections = _group_values(db, section, [u["s"] for u in units]) if section else {}

    tiles = []
    for key, entry in zip(part, units):
        rows = previews.get(key) or []
        if not rows:
            continue
        first = rows[0]
        generation_row = generations.get(first["generation_id"]) or {"id": first["generation_id"]}
        tile = {
            "kind": kind,
            "generation": {k: generation_row.get(k) for k in TILE_FIELDS},
            "images": [{**_image(images[r["id"]]), "checkpoint_path": r["checkpoint_path"],
                        "checkpoint": file_ref(r["checkpoint_path"], known),
                        "loras": [file_ref(p, known) for p in image_loras.get(r["id"], [])]}
                       for r in rows if r["id"] in images],
            "matching_count": entry["n"],
            # The checkpoint its images were made with, if one: a group can span several.
            "checkpoint_path": unit_checkpoints.get(key),
            # For its ⋯ menu: the checkpoint, if its images share one, and every LoRA they used.
            "checkpoint": file_ref(unit_checkpoints.get(key), known),
            "loras": [file_ref(p, known) for p in unit_loras.get(key, [])],
            "level": entry["level"],
            "user_level": entry["user_level"],
        }
        if kind == "group":
            tile["group"] = {"id": group_id(by, entry["u"]), "value": values.get(entry["u"], ""), "by": by,
                             "latest": entry["latest"], "generations": entry["generations"]}
            if section:
                tile["section"] = {"id": group_id(section, entry["s"]), "value": sections.get(entry["s"], ""),
                                   "by": section, "count": entry["section_count"],
                                   "groups": entry["section_groups"]}
        tiles.append(tile)

    counts = db.generation_scope_counts(scope, hide_nsfw, False)
    scope_info: Dict[str, Any] = {"count": counts["filtered"], "first": counts["oldest"],
                                  "last": counts["newest"]}
    if chain:
        scope_info["grouping"] = " › ".join(GROUPINGS[k] for k in chain)
        # What each group opened is: [{"by", "name", "value"}], outermost first.
        if scope.opened and counts["filtered"]:
            scope_info["values"] = []
            for k, opened in scope.opened:
                key = group_key(k, opened)
                scope_info["values"].append({"by": k, "name": GROUPINGS[k],
                                             "value": _group_values(db, k, [key]).get(key, "")})
            scope_info["value"] = scope_info["values"][-1]["value"]
    if generation is not None:
        generation_row = db.get_generations([generation]).get(generation) or {}
        scope_info["generation"] = {k: generation_row.get(k) for k in TILE_FIELDS}

    return {
        "tiles": tiles,
        "more": more,
        "state": {
            "generation_count": counts["generation_count"],
            "stored_generations": db.count_generations(None),
            "hide_nsfw_images": hide_nsfw,
            **_switches(counts),
        },
        "scope": scope_info,
    }


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""
    _register_sync(app)
    _register(app)


def _register_sync(app: FastAPI):
    """Sync images (#233): the folders, what is new in them, and the long job."""
    from ..forge_host import store_settings
    from ..image_sync import (FOLDERS_OFF_SETTING, GROUP_SETTING, KIND, LEVEL_SETTING, ImageSync, add_folder,
                              counts, level_of, remove_folder, unticked)
    from ..image_sync import folders as image_folders
    from ..jobs import jobs
    from ..nsfw import LEVEL_TO_NAME, UNKNOWN, USER_LEVELS
    from .jobs import _cancel, _progress, _start, _yes

    # Start reads the folder list, then registers its job as running; Remove
    # checks for a running job, then deletes. Each holds this throughout, or
    # a Remove landing between Start's two steps takes off the list a folder
    # the sync is about to write - seen on 7880: 54 generations left under
    # no listed folder, which no Remove could reach again.
    folders_lock = threading.Lock()

    @app.get("/model-manager/generations/sync/folders")
    @gate("generations")
    def sync_folders():
        """
        The folders Sync images can read - Forge's result folders, read from
        its settings now, and the ones added - with whether each is ticked;
        the level an image with no text gets to begin with, the levels to
        choose from, and whether images with no text are grouped. Each
        folder says how many generations its syncs brought (`synced`), which
        Remove would take.
        """
        try:
            synced = get_models_db().synced_counts()
            return JSONResponse({
                "success": True,
                "folders": [{**f, "synced": synced.get(f["path"].lower(), 0)} for f in image_folders()],
                "level": setting(LEVEL_SETTING),
                "levels": [LEVEL_TO_NAME[level] for level in (*USER_LEVELS, UNKNOWN)],
                "group": bool(setting(GROUP_SETTING)),
            })
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/generations/sync/estimate")
    @gate("generations")
    def sync_estimate():
        """How many new images each folder holds, and how many synced ones a
        Force sync would read again, by path: a walk, nothing read."""
        try:
            new, again = counts(get_models_db(), image_folders())
            return JSONResponse({"success": True, "counts": new, "again": again})
        except Exception as e:
            return failed(e)

    @app.post("/model-manager/generations/sync")
    @gate("generations")
    def start_sync(folders: str = Form(default="[]"), level: str = Form(default=""),
                   group: str = Form(default="true"), force: str = Form(default="false")):
        """
        Start Sync images over the ticked folders, by path - JSON. Forge's
        folders left unticked are remembered, as is the level the dialog had
        and whether it grouped images with no text: the next dialog starts
        from them. With `force`, the folders' synced images are read again
        too (#246); the box itself is not remembered.
        """
        try:
            ticked = {str(p).lower() for p in json.loads(folders or "[]")}
        except ValueError:
            return JSONResponse({"success": False, "error": "Folders not understood"}, status_code=400)
        grouped = _yes(group)
        with folders_lock:
            listed = image_folders()
            entries = [f for f in listed if f["path"].lower() in ticked]
            try:
                store_settings({FOLDERS_OFF_SETTING: "\n".join(unticked(listed, ticked)),
                                LEVEL_SETTING: level or setting(LEVEL_SETTING),
                                GROUP_SETTING: grouped})
            except Exception as e:
                say(f"Sync images: could not keep the dialog's choices: {e}")
            if not entries:
                return JSONResponse({"success": False, "error": "No folder ticked"}, status_code=400)
            return _start(KIND,
                          lambda: ImageSync(entries, level_of(level), grouped, _yes(force)),
                          lambda sync: sync.run(), "Sync images started")

    @app.post("/model-manager/generations/sync/folders/add")
    @gate("generations")
    def add_sync_folder(path: str = Form(default="")):
        """Add a folder for Sync images to read, kept in this WebUI's settings."""
        try:
            added, why = add_folder(path)
            if why:
                return JSONResponse({"success": False, "error": why}, status_code=400)
            return JSONResponse({"success": True, "path": added})
        except Exception as e:
            return failed(e)

    @app.post("/model-manager/generations/sync/folders/remove")
    @gate("generations")
    def remove_sync_folder(path: str = Form(default="")):
        """
        Take an added folder off the list, and remove the generations its
        syncs brought - never a file. Refused while Sync images runs: it
        could be writing that folder's generations.
        """
        try:
            with folders_lock:
                if jobs.running(KIND):
                    return JSONResponse({"success": False, "error": "Sync images is running: remove the folder "
                                         "once it has finished."}, status_code=409)
                removed, why = remove_folder(get_models_db(), path)
            if why:
                return JSONResponse({"success": False, "error": why}, status_code=400)
            say(f"Sync images: removed a folder, and the {removed} generation(s) it brought")
            return JSONResponse({"success": True, "removed": removed})
        except Exception as e:
            return failed(e)

    @app.get("/model-manager/generations/sync/progress")
    @gate("generations")
    def sync_progress():
        """How far Sync images has got; null before one has run."""
        return _progress(KIND)

    @app.post("/model-manager/generations/sync/cancel")
    @gate("generations")
    def cancel_sync():
        """Stop Sync images: what it has written stays."""
        return _cancel(KIND)


def _register(app: FastAPI):
    """Your generations' galleries, the Generations tab, and what changes them."""

    @app.get("/model-manager/generations/browse")
    @gate("generations")
    def get_browse_page(page: int = 1, hide_nsfw_images: Optional[bool] = None,
                              group: str = "", in_group: str = "",
                              generation: Optional[int] = None, in_subgroup: str = "",
                              search: str = ""):
        """
        Part `page` of a level of the Generations tab, through the NSFW switch
        - the tab's own setting decides it when not sent. See browse_page().

        Args:
            group: what images are grouped by (GROUPINGS), or two of them
                joined by ">" (grouping_chain()), or none.
            in_group: the group opened, by its id.
            in_subgroup: grouped twice, the group opened inside that one.
            generation: the generation opened.
            search: what the images must match (search_terms()).
        """
        try:
            hide_nsfw = generations_hide_nsfw() if hide_nsfw_images is None else hide_nsfw_images
            return JSONResponse({"success": True, **browse_page(
                get_models_db(), hide_nsfw, page, group, in_group, generation, in_subgroup, search)})
        except Exception as e:
            return failed(e, "Generations page error")

    @app.get("/model-manager/generations/page")
    @gate("generations")
    def get_generation_page(path: str, page: int = 1,
                                  hide_nsfw_images: Optional[bool] = None,
                                  hide_promptless_images: Optional[bool] = None):
        """
        Page `page` of the open model's generations, through the gallery's
        two switches - the settings decide either one not sent. See
        generation_page().

        Args:
            path: The open model's file; its version's files make the gallery.
            page: Which page, from 1.
        """
        try:
            hide_nsfw, hide_promptless = gallery_switches(hide_nsfw_images,
                                                          hide_promptless_images)
            return JSONResponse({"success": True, **generation_page(
                get_models_db(), path, hide_nsfw, hide_promptless, page)})
        except Exception as e:
            return failed(e, "Generation page error")

    @app.get("/model-manager/generations/{generation_id}/images")
    @gate("generations")
    def get_generation_all_images(generation_id: int, path: str = "",
                                        hide_nsfw_images: Optional[bool] = None,
                                        hide_promptless_images: Optional[bool] = None):
        """
        Every image of one generation a gallery shows, for "Show images" - or,
        with no path, as the Generations tab shows it, for expanding its tile.
        """
        try:
            db = get_models_db()
            hide_nsfw, hide_promptless = gallery_switches(hide_nsfw_images,
                                                          hide_promptless_images)
            files = db.generation_gallery_files(path) if path else None
            rows = db.generation_scope_rows(Scope(files=files, generation=generation_id))
            shown, _ = _filtered(rows, hide_nsfw, hide_promptless)
            images = db.get_generation_images([r["id"] for r in shown])
            return JSONResponse({"success": True,
                                 "images": [_image(images[r["id"]]) for r in shown
                                            if r["id"] in images]})
        except Exception as e:
            say(f"Generation images error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/{generation_id}/send-plan")
    @gate("generations")
    def get_send_plan(generation_id: int, use_version: Optional[int] = None):
        """
        How to set Forge up before sending a generation back: see send_plan().
        `use_version`: send with the library's file of this version instead of
        the image's own (#233). A plain `def`: it may read the checkpoint's header.
        """
        try:
            plan = send_plan(get_models_db(), generation_id, use_version)
            if plan is None:
                return JSONResponse({"success": False, "error": "No such generation"}, status_code=404)
            return JSONResponse({"success": True, **plan})
        except Exception as e:
            say(f"Send plan error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/images/{image_id}/file")
    @gate("generations")
    def get_generation_image_file(image_id: int):
        """A generated image, by its record: only what was recorded is served."""
        path = get_models_db().get_generation_image_path(image_id)
        if not path or not os.path.isfile(path):
            return JSONResponse({"success": False, "error": "Image not found"}, status_code=404)
        return FileResponse(path)

    @app.post("/model-manager/generations/images/{image_id}/delete")
    @gate("generations")
    def delete_generation_image(image_id: int, delete_files: bool = Form(default=False)):
        """
        Remove one generated image's record - its generation's too, when it
        was the last - and with delete_files its file, if no other record
        names it. Only the file it was saved to is touched.

        Returns:
            deleted_files, failed (as delete_generation), and
            generation_deleted: the generation's id when it went with it.
        """
        try:
            db = get_models_db()
            paths, gone = db.delete_generation_image(image_id)
            deleted, failed = _delete_files(paths) if delete_files else ([], [])
            remember_kept(db, paths)
            say(f"Deleted generated image {image_id}"
                  + (" and its file" if deleted else ""))
            return JSONResponse({"success": True, "deleted_files": len(deleted), "failed": failed,
                                 "generation_deleted": gone})
        except Exception as e:
            say(f"Delete generated image error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/rate")
    @gate("generations")
    def rate_generated_images(level: str = Form(default=""), image_id: Optional[int] = Form(default=None),
                              group: str = Form(default=""), in_group: str = Form(default=""),
                              in_subgroup: str = Form(default=""),
                              generation: Optional[int] = Form(default=None), path: str = Form(default=""),
                              hide_nsfw_images: bool = Form(default=True),
                              hide_promptless_images: bool = Form(default=False),
                              search: str = Form(default="")):
        """
        Rate your own images' NSFW level - `level` one of nsfw.USER_LEVELS, or
        empty to clear the rating, back to what the prompt gives. Which images:

        - `image_id`: that one;
        - `path` and `generation`: a model's "Your generations" card - its
          images that gallery shows, through both its switches;
        - `generation`: a batch of the Generations tab - within the group
          `in_group` (and `in_subgroup`), if opened from one - its images the tab shows, through
          its search and the NSFW switch.

        Only what the page showed is rated: an image a switch hid, nobody saw.
        A group is not rated whole: its images are of any number of prompts
        and settings, and one click would misrate many.

        Returns:
            rated: how many; and for one image, image: it as the page draws
            one, and visible: whether the switches still let it through.
        """
        try:
            db = get_models_db()
            try:
                chosen = user_level(level)
            except ValueError as e:
                return JSONResponse({"success": False, "error": str(e)}, status_code=400)
            if image_id is not None:
                ids = [image_id]
            elif path and generation is not None:
                rows = db.generation_scope_rows(Scope(files=db.generation_gallery_files(path),
                                                      generation=generation))
                ids = [r["id"] for r in _filtered(rows, hide_nsfw_images, hide_promptless_images)[0]]
            elif generation is not None:
                rows = db.generation_scope_rows(_scope(group, in_group, generation, in_subgroup, search))
                ids = [r["id"] for r in _filtered(rows, hide_nsfw_images, False)[0]]
            else:
                return JSONResponse({"success": False, "error": "Nothing to rate"}, status_code=400)
            rated = db.set_generation_image_levels(ids, chosen)
            answer = {"success": True, "rated": rated}
            if image_id is not None:
                row = db.get_generation_images([image_id]).get(image_id)
                if row:
                    answer["image"] = _image(row)
                    level_now = answer["image"]["mm_level"]
                    answer["visible"] = not hide_nsfw_images or (level_now is not None and level_now <= SFW_MAX)
            return JSONResponse(answer)
        except Exception as e:
            say(f"Rate images error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/delete-many")
    @gate("generations")
    def delete_many(generation_ids: str = Form(default=""), image_ids: str = Form(default=""),
                    delete_files: bool = Form(default=False)):
        """
        Select's one Delete: these generations whole - every image, as a
        batch's own Delete - and these images, with delete_files their files.
        Each as the single deletes do it: a file only if no other record names
        it. The images first, as one may be of a generation also chosen.

        Returns:
            images: how many image records went; deleted_files, failed (as
            delete_generation); and missing: ids already gone.
        """
        def ids(text):
            return list(dict.fromkeys(int(v) for v in (text or "").split(",") if v.strip().isdigit()))

        try:
            db = get_models_db()
            paths, missing, images = [], [], 0
            for image_id in ids(image_ids):
                try:
                    found, _ = db.delete_generation_image(image_id)
                    paths += found
                    images += 1
                except Exception as e:
                    missing.append({"image": image_id, "error": str(e)})
            for generation_id in ids(generation_ids):
                try:
                    count = db.count_generation_images(generation_id)
                    paths += db.delete_generation(generation_id)
                    images += count
                except Exception as e:
                    missing.append({"generation": generation_id, "error": str(e)})
            deleted, failed = _delete_files(list(dict.fromkeys(paths))) if delete_files else ([], [])
            remember_kept(db, paths)
            say(f"Deleted {images} generated image record(s)"
                  + (f" and {len(deleted)} file(s)" if delete_files else ""))
            return JSONResponse({"success": True, "images": images, "deleted_files": len(deleted),
                                 "failed": failed, "missing": missing})
        except Exception as e:
            say(f"Delete generations error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/{generation_id}/delete")
    @gate("generations")
    def delete_generation(generation_id: int, delete_files: bool = Form(default=False)):
        """
        Remove a generation's records, and with delete_files its image files.

        Only the files its images were saved to are touched - nothing a path
        from the page names - and of those, only ones no other record names.

        Returns:
            deleted_files, and failed: the files that could not be removed,
            with why.
        """
        try:
            db = get_models_db()
            paths = db.delete_generation(generation_id)
            deleted, failed = _delete_files(paths) if delete_files else ([], [])
            remember_kept(db, paths)
            say(f"Deleted generation {generation_id}"
                  + (f" and {len(deleted)} of its image files" if delete_files else ""))
            return JSONResponse({"success": True, "deleted_files": len(deleted),
                                 "failed": failed})
        except Exception as e:
            say(f"Delete generation error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)
