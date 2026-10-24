"""
Links to folders, for the checks of a walk through them (#348), made the way
this machine allows.

A symbolic link to a folder needs admin rights or Developer Mode on Windows.
Refused, a junction stands in, and `os.path.islink` is made to call it a
link: `os.walk` decides whether to enter a folder by asking it, so the walk
sees what a symbolic link shows it - seen in Python 3.13 and 3.10 alike. A
junction made as one is left as Windows says it is: entered by any walk.

Links go before the tree they sit in: `shutil.rmtree` in Python 3.10 walks
into a junction.
"""
import os

_dressed = set()
_islink = os.path.islink


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _reports(path):
    return _key(path) in _dressed or _islink(path)


def symbolic(target, link):
    """A symbolic link at `link` to the folder `target`. Says which it is."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return "a symbolic link"
    except OSError:
        junction(target, link)
        _dressed.add(_key(link))
        os.path.islink = _reports
        return "a junction taken for a symbolic link"


def junction(target, link):
    """A junction at `link` to the folder `target`: no privilege needed. Where
    there are no junctions, a symbolic link."""
    try:
        import _winapi
    except ImportError:
        os.symlink(target, link, target_is_directory=True)
        return
    _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))


def remove(link):
    """Take a link away, never what it leads to. A link not there is fine."""
    _dressed.discard(_key(link))
    try:
        os.readlink(link)
    except (OSError, ValueError):
        return
    try:
        os.rmdir(link)
    except OSError:
        os.unlink(link)
