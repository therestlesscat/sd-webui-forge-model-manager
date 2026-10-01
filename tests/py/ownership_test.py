"""
Which paid versions the API key's account bought (model_manager/civitai/ownership.py, #43).

A version reads the same to everyone; only Civitai's permissions check says
the caller bought it. Here Civitai is a fake client: nothing reaches it.
What is checked: no key, no question asked; the account id asked once per
key; many versions in one question, remembered a few minutes; a failure is
"unknown", never "not bought"; and mark_owned stamps only paid versions.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

import model_manager.civitai.ownership as ownership      # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


calls = []


class FakeCivitai:
    """Account 77; it bought versions 518881 and 900001."""
    bought = {518881, 900001}
    fail = False

    def __init__(self, api_key='key-a'):
        self.api_key = api_key

    def whoami(self):
        calls.append('me')
        if FakeCivitai.fail:
            raise RuntimeError('offline')
        return {'id': 77, 'username': 'someone'}

    def check_permissions(self, ids, user_id):
        calls.append(('check', sorted(ids), user_id))
        if FakeCivitai.fail:
            raise RuntimeError('offline')
        return {i: i in self.bought for i in ids}

    def close(self):
        calls.append('close')


clock = [1000.0]
now = lambda: clock[0]                                    # noqa: E731


def owned(ids, key='key-a'):
    return ownership.owned_versions(ids, client_factory=lambda: FakeCivitai(key), now=now)


check('no versions: nothing asked', [owned([]), calls], [{}, []])
check('no API key: unknown, and nothing asked', [owned([518881], key=''), [c for c in calls if c != 'close']],
      [None, []])

calls.clear()
check('asked once for them all: what the account bought, and what it did not',
      [owned([712530, 518881, 900001]), [c for c in calls if c != 'close']],
      [{518881: True, 712530: False, 900001: True}, ['me', ('check', [518881, 712530, 900001], 77)]])

calls.clear()
check('asked again within minutes: remembered, Civitai not asked',
      [owned([518881, 712530]), [c for c in calls if c != 'close']], [{518881: True, 712530: False}, []])
check('a version not asked before is asked alone, the account id remembered',
      [owned([518881, 123]), [c for c in calls if c != 'close']], [{518881: True, 123: False}, [('check', [123], 77)]])

calls.clear()
clock[0] += ownership.OWNED_TTL + 1
FakeCivitai.bought = {518881, 900001, 712530}             # bought since
check('after a few minutes, asked afresh: a purchase since is seen', owned([712530]), {712530: True})

calls.clear()
check('another key is another account: its id asked anew', [owned([712530], key='key-b'), calls[0]],
      [{712530: True}, 'me'])

calls.clear()
FakeCivitai.fail = True
clock[0] += ownership.OWNED_TTL + 1
check('Civitai not answering: unknown, never "not bought"', owned([712530], key='key-c'), None)
FakeCivitai.fail = False
check('and the client is closed every time', calls.count('close') >= 1, True)

# mark_owned: only paid versions get `owned`, from one question.
real = ownership.owned_versions
asked = []
ownership.owned_versions = lambda ids: asked.append(sorted(ids)) or {518881: True, 712530: False}
versions = [{'id': 518881, 'paid_access': {'permanent': True, 'ends_at': None}},
            {'id': 712530, 'paid_access': {'permanent': True, 'ends_at': None}},
            {'id': 5, 'paid_access': None}]
ownership.mark_owned(versions)
check('mark_owned stamps each paid version, asking once for them all',
      [[v['paid_access'] and v['paid_access'].get('owned') for v in versions], asked],
      [[True, False, None], [[518881, 712530]]])
ownership.owned_versions = lambda ids: None
versions = [{'id': 1, 'paid_access': {'permanent': True, 'ends_at': None}}]
ownership.mark_owned(versions)
check('unknown stays unknown', versions[0]['paid_access']['owned'], None)
asked.clear()
ownership.owned_versions = lambda ids: asked.append(1) or {}
ownership.mark_owned([{'id': 1, 'paid_access': None}])
check('no paid version: nothing asked', asked, [])
ownership.owned_versions = real

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
