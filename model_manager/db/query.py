"""
Turning a filter bar into one SQL query.

The Model Manager grid asks a lot at once: a text search, a type, a base
model, NSFW levels, licence terms, bookmark state, a sort column, a page. All
of it has to become a single grouped query, because the grid shows one card
per Civitai model while the library stores one row per local file.

The grouping is the reason this is not a simple SELECT. A model with four
local versions is one card, and the card has to show the newest version, the
least NSFW preview and a count - so the query picks a representative version
per group rather than returning all four.

Kept apart from models_ops.py because reading rows and composing a query out
of user choices are different jobs; this one changes whenever the filter bar
does.
"""
import json
import os
import time

from ..nsfw import SFW_MAX, UNKNOWN, max_mode_ceiling, model_level_sql

# How many of a version's images "Only with SFW images" looks at - the same
# sample the Civitai Browser judges a model by (PROMPT_SAMPLE_SIZE there).
SFW_SAMPLE_SIZE = 20
from typing import Any, Callable, Dict, List, Optional, Tuple


def _targeted_search_condition(search: str) -> Optional[Tuple[str, Any]]:
    """
    Turn a "prefix:value" search into an exact lookup.

    Lets something else - the Civitai Browser's "Show in Model Manager"
    button, say - point at one specific model instead of hoping a free-text
    search happens to match it.

    Supported: model:<id>, version:<id>, hash:<any hash>, file:<name>.
    Anything else (including a plain search that happens to contain a
    colon) returns None so the caller falls back to free-text matching.

    Returns:
        Tuple of (SQL condition with one placeholder, value), or None.
    """
    prefix, separator, value = search.partition(":")
    if not separator:
        return None

    prefix = prefix.strip().lower()
    value = value.strip()
    if not value:
        return None

    if prefix in ("model", "version") and value.isdigit():
        column = "v.model_id" if prefix == "model" else "v.id"
        return f"{column} = ?", int(value)

    if prefix == "hash":
        # file_hashes is a JSON object of hash type -> uppercase hash
        return "UPPER(COALESCE(v.file_hashes, '')) LIKE ?", f"%{value.upper()}%"

    if prefix == "file":
        return "v.file_name LIKE ?", f"%{value}%"

    return None


def query_models_grouped(
    cursor_factory: Callable,
    search: Optional[str] = None,
    model_type: Optional[str] = None,
    base_model: Optional[str] = None,
    nsfw_levels: Optional[List[int]] = None,
    nsfw_mode: str = "max",
    has_civitai: Optional[bool] = None,
    is_bookmarked: Optional[bool] = None,
    min_versions: Optional[int] = None,
    sort_by: str = "file_modified",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    preview_least_nsfw: bool = True,
    commercial_use: Optional[str] = None,
    allow_derivatives: Optional[str] = None,
    allow_different_license: Optional[str] = None,
    checkpoint_type: Optional[str] = None,
    sfw_only: bool = False
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Query models grouped by civitai_model_id.
    Returns latest version per group with version count.

    Args:
        preview_least_nsfw: If True, preview is image with lowest NSFW level.
                           If False, preview is most recent image by created_at.
    """
    conditions = []
    params = []

    # Build WHERE conditions for versions
    if search:
        targeted = _targeted_search_condition(search)
        if targeted:
            condition, value = targeted
            conditions.append(condition)
            params.append(value)
        else:
            conditions.append("""(
                v.file_name LIKE ? OR
                v.trained_words LIKE ? OR
                COALESCE(m.name, v.file_name) LIKE ? OR
                COALESCE(m.tags, '[]') LIKE ?
            )""")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    if model_type:
        conditions.append("COALESCE(m.type, 'Unknown') = ?")
        params.append(model_type)

    if base_model:
        conditions.append("v.base_model = ?")
        params.append(base_model)

    if nsfw_levels:
        # The same rule as nsfw.model_level(), expressed for the database so
        # the grid can filter without loading every row.
        effective_level_expr = model_level_sql(
            "m.nsfw_level",
            "v.nsfw_level",
            "SELECT MAX(effective_nsfw_level) FROM images WHERE version_id = v.id",
        )

        if nsfw_mode == "contains":
            # Exactly the chosen levels, nothing else.
            placeholders = ','.join(['?'] * len(nsfw_levels))
            conditions.append(f"({effective_level_expr}) IN ({placeholders})")
            params.extend(nsfw_levels)
        else:
            # Everything up to the highest chosen level. See max_mode_ceiling
            # for why this is a `<` against a doubled bound.
            conditions.append(f"({effective_level_expr}) < ?")
            params.append(max_mode_ceiling(nsfw_levels))

    if has_civitai is not None:
        conditions.append("v.has_civitai_data = ?")
        params.append(1 if has_civitai else 0)

    if is_bookmarked is not None:
        conditions.append("COALESCE(m.is_bookmarked, 0) = ?")
        params.append(1 if is_bookmarked else 0)

    # License filters (only apply to models with Civitai data)
    # allow_commercial_use is stored as PostgreSQL-style array literal: "{Image,RentCivit,Rent}"
    # Filter can have multiple comma-separated values; model matches if it contains ANY of them
    if commercial_use:
        values = [v.strip() for v in commercial_use.split(',') if v.strip()]
        if values:
            value_conditions = []
            for v in values:
                # Boundary-aware matching: value must be delimited by { } or ,
                # Matches: {V} (only), {V,... (first), ...,V} (last), ...,V,... (middle)
                value_conditions.append(
                    "(m.allow_commercial_use LIKE ? OR "
                    "m.allow_commercial_use LIKE ? OR "
                    "m.allow_commercial_use LIKE ? OR "
                    "m.allow_commercial_use LIKE ?)"
                )
                params.extend([f"{{{v}}}", f"{{{v},%", f"%,{v}}}", f"%,{v},%"])
            conditions.append("(" + " OR ".join(value_conditions) + ")")

    # Four-valued, because the data is: a model with no Civitai row has
    # no licence at all, and the LEFT JOIN leaves these NULL. "unknown"
    # is the only way to ask for those - "true"/"false" exclude them,
    # which is why picking either quietly drops every unsynced model.
    # Trained or merged, which only checkpoints have. Three-valued like the
    # licence columns: NULL is a model nobody has established it for, which is
    # every model Civitai no longer serves.
    if checkpoint_type == "unknown":
        conditions.append("m.checkpoint_type IS NULL")
    elif checkpoint_type in ("Trained", "Merge"):
        conditions.append("m.checkpoint_type = ?")
        params.append(checkpoint_type)

    for column, choice in (
        ("allow_derivatives", allow_derivatives),
        ("allow_different_license", allow_different_license),
    ):
        if choice == "unknown":
            conditions.append(f"m.{column} IS NULL")
        elif choice in ("true", "false"):
            conditions.append(f"m.{column} = ?")
            params.append(1 if choice == "true" else 0)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort field. Text sorts ignore case: SQLite's default collation
    # compares bytes, which put every capitalised name before every
    # lowercase one - "Zeta" ahead of "alpha".
    valid_sort_fields = {
        "name": "COALESCE(cm_name, file_name) COLLATE NOCASE",
        "display_name": "COALESCE(cm_name, file_name) COLLATE NOCASE",
        "file_name": "file_name COLLATE NOCASE",
        "file_size": "file_size",
        "file_modified": "file_modified",
        "base_model": "base_model COLLATE NOCASE",
        "nsfw_level": "nsfw_level",
        "rating": "COALESCE(cm_stats_rating, 0)",
        "download_count": "COALESCE(cm_stats_download_count, stats_download_count)",
        "published_at": "published_at",
        "scanned_at": "scanned_at",
        # downloaded_at is only set for models fetched through the
        # Civitai Browser. Everything acquired another way falls back
        # to the file timestamp, which is when it landed on disk.
        "downloaded_at": "group_acquired_at",
        "updated_at": "cm_updated_at"
    }
    sort_field = valid_sort_fields.get(sort_by, "file_modified")
    sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

    # Build outer WHERE clause (filters on CTE results)
    outer_conditions = ["rn = 1"]
    outer_params = []
    if min_versions is not None and min_versions > 1:
        outer_conditions.append("local_version_count >= ?")
        outer_params.append(min_versions)
    if sfw_only:
        # "Only with SFW images", as the Civitai Browser asks it: none of the
        # first 20 images of the version the card shows - in the order its
        # gallery shows them - is above PG-13, or unrated. And there has to
        # be at least one: a model with no images has nothing to show it
        # does not generate NSFW, so it is left out too.
        #
        # Asked here, of the one row per model the grid shows, rather than
        # of every version: checking every image of every version took
        # 13.7 s against a library of 101,759 images, the unfiltered grid 1.1.
        outer_conditions.append("""EXISTS (
            SELECT 1 FROM images WHERE version_id = ranked.id
        ) AND NOT EXISTS (
            SELECT 1 FROM (
                SELECT effective_nsfw_level FROM images
                WHERE version_id = ranked.id
                ORDER BY page, id
                LIMIT ?
            ) WHERE effective_nsfw_level > ?
        )""")
        outer_params.extend([SFW_SAMPLE_SIZE, SFW_MAX])
    outer_where = " AND ".join(outer_conditions)

    preview_url_column = "ips.preview_url_least_nsfw" if preview_least_nsfw else "ips.preview_url_recent"

    # Query for latest version per model group
    query = f"""
        WITH filtered_versions AS (
            SELECT
                v.*,
                m.id as cm_id,
                m.name as cm_name,
                m.description as cm_description,
                m.type as cm_type,
                m.nsfw as cm_nsfw,
                m.nsfw_level as cm_nsfw_level,
                m.tags as cm_tags,
                m.creator_username as cm_creator_username,
                m.creator_image_url as cm_creator_image_url,
                m.stats_download_count as cm_stats_download_count,
                m.stats_thumbs_up as cm_stats_thumbs_up,
                m.stats_thumbs_down as cm_stats_thumbs_down,
                m.stats_rating as cm_stats_rating,
                m.allow_no_credit as cm_allow_no_credit,
                m.allow_commercial_use as cm_allow_commercial_use,
                m.checkpoint_type as cm_checkpoint_type,
                m.allow_derivatives as cm_allow_derivatives,
                m.allow_different_license as cm_allow_different_license,
                m.supports_generation as cm_supports_generation,
                m.is_bookmarked as cm_is_bookmarked,
                m.updated_at as cm_updated_at
            FROM model_versions v
            LEFT JOIN civitai_models m ON v.model_id = m.id
            WHERE {where_clause}
        ),
        image_aggregates AS (
            SELECT
                i.version_id,
                MAX(i.effective_nsfw_level) as max_image_nsfw
            FROM images i
            INNER JOIN filtered_versions fv ON fv.id = i.version_id
            GROUP BY i.version_id
        ),
        image_preview_ranked AS (
            SELECT
                i.version_id,
                i.url,
                ROW_NUMBER() OVER (
                    PARTITION BY i.version_id
                    ORDER BY i.effective_nsfw_level ASC, i.created_at DESC, i.id DESC
                ) as rn_least_nsfw,
                ROW_NUMBER() OVER (
                    PARTITION BY i.version_id
                    ORDER BY i.created_at DESC, i.id DESC
                ) as rn_recent
            FROM images i
            INNER JOIN filtered_versions fv ON fv.id = i.version_id
        ),
        image_preview_selected AS (
            SELECT
                version_id,
                MAX(CASE WHEN rn_least_nsfw = 1 THEN url END) as preview_url_least_nsfw,
                MAX(CASE WHEN rn_recent = 1 THEN url END) as preview_url_recent
            FROM image_preview_ranked
            GROUP BY version_id
        ),
        ranked AS (
            SELECT
                fv.*,
                COALESCE(ia.max_image_nsfw, {UNKNOWN}) as max_image_nsfw,
                {preview_url_column} as preview_url,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(fv.model_id, fv.file_path)
                    ORDER BY fv.published_at DESC NULLS LAST
                ) as rn,
                COUNT(*) OVER (
                    PARTITION BY COALESCE(fv.model_id, fv.file_path)
                ) as local_version_count,
                -- Newest acquisition across every version of this model.
                -- The row shown for a group is its latest *published*
                -- version, which is frequently not the one most recently
                -- downloaded - so sorting on the shown row's own date puts
                -- freshly downloaded models in the wrong position.
                MAX(COALESCE(fv.downloaded_at, fv.file_modified)) OVER (
                    PARTITION BY COALESCE(fv.model_id, fv.file_path)
                ) as group_acquired_at
            FROM filtered_versions fv
            LEFT JOIN image_aggregates ia ON ia.version_id = fv.id
            LEFT JOIN image_preview_selected ips ON ips.version_id = fv.id
        )
        SELECT * FROM ranked WHERE {outer_where}
        ORDER BY {sort_field} {sort_dir}
    """

    # Get total count
    count_query = f"""
        WITH filtered_versions AS (
            SELECT
                v.id,
                v.model_id,
                v.file_path,
                v.published_at
            FROM model_versions v
            LEFT JOIN civitai_models m ON v.model_id = m.id
            WHERE {where_clause}
        ),
        ranked AS (
            SELECT
                fv.id,          -- the outer filters may ask about the shown version
                fv.file_path,
                ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(fv.model_id, fv.file_path)
                    ORDER BY fv.published_at DESC NULLS LAST
                ) as rn,
                COUNT(*) OVER (
                    PARTITION BY COALESCE(fv.model_id, fv.file_path)
                ) as local_version_count
            FROM filtered_versions fv
        )
        SELECT COUNT(*) FROM ranked WHERE {outer_where}
    """

    # Combine inner params (WHERE clause) with outer params (version count filter)
    all_params = params + outer_params

    count_start = time.perf_counter()
    with cursor_factory() as cursor:
        cursor.execute(count_query, all_params)
        total_count = cursor.fetchone()[0]
    count_ms = (time.perf_counter() - count_start) * 1000

    data_start = time.perf_counter()
    with cursor_factory() as cursor:
        paginated_query = f"{query} LIMIT ? OFFSET ?"
        cursor.execute(paginated_query, all_params + [limit, offset])
        rows = cursor.fetchall()
    data_ms = (time.perf_counter() - data_start) * 1000

    print(
        f"[ModelManager] query_models_grouped count_ms={count_ms:.1f} data_ms={data_ms:.1f} "
        f"rows={len(rows)} total={total_count}"
    )

    models = [_grouped_row_to_dict(row) for row in rows]
    return models, total_count

# ==================== Utility Methods ====================


def _grouped_row_to_dict(row) -> Dict[str, Any]:
    """Convert a grouped query row (version + model) to a dictionary."""
    result = {
        "id": row["id"],
        "model_id": row["model_id"],
        "version_name": row["version_name"],
        "base_model": row["base_model"],
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "nsfw_level": row["nsfw_level"],
        "trained_words": json.loads(row["trained_words"] or "[]"),
        "description": row["description"],
        "stats_download_count": row["stats_download_count"],
        "stats_thumbs_up": row["stats_thumbs_up"],
        "file_path": row["file_path"],
        "file_name": row["file_name"],
        "file_size": row["file_size"],
        "file_hashes": json.loads(row["file_hashes"]) if row["file_hashes"] else None,
        "file_modified": row["file_modified"],
        "file_extension": row["file_extension"],
        "preview_url": row["preview_url"] if "preview_url" in row.keys() else None,
        "has_civitai_data": bool(row["has_civitai_data"]),
        "scanned_at": row["scanned_at"],
        "downloaded_at": row["downloaded_at"] if "downloaded_at" in row.keys() else None,
        "next_images_cursor": row["next_images_cursor"] if "next_images_cursor" in row.keys() else None,
        "images_sync_last_date": row["images_sync_last_date"] if "images_sync_last_date" in row.keys() else None,
        "local_version_count": row["local_version_count"],
        # Newest acquisition across the group - what the default sort uses,
        # and the honest "when did I get this" for a grouped model
        "group_acquired_at": row["group_acquired_at"] if "group_acquired_at" in row.keys() else None,
        "max_image_nsfw": row["max_image_nsfw"],
        "is_bookmarked": bool(row["cm_is_bookmarked"]) if row["cm_is_bookmarked"] else False,
        "updated_at": row["cm_updated_at"] if "cm_updated_at" in row.keys() else None,
    }

    # Civitai model data (if available)
    if row["cm_id"]:
        result["civitai_model"] = {
            "id": row["cm_id"],
            "name": row["cm_name"],
            "description": row["cm_description"],
            "type": row["cm_type"],
            "nsfw": bool(row["cm_nsfw"]),
            "nsfw_level": row["cm_nsfw_level"],
            "tags": json.loads(row["cm_tags"] or "[]"),
            "creator_username": row["cm_creator_username"],
            "creator_image_url": row["cm_creator_image_url"],
            "stats_download_count": row["cm_stats_download_count"],
            "stats_thumbs_up": row["cm_stats_thumbs_up"],
            "stats_thumbs_down": row["cm_stats_thumbs_down"],
            "stats_rating": row["cm_stats_rating"],
            "allow_no_credit": bool(row["cm_allow_no_credit"]) if row["cm_allow_no_credit"] is not None else True,
            "allow_commercial_use": row["cm_allow_commercial_use"],
            "checkpoint_type": row["cm_checkpoint_type"] if "cm_checkpoint_type" in row.keys() else None,
        "allow_derivatives": bool(row["cm_allow_derivatives"]) if row["cm_allow_derivatives"] is not None else True,
            "allow_different_license": bool(row["cm_allow_different_license"]) if row["cm_allow_different_license"] is not None else True,
            "supports_generation": bool(row["cm_supports_generation"]) if row["cm_supports_generation"] is not None else False,
        }
        result["display_name"] = row["cm_name"]
        result["model_type"] = row["cm_type"]
        result["tags"] = json.loads(row["cm_tags"] or "[]")
        result["creator"] = row["cm_creator_username"]
        result["download_count"] = row["cm_stats_download_count"] or row["stats_download_count"]
        result["rating"] = row["cm_stats_rating"] or 0
        result["thumbs_up"] = row["cm_stats_thumbs_up"] or 0
        result["thumbs_down"] = row["cm_stats_thumbs_down"] or 0
    else:
        result["civitai_model"] = None
        result["display_name"] = os.path.splitext(row["file_name"])[0]
        result["model_type"] = "Unknown"
        result["tags"] = []
        result["creator"] = None
        result["download_count"] = row["stats_download_count"] or 0
        result["rating"] = 0
        result["thumbs_up"] = row["stats_thumbs_up"] or 0
        result["thumbs_down"] = 0

    return result
