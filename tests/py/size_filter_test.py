"""
Filtering a Civitai search by file size.

Civitai's search takes no size, so the browser checks each result's latest
version's primary file itself and fills the page from what fits - through the
same loop the prompt filter uses, which is what keeps paging exact. The check
is free, so what has to be bounded is the number of searches, and a model the
size rules out must never cost a prompt check.
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

from model_manager.civitai import prompt_filter as pf    # noqa: E402
from model_manager.civitai.size_filter import (          # noqa: E402
    KB_PER_GB, primary_file_size_kb, size_range_check,
)

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def gb(size):
    return size * KB_PER_GB


def model(model_id, *version_files):
    """A model whose versions, newest first, have these files: (sizeGB, primary)."""
    return {'id': model_id, 'modelVersions': [
        {'id': model_id * 10 + v,
         'files': [{'sizeKB': gb(size) if size is not None else None, 'primary': primary}
                   for size, primary in files]}
        for v, files in enumerate(version_files)]}


def sized(model_id, size):
    """A model with one version and one primary file of `size` GB."""
    return model(model_id, [(size, True)])


# ------------------------------------------------------------ which file counts
check('the primary file is the one measured',
      primary_file_size_kb(model(1, [(6.5, False), (2.0, True)])), gb(2.0))
check('with none marked primary, the first file',
      primary_file_size_kb(model(1, [(6.5, False), (2.0, False)])), gb(6.5))
check('only the latest version counts, which Civitai lists first',
      primary_file_size_kb(model(1, [(2.0, True)], [(9.0, True)])), gb(2.0))
check('no versions has no size', primary_file_size_kb({'id': 1}), None)
check('nor a version with no files', primary_file_size_kb(model(1, [])), None)
check('nor a file with no size', primary_file_size_kb(model(1, [(None, True)])), None)

# ------------------------------------------------------------------ the range
check('no bounds is no filter at all', size_range_check(0, 0), None)
check('and neither is nothing', size_range_check(None, None), None)
between = size_range_check(2, 7)
check('inside the range passes', between(sized(1, 6.5)), True)
check('the bounds themselves are inside', (between(sized(1, 2)), between(sized(1, 7))),
      (True, True))
check('below it does not', between(sized(1, 1.99)), False)
check('nor above it', between(sized(1, 7.01)), False)
check('a size nobody recorded is not in any range', between(model(1, [(None, True)])), False)
check('a minimum alone has no ceiling', size_range_check(2, 0)(sized(1, 23)), True)
check('a maximum alone has no floor', size_range_check(0, 0.2)(sized(1, 0.14)), True)
check('GB means what the cards show: 1024^3 bytes',
      size_range_check(0, 1)({'modelVersions': [{'files': [
          {'sizeKB': 1024 * 1024, 'primary': True}]}]}), True)


# ------------------------------------------------------------------- the loop
class Searcher:
    """Civitai, answering one batch per call from a script of pages."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def search_models(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            return {'items': []}
        items, cursor = self.pages.pop(0)
        return {'items': items, 'nextCursor': cursor}


def run(searcher, page_size, accept, count=None, **kwargs):
    return pf.search_models_with_usable_prompts(
        searcher, {'query': ''}, count, page_size, accept=accept, **kwargs)


small = size_range_check(0, 1)

# Size alone: no prompt check, only what fits.
search = Searcher([([sized(1, 0.1), sized(2, 6.5), sized(3, 0.2)], None)])
done = run(search, 10, small)
check('size alone keeps what fits', [m['id'] for m in done['models']], [1, 3])
check('counting the rest as outside the range', done['rejected'], 1)
check('not as failing a prompt check', done['dropped'], 0)
check('and no prompt check was made', done['checked'], 0)

# A page fills across batches, and stops exactly where it filled.
search = Searcher([
    ([sized(1, 6.5), sized(2, 0.1), sized(3, 6.5)], 'b2'),
    ([sized(4, 0.1), sized(5, 0.1), sized(6, 6.5)], 'b3'),
])
done = run(search, 2, small)
check('a page is filled from as many batches as it takes',
      [m['id'] for m in done['models']], [2, 4])
check('asking Civitai twice', len(search.calls), 2)
check('and resumes right after the last model it took',
      pf.decode_filter_token(done['nextCursor']), ('b2', 1))

search = Searcher([([sized(4, 0.1), sized(5, 0.1), sized(6, 6.5)], 'b3')])
done = run(search, 2, small, start_token=done['nextCursor'])
check('so the next page starts with the model after it',
      [m['id'] for m in done['models']], [5])
check('skipping nothing and repeating nothing', search.calls[0]['cursor'], 'b2')

# A range nothing is in stops after its searches rather than running on.
search = Searcher([([sized(i, 6.5)], 'c%d' % i) for i in range(1, 20)])
done = run(search, 10, small, max_searches=3)
check('a narrow range gives up after its searches', len(search.calls), 3)
check('and says it stopped early', done['budget_reached'], True)
check('pointing at the batch it did not get to',
      pf.decode_filter_token(done['nextCursor']), ('c3', 0))
check('having found nothing', done['models'], [])

# Size and prompt together: the size goes first, and is free.
prompt_checked = []
def count(m):
    prompt_checked.append(m['id'])
    return 1 if m['id'] % 2 else 0

search = Searcher([([sized(1, 0.1), sized(2, 6.5), sized(3, 6.5),
                     sized(4, 0.1), sized(5, 0.1)], None)])
done = run(search, 10, small, count=count, workers=4)
check('with both filters, a model must pass both', [m['id'] for m in done['models']], [1, 5])
check('a model the size rules out is never prompt-checked',
      sorted(prompt_checked), [1, 4, 5])
check('so only the prompt checks count against the check budget', done['checked'], 3)
check('and each filter reports its own',
      (done['dropped'], done['rejected']), (1, 2))

# The live events carry the size count too.
search = Searcher([([sized(1, 6.5), sized(2, 0.1)], None)])
events = list(pf.iter_models_with_usable_prompts(
    search, {'query': ''}, count, 5, accept=small))
check('the progress events count what the size ruled out',
      [p['rejected'] for kind, p in events if kind == 'progress'][-1], 1)
check('and so does the summary', events[-1][1]['rejected'], 1)

# With size alone there are no prompt checks to report between, so progress
# comes after every search - each one is a wait of its own.
search = Searcher([([sized(1, 6.5), sized(2, 6.5)], 'b2'),
                   ([sized(3, 6.5), sized(4, 0.1)], None)])
events = list(pf.iter_models_with_usable_prompts(
    search, {'query': ''}, None, 5, accept=small))
progress = [p for kind, p in events if kind == 'progress']
check('size alone reports progress after each search', len(progress), 2)
check('counting what the searches so far passed over',
      [p['rejected'] for p in progress], [0, 2])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
