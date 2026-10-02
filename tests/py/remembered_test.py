"""
Answers kept in memory: a bounded, locked map (model_manager/remembered.py, #68).

Five caches were dicts of their own, two without a lock though threads share
them, and none with a bound. What is checked: past its bound the oldest set
is dropped, and setting one again makes it the newest; without a bound it
keeps everything; many threads at once leave it whole and within its bound;
and each of the five is one - bounded, but for file hashes, which are kept
per file and refreshed when the file changes.
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

webui_stub.install()

from model_manager.remembered import Remembered          # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------------ a bound
kept = Remembered(most=3)
for n in range(1, 6):
    kept[n] = n * 10
check('past its bound, the oldest are dropped', ([n in kept for n in range(1, 6)], len(kept)),
      ([False, False, True, True, True], 3))
check('what is kept is what was set', (kept.get(5), kept.get(1), kept.get(1, 'none')), (50, None, 'none'))

kept[3] = 31
kept[6] = 60
check('setting one again makes it the newest: the next to go is the one after it',
      ([n in kept for n in (3, 4, 5, 6)], kept.get(3)), ([True, False, True, True], 31))

kept.clear()
check('and it can be emptied', (len(kept), 5 in kept), (0, False))

everything = Remembered()
for n in range(5000):
    everything[n] = n
check('without a bound it keeps everything', len(everything), 5000)

# ------------------------------------------------------------------ threads
shared, errors = Remembered(most=100), []


def hammer(offset):
    try:
        for n in range(2000):
            shared[offset * 10000 + n] = n
            shared.get(offset * 10000 + n // 2)
    except Exception as e:                               # pragma: no cover - what is checked
        errors.append(e)


threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join(10)
check('eight threads at once: no error, and within its bound', (errors, len(shared)), ([], 100))

# ---------------------------------------------------------------- the five
import model_manager.send_plan as send_plan              # noqa: E402
import model_manager.resources as resources              # noqa: E402
import model_manager.api.prompts as prompts              # noqa: E402
import model_manager.hashing as hashing                  # noqa: E402
import model_manager.civitai.ownership as ownership      # noqa: E402

# The owned versions are per API key: a first ask with one makes them.
ownership.owned_versions([1], client_factory=lambda: type('C', (), {
    'api_key': 'a key', 'whoami': lambda self: {}, 'close': lambda self: None})())
caches = {
    'send_plan._remembered': send_plan._remembered,
    'resources._MISSING_FILES': resources._MISSING_FILES,
    'api.prompts._sfw_verdicts': prompts._sfw_verdicts,
    'civitai.ownership owned': ownership._state['owned'],
    'hashing._sha256_seen': hashing._sha256_seen,
}
check('each cache is a Remembered', {name: type(c).__name__ for name, c in caches.items()},
      {name: 'Remembered' for name in caches})
check('bounded, but for file hashes: one per file, refreshed when it changes',
      {name: getattr(c, 'most', None) is not None for name, c in caches.items()},
      {name: name != 'hashing._sha256_seen' for name in caches})

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
