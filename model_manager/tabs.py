"""
Which of the extension's tabs are on, and what each part of it needs (#41).

Each tab has a switch: off, it does nothing at all. It is not created at the
next start, its routes refuse (api/common.py's gate), and what it would start
in the background is not started. What several tabs share - downloads, Send -
is on while any of them is. This is the one place that says so: each switch
was read three ways - by the server, the tabs' build and the page - and only
the queue's Start and Run next refused while the queue was off.

An area is a tab, a service, ALWAYS, or ANY - every tab's. Routes and startup work
name theirs (api/common.py's gate; tab_switches_test.py holds every route to
one), and a misspelt one is a KeyError, not an area that is always on.
"""
from typing import Dict, FrozenSet, Iterable, Tuple

from .forge_host import setting

# Each tab, in the order they are created, and the setting that switches it
# off (#185). Their defaults are forge_host.DEFAULTS'.
TABS: Dict[str, str] = {
    "queue": "model_manager_queue_enabled",
    "generations": "model_manager_record_generations",
    "model_manager": "model_manager_model_manager_enabled",
    "civitai_browser": "model_manager_civitai_browser_enabled",
}

# What a refusal calls each tab.
NAMES = {
    "queue": "The Queue",
    "generations": "Your generations",
    "model_manager": "The Model Manager tab",
    "civitai_browser": "The Civitai Browser tab",
}

# What every tab's page asks, and what is on while any tab is: the settings
# window, the notes, the newer-version check.
ANY = "any"

# What several tabs share: on while any of them is.
SERVICES: Dict[str, Tuple[str, ...]] = {
    # A download started in either tab, or from Send's Resources and chips.
    "downloads": ("model_manager", "civitai_browser"),
    "saved_search": ("model_manager", "civitai_browser"),
    # Send to txt2img and its lookups: Forge's modules, an image's resources,
    # the chips. The Civitai Browser opens Resources, the Queue loads a task.
    "send": ("model_manager", "civitai_browser", "generations", "queue"),
    # Stored image levels judged again (prompt_levels.py): the Model Manager's
    # galleries and your generations.
    "restamp": ("model_manager", "generations"),
    ANY: tuple(TABS),
}

# What the loader asks before anything - the shared version, and ui-options,
# how the page learns what is on - so they answer even with every tab off.
ALWAYS = "always"

_built: FrozenSet[str] = frozenset()


def check_area(area: str) -> str:
    """`area`, if it is one; a KeyError if not - a misspelt area is never on by mistake."""
    if area != ALWAYS and area not in TABS and area not in SERVICES:
        raise KeyError(f"no such area: {area!r}")
    return area


def on(area: str) -> bool:
    """
    Whether `area` is on: a tab by its setting - one that cannot be read is
    on, as by default; a service while any of its tabs is; ALWAYS always.
    """
    check_area(area)
    if area == ALWAYS:
        return True
    if area in TABS:
        return bool(setting(TABS[area]))
    return any(on(tab) for tab in SERVICES[area])


def why_off(area: str) -> str:
    """What a refusal says."""
    if area in NAMES:
        return f"{NAMES[area]} is turned off in the settings"
    return "Every tab that uses this is turned off in the settings"


def mark_built(tabs: Iterable[str]) -> None:
    """The tabs the WebUI's build has just created: at each start, and at Reload UI."""
    global _built
    tabs = frozenset(tabs)
    for tab in tabs:
        if tab not in TABS:
            raise KeyError(f"no such tab: {tab!r}")
    _built = tabs


def built() -> FrozenSet[str]:
    """
    The tabs created at this build. A tab switched on since is not there
    until the next start: Gradio adds tabs only as the UI is built.
    """
    return _built
