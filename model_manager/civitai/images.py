"""
Civitai's image server, as the server asks it directly: only its own
addresses, over https - a video's still (api/images.py), an original sent
into img2img (scheduler/load.py, #299). Nothing else is asked for.
"""
from urllib.parse import urlparse

IMAGE_HOST = "image.civitai.com"


def is_image_address(url: str) -> bool:
    """Whether `url` is Civitai's image server, over https."""
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname == IMAGE_HOST
