"""
What a level of a tab of tiles is asked for - the Generations tab's and the
Civitai Images tab's alike (#283): what it is grouped by, one grouping or two,
and the words a search asks for. Both tabs' endpoints read their requests
through this module; neither imports the other's.
"""
import re
from dataclasses import dataclass, field
from typing import Collection, List, Optional


def grouping_chain(group: str, groupings: Collection[str]) -> List[str]:
    """
    What `group` groups by, in order: one grouping ("model"), or two
    ("model>day") - a group of the first opens onto groups of the second.
    Anything not in `groupings`, or more than two, is no grouping at all.
    """
    keys = [k for k in str(group or "").split(">")]
    return keys if 1 <= len(keys) <= 2 and all(k in groupings for k in keys) else []


# The keys naming images by id (#336), and the list each fills; generation:
# (#241) the Generations tab's alone, as task: is.
_ID_KEYS = {"image": "images", "version": "versions", "model": "models", "generation": "generations"}


@dataclass
class Search:
    """
    What a search asks for: the words an image's prompt or negative prompt
    must each hold, the Queue's task whose run made it, and the images, the
    Civitai versions and models (any resource it used) it must be one of,
    and in the Generations tab the generations (#241). An empty list asks
    nothing.
    """
    words: List[str] = field(default_factory=list)
    task: Optional[int] = None
    images: List[int] = field(default_factory=list)
    versions: List[int] = field(default_factory=list)
    models: List[int] = field(default_factory=list)
    generations: List[int] = field(default_factory=list)


def search_terms(text: str, tasks: bool = True) -> Search:
    """
    What a search asks for: its words - a "quoted phrase" as one - and its
    keys. image:, version: and model: take ids, one or a comma-separated
    list, and the same key again adds to its list (#336); task:<number>, the
    Queue's task whose run made it, and generation: with its list (#241),
    are keys only where `tasks`, and words like any other elsewhere. Nothing else is a key: a prompt's own
    "(red:1.2)", or image:abc, is searched for as typed.
    """
    search = Search()
    for quoted, plain in re.findall(r'"([^"]*)"|(\S+)', text or ""):
        task = re.fullmatch(r"task:(\d+)", plain, re.IGNORECASE) if tasks else None
        ids = re.fullmatch(r"(image|version|model|generation):(\d+(?:,\d+)*)", plain, re.IGNORECASE)
        if ids and ids.group(1).lower() == "generation" and not tasks:
            ids = None
        if task:
            search.task = int(task.group(1))
        elif ids:
            getattr(search, _ID_KEYS[ids.group(1).lower()]).extend(int(n) for n in ids.group(2).split(","))
        elif (quoted or plain).strip():
            search.words.append(quoted or plain)
    return search
