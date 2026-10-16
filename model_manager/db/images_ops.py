"""
Internal module for the Civitai images stored for the library's versions.

Each image is stored once (#283, v42): `images` what search and grouping read
of it, `image_records` Civitai's record of it, whole, `image_resources` and
`image_prompts` made from the record, and `image_galleries` which versions'
galleries show it, where, and how explicit it is.
Used by ModelsDatabase facade - do not import directly.
"""
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from ..nsfw import SFW_MAX, image_level
from ..prompt_rules import MIN_PROMPT_LENGTH
from .prompt_table import PromptTable

# The order a gallery shows a version's images in: Civitai's, as stored in
# `position`, page by page, over image_galleries' columns. The image id only
# breaks ties, and orders rows stored before positions were kept (schema v19).
GALLERY_ORDER = "page, position, image_id"

# Civitai's images' prompts: every column naming a row, each indexed (v42).
IMAGE_PROMPTS = PromptTable("image_prompts", (("images", "prompt_id"), ("images", "negative_id")))

# Civitai's resource types, as the grouping reads them; anything else is `other`.
ROLES = {"checkpoint": "checkpoint", "lora": "lora", "locon": "lora", "dora": "lora",
         "textualinversion": "embedding", "vae": "vae", "upscaler": "upscaler"}

# A gallery's rows with each image's prompt row, for "worth reading".
_WITH_PROMPT = (" JOIN images i ON i.id = g.image_id"
                " LEFT JOIN image_prompts ip INDEXED BY idx_image_prompts_lookup ON ip.id = i.prompt_id")
_READABLE = f"COALESCE(ip.length, 0) >= {MIN_PROMPT_LENGTH}"
_UNREADABLE = f"COALESCE(ip.length, 0) < {MIN_PROMPT_LENGTH}"
# SQLite's limit on bound values is 999 in older builds.
_CHUNK = 500


def resource_rows(record: Any) -> List[tuple]:
    """Each resource a record lists, as image_resources' columns from `position` on."""
    meta = record.get("meta") if isinstance(record, dict) else None
    listed = meta.get("civitaiResources") if isinstance(meta, dict) else None
    rows = []
    for position, entry in enumerate(listed if isinstance(listed, list) else []):
        if isinstance(entry, dict):
            kind = entry.get("type")
            rows.append((position, ROLES.get(str(kind or "").lower(), "other"), kind, entry.get("modelId"),
                         entry.get("modelVersionId"), entry.get("weight"), entry.get("name"),
                         entry.get("modelVersionName")))
    return rows


def _text(record: Dict[str, Any], key: str) -> Optional[str]:
    meta = record.get("meta")
    text = meta.get(key) if isinstance(meta, dict) else None
    return text if isinstance(text, str) else None


def carry_generation_data(fresh: Dict[str, Any], stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    A fresh copy of an image with the generation data the stored record has,
    where the fresh one has no prompt - keep_generation_data's rule, in the
    write itself (#283, R2): Civitai's image list carries no prompts, and the
    lookup that adds them is skipped without "Image prompts" or fails without
    an API key, so a fetch must never empty the one record every gallery
    showing the image reads. Anything the fresh meta does carry wins.
    """
    meta = fresh.get("meta") if isinstance(fresh.get("meta"), dict) else {}
    old = stored.get("meta") if isinstance(stored, dict) else None
    if meta.get("prompt") or not isinstance(old, dict) or not old:
        return fresh
    carried = dict(old)
    carried.update({key: value for key, value in meta.items() if value is not None})
    return {**fresh, "meta": carried}


def _chunks(ids: Iterable[int]):
    ids = list(dict.fromkeys(i for i in ids if i is not None))
    for start in range(0, len(ids), _CHUNK):
        yield ids[start:start + _CHUNK]


def forget_unshown(cursor, image_ids: Iterable[int]) -> int:
    """
    Of these images, forget those no gallery shows any more - their row, record
    and resources - and the prompts nothing names after them. Run inside the
    transaction that took their gallery rows.

    Returns:
        How many images went.
    """
    gone, prompts = 0, set()
    for part in _chunks(image_ids):
        marks = ", ".join("?" * len(part))
        cursor.execute(f"SELECT id, prompt_id, negative_id FROM images WHERE id IN ({marks}) AND NOT EXISTS "
                       "(SELECT 1 FROM image_galleries g WHERE g.image_id = images.id)", part)
        rows = cursor.fetchall()
        unshown = [row[0] for row in rows]
        prompts.update(p for row in rows for p in row[1:])
        # An image whose row was never written still has its record to forget.
        cursor.execute(f"SELECT image_id FROM image_records WHERE image_id IN ({marks}) AND NOT EXISTS "
                       "(SELECT 1 FROM image_galleries g WHERE g.image_id = image_records.image_id)", part)
        unshown = list(dict.fromkeys(unshown + [row[0] for row in cursor.fetchall()]))
        if not unshown:
            continue
        marks = ", ".join("?" * len(unshown))
        for table, column in (("images", "id"), ("image_records", "image_id"), ("image_resources", "image_id")):
            cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({marks})", unshown)
        gone += len(unshown)
    IMAGE_PROMPTS.drop_unused(cursor, prompts)
    return gone


class ImagesOps:
    """
    The Civitai images stored for the library's versions.

    Receives a cursor factory from the parent facade.
    """

    def __init__(self, cursor_factory: Callable):
        self._cursor = cursor_factory

    # ==================== Writing ====================

    def store_images(self, version_id: int, page: int, images: List[Dict[str, Any]]):
        """
        Store a page of a version's gallery, in the order Civitai gave it: that
        order is kept as `position`, because it is Civitai's ranking and the id
        says nothing about it. Page 1 is the first fetch, 2 the first Load more.
        """
        with self._cursor() as cursor:
            self.insert_images(cursor, version_id, page, images)

    def insert_images(self, cursor, version_id: int, page: int, images: List[Dict[str, Any]]):
        """
        store_images(), into a transaction the caller holds. An image is
        stored once whatever galleries show it: the newest fetch is its record
        for all of them - its generation data kept where the fetch has none
        (carry_generation_data) - and its level is written to each of its
        gallery rows.
        """
        touched = set()
        for position, fresh in enumerate(images):
            image_id = fresh.get("id")
            if not image_id:
                continue
            cursor.execute("SELECT data FROM image_records WHERE image_id = ?", (image_id,))
            row = cursor.fetchone()
            try:
                stored = json.loads(row[0]) if row else None
            except (TypeError, ValueError):
                stored = None
            record = carry_generation_data(fresh, stored)
            level = image_level(record)  # the rule lives in model_manager.nsfw
            cursor.execute("SELECT prompt_id, negative_id FROM images WHERE id = ?", (image_id,))
            touched.update(cursor.fetchone() or ())
            cursor.execute(
                "INSERT OR REPLACE INTO images (id, prompt_id, negative_id, width, height, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (image_id, IMAGE_PROMPTS.id_for(cursor, _text(record, "prompt")),
                 IMAGE_PROMPTS.id_for(cursor, _text(record, "negativePrompt")),
                 record.get("width"), record.get("height"),
                 record.get("type") if isinstance(record.get("type"), str) else "image",
                 record.get("createdAt")))
            cursor.execute("INSERT OR REPLACE INTO image_records (image_id, url, data) VALUES (?, ?, ?)",
                           (image_id, record.get("url"), json.dumps(record)))
            cursor.execute("DELETE FROM image_resources WHERE image_id = ?", (image_id,))
            cursor.executemany("INSERT INTO image_resources (image_id, position, role, type, model_id, version_id, "
                               "weight, name, version_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               [(image_id,) + r for r in resource_rows(record)])
            cursor.execute("INSERT OR REPLACE INTO image_galleries (version_id, image_id, page, position, "
                           "effective_nsfw_level) VALUES (?, ?, ?, ?, ?)",
                           (version_id, image_id, page, position, level))
            cursor.execute("UPDATE image_galleries SET effective_nsfw_level = ? WHERE image_id = ? "
                           "AND effective_nsfw_level IS NOT ?", (level, image_id, level))
        IMAGE_PROMPTS.drop_unused(cursor, touched)

    # How often restamp_levels() says how far it has got: on 109,738 images
    # judging took 3-7 s, so this is a few reports a second.
    RESTAMP_REPORT_EVERY = 2000

    def restamp_levels(self, progress=None) -> Tuple[int, int, int]:
        """
        Judge every stored image again, as image_level() now would.

        A level is stamped when an image is stored, so a change to how images
        are judged - the prompt words, above all - leaves the rows on the old
        verdict. The record is stored beside it, so nothing is refetched. A
        changed level is written to each of the image's gallery rows. A
        version's safe cover that is now an unsafe image is cleared, and the
        grid falls back to the version's first image that is still safe until
        a sync picks the cover again.

        Args:
            progress: called as progress(judged, total) once the images are
                read, every RESTAMP_REPORT_EVERY images, and at the end.

        Returns:
            (images changed, images read, safe covers cleared)
        """
        with self._cursor() as cursor:
            cursor.execute("SELECT r.image_id, r.data, (SELECT MAX(g.effective_nsfw_level) FROM image_galleries g "
                           "WHERE g.image_id = r.image_id) FROM image_records r")
            rows = cursor.fetchall()
        report = progress or (lambda judged, total: None)
        report(0, len(rows))
        changed = []
        for done, (image_id, data, stored) in enumerate(rows, 1):
            if done % self.RESTAMP_REPORT_EVERY == 0:
                report(done, len(rows))
            if not data:
                continue
            try:
                level = image_level(json.loads(data))
            except (ValueError, TypeError):
                continue
            if level != stored:
                changed.append((level, image_id))
        report(len(rows), len(rows))
        with self._cursor() as cursor:
            cursor.executemany("UPDATE image_galleries SET effective_nsfw_level = ? WHERE image_id = ?", changed)
            cursor.execute(
                "UPDATE versions SET safe_cover_url = '' WHERE safe_cover_url IN"
                " (SELECT r.url FROM image_records r WHERE EXISTS (SELECT 1 FROM image_galleries g"
                " WHERE g.image_id = r.image_id AND g.effective_nsfw_level > ?))", (SFW_MAX,))
            covers = cursor.rowcount
        return len(changed), len(rows), covers

    def clear_version(self, version_id: int):
        """Clear a version's gallery, and the images no other gallery shows."""
        with self._cursor() as cursor:
            forget_unshown(cursor, self.clear_version_in(cursor, version_id))

    def clear_version_in(self, cursor, version_id: int) -> List[int]:
        """clear_version() inside a caller's transaction, without the clean-up: the
        image ids its gallery held, for forget_unshown() once the caller is done."""
        cursor.execute("SELECT image_id FROM image_galleries WHERE version_id = ?", (version_id,))
        held = [row[0] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM image_galleries WHERE version_id = ?", (version_id,))
        return held

    # ==================== Reading ====================

    def stored_records(self, image_ids: Iterable[int]) -> List[Dict[str, Any]]:
        """
        The stored records of these images, whatever galleries show them: what
        a sync carries generation data over from (keep_generation_data), so an
        image another gallery already has a prompt for is not looked up again.
        """
        found = []
        with self._cursor() as cursor:
            for part in _chunks(image_ids):
                cursor.execute(f"SELECT data FROM image_records WHERE image_id IN ({', '.join('?' * len(part))})",
                               part)
                for (data,) in cursor.fetchall():
                    try:
                        record = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(record, dict):
                        found.append(record)
        return found

    def _gallery(self, version_id: int, page: Optional[int], max_nsfw_level: Optional[int],
                 require_prompt: bool) -> Tuple[str, Tuple]:
        """A version's gallery rows, filtered: the FROM and WHERE, and their values."""
        sql = " FROM image_galleries g JOIN image_records r ON r.image_id = g.image_id"
        where, args = ["g.version_id = ?"], [version_id]
        if require_prompt:
            sql += _WITH_PROMPT
            where.append(_READABLE)
        if page is not None:
            where.append("g.page = ?")
            args.append(page)
        if max_nsfw_level is not None:
            where.append("g.effective_nsfw_level <= ?")
            args.append(max_nsfw_level)
        return f"{sql} WHERE {' AND '.join(where)}", tuple(args)

    def get_images(
        self,
        version_id: int,
        page: Optional[int] = None,
        max_nsfw_level: Optional[int] = None,
        require_prompt: bool = False
    ) -> List[Dict[str, Any]]:
        """
        A version's stored images, in gallery order.

        Args:
            version_id: Civitai model version ID.
            page: Specific page number, or None for all pages.
            max_nsfw_level: If set, only images whose level is at most this.
            require_prompt: Drop images whose prompt is too short to be one.
        """
        sql, args = self._gallery(version_id, page, max_nsfw_level, require_prompt)
        with self._cursor() as cursor:
            cursor.execute(f"SELECT r.data{sql} ORDER BY g.page, g.position, g.image_id", args)
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def get_image_page(
        self,
        version_id: int,
        offset: int,
        limit: int,
        max_nsfw_level: Optional[int] = None,
        require_prompt: bool = False
    ) -> List[Dict[str, Any]]:
        """
        One page of a version's gallery: the images get_images() would give,
        from the offset-th on, at most limit of them.

        A gallery used to be sent whole and paged in the browser - 200 images
        and 900 KB for one version of a real library, where one page is 100.
        """
        sql, args = self._gallery(version_id, None, max_nsfw_level, require_prompt)
        with self._cursor() as cursor:
            cursor.execute(f"SELECT r.data{sql} ORDER BY g.page, g.position, g.image_id LIMIT ? OFFSET ?",
                           args + (limit, offset))
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def get_all_images_for_version(
        self,
        version_id: int,
        max_nsfw_level: Optional[int] = None,
        require_prompt: bool = False
    ) -> List[Dict[str, Any]]:
        """Every stored image of a version (all pages), as get_images()."""
        return self.get_images(version_id, page=None, max_nsfw_level=max_nsfw_level,
                               require_prompt=require_prompt)

    def get_image_counts(self, version_id: int, max_nsfw_level: Optional[int] = None,
                         require_prompt: bool = False) -> Dict[str, int]:
        """
        Get total and filtered image counts for a version.

        Returns:
            Dict with 'total' and 'filtered' counts, and 'hidden' (total - filtered):
            'hidden_nsfw' and 'hidden_promptless', what each filter alone hides,
            and 'hidden_both', what both do - the three adding up to 'hidden';
            and 'promptless_total', every image with an unusable prompt.
        """
        def count(*conditions, args=()):
            where = " AND ".join(("g.version_id = ?",) + conditions)
            cursor.execute(f"SELECT COUNT(*) FROM image_galleries g{_WITH_PROMPT} WHERE {where}",
                           (version_id,) + tuple(args))
            return cursor.fetchone()[0]

        with self._cursor() as cursor:
            total = count()

            # What each filter hides on its own, so the panel can say which
            # one is responsible rather than reporting one number for both.
            nsfw = () if max_nsfw_level is None else ("g.effective_nsfw_level <= ?",)
            nsfw_args = () if max_nsfw_level is None else (max_nsfw_level,)
            prompt = (_READABLE,) if require_prompt else ()

            filtered = count(*(nsfw + prompt), args=nsfw_args)
            nsfw_kept = count(*nsfw, args=nsfw_args)

            # What each gallery switch is acting on right now: the number beside
            # it, and the number its banner states - the two must always agree.
            # Each counts its own kind among the images the *other* switch lets
            # through, so it is the number a click would hide or bring back,
            # and it moves when the other switch does. It is not 0 when the
            # switch is showing everything: it is then how many it is showing.
            nsfw_count = count("g.effective_nsfw_level > ?", *prompt, args=(SFW_MAX,))
            promptless_count = count(*nsfw, _UNREADABLE, args=nsfw_args)

            # Every image with an unusable prompt, whatever the NSFW filter
            # does: the number on the prompt switch, which so stays put
            # however either switch is set.
            promptless_total = count(_UNREADABLE)

            # An image both filters hide is counted apart: credited to one of
            # them, that switch's number changed when the other was flipped -
            # 51 NSFW hidden, 49 shown once ticked, the other 2 still hidden
            # for their prompt. So each switch's number is what it alone
            # hides, and stays put when it is flipped.
            both = 0
            if max_nsfw_level is not None and require_prompt:
                # Not kept by the NSFW filter - a missing level included,
                # as its "<= ?" hides that too.
                both = count("NOT COALESCE(g.effective_nsfw_level <= ?, 0)", _UNREADABLE, args=(max_nsfw_level,))

            return {
                "total": total,
                "filtered": filtered,
                "hidden_nsfw": total - nsfw_kept - both,
                "hidden_promptless": nsfw_kept - filtered,
                "hidden_both": both,
                "hidden": total - filtered,
                "nsfw_count": nsfw_count,
                "promptless_count": promptless_count,
                "promptless_total": promptless_total,
            }

    def get_image_ids(self, version_id: int) -> Set[int]:
        """The ids of the images stored for a version."""
        with self._cursor() as cursor:
            cursor.execute("SELECT image_id FROM image_galleries WHERE version_id = ?", (version_id,))
            return {row[0] for row in cursor.fetchall()}

    def get_cached_page_count(self, version_id: int) -> int:
        """How many pages have been stored for a version."""
        with self._cursor() as cursor:
            cursor.execute("SELECT MAX(page) FROM image_galleries WHERE version_id = ?", (version_id,))
            return cursor.fetchone()[0] or 0

    def count_by_version(self, version_ids: Optional[List[int]] = None) -> Dict[int, int]:
        """
        How many images are stored for each version.

        The sync dialog costs a gallery refresh from these: generation data is
        fetched 30 ids per request, so what a refresh will cost depends on how
        many images the galleries hold. Last time's counts are the only guide
        available before the fetch, and galleries change slowly.

        Args:
            version_ids: Restrict to these versions, or None for every one.

        Returns:
            Version id -> image count. Versions with no stored images are absent.
        """
        with self._cursor() as cursor:
            if version_ids is None:
                cursor.execute("SELECT version_id, COUNT(*) FROM image_galleries GROUP BY version_id")
            else:
                ids = [int(v) for v in version_ids if v]
                if not ids:
                    return {}
                cursor.execute(
                    "SELECT version_id, COUNT(*) FROM image_galleries WHERE version_id IN (%s)"
                    " GROUP BY version_id" % ",".join("?" * len(ids)),
                    ids,
                )
            return {row[0]: row[1] for row in cursor.fetchall()}
