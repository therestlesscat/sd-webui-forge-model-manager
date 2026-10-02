"""
Which paid versions the API key's account may download.

A version's payload says it is paid (`paidAccess`) and reads the same to
everyone, key or none: it never says whether the caller bought it. Civitai's
permissions check does. Measured on one account: version 518881, bought, was
`true` there and its download redirected to the file; 712530 was `false` and
its download answered 403 "Early Access" - while the website, logged in,
already downloaded it. Some minutes later the check said `true` and the
download redirected: the API learns of a purchase after the website does.

Asked once for many versions, and remembered a few minutes; the account id
once per key. Any failure leaves the answer unknown (None), never "not
bought".
"""
import hashlib
import threading
import time
from typing import Callable, Dict, Iterable, Optional

from ..remembered import Remembered

OWNED_TTL = 300.0
# The versions asked about for a key: the 2,000 most recent.
OWNED_MOST = 2000

# The key asked with (hashed), its account, and what was asked about for it:
# version id -> (bought, when asked). Requests on several threads share it.
_state: Dict[str, object] = {"key": None, "user_id": None, "owned": Remembered(OWNED_MOST)}
_lock = threading.Lock()


def _client():
    from .client import CivitaiClient
    return CivitaiClient.from_settings()


def owned_versions(version_ids: Iterable[int], client_factory: Callable = _client,
                   now: Callable[[], float] = time.monotonic) -> Optional[Dict[int, bool]]:
    """
    {version id: bought} for these versions, or None when it cannot be known:
    no API key, or Civitai could not be asked.
    """
    ids = sorted({int(v) for v in version_ids if v})
    if not ids:
        return {}
    client = client_factory()
    try:
        if not getattr(client, "api_key", None):
            return None
        key = hashlib.sha256(client.api_key.encode("utf-8")).hexdigest()
        with _lock:
            if _state["key"] != key:
                _state.update(key=key, user_id=None, owned=Remembered(OWNED_MOST))
            owned, user_id = _state["owned"], _state["user_id"]
        if user_id is None:
            user_id = (client.whoami() or {}).get("id")
            with _lock:
                if _state["key"] == key:
                    _state["user_id"] = user_id
        if not user_id:
            return None
        # Read once each: another request may drop one between asking and reading.
        known = {i: owned.get(i) for i in ids}
        stale = [i for i, entry in known.items() if entry is None or now() - entry[1] > OWNED_TTL]
        if stale:
            answered = client.check_permissions(stale, user_id)
            for i in stale:
                known[i] = owned[i] = (bool(answered.get(i)), now())
        return {i: known[i][0] for i in ids}
    except Exception as e:
        print(f"[ModelManager] Could not ask Civitai which paid versions are yours: {e}")
        return None
    finally:
        if hasattr(client, "close"):
            client.close()


def mark_owned(versions: Iterable[dict]) -> None:
    """
    Add `owned` to each paid version's `paid_access`, in place: True when
    the key's account bought it, False when not, None when unknown.
    """
    paid = [v for v in versions if isinstance(v.get("paid_access"), dict) and v.get("id")]
    if not paid:
        return
    owned = owned_versions(v["id"] for v in paid)
    for version in paid:
        version["paid_access"]["owned"] = None if owned is None else owned.get(int(version["id"]))
