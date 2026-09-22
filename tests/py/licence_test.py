"""The licence filters: four states, over a copy of the real library."""

import os
import sys

# The extension and the test helpers, found from this file rather than from a
# working directory, so a suite runs from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures                                       # noqa: E402

WORK = os.path.join(TESTS, 'work', 'licence_test')
import io
import os
import re
import shutil
import sqlite3
import sys



fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# ---------------------------------------------------------------- the markup
UI = io.open(os.path.join(ROOT, 'model_manager/ui/tab_model_manager.py'), encoding='utf-8').read()
JS = io.open(os.path.join(ROOT, 'javascript/model_manager.mjs'), encoding='utf-8').read()

for control in ('mm_allow_derivatives', 'mm_allow_different_license'):
    block = UI[UI.index('id="%s"' % control):]
    block = block[:block.index('</select>')]
    for value, label in (('""', 'Any'), ('"true"', 'Yes'), ('"false"', 'No'), ('"unknown"', 'Unknown')):
        check('%s offers %s' % (control, label), ('value=%s' % value) in block)
    check('%s defaults to Any' % control, 'value="" selected' in block)
    check('%s is a single control' % control, UI.count('id="%s"' % control), 1)

check('the checkbox pairs are gone',
      any(old in UI for old in ('mm_allow_derivatives_yes', 'mm_allow_different_license_no')), False)
check('no stale references in the JS',
      any(old in JS for old in ('mm_allow_derivatives_yes', 'derivYes', 'diffLicNo')), False)
check('saved searches persist the choice',
      "allow_derivatives: document.getElementById('mm_allow_derivatives')?.value" in JS)
check('saved searches restore the choice',
      "document.getElementById('mm_allow_derivatives').value = filters.allow_derivatives" in JS)
check('clearing resets to Any', "setValue('mm_allow_derivatives', '')" in JS)


# ------------------------------------------------------------- the SQL itself
if True:
    # The fixture carries one model that refuses everything, one that says
    # nothing at all, and the rest permissive - so all three choices have
    # something to find, which a real library only happens to.
    db, facts = fixtures.build(WORK)
    DB = facts['db_path']

    raw = sqlite3.connect(DB)
    total = raw.execute('SELECT COUNT(*) FROM model_versions').fetchone()[0]

    def truth(column):
        rows = raw.execute("""
            SELECT CASE WHEN m.%s IS NULL THEN 'unknown'
                        WHEN m.%s = 1 THEN 'true' ELSE 'false' END, COUNT(*)
            FROM model_versions v LEFT JOIN civitai_models m ON v.model_id = m.id
            GROUP BY 1
        """ % (column, column)).fetchall()
        return dict(rows)

    print('  library: %d versions' % total)
    for column in ('allow_derivatives', 'allow_different_license'):
        expected = truth(column)
        print('  %s: %s' % (column, expected))

        seen = {}
        for choice in ('true', 'false', 'unknown'):
            kwargs = {column: choice, 'limit': 5000}
            _, count = db.query_models_grouped(**kwargs)
            seen[choice] = count

        # Grouped query counts models, not versions, so compare the partition
        # rather than raw totals: the three choices must be disjoint and cover
        # everything the unfiltered query returns.
        _, any_count = db.query_models_grouped(limit=5000)
        check('%s: the three choices partition the library' % column,
              sum(seen.values()), any_count)
        check('%s: Any returns the most' % column, all(v <= any_count for v in seen.values()))
        check('%s: unknown is non-empty' % column, seen['unknown'] > 0)
        check('%s: every choice is reachable' % column, all(v > 0 for v in seen.values()))
        print('     filtered -> true=%d false=%d unknown=%d   any=%d'
              % (seen['true'], seen['false'], seen['unknown'], any_count))

        # The old behaviour: picking true/false silently dropped the unknowns.
        check('%s: choosing true really excludes the unknowns' % column,
              seen['true'] + seen['unknown'] <= any_count)

        # An unrecognised value must be ignored, not crash or filter oddly.
        _, junk = db.query_models_grouped(limit=5000, **{column: 'banana'})
        check('%s: an unknown choice is ignored' % column, junk, any_count)
        _, empty = db.query_models_grouped(limit=5000, **{column: None})
        check('%s: None means no filter' % column, empty, any_count)

    # Both filters at once must intersect, not conflict.
    _, both = db.query_models_grouped(limit=5000, allow_derivatives='unknown',
                                      allow_different_license='unknown')
    _, one = db.query_models_grouped(limit=5000, allow_derivatives='unknown')
    check('both filters intersect', both <= one)
    check('unknown+unknown is the unsynced set', both, one)
    raw.close()

print()
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
