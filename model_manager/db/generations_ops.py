"""
Internal module for the images you generate, in the tables of schema v37 (#231),
named for them since v41 (#284):

- generations and generation_images: what lists, groups and filters read,
  narrow, so a scan of tens of thousands of images reads few pages - a wide
  row costs its whole page whatever column is read;
- generation_details and generation_image_details: one row each, what one Send or one
  tile reads, with the lists and paths exactly as Forge recorded them;
- generation_prompts: each text once. `grouped_as` is the row holding the text with its
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
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from ..console import say_failure
from ..gallery import switch_counts_sql
from ..nsfw import SFW_MAX
from ..prompt_rules import MIN_PROMPT_LENGTH
from .library import LIBRARY
from .prompt_table import PromptTable, like_pattern, tidy  # noqa: F401 - tidy is read from here

# A generation's columns as the recorder hands them, by the table keeping them.
_GENERATION_COLUMNS = ("created_at", "mode", "forge", "image_count", "prompt_nsfw_level",
                       "user_nsfw_level", "source_id")
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
# Your generations' prompts: every column naming a row, each indexed (v40).
PROMPTS = PromptTable("generation_prompts", (("generations", "prompt_id"), ("generations", "negative_id"),
                                             ("generation_images", "prompt_id"),
                                             ("generation_images", "negative_id")))
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
    elif generation.get("checkpoint_name"):
        # An image synced from a folder names a checkpoint the library does
        # not hold (#233): the name is kept, for grouping by model, and no path.
        entries.append(["checkpoint", 0, None, {"name": generation["checkpoint_name"]}])
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
        elif path is None:
            rows.append((role, position, str(lora["name"]), None, None))
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
    opened - each (grouping, group id) - the search's words, the Queue's
    task, and the images, Civitai versions and models a search names (#336),
    an empty list naming none.
    """
    files: Optional[List[str]] = None
    generation: Optional[int] = None
    generations: Optional[List[int]] = None
    opened: List[Tuple[str, str]] = field(default_factory=list)
    words: List[str] = field(default_factory=list)
    task: Optional[int] = None
    images: List[int] = field(default_factory=list)
    versions: List[int] = field(default_factory=list)
    models: List[int] = field(default_factory=list)
    # generation: in a search (#241), apart from `generations`: one JSON
    # value, as a list a person names can pass the older SQLite's 999.
    named_generations: List[int] = field(default_factory=list)


def _unit_columns(unit: str, section: Optional[str]) -> List[str]:
    """The columns of `shown` naming a unit: its section's key, then its own."""
    own = {"image": "id", "generation": "generation_id"}.get(unit, f"k_{unit}")
    return ([f"k_{section}"] if section else []) + [own]


def _units_sql(source: str, names: Sequence[str], section: bool) -> str:
    """
    Single pass's units of a level, from `source`'s images, as scope_units()
    gives them, in the tab's order, ending in `LIMIT ? OFFSET ?`: `names` the
    columns naming a unit, its section's first. Its own copy of Classic's
    SQL, which stays as it was while Single pass is new: a fault here must
    leave Classic a way out. tile_reading_test holds the two to one answer.
    """
    def shared(column):
        return (f"CASE WHEN COUNT(DISTINCT {column}) = 1 AND SUM({column} IS NULL) = 0 "
                f"THEN MIN({column}) END")

    sectioned = (", MAX(first_key) OVER (PARTITION BY s) AS section_first, "
                 "SUM(n) OVER (PARTITION BY s) AS section_count, "
                 "COUNT(*) OVER (PARTITION BY s) AS section_groups") if section else ""
    return f"""units AS (
            SELECT {(names[0] + ' AS s, ') if section else ''}{names[-1]} AS u, MAX(sk) AS first_key,
                   COUNT(*) AS n, COUNT(DISTINCT generation_id) AS generations,
                   MAX(created_at) AS latest, {shared('level')} AS level,
                   {shared('user_level')} AS user_level
            FROM {source} GROUP BY {', '.join(names)})
        SELECT *{sectioned} FROM units
        ORDER BY {'section_first DESC, ' if section else ''}first_key DESC LIMIT ? OFFSET ?"""



def _shared_checkpoints_sql(source: str, on: str, cols: Sequence[str]) -> str:
    """
    Single pass's copy of scope_unit_checkpoints(), after a WITH that has
    `part`: each unit's checkpoint, if every image of it used one, where it is
    now - else NULL - from `source`'s images joined to the part `on` the
    unit's columns `cols`.
    """
    return f"""batch_unit AS (SELECT DISTINCT {', '.join('part.' + c + ' AS ' + c for c in cols)},
                              {source}.generation_id AS g
                       FROM {source} JOIN part ON {on}),
        batch_ck AS (SELECT r.generation_id AS g, MIN(r.file_path) AS path
                     FROM generation_resources r
                     WHERE r.role = 'checkpoint' AND r.generation_id IN (SELECT g FROM batch_unit)
                     GROUP BY r.generation_id)
        SELECT {', '.join('batch_unit.' + c for c in cols)},
               CASE WHEN COUNT(DISTINCT batch_ck.path) = 1 AND SUM(batch_ck.path IS NULL) = 0
                    THEN MIN(batch_ck.path) END
        FROM batch_unit LEFT JOIN batch_ck ON batch_ck.g = batch_unit.g
        GROUP BY {', '.join('batch_unit.' + c for c in cols)}"""


def _unit_loras_sql(source: str, on: str, cols: Sequence[str]) -> str:
    """
    Single pass's copy of scope_unit_loras(), after a WITH that has `part`:
    every LoRA file each unit used, where it is now, once each - the units'
    columns first, newest use first - from `source`'s images joined to the
    part `on` the unit's columns `cols`.
    """
    return f"""SELECT {', '.join('part.' + c for c in cols)}, r.file_path,
               MAX({source}.sk || char(1) || printf('%06d', 999999 - r.position)) AS first_seen
        FROM {source} JOIN part ON {on}
        JOIN generation_resources r ON r.image_id = {source}.id AND r.role = 'lora'
             AND r.file_path IS NOT NULL
        GROUP BY {', '.join('part.' + c for c in cols)}, r.file_path
        ORDER BY {', '.join('part.' + c for c in cols)}, first_seen DESC"""


# Single pass's table of a level's images (scope_level): a temporary table,
# this connection's alone.
_LEVEL_TABLE = "mm_level"


class _ClassicLevel:
    """A level as Classic reads it: each read finds the level's images again."""

    def __init__(self, ops: "GenerationsOps", scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool):
        self._ops = ops
        self._level = (scope, unit, section, hide_nsfw)

    def units(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        return self._ops.scope_units(*self._level, offset, limit)

    def previews(self, part: Sequence[Tuple[Any, ...]], count: int) -> List[Dict[str, Any]]:
        return self._ops.scope_previews(*self._level, part, count)

    def unit_checkpoints(self, part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], Optional[str]]:
        return self._ops.scope_unit_checkpoints(*self._level, part)

    def unit_loras(self, part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], List[str]]:
        return self._ops.scope_unit_loras(*self._level, part)


class _TableLevel:
    """
    A level as Single pass reads it: from its table, which names a unit by
    `cols` - (s, u), or (u) - indexed on them and the tab's order (scope_level).
    Each read answers as Classic's does.
    """

    def __init__(self, cursor, cols: List[str]):
        self._cursor = cursor
        self._cols = cols

    def _part(self, part: Sequence[Tuple[Any, ...]]) -> Tuple[str, List[Any]]:
        values = ", ".join("(" + ", ".join("?" * len(self._cols)) + ")" for _ in part)
        return (f"WITH part({', '.join(self._cols)}) AS (VALUES {values})",
                [value for key in part for value in key])

    def _on(self, table: str) -> str:
        return " AND ".join(f"part.{c} = {table}.{c}" for c in self._cols)

    def units(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        self._cursor.execute(f"WITH {_units_sql(_LEVEL_TABLE, self._cols, len(self._cols) == 2)}",
                             [int(limit), int(offset)])
        return [dict(r) for r in self._cursor.fetchall()]

    def previews(self, part: Sequence[Tuple[Any, ...]], count: int) -> List[Dict[str, Any]]:
        """Each unit's newest `count` images: the place of its count-th newest,
        found through the index, and its images from there up. Numbering every
        image of the part's units, as Classic does, took up to 635 ms."""
        if not part or count < 1:
            return []
        with_part, args = self._part(part)
        self._cursor.execute(f"""{with_part}
            SELECT lv.*, {_CHECKPOINT.format(generation='lv.generation_id')} AS checkpoint_path
            FROM part JOIN {_LEVEL_TABLE} lv ON {self._on('lv')} AND lv.sk >= COALESCE(
                (SELECT x.sk FROM {_LEVEL_TABLE} x WHERE {self._on('x')}
                 ORDER BY x.sk DESC LIMIT 1 OFFSET ?), '')
            ORDER BY lv.sk DESC""", args + [int(count) - 1])
        return [dict(r) for r in self._cursor.fetchall()]

    def unit_checkpoints(self, part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], Optional[str]]:
        if not part:
            return {}
        with_part, args = self._part(part)
        found: Dict[Tuple[Any, ...], Optional[str]] = {tuple(key): None for key in part}
        self._cursor.execute(f"{with_part}, {_shared_checkpoints_sql(_LEVEL_TABLE, self._on(_LEVEL_TABLE), self._cols)}",
                             args)
        for row in self._cursor.fetchall():
            found[tuple(row[:len(self._cols)])] = row[len(self._cols)]
        return found

    def unit_loras(self, part: Sequence[Tuple[Any, ...]]) -> Dict[Tuple[Any, ...], List[str]]:
        if not part:
            return {}
        with_part, args = self._part(part)
        found: Dict[Tuple[Any, ...], List[str]] = {tuple(key): [] for key in part}
        self._cursor.execute(f"{with_part} {_unit_loras_sql(_LEVEL_TABLE, self._on(_LEVEL_TABLE), self._cols)}",
                             args)
        for row in self._cursor.fetchall():
            found.setdefault(tuple(row[:len(self._cols)]), []).append(row[len(self._cols)])
        return found


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
        """The generation_prompts row holding this text, made if there is none (PromptTable.id_for)."""
        return PROMPTS.id_for(cursor, text)

    def record_generation(self, generation: Dict[str, Any],
                          images: List[Dict[str, Any]],
                          files: List[List[str]],
                          input_files: Optional[Dict[str, str]] = None) -> int:
        """
        Store one generation and its images, in one transaction.

        Args:
            generation: The generation, by its columns as recorded - the
                prompts and the details' columns among them.
            images: Each result, by its columns, the same way.
            files: For each image, in the same order, the model files it
                used, as the library spells them.
            input_files: The files kept of the images its press started
                from (#34), by Forge's input name.

        Returns:
            The generation's id.
        """
        with self._cursor() as cursor:
            self._write_lock(cursor)
            generation_id = self._record(cursor, generation, images, files)
            cursor.executemany("INSERT INTO generation_input_files (generation_id, name, path) VALUES (?, ?, ?)",
                               [(generation_id, name, path) for name, path in (input_files or {}).items()])
            return generation_id

    def record_generations(self, generations: Sequence[Tuple[Dict[str, Any], List[Dict[str, Any]],
                                                            List[List[str]]]]) -> List[int]:
        """Several generations, each as record_generation() takes one, in one
        transaction: a sync writes hundreds at a time (#233)."""
        with self._cursor() as cursor:
            self._write_lock(cursor)
            return [self._record(cursor, *generation) for generation in generations]

    def _write_lock(self, cursor) -> None:
        """
        Hold the write lock from here to the commit. Python's sqlite3 begins a
        transaction at its first write, so a prompt looked up before it could
        be deleted by another writer - this WebUI's Delete, or the other WebUI
        on a shared database - before the row naming it is written (#248).
        """
        if not cursor.connection.in_transaction:
            cursor.execute("BEGIN IMMEDIATE")

    def _record(self, cursor, generation: Dict[str, Any], images: List[Dict[str, Any]],
                files: List[List[str]]) -> int:
        """record_generation() inside a caller's transaction."""
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
                f"INSERT INTO generation_image_details (image_id{''.join(', ' + c for c in details)}) "
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
            LEFT JOIN generation_prompts p ON p.id = g.prompt_id
            LEFT JOIN generation_prompts q ON q.id = g.negative_id
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
            LEFT JOIN generation_image_details d ON d.image_id = gi.id
            LEFT JOIN generation_prompts p ON p.id = gi.prompt_id
            LEFT JOIN generation_prompts q ON q.id = gi.negative_id
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
        # Each image's thumbnail as made (#5), by its path: None without one.
        made = self._thumbnails(cursor, [i.get("path") for i in images.values()])
        for image in images.values():
            image["thumbnail"] = made.get((image.get("path") or "").lower())
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
                LEFT JOIN generation_prompts p ON p.id = g.prompt_id
                LEFT JOIN generation_prompts q ON q.id = g.negative_id
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
            joins.append("LEFT JOIN generation_prompts ip INDEXED BY idx_generation_prompts_lookup ON ip.id = gi.prompt_id")
        if "prompt_written" in keys:
            joins.append("LEFT JOIN generation_prompts wp INDEXED BY idx_generation_prompts_lookup ON wp.id = g.prompt_id")
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
        # A list is one JSON value: the older SQLite takes 999 values a statement (#336).
        if scope.images:
            where.append("gi.id IN (SELECT value FROM json_each(?))")
            args_where.append(json.dumps(scope.images))
        if scope.named_generations:
            where.append("gi.generation_id IN (SELECT value FROM json_each(?))")
            args_where.append(json.dumps(scope.named_generations))
        # Any resource the image used whose library file is of one of the
        # versions - or of the models: `generation_resources` holds the
        # library's spelling of a path, as `scope.files` reads it.
        if scope.versions:
            where.append("gi.id IN (SELECT image_id FROM generation_resources WHERE file_path IN "
                         "(SELECT file_path FROM files WHERE version_id IN (SELECT value FROM json_each(?))))")
            args_where.append(json.dumps(scope.versions))
        if scope.models:
            where.append("gi.id IN (SELECT image_id FROM generation_resources WHERE file_path IN "
                         "(SELECT file_path FROM files WHERE version_id IN "
                         "(SELECT id FROM versions WHERE model_id IN (SELECT value FROM json_each(?)))))")
            args_where.append(json.dumps(scope.models))
        for index, word in enumerate(scope.words):
            # A word is matched as typed, ignoring case: % and _ mean themselves.
            ctes.append(PROMPTS.match(f"hit{index}"))
            args.append(like_pattern(word))
            where.append(f"(gi.prompt_id IN hit{index} OR gi.negative_id IN hit{index} "
                         f"OR g.prompt_id IN hit{index} OR g.negative_id IN hit{index})")
        for grouping, opened in scope.opened:
            key = group_key(grouping, opened)
            if key is None:
                where.append("0")
            elif grouping in PROMPT_GROUPINGS:
                column = "gi.prompt_id" if grouping == "prompt" else "g.prompt_id"
                where.append(f"({column} IN (SELECT id FROM generation_prompts WHERE grouped_as = ?)"
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
        they share one, where it is now; None if they do not.

        An image's checkpoint is its batch's, so each unit's batches are listed
        once and each batch's looked up once (#238). Looked up for every image,
        a subquery per row, it was 1.7 s of a 2.8 s request grouped by base
        model: 75,684 lookups for 7,762 batches. The names are this query's
        own - grouped by model, `shown` already has a `ck`."""
        if not part:
            return {}
        sql, args, names = self._part_sql(scope, unit, section, hide_nsfw, part)
        cols = ["s", "u"][-len(names):]
        on = " AND ".join(f"part.{p} = shown.{n}" for p, n in zip(cols, names))
        found: Dict[Tuple[Any, ...], Optional[str]] = {tuple(key): None for key in part}
        with self._cursor() as cursor:
            cursor.execute(f"""{sql},
                batch_unit AS (SELECT DISTINCT {', '.join('part.' + c + ' AS ' + c for c in cols)},
                                      shown.generation_id AS g
                               FROM shown JOIN part ON {on}),
                batch_ck AS (SELECT r.generation_id AS g, MIN(r.file_path) AS path
                             FROM generation_resources r
                             WHERE r.role = 'checkpoint' AND r.generation_id IN (SELECT g FROM batch_unit)
                             GROUP BY r.generation_id)
                SELECT {', '.join('batch_unit.' + c for c in cols)},
                       CASE WHEN COUNT(DISTINCT batch_ck.path) = 1 AND SUM(batch_ck.path IS NULL) = 0
                            THEN MIN(batch_ck.path) END
                FROM batch_unit LEFT JOIN batch_ck ON batch_ck.g = batch_unit.g
                GROUP BY {', '.join('batch_unit.' + c for c in cols)}""", args)
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

    @contextmanager
    def scope_level(self, scope: Scope, unit: str, section: Optional[str], hide_nsfw: bool,
                    single_pass: bool = True) -> Iterator[Any]:
        """
        A level of the Generations tab, to pick a part of and read its tiles
        from: `units(offset, limit)`, then for the part `previews(part,
        count)`, `unit_checkpoints(part)` and `unit_loras(part)`, each
        answering as scope_units() and the three part reads do.

        Single pass (#238, #259) reads the level's images once, into a
        temporary table in memory indexed by unit and the tab's order, and
        reads every tile through it. Classic finds them again for each read -
        four passes over the level - and grouped by base model SQLite joined
        them to the part in an order that looked each image's checkpoint and
        base model up once per group: 1.46 s at 75,682 images in 14 groups,
        0.27 s in one pass. The table is this connection's alone, so two
        requests at once have one each. It is dropped on the way out, and a
        table a failed drop left is dropped first.
        """
        if not single_pass:
            yield _ClassicLevel(self, scope, unit, section, hide_nsfw)
            return
        keys = [k for k in (unit, section) if k and k in GROUP_KEYS]
        sql, args = self._rows_sql(scope, keys, hide_nsfw)
        names = _unit_columns(unit, section)
        cols = ["s", "u"][-len(names):]
        with self._cursor() as cursor:
            # SQLite keeps 2 MB of temporary data in memory and writes the rest
            # to a file in the system's temp folder: the table is about 10 MB at
            # 75,682 images, and every level read 20 to 30% faster in memory.
            cursor.execute("PRAGMA temp_store = MEMORY")
            try:
                cursor.execute(f"DROP TABLE IF EXISTS temp.{_LEVEL_TABLE}")
                cursor.execute(f"CREATE TEMP TABLE {_LEVEL_TABLE} AS {sql} SELECT id, generation_id, sk, "
                               f"created_at, level, user_level, "
                               f"{', '.join(f'{n} AS {c}' for n, c in zip(names, cols))} FROM shown", args)
                cursor.execute(f"CREATE INDEX temp.{_LEVEL_TABLE}_unit ON {_LEVEL_TABLE} ({', '.join(cols)}, sk)")
                yield _TableLevel(cursor, cols)
            finally:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS temp.{_LEVEL_TABLE}")
                    # Back to SQLite's own, so a Classic request on this thread
                    # reads as it always has. A change of it also deletes every
                    # temporary table: a second way the table goes.
                    cursor.execute("PRAGMA temp_store = DEFAULT")
                except sqlite3.Error:
                    say_failure("Generations: a level's table was not dropped; the next request drops it")

    def prompt_texts(self, prompt_ids: Iterable[int]) -> Dict[int, str]:
        """These prompts' texts, by id."""
        ids = sorted({int(i) for i in prompt_ids if i})
        if not ids:
            return {}
        with self._cursor() as cursor:
            return PROMPTS.texts(cursor, ids)

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
            freed: set = set()
            own = self.remove(cursor, generation_id, freed)
            self.drop_unused_prompts(cursor, freed)
            return own

    def remove(self, cursor, generation_id: int, freed: set) -> List[str]:
        """delete_generation() inside a caller's transaction: a task deleted
        with its data takes its generations with it, in one (#162). The
        prompts its rows named are added to `freed`, for the caller to drop
        those left unnamed once its deletes are done (drop_unused_prompts)."""
        cursor.execute("SELECT prompt_id, negative_id FROM generations WHERE id = ? UNION "
                       "SELECT prompt_id, negative_id FROM generation_images WHERE generation_id = ?",
                       (generation_id, generation_id))
        freed.update(p for row in cursor.fetchall() for p in row if p)
        cursor.execute("SELECT path FROM generation_images WHERE generation_id = ?",
                       (generation_id,))
        paths = [r[0] for r in cursor.fetchall()]
        # By image, which their key starts with: by the generation's number
        # read every resource row of the library, 538 ms at 76,000 images.
        cursor.execute("DELETE FROM generation_resources WHERE image_id IN "
                       "(SELECT id FROM generation_images WHERE generation_id = ?)", (generation_id,))
        cursor.execute("DELETE FROM generation_image_details WHERE image_id IN "
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
            freed: set = set()
            gone = self._delete_image(cursor, image_id, freed)
            self.drop_unused_prompts(cursor, freed)
            return gone

    def _delete_image(self, cursor, image_id: int, freed: set) -> Tuple[List[str], Optional[int]]:
        """delete_image() inside a caller's transaction; the prompts its rows
        named go into `freed`, as remove() says."""
        cursor.execute("SELECT generation_id, path, prompt_id, negative_id FROM generation_images WHERE id = ?",
                       (image_id,))
        row = cursor.fetchone()
        if not row:
            return [], None
        generation_id, path = row[0], row[1]
        freed.update(p for p in (row[2], row[3]) if p)
        cursor.execute("DELETE FROM generation_resources WHERE image_id = ?", (image_id,))
        cursor.execute("DELETE FROM generation_image_details WHERE image_id = ?", (image_id,))
        cursor.execute("DELETE FROM generation_images WHERE id = ?", (image_id,))
        cursor.execute("SELECT COUNT(*) FROM generation_images WHERE generation_id = ?",
                       (generation_id,))
        left = cursor.fetchone()[0]
        gone = None
        if left:
            cursor.execute("UPDATE generations SET image_count = ? WHERE id = ?",
                           (left, generation_id))
        else:
            cursor.execute("SELECT prompt_id, negative_id FROM generations WHERE id = ?", (generation_id,))
            freed.update(p for row in cursor.fetchall() for p in row if p)
            cursor.execute("DELETE FROM generation_details WHERE generation_id = ?", (generation_id,))
            cursor.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
            cursor.execute("DELETE FROM task_generations WHERE generation_id = ?", (generation_id,))
            gone = generation_id
        cursor.execute("SELECT 1 FROM generation_images WHERE path = ? COLLATE NOCASE LIMIT 1",
                       (path,))
        return ([] if cursor.fetchone() or not path else [path]), gone

    # ------------------------------------------------- synced from folders

    def held_paths(self) -> set:
        """Every path an image of yours is kept at, lower case: what a sync
        does not bring in again (#233)."""
        with self._cursor() as cursor:
            cursor.execute("SELECT path FROM generation_images")
            return {row[0].lower() for row in cursor.fetchall() if row[0]}

    def synced_paths(self) -> set:
        """Every path a synced image is kept at, lower case: what a Force sync
        reads again."""
        with self._cursor() as cursor:
            cursor.execute("SELECT gi.path FROM generation_images gi JOIN generations g "
                           "ON g.id = gi.generation_id WHERE g.source_id IS NOT NULL")
            return {row[0].lower() for row in cursor.fetchall() if row[0]}

    def kept_paths(self) -> List[str]:
        """Every path an image of yours is kept at, and every path on the
        removed list, as stored: what a path a sync finds is compared with,
        for one file reached by another route (#348)."""
        with self._cursor() as cursor:
            cursor.execute("SELECT path FROM generation_images UNION SELECT path FROM generation_images_removed")
            return [row[0] for row in cursor.fetchall() if row[0]]

    def image_paths(self) -> List[Tuple[int, str, bool]]:
        """Every image's (id, path, whether a sync wrote it), oldest first."""
        with self._cursor() as cursor:
            cursor.execute("SELECT gi.id, gi.path, g.source_id IS NOT NULL FROM generation_images gi "
                           "JOIN generations g ON g.id = gi.generation_id ORDER BY gi.id")
            return [(row[0], row[1], bool(row[2])) for row in cursor.fetchall() if row[1]]

    def drop_synced_copies(self, copies: Sequence[Tuple[int, int]]) -> List[str]:
        """
        Remove these synced images, each another image's file by another path
        - a loop's, a second folder's (#348) - and a generation with its last
        image, in one transaction. Each is (the copy's id, the id of the image
        kept), and the image kept takes the copy's rating when it has none:
        the one thing a person sets on an image. A recorded image is never
        removed.

        Returns:
            The paths no row names any more, whose thumbnails can go.
        """
        with self._cursor() as cursor:
            self._write_lock(cursor)
            freed: set = set()
            paths: List[str] = []
            for copy, kept in copies:
                cursor.execute("SELECT gi.user_nsfw_level FROM generation_images gi "
                               "JOIN generations g ON g.id = gi.generation_id "
                               "WHERE gi.id = ? AND g.source_id IS NOT NULL", (copy,))
                row = cursor.fetchone()
                if not row:
                    continue
                if row[0] is not None:
                    cursor.execute("UPDATE generation_images SET user_nsfw_level = ? "
                                   "WHERE id = ? AND user_nsfw_level IS NULL", (row[0], kept))
                paths += self._delete_image(cursor, copy, freed)[0]
            self.drop_unused_prompts(cursor, freed)
            return paths

    def replace_synced(self, generations: Sequence[Tuple[Dict[str, Any], List[Dict[str, Any]],
                                                        List[List[str]]]]) -> List[int]:
        """
        record_generations() for a Force sync (#233): the synced rows of these
        files go, and the generations are written anew, in one transaction -
        a cancel or a crash leaves either the old rows or the new. What the
        person added is carried over by path: an image's rating, and the level
        a sync's dialog gave an image without infotext. A recorded image's
        rows are never touched.
        """
        paths = list({image["path"].lower(): image["path"] for _, images, _ in generations for image in images}.values())
        with self._cursor() as cursor:
            self._write_lock(cursor)
            freed: set = set()
            rated: Dict[str, int] = {}
            bare: Dict[str, int] = {}
            old: List[int] = []
            for start in range(0, len(paths), 500):
                part = paths[start:start + 500]
                cursor.execute(
                    "SELECT gi.id, gi.path, gi.user_nsfw_level, gi.prompt_nsfw_level, d.infotext IS NULL "
                    "FROM generation_images gi JOIN generations g ON g.id = gi.generation_id "
                    "LEFT JOIN generation_image_details d ON d.image_id = gi.id "
                    f"WHERE g.source_id IS NOT NULL AND gi.path COLLATE NOCASE IN ({', '.join('?' * len(part))})", part)
                for image_id, path, user_level, prompt_level, no_text in cursor.fetchall():
                    old.append(image_id)
                    if user_level is not None:
                        rated[path.lower()] = user_level
                    if no_text and prompt_level is not None:
                        bare[path.lower()] = prompt_level
            for image_id in old:
                self._delete_image(cursor, image_id, freed)
            written = []
            for generation, images, files in generations:
                for image in images:
                    if image.get("infotext") is None and image["path"].lower() in bare:
                        image["prompt_nsfw_level"] = bare[image["path"].lower()]
                if images:
                    generation["prompt_nsfw_level"] = max(image["prompt_nsfw_level"] for image in images)
                generation_id = self._record(cursor, generation, images, files)
                written.append(generation_id)
                cursor.executemany("UPDATE generation_images SET user_nsfw_level = ? "
                                   "WHERE generation_id = ? AND path = ?",
                                   [(rated[image["path"].lower()], generation_id, image["path"])
                                    for image in images if image["path"].lower() in rated])
            # After the new rows: a prompt they name again keeps its number.
            self.drop_unused_prompts(cursor, freed)
            return written

    def source_id(self, folder: str) -> int:
        """The number a synced folder is known by, made the first time."""
        with self._cursor() as cursor:
            cursor.execute("INSERT OR IGNORE INTO generation_sources (path) VALUES (?)", (folder,))
            cursor.execute("SELECT id FROM generation_sources WHERE path = ? COLLATE NOCASE", (folder,))
            return cursor.fetchone()[0]

    def synced_counts(self) -> Dict[str, int]:
        """How many generations each synced folder brought, by its path in
        lower case."""
        with self._cursor() as cursor:
            cursor.execute("SELECT s.path, COUNT(g.id) FROM generation_sources s "
                           "JOIN generations g ON g.source_id = s.id GROUP BY s.id")
            return {row[0].lower(): row[1] for row in cursor.fetchall()}

    def delete_synced_from(self, folder: str) -> Tuple[int, List[str]]:
        """
        Remove every generation a folder's syncs brought, and the folder's
        number - Remove folder (#233). Files are not touched, and nothing goes
        on the removed list: the folder is no longer synced.

        Returns:
            How many generations were removed, and the paths of their images
            no other record names - whose thumbnails can go (#5).
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT id FROM generation_sources WHERE path = ? COLLATE NOCASE", (folder,))
            row = cursor.fetchone()
            if not row:
                return 0, []
            source = row[0]
            images = ("SELECT gi.id FROM generation_images gi JOIN generations g ON g.id = gi.generation_id "
                      "WHERE g.source_id = ?")
            cursor.execute(f"DELETE FROM generation_resources WHERE image_id IN ({images})", (source,))
            cursor.execute(f"DELETE FROM generation_image_details WHERE image_id IN ({images})", (source,))
            made = "SELECT id FROM generations WHERE source_id = ?"
            cursor.execute(f"SELECT prompt_id, negative_id FROM generation_images WHERE generation_id IN ({made}) "
                           "UNION SELECT prompt_id, negative_id FROM generations WHERE source_id = ?", (source, source))
            freed = {p for row in cursor.fetchall() for p in row if p}
            cursor.execute(f"SELECT DISTINCT path FROM generation_images WHERE generation_id IN ({made})",
                           (source,))
            paths = [row[0] for row in cursor.fetchall() if row[0]]
            cursor.execute(f"DELETE FROM generation_images WHERE generation_id IN ({made})", (source,))
            cursor.execute(f"DELETE FROM generation_details WHERE generation_id IN ({made})", (source,))
            cursor.execute(f"DELETE FROM task_generations WHERE generation_id IN ({made})", (source,))
            cursor.execute("DELETE FROM generations WHERE source_id = ?", (source,))
            removed = cursor.rowcount
            cursor.execute("DELETE FROM generation_sources WHERE id = ?", (source,))
            self.drop_unused_prompts(cursor, freed)
            return removed, self._unnamed(cursor, paths)

    def removed_images(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """The removed list: each file whose row was deleted with the file
        kept, lower case -> (size, modified time in ns) as it was then."""
        with self._cursor() as cursor:
            cursor.execute("SELECT path, size, mtime_ns FROM generation_images_removed")
            return {row[0].lower(): (row[1], row[2]) for row in cursor.fetchall()}

    def remember_removed(self, entries: Iterable[Tuple[str, int, int]]) -> None:
        """Put files on the removed list, each (path, size, modified time in ns)."""
        with self._cursor() as cursor:
            cursor.executemany("INSERT OR REPLACE INTO generation_images_removed (path, size, mtime_ns) "
                               "VALUES (?, ?, ?)", list(entries))

    def forget_removed(self, paths: Iterable[str]) -> None:
        """Take files off the removed list: they are gone from disk."""
        with self._cursor() as cursor:
            cursor.executemany("DELETE FROM generation_images_removed WHERE path = ? COLLATE NOCASE",
                               [(p,) for p in paths])

    def drop_unused_prompts(self, cursor, ids: Iterable[Optional[int]]) -> int:
        """
        Of these prompts, delete those nothing names any more - no
        generation's or image's prompt or negative prompt, no other prompt as
        its head - then the heads they named, the same way: a prompt row lives
        as long as something uses it (#248). Run by every delete, inside its
        transaction, once its rows are gone. Each look is one index's (v40),
        so it costs the same in any library.

        Returns:
            How many prompt rows went.
        """
        return PROMPTS.drop_unused(cursor, ids)

    def input_files(self, generation_id: int) -> Dict[str, str]:
        """The files kept of the images a generation's press started from
        (#34), by Forge's input name."""
        with self._cursor() as cursor:
            cursor.execute("SELECT name, path FROM generation_input_files WHERE generation_id = ?",
                           (generation_id,))
            return {name: path for name, path in cursor.fetchall()}

    def input_files_of(self, generation_ids: Iterable[int]) -> Dict[int, Dict[str, str]]:
        """The kept files of each of these generations that kept any (#34):
        {generation id: {input name: path}}, for a page of images at once."""
        ids = list(dict.fromkeys(int(i) for i in generation_ids))
        found: Dict[int, Dict[str, str]] = {}
        with self._cursor() as cursor:
            for start in range(0, len(ids), 500):
                part = ids[start:start + 500]
                cursor.execute("SELECT generation_id, name, path FROM generation_input_files "
                               f"WHERE generation_id IN ({', '.join('?' * len(part))})", part)
                for generation_id, name, path in cursor.fetchall():
                    found.setdefault(generation_id, {})[name] = path
        return found

    def drop_orphan_input_files(self) -> List[str]:
        """
        Remove the kept-file rows of generations that are gone - their ids
        are never reused - whichever delete took them (#34).

        Returns:
            The files those rows named that no row names any more, for the
            caller to delete.
        """
        with self._cursor() as cursor:
            self._write_lock(cursor)
            cursor.execute("SELECT DISTINCT path FROM generation_input_files WHERE generation_id NOT IN "
                           "(SELECT id FROM generations)")
            paths = [row[0] for row in cursor.fetchall()]
            if not paths:
                return []
            cursor.execute("DELETE FROM generation_input_files WHERE generation_id NOT IN "
                           "(SELECT id FROM generations)")
            free = []
            for path in paths:
                cursor.execute("SELECT 1 FROM generation_input_files WHERE path = ? COLLATE NOCASE LIMIT 1",
                               (path,))
                if not cursor.fetchone():
                    free.append(path)
            return free

    @staticmethod
    def _unnamed(cursor, paths: Iterable[str]) -> List[str]:
        """Of these paths, the ones no image's row names any more."""
        free = []
        for path in dict.fromkeys(p for p in paths if p):
            cursor.execute("SELECT 1 FROM generation_images WHERE path = ? COLLATE NOCASE LIMIT 1", (path,))
            if not cursor.fetchone():
                free.append(path)
        return free

    # ------------------------------------------------------------ thumbnails

    @staticmethod
    def _thumbnails(cursor, paths: Iterable[Optional[str]]) -> Dict[str, Dict[str, Any]]:
        """Each of these images' thumbnail rows (#5), by its path in lower case:
        {thumbnail, size, mtime_ns}. A thumbnail of None: the image needs none."""
        paths = list(dict.fromkeys(p for p in paths if p))
        found: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(paths), 500):
            part = paths[start:start + 500]
            cursor.execute("SELECT path, thumbnail, size, mtime_ns FROM generation_thumbnails "
                           f"WHERE path IN ({', '.join('?' * len(part))})", part)
            for path, thumbnail, size, mtime_ns in cursor.fetchall():
                found[path.lower()] = {"thumbnail": thumbnail, "size": size, "mtime_ns": mtime_ns}
        return found

    def thumbnail_rows(self, paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """These images' thumbnail rows, by path in lower case; see _thumbnails()."""
        with self._cursor() as cursor:
            return self._thumbnails(cursor, paths)

    def thumbnail_candidates(self) -> List[Tuple[str, Optional[str], Optional[int], Optional[int]]]:
        """
        Every image path the library holds, once, with its thumbnail's row if
        it has one: (path, thumbnail, size, mtime_ns) - what a sync with
        "Make thumbnails" goes through (#5).
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT MIN(gi.path), t.thumbnail, t.size, t.mtime_ns FROM generation_images gi "
                           "LEFT JOIN generation_thumbnails t ON t.path = gi.path "
                           "WHERE gi.path IS NOT NULL AND gi.path <> '' GROUP BY gi.path COLLATE NOCASE")
            return [tuple(row) for row in cursor.fetchall()]

    def record_thumbnails(self, entries: Iterable[Tuple[str, Optional[str], int, int]]) -> None:
        """Keep each image's thumbnail as made: (path, thumbnail or None, the
        image's size, its modified time in ns), replacing the one before."""
        with self._cursor() as cursor:
            cursor.executemany("INSERT OR REPLACE INTO generation_thumbnails (path, thumbnail, size, mtime_ns) "
                               "VALUES (?, ?, ?, ?)", list(entries))

    def forget_thumbnails(self, paths: Iterable[str]) -> List[str]:
        """
        Remove these images' thumbnail rows.

        Returns:
            The thumbnail files they named, for the caller to delete.
        """
        paths = [p for p in paths if p]
        files = []
        with self._cursor() as cursor:
            for start in range(0, len(paths), 500):
                part = paths[start:start + 500]
                marks = ", ".join("?" * len(part))
                cursor.execute(f"SELECT thumbnail FROM generation_thumbnails WHERE path IN ({marks})", part)
                files += [row[0] for row in cursor.fetchall() if row[0]]
                cursor.execute(f"DELETE FROM generation_thumbnails WHERE path IN ({marks})", part)
        return files

    def unheld_checkpoint(self, generation_id: int) -> Optional[str]:
        """The checkpoint a generation names by name alone - one Sync images
        found in the text and the library lacks - or None."""
        with self._cursor() as cursor:
            cursor.execute("SELECT MIN(name) FROM generation_resources WHERE generation_id = ? "
                           "AND role = 'checkpoint' AND file_path IS NULL AND name <> ''", (generation_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def replace_imported(self, paths: Iterable[str]) -> int:
        """
        Remove the rows a sync wrote for these files, ahead of the recorder
        writing its own: the full record wins (#233). A recorded image's rows
        are left alone.

        Returns:
            How many images were removed.
        """
        paths = [p for p in paths if p]
        if not paths:
            return 0
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT gi.id FROM generation_images gi JOIN generations g ON g.id = gi.generation_id "
                f"WHERE g.source_id IS NOT NULL AND gi.path COLLATE NOCASE IN ({', '.join('?' * len(paths))})",
                paths)
            ids = [row[0] for row in cursor.fetchall()]
            freed: set = set()
            for image_id in ids:
                self._delete_image(cursor, image_id, freed)
            self.drop_unused_prompts(cursor, freed)
            return len(ids)

    def restamp_levels(self, level: Callable[[Optional[Dict[str, Any]]], int]) -> Tuple[int, int]:
        """
        Judge every image's prompt again, and each generation by its most
        explicit image, as level() now would.

        Returns:
            (images changed, images read)
        """
        with self._cursor() as cursor:
            # An image synced with no text keeps the level its sync's dialog
            # gave it (#233): there is no prompt to judge.
            cursor.execute("SELECT gi.id, d.meta, gi.prompt_nsfw_level FROM generation_images gi "
                           "JOIN generations g ON g.id = gi.generation_id "
                           "LEFT JOIN generation_image_details d ON d.image_id = gi.id "
                           "WHERE NOT (g.source_id IS NOT NULL AND d.infotext IS NULL)")
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
