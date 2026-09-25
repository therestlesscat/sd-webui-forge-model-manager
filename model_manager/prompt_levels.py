"""
Keeping stored image levels in step with the NSFW prompt words.

An image's level is stamped when it is stored (images_ops.store_images), and
every view filters on the stamp - in SQL, over the whole library, which is
why it is stamped rather than judged each time (2.7 s a query against 4 ms).
So when the words change - an update to the bundled list, or an edit in the
settings - the stamps are redone, once, from the payloads already stored:
about three seconds for 100,000 images, and nothing asked of Civitai.

The words' fingerprint is kept in the metadata table once a pass finishes.
A pass that is cut short is run again at the next start.
"""
import threading
from typing import Optional

from .nsfw import prompt_words_fingerprint

FINGERPRINT_KEY = "nsfw_prompt_words"

_lock = threading.Lock()
_running = False
_again = False


def bring_up_to_date(db) -> Optional[int]:
    """
    Restamp every stored image if the words changed since the last pass.

    Returns:
        How many images changed level, or None if nothing needed doing.
    """
    fingerprint = prompt_words_fingerprint()
    if db.get_metadata(FINGERPRINT_KEY) == fingerprint:
        return None
    changed, total, covers = db.restamp_image_levels()
    db.set_metadata(FINGERPRINT_KEY, fingerprint)
    print(f"[ModelManager] NSFW prompt words: {changed} of {total} images judged again"
          + (f", {covers} safe covers cleared" if covers else ""))
    return changed


def start_in_background() -> None:
    """
    bring_up_to_date() on a thread, so neither the WebUI's start nor a
    settings save waits for it. Asked again while running, it runs once more
    afterwards, with the words as they are then.
    """
    global _running, _again
    with _lock:
        if _running:
            _again = True
            return
        _running = True

    def run():
        global _running, _again
        while True:
            try:
                from .db import get_models_db
                bring_up_to_date(get_models_db())
            except Exception as e:
                print(f"[ModelManager] Could not apply the NSFW prompt words: {e}")
            with _lock:
                if not _again:
                    _running = False
                    return
                _again = False

    threading.Thread(target=run, name="mm-prompt-levels", daemon=True).start()
