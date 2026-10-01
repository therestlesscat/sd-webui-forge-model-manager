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
import time
from typing import Callable, Dict, Iterable, Optional

OWNED_TTL = 300.0

_state: Dict[str, object] = {"key": None, "user_id": None, "owned": {}}


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
        if _state["key"] != key:
            _state.update(key=key, user_id=None, owned={})
        owned: Dict[int, tuple] = _state["owned"]  # id -> (bought, when asked)
        if _state["user_id"] is None:
            _state["user_id"] = (client.whoami() or {}).get("id")
        if not _state["user_id"]:
            return None
        stale = [i for i in ids if i not in owned or now() - owned[i][1] > OWNED_TTL]
        if stale:
            answered = client.check_permissions(stale, _state["user_id"])
            for i in stale:
                owned[i] = (bool(answered.get(i)), now())
        return {i: owned[i][0] for i in ids}
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
