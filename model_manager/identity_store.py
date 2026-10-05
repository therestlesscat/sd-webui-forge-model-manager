"""
What a model file is, read once and kept with its row.

file_identity.py says what a file is; this stores that on the file's version
row, and says when it has to be asked again - when the file has changed since
it was last read. A sync's walk, a download and Send to txt2img all read
a file through here, so a file is read once per change, whoever comes first.
"""
from typing import Optional

from .architecture import Architecture
from .file_identity import identify
from .model_dirs import file_modified


def needs_check(db, path: str, force: bool = False) -> Optional[str]:
    """
    The file's modified time if its architecture should be read, else None.

    A file already read at this modified time is skipped - including one
    Forge did not recognise, which is stored as None so it is not read again
    until it changes. A file with no row yet is read: its row is about to be
    written. `force` reads it anyway: the sync's "Read every file's header again",
    after an update that tells more kinds of file apart - a LoRA stored in
    diffusers' style was read as a Checkpoint, and would have stayed one.
    """
    modified = file_modified(path)
    if modified is None:
        return None
    if force:
        return modified
    row = db.get_version(path)
    if row and row.get("architecture_checked") == modified:
        return None
    return modified


def store_architecture(db, path: str, found: Optional[Architecture],
                       modified: Optional[str]) -> None:
    """Store what identify() found for a file - None for not readable."""
    db.set_architecture(
        path,
        found.preset if found else None,
        found.model_class if found else None,
        found.bundled_text_encoder if found else False,
        found.bundled_vae if found else False,
        modified,
        file_type=found.file_type if found else "Unknown",
        note=found.note if found else "",
        alias=found.alias if found else None,
    )


def record_architecture(db, path: str, force: bool = False) -> Optional[Architecture]:
    """
    Read what a model file is and store it, unless already done.

    `force` reads it even when unchanged since last time: a forced sync and a
    download use it, being when a file is new or its contents may no longer
    be what was read.

    Returns what was found, or None for unchanged or absent.
    """
    modified = file_modified(path) if force else needs_check(db, path)
    if modified is None or not db.get_version(path):
        return None
    found = identify(path)
    store_architecture(db, path, found, modified)
    return found
