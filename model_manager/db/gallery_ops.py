"""
The Gallery tab's reads (#209): the Civitai images stored for the models in the
library, in an order a seed picks.

Each image is shown once, under the lowest version id it is stored under - an
image can be stored under several versions. Each gets a score from the seed
and its own id, and the tab shows them by score: the same seed, the same
order; another seed, another. The score mixes the seed in (XOR, spelt
`(a | b) - (a & b)`, as SQLite has no XOR) before the multiply: added instead,
every seed gave the same cycle, started at another place.

A page is picked by its keys first, then only its rows are read: reading every
row's address and size to pick 100 took 314 ms of 119,731 images; the keys
alone, 8 ms (AGENTS.md, "Choose the page, then look up its details").
"""
import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..nsfw import SFW_MAX

# The multiplier, a large odd number, and the 32 bits the score is kept to.
_MIX = 2654435761
_SPAN = 4294967296

# What a grouping groups by: its key, and what a group is called. The type is
# what the version's file is (file_identity), Civitai's for a file no sync has
# read: Civitai's labels are the uploader's (AGENTS.md).
_FILE_TYPE = ("(SELECT f.file_type FROM files f WHERE f.version_id = v.id AND f.file_type IS NOT NULL"
              " ORDER BY f.file_path LIMIT 1)")
GROUPINGS: Dict[str, Tuple[str, str]] = {
    "model": ("v.model_id", "COALESCE(m.name, '')"),
    "base_model": ("COALESCE(v.base_model, '')", "COALESCE(v.base_model, '')"),
    "type": (f"COALESCE({_FILE_TYPE}, m.type, '')", f"COALESCE({_FILE_TYPE}, m.type, '')"),
    "size": ("COALESCE(i.width || '×' || i.height, '')", "COALESCE(i.width || '×' || i.height, '')"),
}

# Each image once, of a version the library has a file of, with its level -
# the most explicit its copies are stamped, where they differ. Read from an
# index that holds the version, the level and the id
# (idx_images_version_nsfw_created_id): from the rows themselves, about 3.7 KB
# each, a page with NSFW hidden took 590 ms and the counts 700.
_PICKED = """
    WITH lib AS (SELECT DISTINCT version_id FROM files WHERE version_id IS NOT NULL),
    picked AS (SELECT i.id, MIN(i.version_id) AS version_id, MAX(i.effective_nsfw_level) AS level
               FROM images i INDEXED BY idx_images_version_nsfw_created_id
               JOIN lib ON lib.version_id = i.version_id GROUP BY i.id)
"""
_JOINS = """
    FROM picked p JOIN versions v ON v.id = p.version_id LEFT JOIN models m ON m.id = v.model_id
"""
# The size is the one key only the rows hold.
_ROW = " JOIN images i ON i.id = p.id AND i.version_id = p.version_id"
# Explicit, as everywhere: an image no rule has judged reads as not safe.
_EXPLICIT = f"(NOT COALESCE(p.level <= {SFW_MAX}, 0))"
_SCORE = f"((((p.id | :seed) - (p.id & :seed)) * {_MIX}) % {_SPAN})"


def score(image_id: int, seed: int) -> int:
    """An image's score, as the SQL works it out: for tests, and nothing else."""
    return (((image_id | seed) - (image_id & seed)) * _MIX) % _SPAN


class GalleryOps:
    """The Gallery's reads. Writes nothing: the seed is schema_info's (database.py)."""

    def __init__(self, cursor: Callable):
        self._cursor = cursor

    def counts(self) -> Dict[str, int]:
        """Every image the Gallery has, and how many of them are explicit."""
        with self._cursor() as cursor:
            cursor.execute(f"{_PICKED} SELECT COUNT(*), TOTAL({_EXPLICIT}) {_JOINS}")
            total, explicit = cursor.fetchone()
        return {"total": int(total or 0), "nsfw": int(explicit or 0)}

    def image_keys(self, seed: int, hide_nsfw: bool, offset: int, limit: int,
                   group: Optional[str] = None, key: Any = None) -> List[Tuple[int, int]]:
        """
        A page of images by score - every image, or one group's - as (image id,
        version id), in order. Ties broken by the image id: an order that
        cannot tie.
        """
        where, args = ["1"], {"seed": int(seed), "limit": int(limit), "offset": int(offset)}
        if hide_nsfw:
            where.append(f"NOT {_EXPLICIT}")
        if group:
            where.append(f"{GROUPINGS[group][0]} = :key")
            args["key"] = key
        # A model's or a base model's group: its versions named first, so its
        # images are found without joining every image to its version - over
        # every image, a page took 315 ms. Each image is still placed under
        # the lowest version of the whole library: gathered from the group's
        # versions alone, an image also stored under another model's lower
        # version was counted in both, 72 images inside a tile of 63.
        narrow = {"model": "SELECT id FROM versions WHERE model_id = :key",
                  "base_model": "SELECT id FROM versions WHERE COALESCE(base_model, '') = :key"}.get(group or "")
        if narrow:
            where.append(f"p.version_id IN ({narrow})")
        with self._cursor() as cursor:
            joins = _JOINS + (_ROW if group == "size" else "")
            cursor.execute(f"{_PICKED} SELECT p.id, p.version_id {joins} WHERE {' AND '.join(where)}"
                           f" ORDER BY {_SCORE}, p.id LIMIT :limit OFFSET :offset", args)
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def groups(self, seed: int, group: str, hide_nsfw: bool, previews: int = 4) -> List[Dict[str, Any]]:
        """
        Every group of a grouping: its key, its name, how many images it has
        and how many are explicit, and its first `previews` shown images by
        score. A group whose every image the NSFW switch hides is left out.
        The groups' own order is the caller's (one from the seed and the
        group): placed by their lowest-scoring image, the biggest groups came
        first for almost every seed (#209).
        """
        key, label = GROUPINGS[group]
        shown = f"NOT {_EXPLICIT}" if hide_nsfw else "1"
        sql = f"""{_PICKED},
            scored AS (SELECT p.id, p.version_id, {key} AS k, {label} AS name, {_SCORE} AS s,
                              {_EXPLICIT} AS explicit, ({shown}) AS shown
                       {_JOINS}{_ROW if group == "size" else ""}),
            counted AS (SELECT *, COUNT(*) OVER (PARTITION BY k) AS n_all,
                               TOTAL(explicit) OVER (PARTITION BY k) AS n_explicit FROM scored),
            ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY k ORDER BY s, id) AS rn
                       FROM counted WHERE shown)
            SELECT k, name, id, version_id, rn, n_all, n_explicit FROM ranked
            WHERE rn <= :previews ORDER BY k, rn"""
        found: Dict[Any, Dict[str, Any]] = {}
        with self._cursor() as cursor:
            cursor.execute(sql, {"seed": int(seed), "previews": int(previews)})
            for k, name, image_id, version_id, _, n_all, n_explicit in cursor.fetchall():
                entry = found.setdefault(k, {"key": k, "name": name or "", "count": int(n_all),
                                             "nsfw": int(n_explicit), "previews": []})
                entry["previews"].append((image_id, version_id))
        return list(found.values())

    def images(self, keys: Sequence[Tuple[int, int]]) -> List[Dict[str, Any]]:
        """
        The images named by (image id, version id), in that order, each with
        what the tab shows of it: the stored Civitai payload, and its model's
        and version's names and base model.
        """
        if not keys:
            return []
        values = ", ".join("(?, ?)" for _ in keys)
        flat = [part for pair in keys for part in pair]
        with self._cursor() as cursor:
            cursor.execute(
                f"""SELECT i.id, i.version_id, i.url, i.width, i.height, i.created_at, i.data,
                           v.model_id, v.version_name, v.base_model, m.name AS model_name, m.type AS model_type
                    FROM images i JOIN versions v ON v.id = i.version_id LEFT JOIN models m ON m.id = v.model_id
                    WHERE (i.id, i.version_id) IN (VALUES {values})""", flat)
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
        What changes when the Gallery's images might: images stored, removed or
        judged again, files coming or going. A kept group list is worked out
        again when it changes.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*), MAX(rowid), TOTAL(effective_nsfw_level) FROM images")
            images = tuple(cursor.fetchone())
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT version_id) FROM files WHERE version_id IS NOT NULL")
            files = tuple(cursor.fetchone())
        return images + files
