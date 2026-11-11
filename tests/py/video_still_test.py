"""
A video card's still, checked (/model-manager/video-still, api/images.py, #45).

Civitai's still of a video (anim=false) is now and then the whole original - a
32 MB MP4 for 1 video in 80 - which the browser downloaded in full as the
poster, and could not draw. The server asks for the headers only: an image is
a redirect to it, anything else a 404, each with Cache-Control so the browser
remembers. Only https://image.civitai.com is followed. Civitai is a fake here.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager.api.images import still_answer, STILL_IMAGE_SECONDS, STILL_NONE_SECONDS   # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


STILL = 'https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/0e2a/anim=false/clip.mp4'
asked = []


def civitai(content_type, status=200, fail=False):
    def head(url, allow_redirects=False, timeout=None):
        asked.append((url, allow_redirects))
        if fail:
            raise ConnectionError('offline')
        return types.SimpleNamespace(status_code=status, headers={'Content-Type': content_type})
    return head


answer = still_answer(STILL, head=civitai('image/jpeg'))
check('an image: a redirect to Civitai\'s still, the browser fetching it from Civitai',
      [answer.status_code, answer.headers.get('location')], [302, STILL])
check('remembered by the browser for a week', answer.headers.get('cache-control'),
      f'private, max-age={STILL_IMAGE_SECONDS}')
check('only the headers asked for, following redirects', asked, [(STILL, True)])

answer = still_answer(STILL, head=civitai('video/mp4'))
check('the whole video in its place: a 404 - nothing downloaded for a preview it cannot be',
      [answer.status_code, answer.headers.get('location')], [404, None])
check('remembered for a day, so a still Civitai makes later is picked up', answer.headers.get('cache-control'),
      f'private, max-age={STILL_NONE_SECONDS}')
check('a refusal is no still either', still_answer(STILL, head=civitai('text/html', status=403)).status_code, 404)
check('a type with a charset is still an image',
      still_answer(STILL, head=civitai('image/webp; charset=binary')).status_code, 302)

answer = still_answer(STILL, head=civitai('', fail=True))
check('Civitai not answering: redirected all the same, and not remembered - a guard, not a gate',
      [answer.status_code, answer.headers.get('location'), answer.headers.get('cache-control')], [302, STILL, 'no-store'])

asked.clear()
for bad in ('http://image.civitai.com/x/anim=false/a.mp4', 'https://evil.example/anim=false/a.mp4',
            'https://image.civitai.com.evil.example/a.mp4', '', 'file:///C:/secret'):
    check(f'not Civitai\'s image server ({bad!r}): refused', still_answer(bad, head=civitai('image/jpeg')).status_code, 400)
check('and nothing asked of it', asked, [])

# An address the check's parser and the request's read as two hosts: written
# with a character an address may not hold, a user part, another port.
from model_manager.civitai import images as civitai_images   # noqa: E402
from model_manager.civitai.images import is_image_address   # noqa: E402
plain = getattr(civitai_images, 'PLAIN_ADDRESS', None)
check('the plain-character rule alone refuses a backslash, a tab, a newline, a space, a non-ASCII letter',
      [bool(plain and plain.match(u)) for u in ('https://a\\b', 'https://a\tb', 'https://a\nb', 'https://a b',
                                                 'https://\u00e9')], [False] * 5)
check('and lets a plain address through', bool(plain and plain.match(STILL)), True)
asked.clear()
for bad in ('https://other.example\\@image.civitai.com/a.jpeg', 'https://image.civi\ttai.com/a.jpeg',
            'https://image.civi\ntai.com/a.jpeg', 'https://user@image.civitai.com/a.jpeg',
            'https://image.civitai.com:8443/a.jpeg'):
    check(f'not plainly Civitai\'s image server ({bad!r}): refused', is_image_address(bad), False)
check('the backslash form asked of the still route: 400, and nothing asked',
      [still_answer('https://other.example\\@image.civitai.com/a.jpeg', head=civitai('image/jpeg')).status_code, asked],
      [400, []])
for bad in ('https://image.civitai.com\\@other.example/a.jpeg', 'https://image.civitai.com./a.jpeg',
            'https://imag\u00e9.civitai.com/a.jpeg', 'http://image.civitai.com/a.jpeg'):
    check(f'refused, as before ({bad!r})', is_image_address(bad), False)
for good in (STILL, 'https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/0e2a/width=450/123456.jpeg',
             'https://image.civitai.com:443/x/original=true/a.jpeg', 'https://IMAGE.civitai.com/x/a.jpeg'):
    check(f'Civitai\'s image server as it writes its addresses ({good!r}): passes', is_image_address(good), True)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None
if TestClient:
    import model_manager.api.images as images_api
    real = images_api.still_answer
    images_api.still_answer = lambda url: real(url, head=civitai('image/jpeg'))
    app = FastAPI()
    images_api.register(app)
    reply = TestClient(app).get('/model-manager/video-still', params={'url': STILL}, follow_redirects=False)
    check('the endpoint answers so', [reply.status_code, reply.headers.get('location')], [302, STILL])
    images_api.still_answer = real

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
