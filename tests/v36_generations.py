"""
The generation tables' reads as they were at schema v36, frozen: the
Generations tab's and the galleries' answers before #231, for
generations_scale_test to hold the new reads to, on the same images. Copied
from the code of 0.57.1 - api/generations.py and db/generations_ops.py - and
never to be edited: it is what the new code is compared with.

`V36` stands in for the database facade over a v36 database's connection.
"""
import hashlib
import json
import os
import re
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from model_manager.gallery import gallery_page_size, switch_counts
from model_manager.nsfw import PG, SFW_MAX
from model_manager.prompt_rules import MIN_PROMPT_LENGTH, trimmed_sql
from model_manager.db.library import LIBRARY

_GENERATION_COLUMNS = (
    "created_at", "mode", "forge", "prompt", "negative_prompt", "styles",
    "hr_prompt", "hr_negative_prompt", "n_iter", "batch_size", "width", "height",
    "checkpoint_path", "checkpoint_hash", "modules", "hr_checkpoint_path",
    "hr_modules", "refiner_path", "params", "extra_params", "script_args",
    "settings", "infotext", "image_count", "prompt_nsfw_level", "inputs",
)
_IMAGE_COLUMNS = (
    "position", "iteration", "path", "infotext", "meta", "prompt",
    "negative_prompt", "seed", "subseed", "hr_prompt", "hr_negative_prompt",
    "loras", "width", "height", "prompt_nsfw_level",
)
# Stored as JSON text: lists and dicts.
_JSON_COLUMNS = {"styles", "modules", "hr_modules", "params", "extra_params",
                 "script_args", "settings", "meta", "loras", "inputs"}


def _stored(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS and value is not None:
        return json.dumps(value, ensure_ascii=False)
    return value


def _read(row) -> Dict[str, Any]:
    record = dict(row)
    for column in _JSON_COLUMNS & record.keys():
        if record[column] is not None:
            try:
                record[column] = json.loads(record[column])
            except (TypeError, ValueError):
                pass
    return record



class GenerationsOps:
    """
    Operations for the generations tables.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        self._cursor = cursor_factory

    def library_files(self, paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """
        What the library knows of each of these files, by the path as given:
        {version_id, model_id, model_name} - the ids None for a file Civitai
        does not know - and nothing for a path the library does not hold.
        Once per path, ignoring case, as library_spelling() does.
        """
        found: Dict[str, Dict[str, Any]] = {}
        with self._cursor() as cursor:
            for path in {p for p in paths if p}:
                cursor.execute(
                    f"SELECT v.id, v.model_id, m.name FROM {LIBRARY} v "
                    "LEFT JOIN models m ON m.id = v.model_id "
                    "WHERE v.file_path = ? COLLATE NOCASE LIMIT 1", (path,))
                row = cursor.fetchone()
                if row:
                    found[path] = {"version_id": row[0], "model_id": row[1], "model_name": row[2]}
        return found

    def library_spelling(self, paths: Iterable[str]) -> Dict[str, str]:
        """
        Each path as the library spells it, for the files it holds.

        Forge and the library can spell one file two ways - case, above all,
        which Windows ignores and SQL does not - and generation_files is
        joined on equality. A path the library does not hold is left out.
        """
        found: Dict[str, str] = {}
        with self._cursor() as cursor:
            for path in set(paths):
                cursor.execute("SELECT file_path FROM files "
                               "WHERE file_path = ? COLLATE NOCASE LIMIT 1", (path,))
                row = cursor.fetchone()
                if row:
                    found[path] = row[0]
        return found

    def record_generation(self, generation: Dict[str, Any],
                          images: List[Dict[str, Any]],
                          files: List[List[str]]) -> int:
        """
        Store one generation and its images, in one transaction.

        Args:
            generation: The generations row, by column.
            images: One generation_images row per result, by column.
            files: For each image, in the same order, the model files it used.

        Returns:
            The generation's id.
        """
        with self._cursor() as cursor:
            columns = [c for c in _GENERATION_COLUMNS if c in generation]
            cursor.execute(
                f"INSERT INTO generations ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})",
                [_stored(c, generation[c]) for c in columns])
            generation_id = cursor.lastrowid
            for image, used in zip(images, files):
                columns = [c for c in _IMAGE_COLUMNS if c in image]
                cursor.execute(
                    f"INSERT INTO generation_images (generation_id, {', '.join(columns)}) "
                    f"VALUES (?, {', '.join('?' * len(columns))})",
                    [generation_id] + [_stored(c, image[c]) for c in columns])
                image_id = cursor.lastrowid
                cursor.executemany(
                    "INSERT OR IGNORE INTO generation_files (file_path, image_id, generation_id) "
                    "VALUES (?, ?, ?)",
                    [(path, image_id, generation_id) for path in dict.fromkeys(used)])
            return generation_id

    def get_generation(self, generation_id: int) -> Optional[Dict[str, Any]]:
        """A generation, with its images in order, each with the files it used."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM generations WHERE id = ?", (generation_id,))
            row = cursor.fetchone()
            if not row:
                return None
            generation = _read(row)
            cursor.execute("SELECT * FROM generation_images WHERE generation_id = ? "
                           "ORDER BY position", (generation_id,))
            generation["images"] = [_read(r) for r in cursor.fetchall()]
            cursor.execute("SELECT image_id, file_path FROM generation_files "
                           "WHERE generation_id = ? ORDER BY file_path", (generation_id,))
            used: Dict[int, List[str]] = {}
            for image_id, path in cursor.fetchall():
                used.setdefault(image_id, []).append(path)
            for image in generation["images"]:
                image["files"] = used.get(image["id"], [])
            return generation

    # ------------------------------------------------------------ galleries

    def gallery_files(self, path: str) -> List[str]:
        """
        The model files whose generations one gallery shows: every file of the
        open file's Civitai version, as the Civitai tab shows one gallery per
        version; the file alone when it has no version.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT version_id, file_path FROM files "
                           "WHERE file_path = ? COLLATE NOCASE", (path,))
            row = cursor.fetchone()
            if not row:
                return [path]
            if row[0] is None:
                return [row[1]]
            cursor.execute("SELECT file_path FROM files WHERE version_id = ?", (row[0],))
            return [r[0] for r in cursor.fetchall()]

    def gallery_images(self, files: Optional[List[str]]) -> List[Dict[str, Any]]:
        """
        Every image filed under any of these files - or every image recorded,
        for files None: the Generations tab's - with what filtering, ordering
        and grouping need and nothing more: its generation, its place in it,
        its level - the user's rating when set, else the prompt's - how long
        its prompt is, when its generation was made, and what the Generations
        tab groups by: its own prompt and the one typed, its checkpoint and
        the checkpoint's base model - the library's, as the Model Manager's
        Base Model filter reads it - its LoRAs and its size. Newest
        generation first.
        """
        if files is not None and not files:
            return []
        where, args = "", []
        if files is not None:
            where = ("WHERE gi.id IN (SELECT image_id FROM generation_files WHERE file_path IN "
                     f"({', '.join('?' * len(files))}))")
            args = list(files)
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT gi.id, gi.generation_id, gi.position,
                       COALESCE(gi.user_nsfw_level, gi.prompt_nsfw_level) AS level,
                       gi.user_nsfw_level AS user_level,
                       LENGTH({trimmed_sql('gi.prompt')}) AS prompt_length,
                       g.created_at, gi.prompt AS image_prompt, g.prompt AS typed_prompt,
                       g.checkpoint_path, gi.loras, gi.width, gi.height
                FROM generation_images gi
                JOIN generations g ON g.id = gi.generation_id
                {where}
                ORDER BY g.created_at DESC, g.id DESC, gi.position
            """, args)
            rows = [dict(r) for r in cursor.fetchall()]
            # Each checkpoint's base model, once per checkpoint: Forge and the
            # library can spell its path in two cases (library_spelling()), and
            # a comparison that ignores case cannot use the index.
            bases: Dict[str, Optional[str]] = {}
            for path in {r["checkpoint_path"] for r in rows if r["checkpoint_path"]}:
                cursor.execute(f"SELECT base_model FROM {LIBRARY} WHERE file_path = ? COLLATE NOCASE "
                               "AND COALESCE(base_model, '') <> '' LIMIT 1", (path,))
                found = cursor.fetchone()
                bases[path] = found[0] if found else None
            for row in rows:
                row["base_model"] = bases.get(row["checkpoint_path"])
            return rows

    def matching_images(self, words: List[str], task_id: Optional[int] = None) -> Set[int]:
        """
        The images a Generations search finds: each of `words` in the
        image's prompt or negative prompt - as generated, or as typed -
        ignoring case; with `task_id`, only those the task's run made.
        """
        fields = ("gi.prompt", "gi.negative_prompt", "g.prompt", "g.negative_prompt")
        where, args = [], []
        for word in words:
            # A word is matched as typed: % and _ mean themselves.
            pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(" + " OR ".join(f"{f} LIKE ? ESCAPE '\\'" for f in fields) + ")")
            args += [pattern] * len(fields)
        if task_id is not None:
            where.append("gi.generation_id IN (SELECT generation_id FROM task_generations WHERE task_id = ?)")
            args.append(task_id)
        with self._cursor() as cursor:
            cursor.execute("SELECT gi.id FROM generation_images gi JOIN generations g ON g.id = gi.generation_id"
                           + (" WHERE " + " AND ".join(where) if where else ""), args)
            return {r[0] for r in cursor.fetchall()}

    def count_generations(self, files: Optional[List[str]]) -> int:
        """How many generations used any of these files - or at all, for None."""
        if files is None:
            with self._cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM generations")
                return cursor.fetchone()[0]
        if not files:
            return 0
        marks = ", ".join("?" * len(files))
        with self._cursor() as cursor:
            cursor.execute(f"SELECT COUNT(DISTINCT generation_id) FROM generation_files "
                           f"WHERE file_path IN ({marks})", files)
            return cursor.fetchone()[0]

    def get_generations(self, generation_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These generations' rows, without the bulky JSON a card never shows."""
        if not generation_ids:
            return {}
        marks = ", ".join("?" * len(generation_ids))
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT id, created_at, mode, forge, prompt, negative_prompt, n_iter,
                       batch_size, width, height, image_count, infotext, checkpoint_path
                FROM generations WHERE id IN ({marks})
            """, generation_ids)
            return {r["id"]: dict(r) for r in cursor.fetchall()}

    def get_generation_images(self, image_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These images' rows, by id."""
        if not image_ids:
            return {}
        marks = ", ".join("?" * len(image_ids))
        with self._cursor() as cursor:
            cursor.execute(f"SELECT * FROM generation_images WHERE id IN ({marks})", image_ids)
            return {r["id"]: _read(r) for r in cursor.fetchall()}

    def get_image_path(self, image_id: int) -> Optional[str]:
        """Where one generated image was saved."""
        with self._cursor() as cursor:
            cursor.execute("SELECT path FROM generation_images WHERE id = ?", (image_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def count_images(self, generation_id: int) -> int:
        """How many image records a generation has - hidden ones too."""
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM generation_images WHERE generation_id = ?", (generation_id,))
            return cursor.fetchone()[0]

    def delete_generation(self, generation_id: int) -> List[str]:
        """
        Remove a generation's rows from all three tables, and its link to
        the queue's task that made it, if one did.

        Returns:
            The paths its images were saved to that no other record names,
            for a caller asked to delete the files as well. Forge can save a
            later image over an earlier one's file, when its replace action
            is Override, and the earlier record then names a file that is not
            only its own. The files themselves are not touched here.
        """
        with self._cursor() as cursor:
            return self.remove(cursor, generation_id)

    def remove(self, cursor, generation_id: int) -> List[str]:
        """delete_generation() inside a caller's transaction: a task deleted
        with its data takes its generations with it, in one (#162)."""
        cursor.execute("SELECT path FROM generation_images WHERE generation_id = ?",
                       (generation_id,))
        paths = [r[0] for r in cursor.fetchall()]
        cursor.execute("DELETE FROM generation_files WHERE generation_id = ?", (generation_id,))
        cursor.execute("DELETE FROM generation_images WHERE generation_id = ?", (generation_id,))
        cursor.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
        cursor.execute("DELETE FROM task_generations WHERE generation_id = ?", (generation_id,))
        own = []
        for path in dict.fromkeys(paths):
            cursor.execute("SELECT 1 FROM generation_images WHERE path = ? COLLATE NOCASE LIMIT 1",
                           (path,))
            if not cursor.fetchone():
                own.append(path)
        return own

    def set_user_levels(self, image_ids: List[int], level: Optional[int]) -> int:
        """
        Give these images the level a person rated them, or none (None) - they
        go back to their prompt's. The prompt's is left as it is: a restamp
        rewrites only that, so a rating outlives a change of prompt words.

        Returns:
            How many images were rated.
        """
        if not image_ids:
            return 0
        marks = ", ".join("?" * len(image_ids))
        with self._cursor() as cursor:
            cursor.execute(f"UPDATE generation_images SET user_nsfw_level = ? WHERE id IN ({marks})",
                           [level, *image_ids])
            return cursor.rowcount

    def delete_image(self, image_id: int) -> Tuple[List[str], Optional[int]]:
        """
        Remove one image of a generation, and the generation too when it was
        the last one left - with its link to the task that made it.

        Returns:
            (its path, if no other record names it - as delete_generation()
            says why - and the id of the generation removed with it, or None).
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT generation_id, path FROM generation_images WHERE id = ?", (image_id,))
            row = cursor.fetchone()
            if not row:
                return [], None
            generation_id, path = row[0], row[1]
            cursor.execute("DELETE FROM generation_files WHERE image_id = ?", (image_id,))
            cursor.execute("DELETE FROM generation_images WHERE id = ?", (image_id,))
            cursor.execute("SELECT COUNT(*) FROM generation_images WHERE generation_id = ?",
                           (generation_id,))
            left = cursor.fetchone()[0]
            gone = None
            if left:
                cursor.execute("UPDATE generations SET image_count = ? WHERE id = ?",
                               (left, generation_id))
            else:
                cursor.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
                cursor.execute("DELETE FROM task_generations WHERE generation_id = ?", (generation_id,))
                gone = generation_id
            cursor.execute("SELECT 1 FROM generation_images WHERE path = ? COLLATE NOCASE LIMIT 1",
                           (path,))
            return ([] if cursor.fetchone() or not path else [path]), gone

    def restamp_levels(self, level: Callable[[Optional[Dict[str, Any]]], int]) -> Tuple[int, int]:
        """
        Judge every image's prompt again, and each generation by its most
        explicit image, as level() now would.

        Returns:
            (images changed, images read)
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT id, meta, prompt_nsfw_level FROM generation_images")
            rows = cursor.fetchall()
        changed = []
        for image_id, meta, stored in rows:
            try:
                now = level(json.loads(meta) if meta else None)
            except (TypeError, ValueError):
                continue
            if now != stored:
                changed.append((now, image_id))
        with self._cursor() as cursor:
            cursor.executemany("UPDATE generation_images SET prompt_nsfw_level = ? WHERE id = ?",
                               changed)
            if changed:
                cursor.execute("""
                    UPDATE generations SET prompt_nsfw_level = (
                        SELECT MAX(prompt_nsfw_level) FROM generation_images
                        WHERE generation_images.generation_id = generations.id)
                """)
        return len(changed), len(rows)


PREVIEW_IMAGES = 4


# What a tile needs of its generation, besides its images.
TILE_FIELDS = ("id", "created_at", "mode", "image_count", "width", "height", "checkpoint_path")


# What the Generations tab can group images by: name -> (what it is called,
# an image row's value). An image is in exactly one group of each.
GROUPINGS = {
    "prompt_written": ("Prompt, as written", lambda r: _one_line(r.get("typed_prompt"))),
    "prompt": ("Prompt, as generated", lambda r: _one_line(r.get("image_prompt"))),
    # The checkpoint's, as the library holds it - the Model Manager's Base Model filter's.
    "base_model": ("Base model", lambda r: r.get("base_model") or ""),
    "model": ("Model", lambda r: os.path.splitext(os.path.basename(r.get("checkpoint_path") or ""))[0]),
    "loras": ("LoRA combination", lambda r: ", ".join(_lora_names(r.get("loras")))),
    "size": ("Size", lambda r: f"{r.get('width')}×{r.get('height')}" if r.get("width") else ""),
    "day": ("Day", lambda r: str(r.get("created_at") or "")[:10]),
}


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
    return resources


def _lora_paths(row: Dict[str, Any]) -> List[str]:
    """The files of the LoRAs an image used, as its row records them."""
    try:
        loras = json.loads(row.get("loras") or "[]")
    except (TypeError, ValueError):
        return []
    return [l["path"] for l in loras if isinstance(l, dict) and l.get("path")]


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
            "hidden_both": page_counts["hidden_both"],
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


def grouping_chain(group: str) -> List[str]:
    """
    What `group` groups by, in order: one grouping ("model"), or two
    ("model>prompt_written") - a group of the first opens onto groups of the
    second. Anything else, or more than two, is no grouping at all.
    """
    keys = [k for k in str(group or "").split(">")]
    return keys if 1 <= len(keys) <= 2 and all(k in GROUPINGS for k in keys) else []


def group_id(value: str) -> str:
    """A group's id in a request: its value can be a prompt of any length."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


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


def _scoped(db, hide_nsfw: bool, group: str = "", in_group: str = "",
            generation: Optional[int] = None, in_subgroup: str = "",
            search: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    The images a level of the Generations tab holds - inside a group, one of
    its groups when grouped twice, a generation, or these together - that the
    search finds and the NSFW switch lets through, and the counts over them
    all.
    """
    chain = grouping_chain(group)
    rows = db.generation_gallery_images(None)
    words, task = search_terms(search)
    if words or task is not None:
        found = db.search_generation_images(words, task)
        rows = [r for r in rows if r["id"] in found]
    for key, opened in zip(chain, (in_group, in_subgroup)):
        if opened:
            value_of = GROUPINGS[key][1]
            rows = [r for r in rows if group_id(value_of(r)) == opened]
    if generation is not None:
        rows = [r for r in rows if r["generation_id"] == generation]
    return _filtered(rows, hide_nsfw, False)


def browse_page(db, hide_nsfw: bool, page: int = 1, group: str = "",
                in_group: str = "", generation: Optional[int] = None,
                in_subgroup: str = "", search: str = "") -> Dict[str, Any]:
    """
    Part `page` of a level of the Generations tab, newest first. The top level
    is a tile per generation - its first images and how many it has - or, with
    `group`, a tile per group of images (GROUPINGS), whatever generations they
    are of. A level inside one, `in_group` (a group_id) or `generation`, is
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
    chain = grouping_chain(group)
    shown, counts = _scoped(db, hide_nsfw, group, in_group, generation, in_subgroup, search)

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

    units: Dict[Any, List[Dict[str, Any]]] = {}
    sections: Dict[str, List[Dict[str, Any]]] = {}
    if generation is not None:
        kind = "image"
        for row in shown:
            units[row["id"]] = [row]
    elif sectioned:
        # Sections newest first, and in each its groups newest first: a
        # section's groups are one run of tiles, whatever part they fall in.
        kind = "group"
        for row in shown:
            sections.setdefault(GROUPINGS[chain[0]][1](row), []).append(row)
        for section, rows in sections.items():
            for row in rows:
                units.setdefault((section, GROUPINGS[by][1](row)), []).append(row)
    elif by:
        kind = "group"
        for row in shown:
            units.setdefault(GROUPINGS[by][1](row), []).append(row)
    else:
        kind = "generation"
        for row in shown:
            units.setdefault(row["generation_id"], []).append(row)
    order = list(units)
    part = order[(page - 1) * size:page * size]

    previews = {key: units[key][:PREVIEW_IMAGES] for key in part}
    # The files the menus name - each checkpoint and LoRA these tiles used -
    # looked up in the library once each.
    known = db.generation_library_files(
        {r.get("checkpoint_path") for key in part for r in units[key]}
        | {p for key in part for r in units[key] for p in _lora_paths(r)})

    def loras_of(rows):
        return [file_ref(p, known) for p in dict.fromkeys(p for r in rows for p in _lora_paths(r))]
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
            "images": [{**_image(images[r["id"]]), "checkpoint_path": r.get("checkpoint_path"),
                        "checkpoint": file_ref(r.get("checkpoint_path"), known), "loras": loras_of([r])}
                       for r in previews[key] if r["id"] in images],
            "matching_count": len(units[key]),
            "checkpoint_path": next(iter(checkpoints)) if len(checkpoints) == 1 else None,
            # For its ⋯ menu: the checkpoint, if its images share one, and every LoRA they used.
            "checkpoint": file_ref(next(iter(checkpoints)), known) if len(checkpoints) == 1 else None,
            "loras": loras_of(units[key]),
            **shared_levels(units[key]),
        }
        if kind == "group":
            value = key[1] if sectioned else key
            tile["group"] = {"id": group_id(value), "value": value, "by": by, "latest": first.get("created_at"),
                             "generations": len({r["generation_id"] for r in units[key]})}
            if sectioned:
                rows = sections[key[0]]
                tile["section"] = {"id": group_id(key[0]), "value": key[0], "by": chain[0], "count": len(rows),
                                   "groups": len({GROUPINGS[by][1](r) for r in rows})}
        tiles.append(tile)

    scope = {"count": len(shown),
             "first": shown[-1]["created_at"] if shown else None,
             "last": shown[0]["created_at"] if shown else None}
    if chain:
        scope["grouping"] = " › ".join(GROUPINGS[k][0] for k in chain)
        # What each group opened is: [{"by", "name", "value"}], outermost first.
        opened = [(k, g) for k, g in zip(chain, (in_group, in_subgroup)) if g]
        if opened and shown:
            scope["values"] = [{"by": k, "name": GROUPINGS[k][0], "value": GROUPINGS[k][1](shown[0])}
                               for k, _ in opened]
            scope["value"] = scope["values"][-1]["value"]
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


class V36:
    """The facade's names for the v36 reads, over one connection."""

    def __init__(self, connection):
        @contextmanager
        def cursor():
            c = connection.cursor()
            try:
                yield c
                connection.commit()
            finally:
                c.close()
        self.ops = GenerationsOps(cursor)

    def generation_gallery_images(self, files):
        return self.ops.gallery_images(files)

    def generation_gallery_files(self, path):
        return self.ops.gallery_files(path)

    def search_generation_images(self, words, task=None):
        return self.ops.matching_images(words, task)

    def generation_library_files(self, paths):
        return self.ops.library_files(paths)

    def get_generation_images(self, ids):
        return self.ops.get_generation_images(ids)

    def get_generations(self, ids):
        return self.ops.get_generations(ids)

    def count_generations(self, files):
        return self.ops.count_generations(files)

    def record_generation(self, generation, images, files):
        return self.ops.record_generation(generation, images, files)
