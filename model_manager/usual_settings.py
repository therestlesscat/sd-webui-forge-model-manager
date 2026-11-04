"""
What a checkpoint is usually run with (#378): for a checkpoint picked in the
Resources dialog in place of the image's own, the sampler, schedule type,
steps and CFG scale most used with it - and, where its UI preset takes one
in this WebUI, its Distilled CFG Scale or Shift - beside the image's own, for
the dialog to show and Send to use when ticked.

The user's own generations with it answer when 5 or more record settings,
while the Generations tab is on; else the stored Civitai images naming its
version, when 5 or more do; else nothing. Every file of the pick's version
counts: two WebUIs sharing a database each record their own copy's path.
The counting reads the settings rows each image and generation keeps
(`db/params_table.py`), grouped in SQL; the values are split by Send's own
rule (`send.sampler_and_scheduler`) and matched to this WebUI's lists.
"""
from typing import Any, Dict, List, Optional, Tuple

# The uses a source needs to answer, and a setting to be more than "not
# recorded enough": under 5, one odd generation is a fifth of the answer.
MIN_USES = 5
FOUR = ("sampler", "schedule_type", "steps", "cfg")
# The fifth setting's column, by what `forge_host.extra_cfg` names.
EXTRA_COLUMNS = {"distilled": "distilled_cfg", "shift": "shift"}


def most_used(values: List[Tuple[Any, int, int]]) -> Optional[Dict[str, Any]]:
    """
    The most used of `values` - (value, uses, newest id) per group, a value
    in several groups added up - with its count and the uses that record
    one: {value, count, of}. A tie goes to the value of the newest use, so
    the answer is the same whatever order the rows come in. None where no
    use records a value.
    """
    counts: Dict[Any, List[int]] = {}
    for value, uses, newest in values:
        if value is None:
            continue
        seen = counts.setdefault(value, [0, 0])
        seen[0] += uses
        seen[1] = max(seen[1], newest or 0)
    if not counts:
        return None
    value, (count, _) = max(counts.items(), key=lambda item: (item[1][0], item[1][1]))
    return {"value": value, "count": count, "of": sum(c for c, _ in counts.values())}


def _shown(value: Any) -> Any:
    """A number as the dialog shows it: CFG 7.0 is 7."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _named(row: Dict[str, Any], samplers: List[Any], schedulers: List[Any]) -> Dict[str, Any]:
    """
    A settings row's sampler and schedule type as Send reads them
    (`sampler_and_scheduler`): Civitai's `Undefined` is Euler, as both WebUIs
    paste it; Automatic, which Send's lists leave out, is kept as named.
    """
    from .send import sampler_and_scheduler
    sampler = row.get("sampler")
    if sampler == "Undefined":
        sampler = "Euler"
    named = sampler_and_scheduler({"sampler": sampler, "Schedule type": row.get("schedule_type"),
                                   "scheduler": row.get("scheduler")}, samplers, schedulers)
    # ComfyUI's `scheduler` this WebUI lists none of is counted by its name,
    # to be marked missing, as Send's notice names it (`missing_names`) -
    # never dropped, which would leave the row to the uses that remain.
    schedule = named["scheduler"] or row.get("scheduler")
    return {**row, "sampler": named["sampler"], "schedule_type": schedule}


def _missing(key: str, value: Any, samplers: List[Any], schedulers: List[Any]) -> bool:
    """Whether this WebUI lists no such sampler or schedule type; never where its lists could not be read."""
    from .send import _label
    if value is None or key not in ("sampler", "schedule_type") or not samplers:
        return False
    if key == "schedule_type" and value == "Automatic":
        return False
    return value not in [_label(s) for s in (samplers if key == "sampler" else schedulers)]


def _recorded(row: Dict[str, Any]) -> bool:
    return any(row.get(k) is not None for k in (*FOUR, "distilled_cfg", "shift"))


def _source_groups(db, picked: str) -> Tuple[Optional[str], List[Dict[str, Any]], int]:
    """
    Which source answers for the file Forge lists the pick under, and its
    groups of settings: ("yours", groups, uses), ("civitai", ...), or
    (None, [], 0) for neither having 5 uses that record a setting.
    """
    from .tabs import on
    if on("generations"):
        groups = [g for g in db.checkpoint_generation_settings(db.generation_gallery_files(picked)) if _recorded(g)]
        uses = sum(g["uses"] for g in groups)
        if uses >= MIN_USES:
            return "yours", groups, uses
    version = (db.get_version(picked) or {}).get("id")
    if version:
        groups = [g for g in db.checkpoint_image_settings(int(version)) if _recorded(g)]
        uses = sum(g["uses"] for g in groups)
        if uses >= MIN_USES:
            return "civitai", groups, uses
    return None, [], 0


def _image_own(db, source: Dict[str, Any], samplers: List[Any], schedulers: List[Any]) -> Dict[str, Any]:
    """
    The image's own settings, read from the source's own record or text by
    the same readings as the rows (`image_params_row`, `generation_params_row`),
    and whether it had Hires fix, whose own settings stay the image's.
    """
    from .db.params_table import generation_params_row, image_params_row, record_meta
    from .send import had_hires
    if source.get("kind") == "generation":
        generation = db.get_generation(int(source.get("generation") or 0)) or {}
        images = generation.get("images") or []
        image = next((i for i in images if i.get("id") == source.get("image")), images[0] if images else {})
        meta = image.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        text = (generation.get("infotext") if source.get("whole") else None) or image.get("infotext")
        row = generation_params_row(text, None if text else meta)
    else:
        record = next(iter(db.stored_records([int(source.get("image") or 0)])), None) or {}
        meta = record_meta(record) if isinstance(record.get("meta") or {}, dict) else {}
        row = image_params_row(record)
    row = _named(row or {}, samplers, schedulers)
    own = {k: _shown(row.get(k)) for k in (*FOUR, "distilled_cfg", "shift")}
    return {**own, "hires": had_hires(meta)}


def chosen(db, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    The usual settings a Send applies, by key: each with a value 5 or more
    uses record that this WebUI lists. None without `usual` in the source,
    without a pick it applies to - an as-made one, or one Forge no longer
    lists - or with nothing to apply. Worked out again at the Send, by the
    function the dialog asked: the page sends the tick, never the values.
    Asked by Send's callers and handed to send.settings(), which this module
    reads. A failure to read them is said, and the Send goes with the image's.
    """
    if not source.get("usual") or not source.get("use_checkpoint"):
        return None
    try:
        answer = usual(db, source["use_checkpoint"], source)
    except Exception as e:
        # The Send goes with the image's settings, and says what went.
        from .console import say_failure
        say_failure(f"Send: the usual settings could not be read: {e}")
        return None
    # A pick they do not apply to answers no settings.
    found = {row["key"]: row["value"] for row in answer.get("settings") or []
             if row.get("value") is not None and not row.get("thin") and not row.get("missing")}
    return found or None


def usual(db, checkpoint: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """
    What the checkpoint Forge lists as `checkpoint` is usually run with, for
    an image sent with it: `source` as Send takes it (`send/plan`).

        applies   whether the pick is not as made (pick_kind's `file`,
                  `version` or `model`): for `own` and `same` - and a pick
                  Forge no longer lists - the rest is left out
        source    "yours", "civitai", or None for not enough to go by
        uses      the uses that source has that record a setting
        settings  per setting, in the dialog's order - the four, then the
                  fifth where the pick's preset takes one: {key, value,
                  count, of, thin (under 5 record it), missing (this WebUI
                  lists no such sampler or schedule type)}; value None for
                  none recorded
        extra     "distilled", "shift", or None: what the pick's preset
                  takes beside CFG in this WebUI (forge_host.extra_cfg)
        image     the image's own values, and `hires`
    """
    from .forge_host import extra_cfg
    from .send import _picked, _source_pick_kind, forge_lists
    kind = _source_pick_kind(db, {**source, "use_checkpoint": checkpoint})
    if kind in (None, "own", "same"):
        return {"applies": False, "kind": kind}
    picked = _picked(db, checkpoint)
    if not picked:
        return {"applies": False, "kind": None}
    samplers, schedulers = forge_lists()
    # The preset a sync read of the file (`files.architecture`): the ask reads
    # no file, so one no sync has read gets no fifth row.
    extra = extra_cfg((db.get_version(picked) or {}).get("architecture"))
    found, groups, uses = _source_groups(db, picked)
    if found == "civitai" and extra == "distilled":
        # Civitai's Flux images give their CFG as `cfgScale`, which the
        # original Forge's own paste reads as Distilled CFG Scale, with CFG 1.
        groups = [{**g, "distilled_cfg": g["cfg"], "cfg": 1.0}
                  if g["distilled_cfg"] is None and g["cfg"] is not None else g for g in groups]
    groups = [_named(g, samplers, schedulers) for g in groups]
    keys: List[str] = list(FOUR)
    column = EXTRA_COLUMNS.get(extra or "")
    if column:
        recorded = sum(g["uses"] for g in groups if g[column] is not None)
        # Neo writes a Shift only when the loaded model uses one: an SDXL
        # pick none of whose uses record one gets no fifth row.
        if column != "shift" or recorded >= MIN_USES:
            keys.append(column)
    rows = []
    for key in keys:
        best = most_used([(g[key], g["uses"], g["newest"]) for g in groups]) if found else None
        value = _shown(best["value"]) if best else None
        rows.append({"key": key, "value": value, "count": best["count"] if best else 0,
                     "of": best["of"] if best else 0, "thin": not best or best["of"] < MIN_USES,
                     "missing": _missing(key, value, samplers, schedulers)})
    return {"applies": True, "kind": kind, "source": found, "uses": uses, "settings": rows,
            "extra": extra if column in keys else None, "image": _image_own(db, source, samplers, schedulers)}
