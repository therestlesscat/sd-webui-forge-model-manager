"""
How the Generations tab and the Civitai Images tab place their grid of tiles
(#240), a setting each.

Fast, the default, places each tile in the page's own code and keeps only the
rows near the view on the page: at 75,684 images the grid scrolled at 189
images a second to its end, with no freeze over 50 ms. Classic leaves every
tile to the browser's grid: the browser places them all again as each part
arrives, and froze for up to 42 s at that size. The page does the placing
(`javascript/shared/tiles.mjs`); the server only says which.
"""
from . import forge_host

GENERATIONS_GRID = "model_manager_generations_grid"
GALLERY_GRID = "model_manager_gallery_grid"

# As the settings name them, and Forge saves them: by these words.
FAST, CLASSIC = "Fast", "Classic"
CHOICES = (FAST, CLASSIC)


def grid(key: str) -> str:
    """A tab's choice: FAST or CLASSIC - FAST for anything else saved."""
    chosen = str(forge_host.setting(key) or "").strip()
    return chosen if chosen in CHOICES else FAST
