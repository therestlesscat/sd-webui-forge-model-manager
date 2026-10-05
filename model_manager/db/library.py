"""
A file in the library and its version, read as one row.

A Civitai version is one row of `versions`; each of its files is a row of
`files`, naming it by version_id - NULL for a file Civitai does not know
(#133). model_versions held both in one row per file, a copy of the version
in each, and they drifted. Most of what reads the library still
wants a file with its version beside it - a card, the details panel, a lookup
by path or hash - and reads it through LIBRARY, which gives the row
model_versions did: `id` the version's, `has_civitai_data` whether the file
has one. What is written goes to the one table it belongs to.
"""

# A file with no version reads as PG, to be visible when new, with no words
# and no stats: what the walk wrote into its row. A version reads
# as stored, NULL and all.
LIBRARY = """(
    SELECT f.*, f.version_id AS id, f.rowid AS file_order,
           f.version_id IS NOT NULL AS has_civitai_data,
           cv.model_id, cv.version_name, cv.base_model, cv.published_at, cv.created_at,
           CASE WHEN cv.id IS NULL THEN 1 ELSE cv.nsfw_level END AS nsfw_level,
           CASE WHEN cv.id IS NULL THEN '[]' ELSE cv.trained_words END AS trained_words,
           cv.description,
           CASE WHEN cv.id IS NULL THEN 0 ELSE cv.stats_download_count END AS stats_download_count,
           CASE WHEN cv.id IS NULL THEN 0 ELSE cv.stats_thumbs_up END AS stats_thumbs_up,
           cv.cover_url, cv.safe_cover_url, cv.next_images_cursor, cv.images_sync_last_date
    FROM files f
    LEFT JOIN versions cv ON cv.id = f.version_id
)"""
