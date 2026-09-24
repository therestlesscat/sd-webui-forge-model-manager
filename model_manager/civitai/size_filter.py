"""
Filtering a Civitai search by the size of what a download would fetch.

Civitai's search takes no size parameter, but every result carries its
versions and their files, each with sizeKB. So unlike the prompt filter this
costs nothing beyond the search itself: the check is a look at data already
in hand.

The size is that of the latest version's primary file - the version the card
shows, and the file a download fetches unless another is picked.
"""
from typing import Any, Callable, Dict, Optional

# Civitai's sizeKB is in KiB, and the browser displays sizes in GiB
# (formatFileSize divides by 1024^3), so a filter of "2 GB" means what the
# cards say is 2 GB.
KB_PER_GB = 1024 * 1024


def primary_file_size_kb(model: Dict[str, Any]) -> Optional[float]:
    """
    Size of the latest version's primary file, in KiB, or None if unknown.

    Civitai lists versions newest first, so the latest is modelVersions[0].
    The primary file is the one Civitai marks primary, else the first - the
    rule DownloadService.pick_file_index and primaryFileIndex() in the
    browser apply when nothing has been picked.
    """
    versions = model.get("modelVersions") or []
    if not versions:
        return None

    files = versions[0].get("files") or []
    if not files:
        return None

    primary = next((f for f in files if f.get("primary")), files[0])
    size = primary.get("sizeKB")
    return float(size) if size else None


def size_range_check(
    min_gb: Optional[float],
    max_gb: Optional[float],
) -> Optional[Callable[[Dict[str, Any]], bool]]:
    """
    A predicate that accepts models whose primary file is within the range.

    Either bound may be missing or zero, meaning unbounded on that side. With
    neither, there is nothing to filter and this returns None, so callers can
    tell "no size filter" from "a filter that happens to pass everything".

    A model whose size is unknown is rejected: with a range asked for, there
    is no showing it is inside it.
    """
    low = min_gb if min_gb and min_gb > 0 else None
    high = max_gb if max_gb and max_gb > 0 else None
    if low is None and high is None:
        return None

    def accept(model: Dict[str, Any]) -> bool:
        size_kb = primary_file_size_kb(model)
        if size_kb is None:
            return False
        size_gb = size_kb / KB_PER_GB
        return (low is None or size_gb >= low) and (high is None or size_gb <= high)

    return accept
