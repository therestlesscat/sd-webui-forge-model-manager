"""
"I'm feeling lucky": a draw of Civitai's models, every match equally likely.

Civitai is replaced by a population of models it answers about as it was
measured to: `ids` restricts a search to those ids, its own filters apply,
an answer holds at most 100 models - the first by its sort, with a cursor to
the rest - and a search without ids lists every match in that order.
"""
import os
import random
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
webui_stub.install()

import model_manager.civitai.random_draw as rd           # noqa: E402
from model_manager.civitai import CivitaiRateLimitError  # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


class Civitai:
    """Models numbered 1..newest, `present` of them public; each a type and downloads."""

    def __init__(self, newest, present, kind=lambda i: 'LORA', ignore_ids=False,
                 limit_after=None, endless=False):
        self.newest = newest
        self.models = {i: {'id': i, 'type': kind(i), 'downloads': (i * 7919) % 100003}
                       for i in present}
        self.ignore_ids = ignore_ids
        self.limit_after = limit_after
        self.endless = endless
        self.asked = []

    def search_models(self, **kw):
        self.asked.append(kw)
        if self.limit_after is not None and len(self.asked) > self.limit_after:
            raise CivitaiRateLimitError(60)
        if kw.get('sort') == 'Newest':
            top = sorted(self.models, reverse=True)[:kw.get('limit', 20)]
            return {'items': [self.models[i] for i in top], 'nextCursor': None}
        assert kw.get('limit') == 100, kw
        matching = [m for m in self.models.values()
                    if not kw.get('types') or m['type'] in kw['types']]
        if kw.get('ids') and not self.ignore_ids:
            wanted = set(kw['ids'])
            matching = [m for m in matching if m['id'] in wanted]
        matching.sort(key=lambda m: (-m['downloads'], m['id']))
        start = int(kw.get('cursor') or 0)
        page = matching[start:start + 100]
        more = start + 100 < len(matching) or (self.endless and bool(page))
        return {'items': page, 'nextCursor': str(start + 100) if more else None}


def draw(civitai, filters=None, page=20, seed=1, now=lambda: 0.0):
    events = list(rd.iter_random_models(civitai, filters or {'nsfw': True}, page,
                                        rng=random.Random(seed), now=now))
    kinds = [k for k, _ in events]
    assert kinds[-1] == 'done' and kinds.count('done') == 1, kinds
    return events[-1][1], [p for k, p in events if k == 'progress']


def id_batches(civitai):
    return [len(kw['ids']) for kw in civitai.asked if kw.get('ids')]


# ------------------------------------------------------------- no filter
rd.forget()
rng = random.Random(5)
newest = 3_000_000
everyone = Civitai(newest, set(rng.sample(range(1, newest + 1), 600_000)))
done, progress = draw(everyone)
check('a page of models comes back', len(done['models']), 20)
check('none twice', len({m['id'] for m in done['models']}), 20)
check('the newest id and one batch of ids: two requests', done['requests'], 2)
check('asked for the newest id once, by Newest, NSFW included',
      [(kw.get('sort'), kw.get('nsfw')) for kw in everyone.asked if kw.get('sort')], [('Newest', True)])
check('a first batch sized for about 50 matches where one id in five matches', id_batches(everyone), [250])
check('ids are drawn from 1 to the newest',
      all(1 <= i <= newest for i in everyone.asked[1]['ids']), True)
check('progress came before the batch', progress[0]['requests'], 1)
check('not listed: drawn from ids', done['listed'], False)
check('and an estimate of how many match, near 600,000',
      400_000 < done['matches'] < 800_000, True)

everyone.asked.clear()
done, _ = draw(everyone, seed=2)
check('the newest id is remembered: the next draw asks for ids at once',
      [bool(kw.get('ids')) for kw in everyone.asked], [True])
check('sizing its batch from the first draw\'s rate', 150 < id_batches(everyone)[0] < 350, True)
check('another draw, other models', done['models'] != draw(everyone, seed=1)[0]['models'], True)

everyone.asked.clear()
draw(everyone, now=lambda: rd.NEWEST_ID_SECONDS + 1.0)
check('after an hour the newest id is asked again',
      [kw.get('sort') for kw in everyone.asked][0], 'Newest')

# ----------------------------------------------------- what is passed on
rd.forget()
seen = Civitai(1000, range(1, 1001))
draw(seen, {'types': ['Checkpoint', 'LORA'], 'base_models': ['Pony'], 'nsfw': False,
            'tag': 'anime', 'checkpoint_type': 'Trained', 'period': 'Month'})
asked = [kw for kw in seen.asked if kw.get('ids')][0]
check('Civitai\'s own filters go with the ids',
      {k: asked[k] for k in ('types', 'base_models', 'nsfw', 'tag', 'checkpoint_type', 'period')},
      {'types': ['Checkpoint', 'LORA'], 'base_models': ['Pony'], 'nsfw': False, 'tag': 'anime',
       'checkpoint_type': 'Trained', 'period': 'Month'})
check('never a query or a sort', ('query' in asked, 'sort' in asked), (False, False))

# ------------------------------------------------- a cut answer is followed
# Every id a model, so 250 ids match 250: Civitai answers the 100 it sorts
# first. Taking only those would draw from its most downloaded.
rd.forget()
dense = Civitai(10_000, range(1, 10_001))
done, _ = draw(dense)
ids_asks = [kw for kw in dense.asked if kw.get('ids')]
check('a cut answer is followed to its end, with the same ids',
      [(len(kw['ids']), kw.get('cursor')) for kw in ids_asks], [(250, None), (250, '100'), (250, '200')])

# So the models Civitai sorts last come up as often as those it sorts first.
# Each draw starts afresh: one that remembers the rate asks 50 ids at a time,
# and none of its answers is cut.
by_rank = sorted(dense.models.values(), key=lambda m: (-m['downloads'], m['id']))
top = {m['id'] for m in by_rank[:5000]}
drawn = Counter()
for seed in range(200):
    rd.forget()
    done, _ = draw(dense, page=20, seed=seed)
    drawn.update('top' if m['id'] in top else 'bottom' for m in done['models'])
share = drawn['top'] / (drawn['top'] + drawn['bottom'])
check('the half Civitai sorts first is drawn about half the time (%.3f)' % share,
      0.45 < share < 0.55, True)

# ---------------------------------------------------- the type filter
# A checkpoint is one id in 500 here: one batch of 3,500 finds some seven.
rd.forget()
rng = random.Random(9)
newest = 1_000_000
present = set(rng.sample(range(1, newest + 1), 200_000))
checkpoints = set(rng.sample(sorted(present), 2000))
typed = Civitai(newest, present, kind=lambda i: 'Checkpoint' if i in checkpoints else 'LORA')
done, progress = draw(typed, {'types': ['Checkpoint'], 'nsfw': True})
check('a filtered draw fills its page', len(done['models']), 20)
check('with models of that type only', {m['type'] for m in done['models']}, {'Checkpoint'})
check('its first batch the most ids a request takes', id_batches(typed)[0], rd.MOST_IDS)
check('no batch larger', max(id_batches(typed)) <= rd.MOST_IDS, True)
check('2,000 matches: whichever is cheaper, ids or the list, within 15 requests (%d)' % done['requests'],
      done['requests'] <= 15, True)
check('progress says how many ids it asked', progress[-1]['asked'] > 0, True)

# --------------------------------------------- a small set is listed whole
rd.forget()
few = set(random.Random(3).sample(range(1, 1_000_001), 150))
small = Civitai(1_000_000, few | set(range(1, 1001)),
                kind=lambda i: 'Checkpoint' if i in few else 'LORA')
done, progress = draw(small, {'types': ['Checkpoint'], 'nsfw': True})
check('a small set is listed whole and drawn from', done['listed'], True)
check('saying exactly how many match', done['matches'], 150)
check('a full page from it', len(done['models']), 20)
check('every one of them a match', {m['id'] for m in done['models']} <= few, True)
check('listing is a search without ids, 100 a page',
      [kw.get('cursor') for kw in small.asked if 'ids' not in kw and kw.get('sort') is None], [None, '100'])
check('progress while listing says how many it has listed', progress[-1]['listing'], 100)

small.asked.clear()
done, _ = draw(small, {'types': ['Checkpoint'], 'nsfw': True}, seed=4)
check('the next draw lists at once: the count was remembered',
      [bool(kw.get('ids')) for kw in small.asked], [False, False])
check('fewer than a page match: all of them', len(draw(small, {'types': ['Checkpoint'], 'nsfw': True},
                                                        page=500)[0]['models']), 150)

rd.forget()
none = Civitai(1_000_000, range(1, 1001))
done, _ = draw(none, {'types': ['Checkpoint'], 'nsfw': True})
check('nothing matching: an empty draw, listed, saying none match',
      (done['models'], done['listed'], done['matches']), ([], True, 0))
check('found in two requests after the newest id', done['requests'], 3)

# ------------------------------------- an estimate too low, given up on
# Told only 60 match, the draw lists - and finds the pages do not end. It
# gives up once that has cost what ids would, and draws from ids instead:
# a listing's first pages are Civitai's most downloaded, not a sample.
rd.forget()
rng = random.Random(11)
many = set(rng.sample(range(1, 1_000_001), 20_000))
wrong = Civitai(1_000_000, many | set(range(1, 2001)),
                kind=lambda i: 'Checkpoint' if i in many else 'LORA')
rd._rates[rd._filters_key({'types': ['Checkpoint'], 'nsfw': True})] = (1_000_000, 60)
done, _ = draw(wrong, {'types': ['Checkpoint'], 'nsfw': True})
listing_pages = [kw for kw in wrong.asked if 'ids' not in kw and kw.get('sort') is None]
check('it began by listing', len(listing_pages) >= 1, True)
check('gave that up', done['listed'], False)
check('and filled the page from ids', len(done['models']), 20)
first_pages = {m['id'] for m in sorted((wrong.models[i] for i in many),
                                       key=lambda m: (-m['downloads'], m['id']))[:100 * len(listing_pages)]}
check('none of the listed pages\' models kept for being listed',
      len([m for m in done['models'] if m['id'] in first_pages]) < 5, True)
check('remembering that there are at least as many as it listed',
      rd._rates.get(rd._filters_key({'types': ['Checkpoint'], 'nsfw': True}))[1] > 60, True)

# ----------------------------------------------------------- stopping
rd.forget()
deaf = Civitai(1_000_000, range(1, 5001), ignore_ids=True, endless=True)
done, _ = draw(deaf, {'types': ['LORA'], 'nsfw': True})
check('a Civitai that ignores ids hands over none of its own pages as random',
      [m for m in done['models'] if m['id'] > 5000], [])
check('and the draw stops at the safety stop', (done['stopped'], done['requests']), (True, rd.SAFETY_STOP))

rd.forget()
# Some five matches a batch: the page needs a third batch, which Civitai refuses.
busy = Civitai(1_000_000, set(random.Random(2).sample(range(1, 1_000_001), 1_500)),
               kind=lambda i: 'LORA', limit_after=3)
done, _ = draw(busy, {'types': ['LORA'], 'nsfw': True})
check('a 429 ends the draw, saying so', done['rate_limited'], True)
check('with what it found by then', 0 < len(done['models']) < 20, True)

rd.forget()
tiny = Civitai(30, range(1, 31))
done, _ = draw(tiny, page=20)
check('a range smaller than a batch: every id asked once, a page drawn',
      (len(done['models']), len(set(tiny.asked[1]['ids']))), (20, 30))

# ------------------------------------------- what is left out (#191)
# A draw leaves out the models shown by the draws before it, and those the
# library has: their ids are never asked, a listing drops them, and the
# estimate counts only the ids that can still be drawn.
import inspect                                           # noqa: E402
takes_leave_out = 'leave_out' in inspect.signature(rd.iter_random_models).parameters
check('a draw can be told what to leave out', takes_leave_out, True)


def draw_leaving(civitai, leave_out, filters=None, page=20, seed=1):
    events = list(rd.iter_random_models(civitai, filters or {'nsfw': True}, page,
                                        rng=random.Random(seed), leave_out=leave_out))
    return events[-1][1]


if takes_leave_out:
    rd.forget()
    rng = random.Random(21)
    present = set(rng.sample(range(1, 1_000_001), 200_000))
    everyone = Civitai(1_000_000, present)
    first, _ = draw(everyone, seed=1)
    left = set(rng.sample(sorted(present), 50_000)) | {m['id'] for m in first['models']}
    everyone.asked.clear()
    done = draw_leaving(everyone, left, seed=1)
    asked_ids = {i for kw in everyone.asked if kw.get('ids') for i in kw['ids']}
    check('ids left out are never asked', asked_ids & left, set())
    check('nor drawn: the same seed draws others', {m['id'] for m in done['models']} & left, set())
    check('and the page is still full', len(done['models']), 20)

    rd.forget()
    half = Civitai(1000, range(1, 1001))
    done = draw_leaving(half, set(range(1, 501)))
    check('every id a model and half left out: about 500 match, not 1,000', done['matches'], 500)

    rd.forget()
    done = draw_leaving(small, set(sorted(few)[:100]), {'types': ['Checkpoint'], 'nsfw': True})
    check('a listing drops what is left out, and counts the rest',
          (done['listed'], done['matches'], done.get('left_out_matches')), (True, 50, 100))
    check('drawing only from the rest', {m['id'] for m in done['models']} <= set(sorted(few)[100:]), True)
    check('its count remembered whole, to size the next draw',
          (rd._rates.get(rd._filters_key({'types': ['Checkpoint'], 'nsfw': True})) or (None, None))[1], 150)

    rd.forget()
    done = draw_leaving(small, set(few), {'types': ['Checkpoint'], 'nsfw': True})
    check('every match left out: none drawn, saying how many were left out',
          (done['models'], done['listed'], done['matches'], done.get('left_out_matches')), ([], True, 0, 150))

    rd.forget()
    tiny = Civitai(30, range(1, 31))
    done = draw_leaving(tiny, set(range(1, 31)))
    check('every id in range left out: nothing to ask, and the draw ends',
          (done['models'], done['requests']), ([], 1))

# What was shown is kept for the filters it was drawn under: a draw under
# others starts afresh, and Start over forgets it.
F, G = {'types': ['LORA'], 'nsfw': True}, {'types': ['Checkpoint'], 'nsfw': True}
shown_for, remember_shown, forget_shown = (getattr(rd, name, None) for name in
                                           ('shown_for', 'remember_shown', 'forget_shown'))
check('what was shown can be kept, read and forgotten', None not in (shown_for, remember_shown, forget_shown), True)
if None not in (shown_for, remember_shown, forget_shown):
    forget_shown()
    remember_shown(F, [1, 2])
    remember_shown(F, [3])
    check('what each draw showed adds up', shown_for(F), {1, 2, 3})
    check('other filters: nothing shown under them', shown_for(G), set())
    check('and what was shown under the old ones is gone', shown_for(F), set())
    remember_shown(F, [4])
    forget_shown()
    check('Start over forgets it', shown_for(F), set())
    rd.forget()
    remember_shown(F, [5])
    rd.forget()
    check('and so does forget(), for tests', shown_for(F), set())

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
