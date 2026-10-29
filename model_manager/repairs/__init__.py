"""
Repairs: one-off fixes of rows an earlier version wrote wrong, each a module
of its own, here and in javascript/repairs/ (#241). Each says, with a light
check, whether the library needs it; the page asks once its tabs have started
(GET /model-manager/repairs) and loads a repair's script only when it is
named. A repair stays until a later release removes it - its two files and
its line below.

Not ui-options: the page waits for that before any tab starts, and it reads
no database. A repair's check does, and a slow disk would hold every tab.
"""
from typing import Any, Dict

from ..tabs import on
from . import recorded_twice

# Each repair, by the name the page knows it by: its script is
# javascript/repairs/<name>.mjs.
REPAIRS: Dict[str, Any] = {"recorded_twice": recorded_twice}


def needed(db) -> Dict[str, int]:
    """Each repair with work in this library, while its tab is on: {name: how much}."""
    found = {}
    for name, repair in REPAIRS.items():
        if on(repair.AREA):
            count = repair.needed(db)
            if count:
                found[name] = count
    return found


def register(app, common) -> None:
    """The list's route and each repair's own. `common` is the API's
    (gate, failed), handed in: nothing here imports the API."""
    from fastapi.responses import JSONResponse
    from ..db import database_state, get_models_db

    @app.get("/model-manager/repairs")
    @common.gate("always")
    def get_repairs():
        """The repairs this library needs, by name, each with its count and
        the tab whose switch it follows, the page's script stopped with it; none
        while the database is newer than this copy, which reads nothing of it.
        A migration running makes it wait, as every read does: the page asks
        once its tabs have started, so nothing waits on the answer."""
        try:
            if database_state():
                return JSONResponse({"success": True, "repairs": {}})
            return JSONResponse({"success": True, "repairs": {
                name: {"count": count, "tab": REPAIRS[name].AREA}
                for name, count in needed(get_models_db()).items()}})
        except Exception as e:
            return common.failed(e, "Checking which repairs are needed")

    for repair in REPAIRS.values():
        repair.register(app, common)
