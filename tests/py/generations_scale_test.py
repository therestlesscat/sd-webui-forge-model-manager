"""
The Generations tab and the galleries on the tables of v37 (#231): a part is
picked in SQL, and Python is handed about one part's rows - where v36 handed
it every image - with the same answers as v36 gave, group ids aside.

The v36 reads are frozen in tests/v36_generations.py. Each library is written
at v36 (tests/generation_fixture.py), read through them, then migrated and
read again through today's code.
"""
import copy
import os
import sqlite3
import sys
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402

opts = webui_stub.install()
opts.model_manager_gallery_page_size = 4

import generation_fixture                                # noqa: E402
import v36_generations as v36                            # noqa: E402
from model_manager.api import generations as api         # noqa: E402
from model_manager.db.database import ModelsDatabase     # noqa: E402
from model_manager.db.generations_ops import Scope       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'generations_scale')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ------------------------------------------------------------ the library
path, connection = generation_fixture.v36_database(os.path.join(WORK, 'varied'))
facts = generation_fixture.varied(connection, WORK)


def thumbs_aside(answer):
    """An answer with each image's thumbnail address taken out, which v36
    never had (#5). None is made here, so each is None: one that is not is
    left in, to fail the comparison."""
    answer = copy.deepcopy(answer)
    for holder in answer.get('tiles', []) + answer.get('generations', []):
        for image in holder.get('images', []):
            if image.get('thumb', 'absent') is None:
                image.pop('thumb')
    return answer


def ids_aside(answer):
    """An answer with the groups' and sections' ids taken out: v37 names a
    group by its prompt's number or its value, v36 by a hash of its value -
    and the thumbnails' addresses (thumbs_aside)."""
    answer = thumbs_aside(answer)
    for tile in answer.get('tiles', []):
        for part in ('group', 'section'):
            if tile.get(part):
                tile[part].pop('id', None)
    return answer


# Every level the comparison opens, with each side's way there.
levels = []


def browse_both(label, **params):
    """Every part of a level, old and new; each part's tiles for opening more."""
    olds, news = [], []
    for page in range(1, 40):
        o = v36.browse_page(old, page=page, **{k: v[0] if isinstance(v, tuple) else v for k, v in params.items()})
        n = api.browse_page(new, page=page, **{k: v[1] if isinstance(v, tuple) else v for k, v in params.items()})
        olds.append(o)
        news.append(n)
        if not o['more'] or not n['more']:
            break
    levels.append((label, olds, news))
    return olds, news


# browse_both reads both sides at once, so the v36 side reads a copy of the
# v36 database, taken before the migration.
connection.close()
copy_path = os.path.join(WORK, 'varied', 'v36_copy.db')
source = sqlite3.connect(path)
target = sqlite3.connect(copy_path)
source.backup(target)
source.close()
target.close()
old_connection = sqlite3.connect(copy_path)
old_connection.row_factory = sqlite3.Row
old = v36.V36(old_connection)
new = ModelsDatabase(extension_dir=ROOT, custom_db_path=path)
generations = [r[0] for r in old_connection.execute('SELECT id FROM generations ORDER BY id')]


def compare(label, olds, news):
    check(f'{label}: as many parts', len(news), len(olds))
    for index, (o, n) in enumerate(zip(olds, news)):
        check(f'{label}: part {index + 1}', ids_aside(n), ids_aside(o))


# ------------------------------------------------------------ every level, both switch states
chains = [''] + list(api.GROUPINGS) + [f'{a}>{b}' for a in api.GROUPINGS for b in api.GROUPINGS if a != b]
for hide in (False, True):
    for group in chains:
        label = f'grouped by {group or "nothing"}, NSFW {"hidden" if hide else "shown"}'
        olds, news = browse_both(label, hide_nsfw=hide, group=group)
        compare(label, olds, news)
        first_o = olds[0]['tiles'][:2]
        first_n = news[0]['tiles'][:2]
        for o_tile, n_tile in zip(first_o, first_n):
            if o_tile['kind'] == 'generation':
                gid = o_tile['generation']['id']
                compare(f'{label}, inside generation {gid}',
                        *browse_both('', hide_nsfw=hide, group=group, generation=gid))
                continue
            if 'section' in o_tile:
                # A section's groups, then one group inside it, then a batch inside that.
                compare(f'{label}, a section',
                        *browse_both('', hide_nsfw=hide, group=group,
                                     in_group=(o_tile['section']['id'], n_tile['section']['id'])))
                inner = browse_both('', hide_nsfw=hide, group=group,
                                    in_group=(o_tile['section']['id'], n_tile['section']['id']),
                                    in_subgroup=(o_tile['group']['id'], n_tile['group']['id']))
                compare(f'{label}, a group in a section', *inner)
            else:
                inner = browse_both('', hide_nsfw=hide, group=group,
                                    in_group=(o_tile['group']['id'], n_tile['group']['id']))
                compare(f'{label}, a group', *inner)
                o_in, n_in = inner[0][0]['tiles'][:1], inner[1][0]['tiles'][:1]
                for o_g, n_g in zip(o_in, n_in):
                    if o_g['kind'] == 'group':
                        continue
                    compare(f'{label}, a batch in a group',
                            *browse_both('', hide_nsfw=hide, group=group,
                                         in_group=(o_tile['group']['id'], n_tile['group']['id']),
                                         generation=o_g['generation']['id']))

# ------------------------------------------------------------ searching
for search in ('cat', 'CAT', '"red fox"', '100%', 'snake_case', 'snake%case', 'lighthouse',
               f'task:{facts["task"]}', f'cat task:{facts["task"]}', 'nothing-matches'):
    for group in ('', 'prompt', 'model>prompt_written'):
        label = f'search {search!r}, grouped by {group or "nothing"}'
        compare(label, *browse_both(label, hide_nsfw=False, group=group, search=search))

# ------------------------------------------------------------ a model's Your generations
for name in ('a', 'b', 'a2', 'x', 'vae', 'te', 'l', 'm', 'p'):
    model = facts['paths'][name]
    for hide_nsfw in (False, True):
        for hide_promptless in (False, True):
            for page in range(1, 20):
                o = v36.generation_page(old, model, hide_nsfw, hide_promptless, page)
                n = api.generation_page(new, model, hide_nsfw, hide_promptless, page)
                check(f'Your generations of {name}, page {page}, switches {hide_nsfw}/{hide_promptless}',
                      thumbs_aside(n), o)
                if not o['page']['more']:
                    break

# ------------------------------------------------------------ the images a card shows, a batch rated
for generation in generations:
    for hide in (False, True):
        for files in (None, new.generation_gallery_files(facts['paths']['a'])):
            o_rows = [r for r in old.generation_gallery_images(files) if r['generation_id'] == generation]
            o_ids = [r['id'] for r in v36._filtered(o_rows, hide, hide)[0]]
            n_rows = new.generation_scope_rows(Scope(files=files, generation=generation))
            n_ids = [r['id'] for r in api._filtered(n_rows, hide, hide)[0]]
            check(f'Show images of generation {generation}, {"a model" if files else "the tab"}, '
                  f'switches {hide}', n_ids, o_ids)
    for group, search in (('', ''), ('prompt', ''), ('', 'cat')):
        o_ids = [r['id'] for r in v36._scoped(old, True, group, '', generation, '', search)[0]]
        n_rows = new.generation_scope_rows(api._scope(group, '', generation, '', search))
        n_ids = [r['id'] for r in api._filtered(n_rows, True, False)[0]]
        check(f'rating generation {generation}\'s batch, grouped by {group or "nothing"}, search {search!r}',
              n_ids, o_ids)

check('every grouping and pair was compared', len({label for label, _, _ in levels if label}) >= 2 * len(chains),
      True)

# ------------------------------------------------------------ a LoRA combination, its rows in reverse
# Each image's LoRAs are kept in the order loaded; one loaded z then a, the
# other a then z, are one combination - whatever order SQLite meets them in.
raw = sqlite3.connect(path)
pair = raw.execute('SELECT id, generation_id FROM generation_images ORDER BY id LIMIT 2').fetchall()
raw.execute('DELETE FROM generation_resources WHERE role = \'lora\' AND image_id IN (?, ?)',
            (pair[0][0], pair[1][0]))
for (image_id, generation_id), names in zip(pair, (['zz_last', 'aa_first'], ['aa_first', 'zz_last'])):
    for position, name in enumerate(names):
        raw.execute("INSERT INTO generation_resources (image_id, generation_id, role, position, name, file_path) "
                    "VALUES (?, ?, 'lora', ?, ?, NULL)", (image_id, generation_id, position, name))
raw.commit()
raw.close()
combos = [t for page in browse_both('', hide_nsfw=False, group='loras')[1] for t in page['tiles']
          if t['group']['value'] == 'aa_first, zz_last']
check('a LoRA combination loaded in either order is one group, its names sorted',
      [t['matching_count'] for t in combos], [2])

# ------------------------------------------------------------ what Python is handed
class Counting:
    """A cursor that counts the rows it hands back."""
    handed = 0

    def __init__(self, cursor):
        self._cursor = cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        for row in self._cursor:
            Counting.handed += 1
            yield row

    def fetchall(self):
        rows = self._cursor.fetchall()
        Counting.handed += len(rows)
        return rows

    def fetchone(self):
        row = self._cursor.fetchone()
        Counting.handed += row is not None
        return row


def counted(factory):
    @contextmanager
    def cursor():
        with factory() as c:
            yield Counting(c)
    return cursor


big_path, big = generation_fixture.v36_database(os.path.join(WORK, 'big'))
big_facts = generation_fixture.bulk(big, 5000, WORK)
old_big = v36.V36(big)
old_big.ops._cursor = counted(old_big.ops._cursor)


def handed(read):
    Counting.handed = 0
    read()
    return Counting.handed


old_handed = handed(lambda: v36.browse_page(old_big, False))
big.close()
new_big = ModelsDatabase(extension_dir=ROOT, custom_db_path=big_path)
new_big._generations._cursor = counted(new_big._generations._cursor)
first = api.browse_page(new_big, False)
reads = {
    'the top level': lambda: api.browse_page(new_big, False),
    'part 50': lambda: api.browse_page(new_big, False, page=50),
    'grouped by prompt': lambda: api.browse_page(new_big, False, group='prompt'),
    'grouped by LoRA combination': lambda: api.browse_page(new_big, True, group='loras'),
    'grouped twice': lambda: api.browse_page(new_big, False, group='model>prompt_written'),
    'inside a generation': lambda: api.browse_page(new_big, False, generation=first['tiles'][0]['generation']['id']),
    'a search': lambda: api.browse_page(new_big, False, search='prompt 1'),
    "a model's Your generations": lambda: api.generation_page(new_big, big_facts['checkpoint'], False, False),
}
check('the v36 reads hand Python every image: this check can fail', old_handed >= 5000, True)
for label, read in reads.items():
    count = handed(read)
    check(f'{label}: Python is handed about one part\'s rows, not 5,000 ({count})', count <= 200, True)

old_connection.close()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
