"""
Reading a model's terms.

Civitai gates some versions behind Buzz, and says so in a field that does not
appear in `availability` - which stays "Public" either way. Downloading one
without having bought it fails with 401, so it has to be spotted first.
"""
from typing import Any, Dict, Optional


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
