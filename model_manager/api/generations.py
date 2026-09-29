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
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse

from ..civitai.prompt_filter import MIN_PROMPT_LENGTH
from ..db import get_models_db
from ..nsfw import PG, SFW_MAX, user_level
from ..gallery import gallery_page_size
from .images import gallery_switches

# The images a card shows before "Show images".
PREVIEW_IMAGES = 4


def _filtered(rows: List[Dict[str, Any]], hide_nsfw: bool,
              hide_promptless: bool) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    The images the switches let through, and the counts the banner states -
    meaning what ImagesOps.get_image_counts() means by each, so the banner
    reads the same in both tabs.
    """
    safe = [r["level"] is not None and r["level"] <= SFW_MAX for r in rows]
    readable = [r["prompt_length"] >= MIN_PROMPT_LENGTH for r in rows]
    nsfw_kept = [i for i in range(len(rows)) if safe[i] or not hide_nsfw]
    shown = [i for i in nsfw_kept if readable[i] or not hide_promptless]
    return [rows[i] for i in shown], {
        "total": len(rows),
        "filtered": len(shown),
        "hidden_nsfw": len(rows) - len(nsfw_kept),
        "hidden_promptless": len(nsfw_kept) - len(shown),
        "hidden": len(rows) - len(shown),
        "nsfw_count": sum(1 for i in range(len(rows))
                          if not safe[i] and (readable[i] or not hide_promptless)),
        "promptless_count": sum(1 for i in nsfw_kept if not readable[i]),
    }


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
        "meta": row.get("meta") or {},
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
    its page's note.

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
    rows = db.generation_gallery_images(files)
    order = list(dict.fromkeys(r["generation_id"] for r in rows))
    on_page = set(order[(page - 1) * size:page * size])
    page_rows = [r for r in rows if r["generation_id"] in on_page]
    shown, page_counts = _filtered(page_rows, hide_nsfw, hide_promptless)
    _, counts = _filtered(rows, hide_nsfw, hide_promptless)

    by_generation: Dict[int, List[Dict[str, Any]]] = {}
    for row in shown:
        by_generation.setdefault(row["generation_id"], []).append(row)
    drawn = [g for g in order if g in by_generation]

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
            "more": len(order) > page * size,
            "error": None,
        },
        "state": {
            "generation_count": len(order),
            # Every generation filed here, filtered or not: the tab's label.
            "stored_generations": db.count_generations(files),
            "hide_nsfw_images": hide_nsfw,
            "hide_promptless_images": hide_promptless,
            **counts,
        },
    }


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


def forge_checkpoint_name(path: str) -> Optional[str]:
    """
    The name Forge lists a checkpoint file under, for its selectCheckpoint(),
    or None if Forge does not list it - it is gone, or outside every folder
    Forge looks in. Found by the file, not guessed from its folders.
    """
    if not path:
        return None
    try:
        from modules import sd_models
        wanted = os.path.normcase(os.path.abspath(path))
        for info in sd_models.checkpoints_list.values():
            if os.path.normcase(os.path.abspath(info.filename)) == wanted:
                return info.title
    except Exception as e:
        print(f"[ModelManager] Could not ask Forge for its checkpoints: {e}")
    return None


def send_plan(db, generation_id: int) -> Optional[Dict[str, Any]]:
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
        preset (None if unknown), checkpoint (the name Forge lists it under,
        None if it does not), checkpoint_missing (its file name, then),
        target (the module labels to hold), modules_missing (the recorded
        modules Forge does not offer) - or None for no such generation.
    """
    from ..architecture import record_architecture
    from ..file_identity import identify
    from ..forge_modules import installed_modules

    generation = db.get_generation(generation_id)
    if not generation:
        return None
    path = generation.get("checkpoint_path") or ""

    preset = None
    if path:
        # Read as any checkpoint is, once, and stored; a file the library
        # does not hold is read without storing.
        spelled = db.library_spelling([path]).get(path, path)
        try:
            record_architecture(db, spelled)
        except Exception as e:
            print(f"[ModelManager] Could not read {os.path.basename(path)}: {e}")
        preset = (db.get_version(spelled) or {}).get("architecture")
        if not preset and os.path.isfile(path):
            preset = identify(path).preset

    checkpoint = forge_checkpoint_name(path)
    installed = installed_modules()
    recorded = [os.path.basename(p) for p in generation.get("modules") or [] if p]
    return {
        "preset": preset,
        "checkpoint": checkpoint,
        "checkpoint_missing": os.path.basename(path) if path and not checkpoint else None,
        "target": [m for m in recorded if m in installed],
        "modules_missing": [m for m in recorded if m not in installed],
    }


# What a tile needs of its generation, besides its images.
TILE_FIELDS = ("id", "created_at", "mode", "image_count", "width", "height", "checkpoint_path")


def _one_line(text: Any) -> str:
    """A prompt as a group's key: its spacing tidied, nothing else changed."""
    return " ".join(str(text or "").split())


def _lora_names(loras: Any) -> List[str]:
    if isinstance(loras, str):
        try:
            loras = json.loads(loras)
        except ValueError:
            return []
    return sorted({str(l.get("name")) for l in loras or [] if isinstance(l, dict) and l.get("name")})


# What the Generations tab can group images by: name -> (what it is called,
# an image row's value). An image is in exactly one group of each.
GROUPINGS = {
    "prompt_written": ("Prompt, as written", lambda r: _one_line(r.get("typed_prompt"))),
    "prompt": ("Prompt, as generated", lambda r: _one_line(r.get("image_prompt"))),
    "model": ("Model", lambda r: os.path.splitext(os.path.basename(r.get("checkpoint_path") or ""))[0]),
    "loras": ("LoRA combination", lambda r: ", ".join(_lora_names(r.get("loras")))),
    "size": ("Size", lambda r: f"{r.get('width')}×{r.get('height')}" if r.get("width") else ""),
    "day": ("Day", lambda r: str(r.get("created_at") or "")[:10]),
}


def group_id(value: str) -> str:
    """A group's id in a request: its value can be a prompt of any length."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _scoped(db, hide_nsfw: bool, group: str = "", in_group: str = "",
            generation: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    The images a level of the Generations tab holds - inside a group, a
    generation, or both - that the NSFW switch lets through, and the counts
    over them all.
    """
    grouping = GROUPINGS.get(group)
    rows = db.generation_gallery_images(None)
    if grouping and in_group:
        rows = [r for r in rows if group_id(grouping[1](r)) == in_group]
    if generation is not None:
        rows = [r for r in rows if r["generation_id"] == generation]
    return _filtered(rows, hide_nsfw, False)


def browse_page(db, hide_nsfw: bool, page: int = 1, group: str = "",
                in_group: str = "", generation: Optional[int] = None) -> Dict[str, Any]:
    """
    Part `page` of a level of the Generations tab, newest first. The top level
    is a tile per generation - its first images and how many it has - or, with
    `group`, a tile per group of images (GROUPINGS), whatever generations they
    are of. A level inside one, `in_group` (a group_id) or `generation`, is
    what that holds: a group's generations, and a generation's images, each a
    tile - so a group opens onto its batches, and a batch onto its images.

    The tab scrolls rather than pages, so there is no page note to count what
    the NSFW switch hid on each: images are filtered first and the parts cut
    from what is left, and no part comes back emptied. The prompt switch is
    not offered here; nothing is hidden for a prompt.

    Returns:
        tiles: each {"kind": "group" | "generation" | "image", "group",
        "generation", "images", "matching_count"}; more: whether another part
        follows; state: the level's totals, for the banner; scope: what the
        level is, for its header - how many images, from when to when, and
        the group's value or the generation's.
    """
    size = gallery_page_size()
    page = max(1, int(page or 1))
    grouping = GROUPINGS.get(group)
    shown, counts = _scoped(db, hide_nsfw, group, in_group, generation)

    units: Dict[Any, List[Dict[str, Any]]] = {}
    if generation is not None:
        kind = "image"
        for row in shown:
            units[row["id"]] = [row]
    elif grouping and not in_group:
        kind = "group"
        for row in shown:
            units.setdefault(grouping[1](row), []).append(row)
    else:
        kind = "generation"
        for row in shown:
            units.setdefault(row["generation_id"], []).append(row)
    order = list(units)
    part = order[(page - 1) * size:page * size]

    previews = {key: units[key][:PREVIEW_IMAGES] for key in part}
    images = db.get_generation_images([r["id"] for rs in previews.values() for r in rs])
    generations = db.get_generations(list(dict.fromkeys(r["generation_id"] for rs in previews.values()
                                                        for r in rs)))
    tiles = []
    for key in part:
        first = previews[key][0]
        generation_row = generations.get(first["generation_id"]) or {"id": first["generation_id"]}
        # The checkpoint its images were made with, if one: a group can span several.
        checkpoints = {r.get("checkpoint_path") for r in units[key]}
        tile = {
            "kind": kind,
            "generation": {k: generation_row.get(k) for k in TILE_FIELDS},
            "images": [{**_image(images[r["id"]]), "checkpoint_path": r.get("checkpoint_path")}
                       for r in previews[key] if r["id"] in images],
            "matching_count": len(units[key]),
            "checkpoint_path": next(iter(checkpoints)) if len(checkpoints) == 1 else None,
            **shared_levels(units[key]),
        }
        if kind == "group":
            tile["group"] = {"id": group_id(key), "value": key, "latest": first.get("created_at"),
                             "generations": len({r["generation_id"] for r in units[key]})}
        tiles.append(tile)

    scope = {"count": len(shown),
             "first": shown[-1]["created_at"] if shown else None,
             "last": shown[0]["created_at"] if shown else None}
    if grouping:
        scope["grouping"] = grouping[0]
        if in_group and shown:
            scope["value"] = grouping[1](shown[0])
    if generation is not None:
        generation_row = db.get_generations([generation]).get(generation) or {}
        scope["generation"] = {k: generation_row.get(k) for k in TILE_FIELDS}

    return {
        "tiles": tiles,
        "more": len(order) > page * size,
        "state": {
            "generation_count": len({r["generation_id"] for r in shown}),
            "stored_generations": db.count_generations(None),
            "hide_nsfw_images": hide_nsfw,
            **counts,
        },
        "scope": scope,
    }


def register(app: FastAPI):
    """Attach this module's endpoints to the app."""

    @app.get("/model-manager/generations/browse")
    async def get_browse_page(page: int = 1, hide_nsfw_images: Optional[bool] = None,
                              group: str = "", in_group: str = "",
                              generation: Optional[int] = None):
        """
        Part `page` of a level of the Generations tab, through the NSFW switch
        - the setting decides it when not sent. See browse_page().

        Args:
            group: what images are grouped by (GROUPINGS), or none.
            in_group: the group opened, by its id.
            generation: the generation opened.
        """
        try:
            hide_nsfw, _ = gallery_switches(hide_nsfw_images, False)
            return JSONResponse({"success": True, **browse_page(
                get_models_db(), hide_nsfw, page, group, in_group, generation)})
        except Exception as e:
            import traceback
            print(f"[ModelManager] Generations page error: {e}")
            traceback.print_exc()
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/page")
    async def get_generation_page(path: str, page: int = 1,
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
            import traceback
            print(f"[ModelManager] Generation page error: {e}")
            traceback.print_exc()
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/{generation_id}/images")
    async def get_generation_all_images(generation_id: int, path: str = "",
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
            rows = [r for r in db.generation_gallery_images(files)
                    if r["generation_id"] == generation_id]
            shown, _ = _filtered(rows, hide_nsfw, hide_promptless)
            images = db.get_generation_images([r["id"] for r in shown])
            return JSONResponse({"success": True,
                                 "images": [_image(images[r["id"]]) for r in shown
                                            if r["id"] in images]})
        except Exception as e:
            print(f"[ModelManager] Generation images error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/{generation_id}/send-plan")
    def get_send_plan(generation_id: int):
        """
        How to set Forge up before sending a generation back: see send_plan().
        A plain `def`: it may read the checkpoint's header.
        """
        try:
            plan = send_plan(get_models_db(), generation_id)
            if plan is None:
                return JSONResponse({"success": False, "error": "No such generation"}, status_code=404)
            return JSONResponse({"success": True, **plan})
        except Exception as e:
            print(f"[ModelManager] Send plan error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.get("/model-manager/generations/images/{image_id}/file")
    async def get_generation_image_file(image_id: int):
        """A generated image, by its record: only what was recorded is served."""
        path = get_models_db().get_generation_image_path(image_id)
        if not path or not os.path.isfile(path):
            return JSONResponse({"success": False, "error": "Image not found"}, status_code=404)
        return FileResponse(path)

    @app.post("/model-manager/generations/images/{image_id}/delete")
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
            paths, gone = get_models_db().delete_generation_image(image_id)
            deleted, failed = _delete_files(paths) if delete_files else ([], [])
            print(f"[ModelManager] Deleted generated image {image_id}"
                  + (" and its file" if deleted else ""))
            return JSONResponse({"success": True, "deleted_files": len(deleted), "failed": failed,
                                 "generation_deleted": gone})
        except Exception as e:
            print(f"[ModelManager] Delete generated image error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/rate")
    def rate_generated_images(level: str = Form(default=""), image_id: Optional[int] = Form(default=None),
                              group: str = Form(default=""), in_group: str = Form(default=""),
                              generation: Optional[int] = Form(default=None), path: str = Form(default=""),
                              hide_nsfw_images: bool = Form(default=True),
                              hide_promptless_images: bool = Form(default=False)):
        """
        Rate your own images' NSFW level - `level` one of nsfw.USER_LEVELS, or
        empty to clear the rating, back to what the prompt gives. Which images:

        - `image_id`: that one;
        - `path` and `generation`: a model's "Your generations" card - its
          images that gallery shows, through both its switches;
        - `generation`: a batch of the Generations tab - within the group
          `in_group`, if opened from one - its images the tab shows, through
          the NSFW switch.

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
                rows = [r for r in db.generation_gallery_images(db.generation_gallery_files(path))
                        if r["generation_id"] == generation]
                ids = [r["id"] for r in _filtered(rows, hide_nsfw_images, hide_promptless_images)[0]]
            elif generation is not None:
                ids = [r["id"] for r in _scoped(db, hide_nsfw_images, group, in_group, generation)[0]]
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
            print(f"[ModelManager] Rate images error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/group/delete")
    def delete_generation_group(group: str = Form(...), in_group: str = Form(...),
                                hide_nsfw_images: bool = Form(default=True),
                                delete_files: bool = Form(default=False)):
        """
        Delete a group of the Generations tab: the images of it the grid shows
        - through the NSFW switch, so an image it hides, and the tile does not
        count, stays - each as one image is, a generation going with its last.

        Returns:
            deleted: how many images; deleted_files and failed, as
            delete_generation; generations_deleted: the ids that went.
        """
        try:
            db = get_models_db()
            if group not in GROUPINGS:
                return JSONResponse({"success": False, "error": "Not a grouping"}, status_code=400)
            shown, _ = _scoped(db, hide_nsfw_images, group, in_group)
            paths, gone = [], []
            for row in shown:
                own, generation_gone = db.delete_generation_image(row["id"])
                paths += own
                if generation_gone is not None:
                    gone.append(generation_gone)
            deleted, failed = _delete_files(paths) if delete_files else ([], [])
            print(f"[ModelManager] Deleted a group of {len(shown)} generated images"
                  + (f" and {len(deleted)} of their files" if delete_files else ""))
            return JSONResponse({"success": True, "deleted": len(shown), "deleted_files": len(deleted),
                                 "failed": failed, "generations_deleted": gone})
        except Exception as e:
            print(f"[ModelManager] Delete group error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @app.post("/model-manager/generations/{generation_id}/delete")
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
            paths = get_models_db().delete_generation(generation_id)
            deleted, failed = _delete_files(paths) if delete_files else ([], [])
            print(f"[ModelManager] Deleted generation {generation_id}"
                  + (f" and {len(deleted)} of its image files" if delete_files else ""))
            return JSONResponse({"success": True, "deleted_files": len(deleted),
                                 "failed": failed})
        except Exception as e:
            print(f"[ModelManager] Delete generation error: {e}")
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)
