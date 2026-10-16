"""
Reading a model's terms.

Civitai gates some versions behind Buzz, and says so in a field that does not
appear in `availability` - which stays "Public" either way. Downloading one
without having bought it fails with 401, so it has to be spotted first.

And a creator can allow a version only for generating on Civitai's site
(#229): its `usageControl` is then anything but "Download", and its download
answers 401. Only Civitai's lookup by file hash says so - not the search,
nor a model's answer - up to 100 versions a request.
"""
from typing import Any, Dict, Iterable, List, Optional


def paid_access_info(version_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Describe the paywall on a model version, or None if it is free.

    Civitai gates a version behind Buzz in two ways, and neither shows up in
    `availability`, which stays "Public" for both:

      - early access: `paidAccess.endsAt` (also `earlyAccessDeadline`) is the
        moment it becomes free
      - permanent: `paidAccess.permanent` is true and it never does

    Downloading either without having bought it returns HTTP 401/403.

    Returns:
        Dict with 'permanent' and 'ends_at', or None when the version is free.
    """
    paid = version_data.get("paidAccess")
    deadline = version_data.get("earlyAccessDeadline")

    if not isinstance(paid, dict):
        # Some responses carry only the deadline.
        if deadline:
            return {"permanent": False, "ends_at": deadline}
        return None

    permanent = bool(paid.get("permanent"))
    ends_at = paid.get("endsAt") or deadline

    if not permanent and not ends_at:
        return None

    return {"permanent": permanent, "ends_at": ends_at}


def on_site_only(usage_control: Any) -> Optional[bool]:
    """
    Whether Civitai's `usageControl` word keeps a version from downloading:
    any word but "Download" does (Civitai's getFileForModelVersion). None
    when there is no word - Civitai not asked, or not answering - never a
    guess either way.
    """
    if not isinstance(usage_control, str) or not usage_control:
        return None
    return usage_control != "Download"


def look_up_versions(client, hashes: Iterable[str]) -> List[Dict[str, Any]]:
    """Civitai's lookup by hash for all of these, 100 a request: each version it answers, as it sent it."""
    wanted = sorted({h.upper() for h in hashes if h})
    batch = client.VERSIONS_BY_HASH_BATCH
    found: List[Dict[str, Any]] = []
    for start in range(0, len(wanted), batch):
        found.extend(client.get_versions_by_hashes(wanted[start:start + batch]))
    return found


def versions_on_site_only(client, hashes_by_version: Dict[int, str]) -> Dict[int, bool]:
    """
    {version id: on-site only} for these versions, by their files' hashes. A
    version Civitai does not answer is left out: unknown, never "on-site only".
    """
    asked = {int(v) for v in hashes_by_version}
    answer: Dict[int, bool] = {}
    for version in look_up_versions(client, hashes_by_version.values()):
        vid = version.get("id")
        said = on_site_only(version.get("usageControl"))
        if isinstance(vid, int) and vid in asked and said is not None:
            answer[vid] = said
    return answer
