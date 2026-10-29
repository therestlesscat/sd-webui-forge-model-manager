"""
Walking folders as Forge does: into symbolic links, each real folder once (#348).

Forge walks its model folders with `os.walk(path, followlinks=True)`
(`walk_files`, `modules/util.py`), so it loads what a symbolic link inside
them leads to; a walk without it never saw those files. Junctions were
entered either way, and a junction to a folder above it was walked again and
again - each file 64 times, until Windows stops the path - with no record of
the folders already walked. So a folder whose real path was walked already,
on any route and from any folder of the same walk, is not entered again:
one route per folder, and the same one every walk, subfolders being taken in
name order.

A folder's real path is asked of the file system only where the walk starts
and where the listing marks an entry as leading elsewhere: asking opens the
folder, and on a hard disk, cold, 4,395 of them took 40 to 86 s of one walk
(#365). Any other subfolder's real path is its parent's and its name.
"""
import os
import stat
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


def real_folder(path: str) -> str:
    """Where a folder really is, every link on the way resolved, as a key."""
    return os.path.normcase(os.path.realpath(path))


def _leads_elsewhere(entry: os.DirEntry) -> bool:
    """Whether a listing's folder entry is a link of any kind. A junction is
    not a symbolic link to `is_symlink()`, but both are reparse points, which
    the listing says without another look at the disk on Windows."""
    if entry.is_symlink():
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def walk_entries(folders: Iterable[str], walked: Optional[Set[str]] = None
                 ) -> Iterator[Tuple[str, List[str], List[os.DirEntry]]]:
    """
    Each folder in turn, top down, following links, each real folder once -
    by the first route to it. Yields (folder, subfolder names, file entries):
    a caller that takes names out of the list keeps the walk out of them, as
    with os.walk. An entry carries its file's size and time from the listing
    (`entry.stat()`), with no look at the file on Windows. `walked` is the
    record of real folders walked; one shared by several walks makes them
    one. A folder that is not there, or cannot be listed, gives nothing.
    """
    walked = set() if walked is None else walked
    for top in folders:
        if not os.path.isdir(top):
            continue
        real = real_folder(top)
        if real in walked:
            continue
        walked.add(real)
        ahead = [(top, real)]
        while ahead:
            folder, real = ahead.pop()
            try:
                with os.scandir(folder) as listing:
                    entries = list(listing)
            except OSError:
                continue
            subfolders, files = {}, []
            for entry in entries:
                try:
                    is_folder = entry.is_dir()
                except OSError:
                    is_folder = False
                if is_folder:
                    subfolders[entry.name] = entry
                else:
                    files.append(entry)
            names = list(subfolders)
            yield folder, names, files
            # After the caller's own cut, so a folder it left out is not
            # marked walked; in name order, the first in name order walked
            # first.
            below = []
            for name in sorted(names):
                path = os.path.join(folder, name)
                entry = subfolders.get(name)
                key = (real_folder(path) if entry is None or _leads_elsewhere(entry)
                       else os.path.join(real, os.path.normcase(name)))
                if key not in walked:
                    walked.add(key)
                    below.append((path, key))
            ahead.extend(reversed(below))


def walk(folders: Iterable[str], walked: Optional[Set[str]] = None
         ) -> Iterator[Tuple[str, List[str], List[str]]]:
    """
    walk_entries(), with each file's name in place of its entry: (folder,
    subfolders, files) as os.walk yields them.
    """
    for folder, subfolders, files in walk_entries(folders, walked):
        yield folder, subfolders, [entry.name for entry in files]


class SameFiles(object):
    """
    Files known by where they really are: the real folder they are in, and
    their name. Two paths with one key are one file reached by two routes. A
    path given first is the one a file is known by; one real path is read per
    folder.
    """

    def __init__(self, paths: Iterable[str] = ()):
        self._folders: Dict[str, str] = {}
        self._known: Dict[Tuple[str, str], str] = {}
        for path in paths:
            self._known.setdefault(self.key(path), path)

    def key(self, path: str) -> Tuple[str, str]:
        folder, name = os.path.split(path)
        real = self._folders.get(folder)
        if real is None:
            real = self._folders[folder] = real_folder(folder)
        return real, os.path.normcase(name)

    def other(self, path: str) -> Optional[str]:
        """The path this file is known by, when it is not this one."""
        known = self._known.get(self.key(path))
        if known is None or os.path.normcase(known) == os.path.normcase(path):
            return None
        return known

    def linked(self) -> bool:
        """Whether any folder seen is reached through a link: its real path is
        not its own. Without one, no two paths can be one file."""
        return any(real != os.path.normcase(os.path.abspath(folder))
                   for folder, real in self._folders.items())


def found_elsewhere(paths: Iterable[str], found: Iterable[str]) -> Dict[str, str]:
    """
    Of these paths, each whose file a walk found by another route - its folder
    reached through a link, or reached without the one it was stored through:
    the path -> the path the walk found it at.
    """
    paths = list(paths)
    if not paths:
        return {}
    walked = SameFiles(found)
    elsewhere = {}
    for path in paths:
        other = walked.other(path)
        if other is not None:
            elsewhere[path] = other
    return elsewhere
