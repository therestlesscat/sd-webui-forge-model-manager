"""
What a level of a tab of tiles is asked for - the Generations tab's and the
Civitai Images tab's alike (#283): what it is grouped by, one grouping or two,
and the words a search asks for. Both tabs' endpoints read their requests
through this module; neither imports the other's.
"""
import re
from typing import Collection, List, Optional, Tuple


def grouping_chain(group: str, groupings: Collection[str]) -> List[str]:
    """
    What `group` groups by, in order: one grouping ("model"), or two
    ("model>day") - a group of the first opens onto groups of the second.
    Anything not in `groupings`, or more than two, is no grouping at all.
    """
    keys = [k for k in str(group or "").split(">")]
    return keys if 1 <= len(keys) <= 2 and all(k in groupings for k in keys) else []


def search_terms(text: str, tasks: bool = True) -> Tuple[List[str], Optional[int]]:
    """
    What a search asks for: the words an image's prompt or negative prompt
    must each hold - a "quoted phrase" as one - and, where `tasks`, with
    task:<number>, the Queue's task whose run made it; elsewhere that is a
    word like any other. Nothing else is a key: a prompt's own "(red:1.2)" is
    searched for as typed.
    """
    words: List[str] = []
    task = None
    for quoted, plain in re.findall(r'"([^"]*)"|(\S+)', text or ""):
        found = re.fullmatch(r"task:(\d+)", plain, re.IGNORECASE) if tasks else None
        if found:
            task = int(found.group(1))
        elif (quoted or plain).strip():
            words.append(quoted or plain)
    return words, task
