"""
Which version of the extension this is.

MAJOR.MINOR.PATCH.BUILD. A minor version is a feature that stands on its own;
a patch is any other change a user can see, up to the next minor version; the
build is the commit's place in the repository's history - `git rev-list
--count HEAD` - so a commit that changes nothing a user sees (tests, docs,
refactoring) keeps MAJOR.MINOR.PATCH and moves the build on. See CHANGELOG.md,
and AGENTS.md for when to bump which.

Only MAJOR.MINOR.PATCH is written down, here and as the tag vMAJOR.MINOR.PATCH
on the commit that made it. The build is asked of git, once: a copy without
its history - installed from a zip - has none, and says so by leaving it off.
"""
import os
import subprocess
from typing import Dict, Optional

VERSION = "0.43.4"

REPOSITORY = "https://github.com/therestlesscat/sd-webui-forge-model-manager"
CHANGELOG_URL = REPOSITORY + "/blob/HEAD/CHANGELOG.md"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_found: Optional[Dict[str, object]] = None


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", "-C", _ROOT, *args], capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except Exception:
        return None


def describe() -> Dict[str, object]:
    """
    This copy's version: `version` (with the build, where git can say),
    `build`, `commit`, `date` of that commit, and `modified` - whether files
    git tracks have changed since it, as in a copy being worked on.
    """
    global _found
    if _found is None:
        build = _git("rev-list", "--count", "HEAD")
        commit = _git("log", "-1", "--format=%h %cs") or ""
        commit, _, date = commit.partition(" ")
        modified = _git("status", "--porcelain", "--untracked-files=no")
        _found = {
            "version": f"{VERSION}.{build}" if build else VERSION,
            "build": int(build) if build and build.isdigit() else None,
            "commit": commit or None,
            "date": date or None,
            "modified": bool(modified),
        }
    return _found
