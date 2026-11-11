"""
Civitai's image server, as the server asks it directly: only its own
addresses, over https, plainly written - a video's still (api/images.py), an
original sent into img2img (scheduler/load.py, #299). Nothing else is asked
for first; Civitai's own redirects, to its storage, are followed.
"""
import re
from urllib.parse import urlparse

IMAGE_HOST = "image.civitai.com"

# The characters an address may hold (RFC 3986): no backslash, no space or
# control, nothing outside ASCII. Python's urlparse and urllib3 - which
# requests asks with - read one written otherwise as two different hosts.
PLAIN_ADDRESS = re.compile(r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*\Z")


def is_image_address(url: str) -> bool:
    """
    Whether `url` is Civitai's image server, over https, plainly written:
    only an address's own characters, no user part, no port but 443, and
    the same host to urlparse and to urllib3, which requests connects with.
    """
    url = url or ""
    if not PLAIN_ADDRESS.match(url):
        return False
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or "@" in parsed.netloc or port not in (None, 443) or parsed.hostname != IMAGE_HOST:
        return False
    try:
        from urllib3.util import parse_url
        return (parse_url(url).host or "").lower() == IMAGE_HOST
    except Exception:
        return False
