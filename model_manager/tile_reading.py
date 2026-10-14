"""
How the Generations tab reads a level's images for its tiles (#238, #259), a
setting, marked alpha.

Single pass, the default, reads them once per request, into a temporary table
in memory, and builds every tile from it: grouped by base model, 75,682 images
took 0.27 s against 1.46. Classic reads them again for each tile's previews,
checkpoint and LoRAs, as the tab always has, and stays a setting away while
Single pass is new. The database does the reading
(`GenerationsOps.scope_level`); this only says which.
"""
from . import forge_host

SETTING = "model_manager_generations_reading"

# As the settings name them, and Forge saves them: by these words.
SINGLE_PASS, CLASSIC = "Single pass", "Classic"
CHOICES = (SINGLE_PASS, CLASSIC)


def reading() -> str:
    """The tab's choice: SINGLE_PASS or CLASSIC - SINGLE_PASS for anything else saved."""
    chosen = str(forge_host.setting(SETTING) or "").strip()
    return chosen if chosen in CHOICES else SINGLE_PASS
