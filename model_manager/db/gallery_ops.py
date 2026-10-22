"""
The Civitai Images tab's reads (#209, #283): the Civitai images stored for the
models in the library, in an order a seed picks - every image, a search's,
and grouped one or two deep.

Each image is shown once, under the lowest version id the library has a file
of among the galleries that show it (`image_galleries`, v42). Each gets a
score from the seed and its own id, and the tab shows them by score: the same
seed, the same order; another seed, another. The score mixes the seed in
(XOR, spelt `(a | b) - (a & b)`, as SQLite has no XOR) before the multiply:
added instead, every seed gave the same cycle, started at another place.

A page is picked by its keys first, then only its records are read
(model_manager/db/AGENTS.md, "Choose the page, then look up its details").
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from ..console import say_failure
from ..nsfw import SFW_MAX
from .images_ops import IMAGE_PROMPTS
from .prompt_table import like_pattern

# The multiplier, a large odd number, and the 32 bits the score is kept to.
_MIX = 2654435761
_SPAN = 4294967296

# A size as a group's key: width, the sign, height.
SIZE_SIGN = "×"
# The type is what the version's file is (file_identity), Civitai's for a file
# no sync has read (model_manager/AGENTS.md, "Civitai's labels are the uploader's").
_FILE_TYPE = ("(SELECT f.file_type FROM files f WHERE f.version_id = v.id AND f.file_type IS NOT NULL"
              " ORDER BY f.file_path LIMIT 1)")
# What a grouping groups by: its key, and what a group is called. A prompt
# group is named by its text and a LoRA group by its LoRAs, which the endpoint
# reads for the groups it shows rather than for every group.
GROUPINGS: Dict[str, Tuple[str, str]] = {
    "model": ("v.model_id", "COALESCE(m.name, '')"),
    "base_model": ("COALESCE(v.base_model, '')", "COALESCE(v.base_model, '')"),
    "type": (f"COALESCE({_FILE_TYPE}, m.type, '')", f"COALESCE({_FILE_TYPE}, m.type, '')"),
    "size": (f"COALESCE(i.width || '{SIZE_SIGN}' || i.height, '')", f"COALESCE(i.width || '{SIZE_SIGN}' || i.height, '')"),
    "prompt": ("COALESCE(ip.grouped_as, 0)", "''"),
    "loras": ("COALESCE(combo.k, '')", "''"),
    # Your local date: Civitai's times are UTC (#283, question 11).
    "day": ("COALESCE(date(i.created_at, 'localtime'), '')", "COALESCE(date(i.created_at, 'localtime'), '')"),
}
# Groupings whose key is a number in a request.
NUMBER_KEYS = ("model", "prompt")

# Each image once, of a version the library has a file of, with its level -
# the most explicit its rows are stamped, where they differ. Read from the
# index by image (idx_image_galleries_image), which holds the version and level.
_PICKED = """
    WITH lib AS (SELECT DISTINCT version_id FROM files WHERE version_id IS NOT NULL),
    picked AS (SELECT g.image_id AS id, MIN(g.version_id) AS version_id, MAX(g.effective_nsfw_level) AS level
               FROM image_galleries g INDEXED BY idx_image_galleries_image
               JOIN lib ON lib.version_id = g.version_id GROUP BY g.image_id)"""
# Each image's LoRAs, as the LoRA grouping's key: their version ids, sorted,
# once each - made once and joined, as the Generations tab's combination is.
_COMBO = """,
    combo AS (SELECT image_id, group_concat(version_id, ',') AS k FROM (
        SELECT DISTINCT image_id, version_id FROM image_resources INDEXED BY idx_image_resources_image
        WHERE role = 'lora' AND version_id IS NOT NULL ORDER BY image_id, version_id) GROUP BY image_id)"""
_JOINS = """
    FROM picked p JOIN versions v ON v.id = p.version_id LEFT JOIN models m ON m.id = v.model_id
    JOIN images i ON i.id = p.id
    LEFT JOIN image_prompts ip INDEXED BY idx_image_prompts_lookup ON ip.id = i.prompt_id"""
# Explicit, as everywhere: an image no rule has judged reads as not safe.
_EXPLICIT = f"(NOT COALESCE(p.level <= {SFW_MAX}, 0))"
_SCORE = f"((((p.id | :seed) - (p.id & :seed)) * {_MIX}) % {_SPAN})"
# A level's images, read once a request (level()): this connection's alone.
_LEVEL_TABLE = "mm_gallery_level"
# A grouping's joins over the level's table, as _JOINS over `picked`.
_LEVEL_JOINS = f"""
    FROM temp.{_LEVEL_TABLE} p JOIN versions v ON v.id = p.version_id LEFT JOIN models m ON m.id = v.model_id
    JOIN images i ON i.id = p.id
    LEFT JOIN image_prompts ip INDEXED BY idx_image_prompts_lookup ON ip.id = i.prompt_id"""


def score(image_id: int, seed: int) -> int:
    """An image's score, as the SQL works it out: for tests, and nothing else."""
    return (((image_id | seed) - (image_id & seed)) * _MIX) % _SPAN


def day_range(day: str) -> Tuple[str, str]:
    """A local date as the UTC times it covers, in Civitai's spelling: from, and before."""
    start = datetime.strptime(day, "%Y-%m-%d")

    def utc(moment: datetime) -> str:
        return datetime.fromtimestamp(time.mktime(moment.timetuple()), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    return utc(start), utc(start + timedelta(days=1))


@dataclass
class Scope:
    """
    The images a level holds: the NSFW switch, a search's words, the groups
    opened above it, each (grouping, key), and the images, versions and
    models a search names (#336) - an empty list naming none.
    """
    hide_nsfw: bool = False
    words: List[str] = field(default_factory=list)
    opened: List[Tuple[str, Any]] = field(default_factory=list)
    images: List[int] = field(default_factory=list)
    versions: List[int] = field(default_factory=list)
    models: List[int] = field(default_factory=list)


# The images whose resources name one of a list's versions, or models, or
# that one of those versions' galleries shows (#336). A list is one JSON
# value: the older SQLite takes 999 values a statement.
_BY_VERSIONS = """(p.id IN (SELECT image_id FROM image_resources WHERE version_id IN (SELECT value FROM json_each(:versions)))
    OR p.id IN (SELECT image_id FROM image_galleries WHERE version_id IN (SELECT value FROM json_each(:versions))))"""
_BY_MODELS = """(p.id IN (SELECT image_id FROM image_resources WHERE model_id IN (SELECT value FROM json_each(:models)))
    OR p.id IN (SELECT image_id FROM image_galleries WHERE version_id IN
        (SELECT id FROM versions WHERE model_id IN (SELECT value FROM json_each(:models)))))"""


def _scope_sql(scope: Scope, hide: bool) -> Tuple[str, List[str], Dict[str, Any], bool]:
    """A scope as SQL: the CTEs after `picked`, the conditions, their values, and
    whether the LoRA combination is joined."""
    ctes, where, args = "", [], {}
    for n, word in enumerate(scope.words):
        ctes += ",\n    " + IMAGE_PROMPTS.match(f"hit{n}", f":w{n}")
        args[f"w{n}"] = like_pattern(word)
        where.append(f"(i.prompt_id IN hit{n} OR i.negative_id IN hit{n})")
    if scope.images:
        where.append("p.id IN (SELECT value FROM json_each(:images))")
        args["images"] = json.dumps(scope.images)
    if scope.versions:
        where.append(_BY_VERSIONS)
        args["versions"] = json.dumps(scope.versions)
    if scope.models:
        where.append(_BY_MODELS)
        args["models"] = json.dumps(scope.models)
    combo = False
    for n, (grouping, key) in enumerate(scope.opened):
        name = f"o{n}"
        args[name] = key
        if grouping == "model":
            # Its versions named first, so its images are found without
            # joining every image to its version.
            where.append(f"p.version_id IN (SELECT id FROM versions WHERE model_id = :{name})")
        elif grouping == "base_model":
            where.append(f"p.version_id IN (SELECT id FROM versions WHERE COALESCE(base_model, '') = :{name})")
        elif grouping == "size" and SIZE_SIGN in str(key):
            width, height = str(key).split(SIZE_SIGN, 1)
            where.append(f"i.width = :{name}w AND i.height = :{name}h")
            args[f"{name}w"], args[f"{name}h"] = _number(width), _number(height)
            continue
        elif grouping == "prompt":
            where.append(f"(i.prompt_id IN (SELECT id FROM image_prompts WHERE grouped_as = :{name})"
                         + (" OR i.prompt_id IS NULL)" if not key else ")"))
            continue
        elif grouping == "day" and key:
            try:
                args[f"{name}lo"], args[f"{name}hi"] = day_range(str(key))
            except ValueError:
                where.append("0")
                continue
            where.append(f"i.created_at >= :{name}lo AND i.created_at < :{name}hi")
            continue
        combo = combo or grouping == "loras"
        where.append(f"{GROUPINGS[grouping][0]} = :{name}")
    if hide:
        where.append(f"NOT {_EXPLICIT}")
    return ctes, where, args, combo


def _number(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        return text


class GalleryOps:
    """The Civitai Images tab's reads. Writes nothing: the seed is schema_info's (database.py)."""

    def __init__(self, cursor: Callable):
        self._cursor = cursor

    def _level(self, scope: Scope, hide: bool, grouping: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        """The CTEs, the FROM with its joins, and the values, of a scope's images."""
        ctes, where, args, combo = _scope_sql(scope, hide)
        combo = combo or grouping == "loras"
        head = _PICKED + (_COMBO if combo else "") + ctes
        body = _JOINS + (" LEFT JOIN combo ON combo.image_id = p.id" if combo else "")
        return head, f"{body} WHERE {' AND '.join(where) or '1'}", args

    @contextmanager
    def level(self, seed: int, scope: Scope) -> Iterator["_Level"]:
        """
        A level of the Civitai Images tab, read once: its images - the
        search's, inside the groups opened, the NSFW switch aside - each with
        its version, level and score, into a temporary table in memory, which
        its counts, a page and its groups are then read from. Searched, each
        request read every prompt's text twice, for the counts and for the
        page: 1.16 s a request for one word at 117,142 images, 0.57 s through
        the table, and 206 ms against 118 with no search (#283). The table is
        this connection's alone, so two requests at once have one each; it is
        dropped on the way out, and one a failed drop left is dropped first,
        as the Generations tab's Single pass does (#259).
        """
        head, body, args = self._level(scope, hide=False)
        args["seed"] = int(seed)
        with self._cursor() as cursor:
            # SQLite keeps 2 MB of temporary data in memory and writes the rest
            # to a file: the table is a few MB at 117,142 images.
            cursor.execute("PRAGMA temp_store = MEMORY")
            try:
                cursor.execute(f"DROP TABLE IF EXISTS temp.{_LEVEL_TABLE}")
                cursor.execute(f"CREATE TEMP TABLE {_LEVEL_TABLE} AS {head} SELECT p.id AS id, "
                               f"p.version_id AS version_id, p.level AS level, {_SCORE} AS s {body}", args)
                cursor.execute(f"CREATE INDEX temp.{_LEVEL_TABLE}_order ON {_LEVEL_TABLE} (s, id)")
                yield _Level(cursor, scope.hide_nsfw)
            finally:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS temp.{_LEVEL_TABLE}")
                    # Back to SQLite's own: a change of it also deletes every
                    # temporary table, a second way the table goes.
                    cursor.execute("PRAGMA temp_store = DEFAULT")
                except sqlite3.Error:
                    say_failure("Civitai Images: a level's table was not dropped; the next request drops it")

    def prompt_names(self, keys: Sequence[int]) -> Dict[int, str]:
        """Prompt groups' names: each group's text, with its spacing tidied."""
        with self._cursor() as cursor:
            texts = IMAGE_PROMPTS.texts(cursor, sorted({int(k) for k in keys if k}))
        return {k: " ".join(str(t).split()) for k, t in texts.items()}

    def images(self, keys: Sequence[Tuple[int, int]]) -> List[Dict[str, Any]]:
        """
        The images named by (image id, version id), in that order, each with
        what the tab shows of it: the stored Civitai record, and its model's
        and version's names and base model.
        """
        if not keys:
            return []
        values = ", ".join("(?, ?)" for _ in keys)
        flat = [part for pair in keys for part in pair]
        with self._cursor() as cursor:
            cursor.execute(
                f"""WITH k(image_id, version_id) AS (VALUES {values})
                    SELECT k.image_id, k.version_id, r.url, i.width, i.height, i.created_at, r.data,
                           v.model_id, v.version_name, v.base_model, m.name AS model_name, m.type AS model_type
                    FROM k JOIN image_records r ON r.image_id = k.image_id JOIN images i ON i.id = k.image_id
                    JOIN versions v ON v.id = k.version_id LEFT JOIN models m ON m.id = v.model_id""", flat)
            rows = {(row[0], row[1]): row for row in cursor.fetchall()}
        found = []
        for image_id, version_id in keys:
            row = rows.get((image_id, version_id))
            if row is None:
                continue
            try:
                image = json.loads(row[6] or "{}")
            except ValueError:
                image = {}
            if not isinstance(image, dict):
                image = {}
            image.update({"id": row[0], "url": image.get("url") or row[2],
                          "width": image.get("width") or row[3], "height": image.get("height") or row[4],
                          "createdAt": image.get("createdAt") or row[5]})
            found.append({"image": image, "version_id": row[1], "model_id": row[7], "version_name": row[8],
                          "base_model": row[9], "model_name": row[10], "model_type": row[11]})
        return found

    def signature(self) -> Tuple[Any, ...]:
        """
        What changes when the Civitai Images tab's images or groups might:
        images stored, removed or judged again, their prompts or LoRAs
        changed, files coming or going. A kept group list is worked out again
        when it changes.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*), TOTAL(image_id), TOTAL(effective_nsfw_level) FROM image_galleries")
            galleries = tuple(cursor.fetchone())
            cursor.execute("SELECT COUNT(*), TOTAL(prompt_id), TOTAL(negative_id) FROM images")
            images = tuple(cursor.fetchone())
            cursor.execute("SELECT COUNT(*), TOTAL(version_id) FROM image_resources INDEXED BY "
                           "idx_image_resources_image WHERE role = 'lora'")
            loras = tuple(cursor.fetchone())
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT version_id) FROM files WHERE version_id IS NOT NULL")
            files = tuple(cursor.fetchone())
        return galleries + images + loras + files


class _Level:
    """A level read into its table (GalleryOps.level): its counts, a page, its groups."""

    def __init__(self, cursor, hide_nsfw: bool):
        self._cursor = cursor
        self._hide = hide_nsfw

    def counts(self) -> Dict[str, int]:
        """Every image the level holds - the NSFW switch aside - and how many of them are explicit."""
        self._cursor.execute(f"SELECT COUNT(*), TOTAL({_EXPLICIT}) FROM temp.{_LEVEL_TABLE} p")
        total, explicit = self._cursor.fetchone()
        return {"total": int(total or 0), "nsfw": int(explicit or 0)}

    def image_keys(self, offset: int, limit: int) -> List[Tuple[int, int]]:
        """
        A page of the level's images by score, as (image id, version id), in
        order. Ties broken by the image id: an order that cannot tie.
        """
        where = f"WHERE NOT {_EXPLICIT}" if self._hide else ""
        self._cursor.execute(f"SELECT p.id, p.version_id FROM temp.{_LEVEL_TABLE} p {where} "
                             "ORDER BY p.s, p.id LIMIT ? OFFSET ?", (int(limit), int(offset)))
        return [(row[0], row[1]) for row in self._cursor.fetchall()]

    def groups(self, grouping: str, previews: int = 4) -> List[Dict[str, Any]]:
        """
        Every group of a grouping within the level: its key, its name, how many
        images it has and how many are explicit, and its first `previews` shown
        images by score. A group whose every image the NSFW switch hides is
        left out. The groups' own order is the caller's (one from the seed and
        the group): placed by their lowest-scoring image, the biggest groups
        came first for almost every seed (#209).
        """
        key, label = GROUPINGS[grouping]
        combo = grouping == "loras"
        shown = f"NOT {_EXPLICIT}" if self._hide else "1"
        # The LoRA combination is worked out only for the grouping that reads it.
        combo_cte = _COMBO.lstrip(",\n ") + "," if combo else ""
        sql = f"""WITH {combo_cte}
            scored AS (SELECT p.id, p.version_id, {key} AS k, {label} AS name, p.s AS s,
                              {_EXPLICIT} AS explicit, ({shown}) AS shown
                       {_LEVEL_JOINS}{" LEFT JOIN combo ON combo.image_id = p.id" if combo else ""}),
            counted AS (SELECT *, COUNT(*) OVER (PARTITION BY k) AS n_all,
                               TOTAL(explicit) OVER (PARTITION BY k) AS n_explicit FROM scored),
            ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY k ORDER BY s, id) AS rn
                       FROM counted WHERE shown)
            SELECT k, name, id, version_id, rn, n_all, n_explicit FROM ranked
            WHERE rn <= ? ORDER BY k, rn"""
        found: Dict[Any, Dict[str, Any]] = {}
        self._cursor.execute(sql, (int(previews),))
        for k, name, image_id, version_id, _, n_all, n_explicit in self._cursor.fetchall():
            entry = found.setdefault(k, {"key": k, "name": name or "", "count": int(n_all),
                                         "nsfw": int(n_explicit), "previews": []})
            entry["previews"].append((image_id, version_id))
        return list(found.values())
