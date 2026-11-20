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

from ..comfy_graph import FILLED_KEY, JUDGED_KEY, has_graph, judged_image, judging_filled, switch_from
from ..nsfw import SFW_MAX, image_level
from ..prompt_rules import MIN_PROMPT_LENGTH
from .params_table import IMAGE_COLUMNS, image_params_row, settings_group
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
# An image's settings row (#378): every column of image_params, by name.
_PARAMS_UPSERT = (f"INSERT OR REPLACE INTO image_params (image_id, {', '.join(IMAGE_COLUMNS)}) "
                  f"VALUES (?, {', '.join('?' * len(IMAGE_COLUMNS))})")
# The Fill notice's write of a settings row (#232): made where an image had
# none, changed where it differs - never a row taken out and put back.
_PARAMS_FILL = (f"INSERT INTO image_params (image_id, {', '.join(IMAGE_COLUMNS)}) "
                f"VALUES (?, {', '.join('?' * len(IMAGE_COLUMNS))}) ON CONFLICT(image_id) DO UPDATE SET "
                + ", ".join(f"{c} = excluded.{c}" for c in IMAGE_COLUMNS))
# A version's safe cover that is now an image above PG-13 goes; the grid
# falls back to the version's first safe image until a sync picks it again.
# The restamp's rule, written out again in restamp_levels, which the plan
# keeps as it was (#232); a change to one is made to both.
_CLEAR_UNSAFE_COVERS = ("UPDATE versions SET safe_cover_url = '' WHERE safe_cover_url IN"
                        " (SELECT r.url FROM image_records r WHERE EXISTS (SELECT 1 FROM image_galleries g"
                        " WHERE g.image_id = r.image_id AND g.effective_nsfw_level > ?))")


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


def derived_rows(record: Dict[str, Any], filled: bool) -> Dict[str, Any]:
    """
    What the database makes from an image's record, for search and filters:
    its prompt and negative prompt, its settings row (#378) and its level -
    worked out, never written. From its data filled from its ComfyUI graph
    when `filled` (#232), Civitai's alone when not; the record itself stays
    Civitai's either way. Storing writes them (insert_images), and so does
    the Fill notice's job, each its own way.
    """
    judged = judged_image(record, filled)
    return {"prompt": _text(judged, "prompt"), "negative": _text(judged, "negativePrompt"),
            "settings": image_params_row(judged),
            # Already judged: filled again, its graph would be read twice.
            "level": image_level(judged, False)}  # the rule lives in model_manager.nsfw


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
        for table, column in (("images", "id"), ("image_records", "image_id"), ("image_resources", "image_id"),
                              ("image_params", "image_id")):
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
        gallery rows. Its rows are made from its data filled from its ComfyUI
        graph while the switch is on (derived_rows, #232) - read here, on the
        transaction's own cursor, once it holds the write lock: nothing can
        turn the switch between this read and the rows' write, as it could
        while a store read first waited for the lock and Fill passed it by.
        """
        if not cursor.connection.in_transaction:
            cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT key, value FROM schema_info WHERE key IN (?, ?)", (JUDGED_KEY, FILLED_KEY))
        filled, _ = switch_from(dict(cursor.fetchall()))
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
            rows = derived_rows(record, filled)
            level = rows["level"]
            cursor.execute("SELECT prompt_id, negative_id FROM images WHERE id = ?", (image_id,))
            touched.update(cursor.fetchone() or ())
            cursor.execute(
                "INSERT OR REPLACE INTO images (id, prompt_id, negative_id, width, height, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (image_id, IMAGE_PROMPTS.id_for(cursor, rows["prompt"]),
                 IMAGE_PROMPTS.id_for(cursor, rows["negative"]),
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
            # Its settings (#378), from the record as written: a fresh record
            # giving none takes the stored row with it.
            settings = rows["settings"]
            if settings:
                cursor.execute(_PARAMS_UPSERT, (image_id, *(settings[c] for c in IMAGE_COLUMNS)))
            else:
                cursor.execute("DELETE FROM image_params WHERE image_id = ?", (image_id,))
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
        changed level is written to each of the image's gallery rows, unless
        another writer changed it between this pass's read and its write. A
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
        # One way for the whole pass (#232): the switch read once, not again
        # every few seconds while it judges.
        filled = judging_filled()
        changed = []
        for done, (image_id, data, stored) in enumerate(rows, 1):
            if done % self.RESTAMP_REPORT_EVERY == 0:
                report(done, len(rows))
            if not data:
                continue
            try:
                level = image_level(json.loads(data), filled)
            except (ValueError, TypeError):
                continue
            if level != stored:
                changed.append((level, image_id, image_id, stored))
        report(len(rows), len(rows))
        with self._cursor() as cursor:
            # Only where the image still holds the level read above: another
            # writer judged it since - the Fill notice's job in the other WebUI
            # sharing the database (#232), a gallery stored again - and its
            # level is the newer judgement.
            cursor.executemany("UPDATE image_galleries SET effective_nsfw_level = ? WHERE image_id = ? AND"
                               " (SELECT MAX(g.effective_nsfw_level) FROM image_galleries g WHERE g.image_id = ?)"
                               " IS ?", changed)
            cursor.execute(
                "UPDATE versions SET safe_cover_url = '' WHERE safe_cover_url IN"
                " (SELECT r.url FROM image_records r WHERE EXISTS (SELECT 1 FROM image_galleries g"
                " WHERE g.image_id = r.image_id AND g.effective_nsfw_level > ?))", (SFW_MAX,))
            covers = cursor.rowcount
        return len(changed), len(rows), covers

    # ---------------- the Fill notice's job (#232)

    def graph_record_ids(self) -> List[int]:
        """The images whose records may hold a ComfyUI graph: their text names
        `comfy`. Every record's text is read to find them - 19.9 s warm for
        283,110 records, 5,098 found, on one library - so the Fill notice's
        job does it, never a check a page asks."""
        with self._cursor() as cursor:
            cursor.execute("SELECT image_id FROM image_records WHERE instr(data, '\"comfy\"') > 0")
            return [row[0] for row in cursor.fetchall()]

    def fill_stored(self, image_ids: Iterable[int]) -> Dict[str, int]:
        """
        These images' derived rows made from their data filled from their
        ComfyUI graphs (derived_rows, filled), in one transaction holding the
        write lock: each record read again inside it, so an image a gallery
        removed meanwhile is passed over and one stored again is read as it is
        now. Only what differs is written, and only with UPDATE - an INSERT
        for a settings row an image did not have - so nothing a gallery took
        out comes back. The record is never written. Where filling leaves the
        settings empty, the row is kept as it is.

        Every record holding a graph is compared, not only those the fill
        adds to: a later reader (comfy_graph.READER raised) may fill less
        than the one that wrote the rows.

        Returns:
            read: records holding a graph; gained: of them, those whose rows
            were written; prompts: those that gained a prompt where Civitai
            gives none; levels: those whose level changed. What was written,
            so a run after a run cut short counts only the rest.
        """
        counts = {"read": 0, "gained": 0, "prompts": 0, "levels": 0}
        ids = list(image_ids)
        if not ids:
            return counts
        with self._cursor() as cursor:
            if not cursor.connection.in_transaction:
                cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("SELECT r.image_id, r.data, i.prompt_id, i.negative_id FROM image_records r"
                           f" JOIN images i ON i.id = r.image_id WHERE r.image_id IN ({', '.join('?' * len(ids))})",
                           ids)
            rows = cursor.fetchall()
            touched = set()
            for image_id, data, prompt_id, negative_id in rows:
                try:
                    record = json.loads(data)
                except (TypeError, ValueError, RecursionError):
                    # RecursionError: JSON nested too deep for the original
                    # Forge's Python, which Neo's reads; one such record
                    # would fail its whole batch at every press.
                    continue
                if not isinstance(record, dict) or not has_graph(record.get("meta")):
                    continue
                counts["read"] += 1
                made = derived_rows(record, True)
                wrote = False
                new_prompt = IMAGE_PROMPTS.id_for(cursor, made["prompt"])
                new_negative = IMAGE_PROMPTS.id_for(cursor, made["negative"])
                if (new_prompt, new_negative) != (prompt_id, negative_id):
                    cursor.execute("UPDATE images SET prompt_id = ?, negative_id = ? WHERE id = ?",
                                   (new_prompt, new_negative, image_id))
                    touched.update((prompt_id, negative_id))
                    wrote = True
                    if new_prompt != prompt_id and not (_text(record, "prompt") or "").strip():
                        counts["prompts"] += 1
                settings = made["settings"]
                if settings:
                    cursor.execute(f"SELECT {', '.join(IMAGE_COLUMNS)} FROM image_params WHERE image_id = ?",
                                   (image_id,))
                    held = cursor.fetchone()
                    wanted = tuple(settings[c] for c in IMAGE_COLUMNS)
                    if held is None or tuple(held) != wanted:
                        cursor.execute(_PARAMS_FILL, (image_id, *wanted))
                        wrote = True
                cursor.execute("UPDATE image_galleries SET effective_nsfw_level = ? WHERE image_id = ?"
                               " AND effective_nsfw_level IS NOT ?", (made["level"], image_id, made["level"]))
                if cursor.rowcount:
                    counts["levels"] += 1
                    wrote = True
                counts["gained"] += wrote
            IMAGE_PROMPTS.drop_unused(cursor, touched)
        return counts

    def clear_unsafe_covers(self) -> int:
        """Versions' safe covers now above PG-13 cleared, by the restamp's
        rule: how many."""
        with self._cursor() as cursor:
            cursor.execute(_CLEAR_UNSAFE_COVERS, (SFW_MAX,))
            return cursor.rowcount

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

    def checkpoint_image_settings(self, version_id: int) -> List[Dict[str, Any]]:
        """
        The settings the stored Civitai images naming a checkpoint version were
        made with (#378), grouped: each distinct sampler, schedule type,
        scheduler, steps, CFG, Distilled CFG Scale and Shift, how many images
        give it, and the newest of them. The version's rows by its own index,
        which holds no role and answers alone: with `role = 'checkpoint'`
        SQLite reads a row per image, 2,600 pages more for one version of 5,761
        images; the version names the checkpoint anyway. An image listing the
        version twice counts once.
        """
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT p.sampler, p.schedule_type, p.scheduler, p.steps, p.cfg, p.distilled_cfg, p.shift,
                       COUNT(DISTINCT p.image_id), MAX(p.image_id)
                FROM image_resources r INDEXED BY idx_image_resources_version
                JOIN image_params p ON p.image_id = r.image_id
                WHERE r.version_id = ?
                GROUP BY 1, 2, 3, 4, 5, 6, 7""", (version_id,))
            return [settings_group(row) for row in cursor.fetchall()]

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

    def filled_records(self, image_ids: Iterable[int]) -> List[Dict[str, Any]]:
        """
        The stored records of these images, each one's data with what Civitai
        left out filled from its ComfyUI graph (comfy_graph.fill, #232): for
        what shows or sends an image. Never for what a sync carries over
        (stored_records), which would store the fill as Civitai's and never
        ask Civitai for its own.
        """
        from ..comfy_graph import fill
        return [{**record, "meta": fill(record["meta"])} if isinstance(record.get("meta"), dict) else record
                for record in self.stored_records(image_ids)]

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
                         require_prompt: bool = False,
                         min_nsfw_level: Optional[int] = None) -> Dict[str, int]:
        """
        Get total and filtered image counts for a version.

        Args:
            max_nsfw_level: If set, the NSFW filter keeps only images at most this level.
            min_nsfw_level: If set instead, it keeps only those above it, a
                missing level included - the switch's NSFW mode (#363).

        Returns:
            Dict with 'total' and 'filtered' counts, and 'hidden' (total - filtered):
            'hidden_nsfw' (or 'hidden_safe', the safe images NSFW mode hides)
            and 'hidden_promptless', what each filter alone hides, and
            'hidden_both', what both do - the three adding up to 'hidden';
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
            if min_nsfw_level is not None:
                nsfw, nsfw_args = ("NOT COALESCE(g.effective_nsfw_level <= ?, 0)",), (min_nsfw_level,)
            else:
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
            safe_count = count("g.effective_nsfw_level <= ?", *prompt, args=(SFW_MAX,))
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
            if min_nsfw_level is not None and require_prompt:
                both = count("COALESCE(g.effective_nsfw_level <= ?, 0)", _UNREADABLE, args=(min_nsfw_level,))
            elif max_nsfw_level is not None and require_prompt:
                # Not kept by the NSFW filter - a missing level included,
                # as its "<= ?" hides that too.
                both = count("NOT COALESCE(g.effective_nsfw_level <= ?, 0)", _UNREADABLE, args=(max_nsfw_level,))
            hidden_by_nsfw = total - nsfw_kept - both

            return {
                "total": total,
                "filtered": filtered,
                "hidden_nsfw": 0 if min_nsfw_level is not None else hidden_by_nsfw,
                "hidden_safe": hidden_by_nsfw if min_nsfw_level is not None else 0,
                "hidden_promptless": nsfw_kept - filtered,
                "hidden_both": both,
                "hidden": total - filtered,
                "nsfw_count": nsfw_count,
                "safe_count": safe_count,
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
