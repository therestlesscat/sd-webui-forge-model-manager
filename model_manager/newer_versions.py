"""
Whether a model has a version newer than any the library holds (#218).

Newer means listed before every held version, in Civitai's order - the order
a card's shown version, the details panel's "newest" and Download selected
all take. Published dates are not asked: versions share a date to the
millisecond, or have none. The rule reads a version's place in its list,
not its `index`: a stored list is kept in Civitai's order, by `index` where
it has one and newest first where it does not (`_civitai_order`), and a
search answers in Civitai's order - so a list merged from sidecars reads as
one Civitai gave.

The rule lives here twice, as `nsfw.py` keeps a level and its SQL: in Python
for the cards' badge, in SQL for the Model Manager's Newer Version filter.
`newer_versions_test.py` puts every case to both.
"""
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .civitai.licensing import on_site_only, paid_access_info


def newer_versions(listed: List[Dict[str, Any]], held_ids: Iterable[int]) -> List[Dict[str, Any]]:
    """
    The versions listed before the first held one, in list order: none when
    nothing is held, no held version is listed (Civitai deleted it), or the
    first held is first.
    """
    held = set(held_ids)
    for place, version in enumerate(listed or []):
        if version.get("id") in held:
            return list(listed[:place])
    return []


def describe(versions: List[Dict[str, Any]],
             usage_controls: Optional[Mapping[int, str]] = None) -> List[Dict[str, Any]]:
    """
    What a card says of each newer version, both tabs alike: its id, name,
    base model, "Paid" or "Early Access", and whether Civitai allows it only
    on its site - from the stored lookups by hash, where the caller has them
    (the Model Manager); None, unknown, where not (the Civitai Browser's page
    adds what its own marks asked).
    """
    words = usage_controls or {}
    described = []
    for version in versions:
        paid = paid_access_info(version)
        described.append({
            "id": version.get("id"),
            "name": version.get("name") or "",
            "base_model": version.get("baseModel") or "",
            "paid": None if not paid else ("Paid" if paid.get("permanent") else "Early Access"),
            "on_site_only": on_site_only(words.get(version.get("id"))),
        })
    return described


# The same, of the model the version `{version_id}` belongs to: some version
# sits earlier in its stored list than the first one with a file in the
# library. A version id of NULL - a file Civitai does not know - has no model,
# and no newer version.
NEWER_SQL = """EXISTS (
    SELECT 1 FROM versions nv JOIN models nm ON nm.id = nv.model_id
    WHERE nv.id = {version_id} AND nm.versions IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM json_each(nm.versions) j
        WHERE CAST(j.key AS INTEGER) < (
            SELECT MIN(CAST(h.key AS INTEGER)) FROM json_each(nm.versions) h
            WHERE EXISTS (SELECT 1 FROM files f
                          WHERE f.version_id = json_extract(h.value, '$.id'))
        )
      )
)"""
