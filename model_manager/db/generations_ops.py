"""
Internal module for the images you generate: generations, generation_images
and generation_files.

A generation is written once, whole, when Forge has finished it, and is not
changed afterwards: only what is derived from it - the prompt's NSFW level -
is stamped again, and the user's own rating set. See migrations._migrate_to_v27.

Used by ModelsDatabase facade - do not import directly.
"""
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

_GENERATION_COLUMNS = (
    "created_at", "mode", "forge", "prompt", "negative_prompt", "styles",
    "hr_prompt", "hr_negative_prompt", "n_iter", "batch_size", "width", "height",
    "checkpoint_path", "checkpoint_hash", "modules", "hr_checkpoint_path",
    "hr_modules", "refiner_path", "params", "extra_params", "script_args",
    "settings", "infotext", "image_count", "prompt_nsfw_level",
)
_IMAGE_COLUMNS = (
    "position", "iteration", "path", "infotext", "meta", "prompt",
    "negative_prompt", "seed", "subseed", "hr_prompt", "hr_negative_prompt",
    "loras", "width", "height", "prompt_nsfw_level",
)
# Stored as JSON text: lists and dicts.
_JSON_COLUMNS = {"styles", "modules", "hr_modules", "params", "extra_params",
                 "script_args", "settings", "meta", "loras"}


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

    def library_spelling(self, paths: Iterable[str]) -> Dict[str, str]:
        """
        Each path as model_versions spells it, for the files it holds.

        Forge and the library can spell one file two ways - case, above all,
        which Windows ignores and SQL does not - and generation_files is
        joined on equality. A path the library does not hold is left out.
        """
        found: Dict[str, str] = {}
        with self._cursor() as cursor:
            for path in set(paths):
                cursor.execute("SELECT file_path FROM model_versions "
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
            cursor.execute("SELECT id, file_path FROM model_versions "
                           "WHERE file_path = ? COLLATE NOCASE", (path,))
            row = cursor.fetchone()
            if not row:
                return [path]
            if row[0] is None:
                return [row[1]]
            cursor.execute("SELECT file_path FROM model_versions WHERE id = ?", (row[0],))
            return [r[0] for r in cursor.fetchall()]

    def gallery_images(self, files: List[str]) -> List[Dict[str, Any]]:
        """
        Every image filed under any of these files, with what filtering and
        ordering need and nothing more: its generation, its place in it, its
        level - the user's rating when set, else the prompt's - how long its
        prompt is, and when its generation was made. Newest generation first.
        """
        if not files:
            return []
        marks = ", ".join("?" * len(files))
        with self._cursor() as cursor:
            cursor.execute(f"""
                SELECT gi.id, gi.generation_id, gi.position,
                       COALESCE(gi.user_nsfw_level, gi.prompt_nsfw_level) AS level,
                       LENGTH(TRIM(COALESCE(gi.prompt, ''))) AS prompt_length,
                       g.created_at
                FROM generation_images gi
                JOIN generations g ON g.id = gi.generation_id
                WHERE gi.id IN (SELECT image_id FROM generation_files WHERE file_path IN ({marks}))
                ORDER BY g.created_at DESC, g.id DESC, gi.position
            """, files)
            return [dict(r) for r in cursor.fetchall()]

    def count_generations(self, files: List[str]) -> int:
        """How many generations used any of these files."""
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

    def delete_generation(self, generation_id: int) -> List[str]:
        """
        Remove a generation's rows from all three tables.

        Returns:
            The paths its images were saved to that no other record names,
            for a caller asked to delete the files as well. Forge can save a
            later image over an earlier one's file, when its replace action
            is Override, and the earlier record then names a file that is not
            only its own. The files themselves are not touched here.
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT path FROM generation_images WHERE generation_id = ?",
                           (generation_id,))
            paths = [r[0] for r in cursor.fetchall()]
            cursor.execute("DELETE FROM generation_files WHERE generation_id = ?", (generation_id,))
            cursor.execute("DELETE FROM generation_images WHERE generation_id = ?", (generation_id,))
            cursor.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
            own = []
            for path in dict.fromkeys(paths):
                cursor.execute("SELECT 1 FROM generation_images WHERE path = ? COLLATE NOCASE LIMIT 1",
                               (path,))
                if not cursor.fetchone():
                    own.append(path)
            return own

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
