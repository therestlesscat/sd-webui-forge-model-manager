"""
Internal module for the images you generate, in the tables of schema v37 (#231):

- generations and generation_images: what lists, groups and filters read,
  narrow, so a scan of tens of thousands of images reads few pages - a wide
  row costs its whole page whatever column is read;
- generation_details and image_details: one row each, what one Send or one
  tile reads, with the lists and paths exactly as Forge recorded them;
- prompts: each text once. `grouped_as` is the row holding the text with its
  spacing tidied (0 when nothing is left), which the Generations tab groups by;
  `length` how long it is, trimmed as a prompt worth reading is - both held by
  an index, read for every image without reading the texts;
- generation_resources: every file an image used, with its role and its place
  in the list it came from, spelled as the library spells the file - an index
  made from the recorded lists, which a moved file's path follows.

A generation is written once, whole, when Forge has finished it, and is not
changed afterwards: only what is derived from it - the prompt's NSFW level -
is stamped again, the user's own rating set, and a moved file followed. See
migrations._migrate_to_v37.

The Generations tab and the galleries pick a part in SQL - filtered, grouped,
ordered and cut - then read only its rows (`Scope`): reading every image into
Python took 300 to 900 ms a request at 76,000 images (#231).

Used by ModelsDatabase facade - do not import directly.
"""
import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..gallery import switch_counts_sql
from ..nsfw import SFW_MAX
from ..prompt_rules import MIN_PROMPT_LENGTH, trimmed_sql
from .library import LIBRARY

# A generation's columns as the recorder hands them, by the table keeping them.
_GENERATION_COLUMNS = ("created_at", "mode", "forge", "image_count", "prompt_nsfw_level",
                       "user_nsfw_level")
_GENERATION_DETAILS = ("checkpoint_path", "modules", "hr_checkpoint_path", "hr_modules",
                       "refiner_path", "infotext", "styles", "hr_prompt", "hr_negative_prompt",
                       "n_iter", "batch_size", "width", "height", "checkpoint_hash", "params",
                       "extra_params", "script_args", "settings", "inputs")
_IMAGE_COLUMNS = ("position", "iteration", "path", "seed", "subseed", "width", "height",
                  "prompt_nsfw_level", "user_nsfw_level")
_IMAGE_DETAILS = ("infotext", "meta", "loras", "hr_prompt", "hr_negative_prompt")
# Stored as JSON text: lists and dicts.
_JSON_COLUMNS = {"styles", "modules", "hr_modules", "params", "extra_params",
                 "script_args", "settings", "meta", "loras", "inputs"}
# The path column a resource of each single-file role stands for.
_SINGLE_PATHS = {"checkpoint": "checkpoint_path", "hr_checkpoint": "hr_checkpoint_path",
                 "refiner": "refiner_path"}
_MODULE_ROLES = ("vae", "text_encoder", "module")

# The groupings whose groups are prompts: a group's id names its `grouped_as`.
PROMPT_GROUPINGS = ("prompt_written", "prompt")

# SQLite sorts inside group_concat from 3.44. Before it, the order comes from
# a sorted subquery, which SQLite follows though it does not promise to; a
# test feeds the rows in reverse to see one group come out.
_ORDERED_CONCAT = sqlite3.sqlite_version_info >= (3, 44, 0)
# Each image's LoRA combination - its LoRAs' names, sorted, once each - made
# once per image and joined: worked out per row inside the grouping, SQLite
# worked it out again for every use, 4.5 s at 10,000 images (#231).
_COMBOS = (
    "combo AS (SELECT image_id, group_concat(name, ', '{order}) AS k FROM ("
    "SELECT DISTINCT image_id, name FROM generation_resources WHERE role = 'lora' AND name <> ''{sub}"
    ") GROUP BY image_id)"
).format(order=" ORDER BY name" if _ORDERED_CONCAT else "",
         sub="" if _ORDERED_CONCAT else " ORDER BY image_id, name")

# What each grouping groups by, as SQL over a scope's images (`gi`), their
# generation (`g`), their prompts (`ip`, `wp`), their generation's checkpoint
# (`ck`) and its base model (`bm`), its LoRA combination (`combo`). An image is
# in exactly one group of each.
GROUP_KEYS = {
    "prompt_written": "COALESCE(wp.grouped_as, 0)",
    "prompt": "COALESCE(ip.grouped_as, 0)",
    "base_model": "COALESCE(bm.base, '')",
    "model": "COALESCE(ck.name, '')",
    "loras": "COALESCE(combo.k, '')",
    "size": "CASE WHEN gi.width THEN gi.width || '×' || COALESCE(gi.height, 'None') ELSE '' END",
    "day": "substr(g.created_at, 1, 10)",
}

# A generation's checkpoint, where it is now: read from an index that holds it.
_CHECKPOINT = ("(SELECT MIN(r.file_path) FROM generation_resources r "
               "WHERE r.role = 'checkpoint' AND r.generation_id = {generation})")

# Explicit, as everywhere: an image no rule has judged reads as not safe.
_LEVEL = "COALESCE(gi.user_nsfw_level, gi.prompt_nsfw_level)"
_SAFE = f"COALESCE({_LEVEL} <= {SFW_MAX}, 0)"
# Newest first: the order every list of your images is in.
_ORDER = "created_at DESC, generation_id DESC, position"
# The same order as one value, highest first, so a unit is placed by its
# newest image's key without numbering every image: a numbering sorted the
# whole scope, in each of a request's four reads (#231). The date as stored,
# then a byte below any of its characters - so a date that is another's
# prefix sorts first, as text does - then the generation's id and the
# position, each at a fixed width.
_SORT_KEY = ("g.created_at || char(1) || printf('%012d', gi.generation_id) || char(1) "
             "|| printf('%06d', 999999 - gi.position)")


def tidy(text: Any) -> str:
    """A prompt as a group's key: its spacing tidied, nothing else changed."""
    return " ".join(str(text if text is not None else "").split())


def group_id(grouping: str, key: Any) -> str:
    """A group's id in a request: its prompt's `grouped_as`, or its value."""
    return f"p{int(key or 0)}" if grouping in PROMPT_GROUPINGS else f"v{key}"


def group_key(grouping: str, group: str) -> Any:
    """The key a group id names, as GROUP_KEYS gives it; None for no group."""
    group = str(group or "")
    if grouping in PROMPT_GROUPINGS:
        return int(group[1:]) if group[:1] == "p" and group[1:].isdigit() else None
    return group[1:] if group[:1] == "v" else None


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


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _stem(path: Optional[str]) -> str:
    return os.path.splitext(os.path.basename(path or ""))[0]


def resource_rows(generation: Dict[str, Any], image: Dict[str, Any], files: Sequence[str],
                  module_roles: Dict[str, str]) -> List[Tuple[str, int, str, Optional[str], Optional[float]]]:
    """
    The files one image used, each (role, position, name, path, weight):
    named by the lists the generation and the image recorded, and spelled as
    `files` - the library's spelling, the recorder's `used` - spells them. A
    recorded path is matched ignoring case; what is left by its file name,
    after every exact match, so a name never takes another file's spelling. A
    file of `files` no list names is kept as `other`. Migration v37 keeps a
    frozen copy of this.
    """
    entries: List[List[Any]] = []
    if generation.get("checkpoint_path"):
        entries.append(["checkpoint", 0, generation["checkpoint_path"], None])
    for position, path in enumerate(_as_list(generation.get("modules"))):
        if isinstance(path, str) and path:
            entries.append(["module", position, path, None])
    if generation.get("hr_checkpoint_path"):
        entries.append(["hr_checkpoint", 0, generation["hr_checkpoint_path"], None])
    for position, path in enumerate(_as_list(generation.get("hr_modules"))):
        if isinstance(path, str) and path:
            entries.append(["hr_module", position, path, None])
    if generation.get("refiner_path"):
        entries.append(["refiner", 0, generation["refiner_path"], None])
    for position, lora in enumerate(_as_list(image.get("loras"))):
        if isinstance(lora, dict):
            path = lora.get("path") if isinstance(lora.get("path"), str) else None
            entries.append(["lora", position, path, lora])

    unclaimed = list(files)
    spelled: List[Optional[str]] = [None] * len(entries)
    for same in (lambda f, p: f.lower() == p.lower(),
                 lambda f, p: os.path.basename(f).lower() == os.path.basename(p).lower()):
        for index, (_, _, path, _) in enumerate(entries):
            if spelled[index] is None and path:
                found = next((f for f in unclaimed if same(f, path)), None)
                if found is not None:
                    unclaimed.remove(found)
                    spelled[index] = found
    for index, (_, _, path, _) in enumerate(entries):
        # The same file named twice - a LoRA loaded twice, a hires checkpoint
        # that is the checkpoint - shares its one spelling.
        if spelled[index] is None and path:
            spelled[index] = next((f for f in files if f.lower() == path.lower()), None) or \
                next((f for f in files if os.path.basename(f).lower() == os.path.basename(path).lower()), path)

    rows = []
    for (role, position, path, lora), found in zip(entries, spelled):
        if role == "lora":
            weight = lora.get("te_multiplier")
            if weight is None:
                weight = lora.get("weight")
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                weight = None
            name = lora.get("name")
            rows.append(("lora", position, str(name) if name else "", found, weight))
        else:
            if role == "module":
                role = module_roles.get((found or "").lower(), "module")
            rows.append((role, position, _stem(path), found, None))
    for position, path in enumerate(unclaimed):
        rows.append(("other", position, _stem(path), path, None))
    return rows


@dataclass
class Scope:
    """
    Which of your images a read is about, read from the request once: a
    model's gallery (`files`), one generation or a page of them, the groups
    opened - each (grouping, group id) - the search's words, and the Queue's
    task.
    """
    files: Optional[List[str]] = None
    generation: Optional[int] = None
    generations: Optional[List[int]] = None
    opened: List[Tuple[str, str]] = field(default_factory=list)
    words: List[str] = field(default_factory=list)
    task: Optional[int] = None


def _unit_columns(unit: str, section: Optional[str]) -> List[str]:
    """The columns of `shown` naming a unit: its section's key, then its own."""
    own = {"image": "id", "generation": "generation_id"}.get(unit, f"k_{unit}")
    return ([f"k_{section}"] if section else []) + [own]


class GenerationsOps:
    """
    Operations for the generation tables.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        self._cursor = cursor_factory

    # ------------------------------------------------------------ the library

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
        which Windows ignores and SQL does not - and generation_resources is
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

    # ---------------------------------------------------------------- writing

    def _prompt_id(self, cursor, text: Optional[str]) -> Optional[int]:
        """The prompts row holding this text, made if there is none: grouped
        by the row holding its tidied text, made too where needed."""
        if text is None:
            return None
        cursor.execute("SELECT id FROM prompts WHERE text = ?", (text,))
        row = cursor.fetchone()
        if row:
            return row[0]
        tidied = tidy(text)
        grouped = 0 if tidied == "" else None if tidied == text else self._prompt_id(cursor, tidied)
        cursor.execute(f"INSERT INTO prompts (text, grouped_as, length) VALUES (?, ?, LENGTH({trimmed_sql('?')}))",
                       (text, grouped or 0, text))
        new_id = cursor.lastrowid
        if grouped is None:
            cursor.execute("UPDATE prompts SET grouped_as = ? WHERE id = ?", (new_id, new_id))
        return new_id

    def record_generation(self, generation: Dict[str, Any],
                          images: List[Dict[str, Any]],
                          files: List[List[str]]) -> int:
        """
        Store one generation and its images, in one transaction.

        Args:
            generation: The generation, by its columns as recorded - the
                prompts and the details' columns among them.
            images: Each result, by its columns, the same way.
            files: For each image, in the same order, the model files it
                used, as the library spells them.

        Returns:
            The generation's id.
        """
        with self._cursor() as cursor:
            columns = [c for c in _GENERATION_COLUMNS if c in generation]
            cursor.execute(
                f"INSERT INTO generations ({', '.join(columns)}, prompt_id, negative_id) "
                f"VALUES ({', '.join('?' * (len(columns) + 2))})",
                [generation[c] for c in columns]
                + [self._prompt_id(cursor, generation.get("prompt")),
                   self._prompt_id(cursor, generation.get("negative_prompt"))])
            generation_id = cursor.lastrowid
            details = [c for c in _GENERATION_DETAILS if c in generation]
            cursor.execute(
                f"INSERT INTO generation_details (generation_id{''.join(', ' + c for c in details)}) "
                f"VALUES ({', '.join('?' * (len(details) + 1))})",
                [generation_id] + [_stored(c, generation[c]) for c in details])
            module_roles = self._module_roles(cursor, [f for used in files for f in used])
            for image, used in zip(images, files):
                columns = [c for c in _IMAGE_COLUMNS if c in image]
                cursor.execute(
                    f"INSERT INTO generation_images (generation_id, {', '.join(columns)}, prompt_id, negative_id) "
                    f"VALUES ({', '.join('?' * (len(columns) + 3))})",
                    [generation_id] + [image[c] for c in columns]
                    + [self._prompt_id(cursor, image.get("prompt")),
                       self._prompt_id(cursor, image.get("negative_prompt"))])
                image_id = cursor.lastrowid
                details = [c for c in _IMAGE_DETAILS if c in image]
                cursor.execute(
                    f"INSERT INTO image_details (image_id{''.join(', ' + c for c in details)}) "
                    f"VALUES ({', '.join('?' * (len(details) + 1))})",
                    [image_id] + [_stored(c, image[c]) for c in details])
                cursor.executemany(
                    "INSERT INTO generation_resources (image_id, generation_id, role, position, name, "
                    "file_path, weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(image_id, generation_id, *row)
                     for row in resource_rows(generation, image, list(dict.fromkeys(used)), module_roles)])
            return generation_id

    def _module_roles(self, cursor, paths: Iterable[str]) -> Dict[str, str]:
        """What the library read each of these files to be, for a module's role."""
        roles: Dict[str, str] = {}
        for path in {p for p in paths if p}:
            cursor.execute("SELECT file_type FROM files WHERE file_path = ? COLLATE NOCASE "
                           "AND file_type IN ('VAE', 'Text Encoder') LIMIT 1", (path,))
            row = cursor.fetchone()
            if row:
                roles[path.lower()] = "vae" if row[0] == "VAE" else "text_encoder"
        return roles

    # ------------------------------------------------------- one generation

    def get_generation(self, generation_id: int) -> Optional[Dict[str, Any]]:
        """
        A generation, with its images in order, each with the files it used -
        every column as recorded, but its files where they are now: a path
        the library spells otherwise, or a file moved since, is read from
        its resource row.
        """
        with self._cursor() as cursor:
            generation = self._generations(cursor, [generation_id]).get(generation_id)
            if generation is None:
                return None
            cursor.execute("SELECT id FROM generation_images WHERE generation_id = ? ORDER BY position",
                           (generation_id,))
            ids = [r[0] for r in cursor.fetchall()]
            images = self._images(cursor, ids)
            generation["images"] = [images[i] for i in ids if i in images]
            first = generation["images"][0]["id"] if generation["images"] else None
            if first is not None:
                where = self._resources(cursor, [first]).get(first, {})
                for role, column in _SINGLE_PATHS.items():
                    if generation.get(column) and (role, 0) in where:
                        generation[column] = where[(role, 0)][1] or generation[column]
                generation["modules"] = self._followed(generation.get("modules"), where, _MODULE_ROLES)
                generation["hr_modules"] = self._followed(generation.get("hr_modules"), where, ("hr_module",))
            return generation

    @staticmethod
    def _followed(paths: Any, where: Dict[Tuple[str, int], Tuple[str, Optional[str]]],
                  roles: Sequence[str]) -> Any:
        """A recorded list of paths, each where its resource row says it is now."""
        if not isinstance(paths, list):
            return paths
        now = []
        for position, path in enumerate(paths):
            found = next((where[(role, position)][1] for role in roles if (role, position) in where), None)
            now.append(found or path)
        return now

    def _resources(self, cursor, image_ids: List[int]) -> Dict[int, Dict[Tuple[str, int], Tuple[str, Optional[str]]]]:
        """Each image's resources: (role, position) -> (name, path)."""
        found: Dict[int, Dict[Tuple[str, int], Tuple[str, Optional[str]]]] = {}
        if not image_ids:
            return found
        cursor.execute(f"SELECT image_id, role, position, name, file_path FROM generation_resources "
                       f"WHERE image_id IN ({', '.join('?' * len(image_ids))})", list(image_ids))
        for image_id, role, position, name, path in cursor.fetchall():
            found.setdefault(image_id, {})[(role, position)] = (name, path)
        return found

    def _generations(self, cursor, generation_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These generations, every column as recorded, the prompts' texts in place."""
        if not generation_ids:
            return {}
        cursor.execute(f"""
            SELECT g.id, {', '.join('g.' + c for c in _GENERATION_COLUMNS)},
                   {', '.join('d.' + c for c in _GENERATION_DETAILS)},
                   p.text AS prompt, q.text AS negative_prompt
            FROM generations g
            LEFT JOIN generation_details d ON d.generation_id = g.id
            LEFT JOIN prompts p ON p.id = g.prompt_id
            LEFT JOIN prompts q ON q.id = g.negative_id
            WHERE g.id IN ({', '.join('?' * len(generation_ids))})
        """, list(generation_ids))
        return {r["id"]: _read(r) for r in cursor.fetchall()}

    def _images(self, cursor, image_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These images, every column as recorded, the prompts' texts in place,
        and the files each used (`files`)."""
        if not image_ids:
            return {}
        marks = ", ".join("?" * len(image_ids))
        cursor.execute(f"""
            SELECT gi.id, gi.generation_id, {', '.join('gi.' + c for c in _IMAGE_COLUMNS)},
                   {', '.join('d.' + c for c in _IMAGE_DETAILS)},
                   p.text AS prompt, q.text AS negative_prompt
            FROM generation_images gi
            LEFT JOIN image_details d ON d.image_id = gi.id
            LEFT JOIN prompts p ON p.id = gi.prompt_id
            LEFT JOIN prompts q ON q.id = gi.negative_id
            WHERE gi.id IN ({marks})
        """, list(image_ids))
        images = {r["id"]: _read(r) for r in cursor.fetchall()}
        cursor.execute(f"SELECT DISTINCT image_id, file_path FROM generation_resources "
                       f"WHERE image_id IN ({marks}) AND file_path IS NOT NULL "
                       f"ORDER BY image_id, file_path", list(image_ids))
        for image in images.values():
            image["files"] = []
        for image_id, path in cursor.fetchall():
            images[image_id]["files"].append(path)
        return images

    def get_generations(self, generation_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These generations' rows, without the bulky JSON a card never shows:
        the checkpoint where it is now."""
        if not generation_ids:
            return {}
        marks = ", ".join("?" * len(generation_ids))
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT g.id, g.created_at, g.mode, g.forge, p.text AS prompt, q.text AS negative_prompt,
                       d.n_iter, d.batch_size, d.width, d.height, g.image_count, d.infotext,
                       COALESCE((SELECT MIN(r.file_path) FROM generation_resources r
                                 WHERE r.role = 'checkpoint' AND r.generation_id = g.id),
                                d.checkpoint_path) AS checkpoint_path
                FROM generations g
                LEFT JOIN generation_details d ON d.generation_id = g.id
                LEFT JOIN prompts p ON p.id = g.prompt_id
                LEFT JOIN prompts q ON q.id = g.negative_id
                WHERE g.id IN ({marks})
            """, list(generation_ids))
            return {r["id"]: dict(r) for r in cursor.fetchall()}

    def get_generation_images(self, image_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """These images' rows, by id, every column as recorded."""
        with self._cursor() as cursor:
            return self._images(cursor, list(image_ids))

    def image_loras(self, image_ids: List[int]) -> Dict[int, List[str]]:
        """Each image's LoRA files, where they are now, in the order loaded, once each."""
        found: Dict[int, List[str]] = {i: [] for i in image_ids}
        if not image_ids:
            return found
        with self._cursor() as cursor:
            cursor.execute(f"SELECT image_id, file_path FROM generation_resources WHERE role = 'lora' "
                           f"AND file_path IS NOT NULL AND image_id IN ({', '.join('?' * len(image_ids))}) "
                           f"ORDER BY image_id, position", list(image_ids))
            for image_id, path in cursor.fetchall():
                if path not in found[image_id]:
                    found[image_id].append(path)
        return found

    # ----------------------------------------------------------- the scopes

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

    def _rows_sql(self, scope: Scope, keys: Iterable[str], hide_nsfw: Optional[bool] = None,
                  needs: Iterable[str] = ()) -> Tuple[str, List[Any]]:
        """
        The scope's images as `rows` - one each, with its generation, place,
        date, level, the user's rating, whether it is safe, its place in the
        order every list shows them (`sk`, highest first), the key of each
        grouping in `keys`, and what `needs` names: whether its prompt is worth
        reading ("readable"), its checkpoint ("checkpoint") - and, given
        `hide_nsfw`, those the NSFW switch lets through as `shown`. WITH
        clauses, with their arguments in order. A join is made only where
        something reads it: at 76,000 images the prompts' cost 30 ms, the
        checkpoints' 70 (#231).
        """
        keys = set(keys) | {grouping for grouping, _ in scope.opened}
        needs = set(needs)
        ctes: List[str] = []
        args: List[Any] = []
        joins = ["JOIN generations g ON g.id = gi.generation_id"]
        if "readable" in needs or "prompt" in keys:
            # Named: SQLite looked each prompt up by its row, text and all -
            # 130 ms at 76,000 images, against 26 through the index (#231).
            joins.append("LEFT JOIN prompts ip INDEXED BY idx_prompts_lookup ON ip.id = gi.prompt_id")
        if "prompt_written" in keys:
            joins.append("LEFT JOIN prompts wp INDEXED BY idx_prompts_lookup ON wp.id = g.prompt_id")
        if "checkpoint" in needs or keys & {"model", "base_model"}:
            ctes.append("ck AS (SELECT generation_id, MIN(name) AS name, MIN(file_path) AS path "
                        "FROM generation_resources WHERE role = 'checkpoint' GROUP BY generation_id)")
            joins.append("LEFT JOIN ck ON ck.generation_id = g.id")
        if "loras" in keys:
            ctes.append(_COMBOS)
            joins.append("LEFT JOIN combo ON combo.image_id = gi.id")
        if "base_model" in keys:
            # The checkpoint's base model as the library holds it - the Model
            # Manager's Base Model filter's - matched ignoring case, as Forge
            # and the library can spell one path two ways.
            ctes.append(f"bm AS (SELECT lower(file_path) AS lpath, base_model AS base, MIN(file_order) "
                        f"FROM {LIBRARY} WHERE COALESCE(base_model, '') <> '' GROUP BY lower(file_path))")
            joins.append("LEFT JOIN bm ON bm.lpath = lower(ck.path)")
        where: List[str] = []
        args_where: List[Any] = []
        if scope.files is not None:
            if scope.files:
                where.append("gi.id IN (SELECT image_id FROM generation_resources WHERE file_path IN "
                             f"({', '.join('?' * len(scope.files))}))")
                args_where += scope.files
            else:
                where.append("0")
        if scope.generation is not None:
            where.append("gi.generation_id = ?")
            args_where.append(scope.generation)
        if scope.generations is not None:
            where.append(f"gi.generation_id IN ({', '.join('?' * len(scope.generations))})"
                         if scope.generations else "0")
            args_where += scope.generations
        if scope.task is not None:
            where.append("gi.generation_id IN (SELECT generation_id FROM task_generations WHERE task_id = ?)")
            args_where.append(scope.task)
        for index, word in enumerate(scope.words):
            # A word is matched as typed, ignoring case: % and _ mean themselves.
            ctes.append(f"hit{index} AS (SELECT id FROM prompts WHERE text LIKE ? ESCAPE '\\')")
            args.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
            where.append(f"(gi.prompt_id IN hit{index} OR gi.negative_id IN hit{index} "
                         f"OR g.prompt_id IN hit{index} OR g.negative_id IN hit{index})")
        for grouping, opened in scope.opened:
            key = group_key(grouping, opened)
            if key is None:
                where.append("0")
            elif grouping in PROMPT_GROUPINGS:
                column = "gi.prompt_id" if grouping == "prompt" else "g.prompt_id"
                where.append(f"({column} IN (SELECT id FROM prompts WHERE grouped_as = ?)"
                             + (f" OR {column} IS NULL)" if key == 0 else ")"))
                args_where.append(key)
            else:
                where.append(f"{GROUP_KEYS[grouping]} = ?")
                args_where.append(key)
        columns = ["gi.id AS id", "gi.generation_id AS generation_id", "gi.position AS position",
                   "g.created_at AS created_at", f"{_LEVEL} AS level", "gi.user_nsfw_level AS user_level",
                   f"{_SAFE} AS safe", f"{_SORT_KEY} AS sk"]
        if "readable" in needs:
            columns += [f"COALESCE(ip.length, 0) >= {MIN_PROMPT_LENGTH} AS readable",
                        "COALESCE(ip.length, 0) AS prompt_length"]
        if "checkpoint" in needs:
            columns.append("ck.path AS checkpoint_path")
        columns += [f"{GROUP_KEYS[k]} AS k_{k}" for k in sorted(keys)]
        ctes.append(f"rows AS (SELECT {', '.join(columns)} FROM generation_images gi {' '.join(joins)}"
                    + (f" WHERE {' AND '.join(where)}" if where else "") + ")")
        args += args_where
        if hide_nsfw is not None:
            ctes.append("shown AS (SELECT * FROM rows WHERE safe OR NOT ?)")
            args.append(1 if hide_nsfw else 0)
        return "WITH " + ", ".join(ctes), args

    def scope_counts(self, scope: Scope, hide_nsfw: bool, hide_promptless: bool) -> Dict[str, Any]:
        """
        The scope's counts through the two switches, in the meanings every
        gallery's switches keep (gallery.switch_counts), and of what they let
        through: how many generations, and its first and last date.
        """
        sql, args = self._rows_sql(scope, (), needs=("readable",))
        shown = (f"(safe OR NOT {1 if hide_nsfw else 0}) AND (readable OR NOT {1 if hide_promptless else 0})")
        with self._cursor() as cursor:
            cursor.execute(f"""{sql} SELECT {switch_counts_sql(hide_nsfw, hide_promptless)},
                COUNT(DISTINCT CASE WHEN {shown} THEN generation_id END) AS generation_count,
                MIN(CASE WHEN {shown} THEN created_at END) AS oldest,
                MAX(CASE WHEN {shown} THEN created_at END) AS newest
                FROM rows""", args)
            row = dict(cursor.fetchone())
        return {k: (int(v or 0) if k not in ("oldest", "newest") else v) for k, v in row.items()}

    def scope_rows(self, scope: Scope) -> List[Dict[str, Any]]:
        """The scope's images, newest first, one narrow row each: for a scope of
        a few generations - a page of a gallery, one batch."""
        sql, args = self._rows_sql(scope, (), needs=("readable", "checkpoint"))
        with self._cursor() as cursor:
            cursor.execute(f"{sql} SELECT * FROM rows ORDER BY {_ORDER}", args)
            return [dict(r) for r in cursor.fetchall()]

    def scope_generations(self, scope: Scope, offset: int, limit: int) -> Tuple[List[int], int]:
        """The generations with an image in the scope, newest first: `limit` of
        them from `offset`, and how many there are."""
        sql, args = self._rows_sql(scope, ())
        with self._cursor() as cursor:
            cursor.execute(f"""{sql}, gens AS (SELECT generation_id, MAX(created_at) AS created_at
                                                FROM rows GROUP BY generation_id)
                SELECT generation_id, COUNT(*) OVER () FROM gens
                ORDER BY created_at DESC, generation_id DESC LIMIT ? OFFSET ?""",
                           args + [int(limit), int(offset)])
            found = cursor.fetchall()
            if found:
                return [r[0] for r in found], int(found[0][1])
            cursor.execute(f"{sql} SELECT COUNT(DISTINCT generation_id) FROM rows", args)
            return [], int(cursor.fetchone()[0])

    def scope_units(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                    offset: int, limit: int) -> List[Dict[str, Any]]:
        """
        A part of a level of the Generations tab: `limit` of its units from
        `offset`, in the order the tab shows them. A unit is an image, a
        generation, or a group of a grouping (GROUP_KEYS) - in sections of
        another, given `section`: sections by their newest image, and each
        one's groups so. Each unit: its key (and its section's), how many
        images and generations it has, its newest image's date, the level and
        rating all its images share, if they do - None if not - and, in a
        section, the section's image and group counts.
        """
        keys = [k for k in (unit, section) if k and k in GROUP_KEYS]
        sql, args = self._rows_sql(scope, keys, hide_nsfw)
        names = _unit_columns(unit, section)
        own = names[-1]
        by = ", ".join(names)

        def shared(column):
            return (f"CASE WHEN COUNT(DISTINCT {column}) = 1 AND SUM({column} IS NULL) = 0 "
                    f"THEN MIN({column}) END")

        sectioned = (", MAX(first_key) OVER (PARTITION BY s) AS section_first, "
                     "SUM(n) OVER (PARTITION BY s) AS section_count, "
                     "COUNT(*) OVER (PARTITION BY s) AS section_groups") if section else ""
        with self._cursor() as cursor:
            cursor.execute(f"""{sql}, units AS (
                    SELECT {(names[0] + ' AS s, ') if section else ''}{own} AS u, MAX(sk) AS first_key,
                           COUNT(*) AS n, COUNT(DISTINCT generation_id) AS generations,
                           MAX(created_at) AS latest, {shared('level')} AS level,
                           {shared('user_level')} AS user_level
                    FROM shown GROUP BY {by})
                SELECT *{sectioned} FROM units
                ORDER BY {'section_first DESC, ' if section else ''}first_key DESC LIMIT ? OFFSET ?""",
                           args + [int(limit), int(offset)])
            return [dict(r) for r in cursor.fetchall()]

    def _part_sql(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                  part: Sequence[Tuple[Any, ...]]) -> Tuple[str, List[Any], List[str]]:
        """`shown`, and the units of a part as `part` (s, u) or (u)."""
        keys = [k for k in (unit, section) if k and k in GROUP_KEYS]
        sql, args = self._rows_sql(scope, keys, hide_nsfw)
        names = _unit_columns(unit, section)
        width = len(names)
        values = ", ".join("(" + ", ".join("?" * width) + ")" for _ in part)
        sql += f", part({', '.join(['s', 'u'][-width:])}) AS (VALUES {values})"
        args += [value for key in part for value in key]
        return sql, args, names

    def scope_previews(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                       part: Sequence[Tuple[Any, ...]], count: int) -> List[Dict[str, Any]]:
        """The first `count` images of each unit of a part, each with its unit's
        key (`s`, `u`) and its checkpoint, in the order the tab shows them."""
        if not part:
            return []
        sql, args, names = self._part_sql(scope, unit, section, hide_nsfw, part)
        on = " AND ".join(f"part.{p} = shown.{n}" for p, n in zip(["s", "u"][-len(names):], names))
        with self._cursor() as cursor:
            cursor.execute(f"""{sql} SELECT pv.*, {_CHECKPOINT.format(generation='pv.generation_id')}
                    AS checkpoint_path FROM (
                    SELECT shown.*, {', '.join('part.' + p for p in ['s', 'u'][-len(names):])},
                           ROW_NUMBER() OVER (PARTITION BY {', '.join('part.' + p for p in ['s', 'u'][-len(names):])}
                                              ORDER BY shown.sk DESC) AS place
                    FROM shown JOIN part ON {on}) AS pv
                WHERE place <= ? ORDER BY sk DESC""", args + [int(count)])
            return [dict(r) for r in cursor.fetchall()]

    def scope_unit_checkpoints(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                               part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], Optional[str]]:
        """The checkpoint every image of each unit of a part was made with, if
        they share one, where it is now; None if they do not."""
        if not part:
            return {}
        sql, args, names = self._part_sql(scope, unit, section, hide_nsfw, part)
        cols = ["s", "u"][-len(names):]
        on = " AND ".join(f"part.{p} = shown.{n}" for p, n in zip(cols, names))
        found: Dict[Tuple[Any, ...], Optional[str]] = {tuple(key): None for key in part}
        with self._cursor() as cursor:
            cursor.execute(f"""{sql} SELECT {', '.join(cols)},
                       CASE WHEN COUNT(DISTINCT path) = 1 AND SUM(path IS NULL) = 0 THEN MIN(path) END
                FROM (SELECT {', '.join('part.' + c for c in cols)},
                             {_CHECKPOINT.format(generation='shown.generation_id')} AS path
                      FROM shown JOIN part ON {on})
                GROUP BY {', '.join(cols)}""", args)
            for row in cursor.fetchall():
                found[tuple(row[:len(cols)])] = row[len(cols)]
        return found

    def scope_unit_loras(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                         part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], List[str]]:
        """Every LoRA file each unit of a part used, where it is now, once each,
        in the order its images show and loaded them."""
        if not part:
            return {}
        sql, args, names = self._part_sql(scope, unit, section, hide_nsfw, part)
        cols = ["s", "u"][-len(names):]
        on = " AND ".join(f"part.{p} = shown.{n}" for p, n in zip(cols, names))
        found: Dict[Tuple[Any, ...], List[str]] = {tuple(key): [] for key in part}
        with self._cursor() as cursor:
            cursor.execute(f"""{sql} SELECT {', '.join('part.' + c for c in cols)}, r.file_path,
                       MAX(shown.sk || char(1) || printf('%06d', 999999 - r.position)) AS first_seen
                FROM shown JOIN part ON {on}
                JOIN generation_resources r ON r.image_id = shown.id AND r.role = 'lora'
                     AND r.file_path IS NOT NULL
                GROUP BY {', '.join('part.' + c for c in cols)}, r.file_path
                ORDER BY {', '.join('part.' + c for c in cols)}, first_seen DESC""", args)
            for row in cursor.fetchall():
                found.setdefault(tuple(row[:len(cols)]), []).append(row[len(cols)])
        return found

    def prompt_texts(self, prompt_ids: Iterable[int]) -> Dict[int, str]:
        """These prompts' texts, by id."""
        ids = sorted({int(i) for i in prompt_ids if i})
        if not ids:
            return {}
        with self._cursor() as cursor:
            cursor.execute(f"SELECT id, text FROM prompts WHERE id IN ({', '.join('?' * len(ids))})", ids)
            return {r[0]: r[1] for r in cursor.fetchall()}

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
            cursor.execute(f"SELECT COUNT(DISTINCT generation_id) FROM generation_resources "
                           f"WHERE file_path IN ({marks})", files)
            return cursor.fetchone()[0]

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

    # ---------------------------------------------------------------- changes

    def delete_generation(self, generation_id: int) -> List[str]:
        """
        Remove a generation's rows from every table, and its link to the
        queue's task that made it, if one did.

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
        cursor.execute("DELETE FROM generation_resources WHERE generation_id = ?", (generation_id,))
        cursor.execute("DELETE FROM image_details WHERE image_id IN "
                       "(SELECT id FROM generation_images WHERE generation_id = ?)", (generation_id,))
        cursor.execute("DELETE FROM generation_images WHERE generation_id = ?", (generation_id,))
        cursor.execute("DELETE FROM generation_details WHERE generation_id = ?", (generation_id,))
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
            cursor.execute("DELETE FROM generation_resources WHERE image_id = ?", (image_id,))
            cursor.execute("DELETE FROM image_details WHERE image_id = ?", (image_id,))
            cursor.execute("DELETE FROM generation_images WHERE id = ?", (image_id,))
            cursor.execute("SELECT COUNT(*) FROM generation_images WHERE generation_id = ?",
                           (generation_id,))
            left = cursor.fetchone()[0]
            gone = None
            if left:
                cursor.execute("UPDATE generations SET image_count = ? WHERE id = ?",
                               (left, generation_id))
            else:
                cursor.execute("DELETE FROM generation_details WHERE generation_id = ?", (generation_id,))
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
            cursor.execute("SELECT gi.id, d.meta, gi.prompt_nsfw_level FROM generation_images gi "
                           "LEFT JOIN image_details d ON d.image_id = gi.id")
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
