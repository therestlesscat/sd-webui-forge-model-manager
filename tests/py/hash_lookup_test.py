"""
Finding files in the library by hash, version id or name (db/models_ops.py, #70).

The four lookups read one narrow pass over the table now, not every column of
every row. What they answer is what callers rely on: any kind of stored hash
finds a file, in any case, where hashes_from_local_models() takes AutoV2
alone; between files that share a hash or a version id, table order decides -
the first, for a per-resource answer; hash matches come before id matches,
and a file is listed once; a name is a file's name without its extension,
in any case. The files are named so that table order is not path order.
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

import fixtures                                          # noqa: E402

WORK = os.path.join(TESTS, 'work', 'hash_lookup')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


db, facts = fixtures.build(WORK)
LIB = os.path.join(WORK, 'library')
A, B, C = (os.path.join(LIB, name) for name in ('z_first.safetensors', 'm_copy.safetensors', 'a_last.SafeTensors'))
SHA_A = 'a' * 64
for path, version_id, hashes in (
        (A, 7001, {'AutoV2': 'AAAAAAAAAA', 'SHA256': SHA_A.upper()}),
        (B, 7001, {'autov2': 'aaaaaaaaaa', 'sha256': SHA_A}),                 # a copy of A
        (C, 7002, {'AUTOV2': 'CCCCCCCCCC', 'blake3': 'c' * 64})):
    db.upsert_version({'file_path': path, 'file_name': os.path.basename(path), 'id': version_id,
                       'model_id': 70, 'file_hashes': hashes, 'has_civitai_data': True})


def paths(rows):
    return [os.path.basename(row['file_path']) for row in rows]


# ------------------------------------------------------------- per resource
by_id, by_hash = db.local_versions_by_key([7001, '7002', 'x', 99999], ['aaaaaaaaaa', SHA_A, 'C' * 64, 'f' * 10])
check('a version id finds the first of its files, in table order',
      {i: os.path.basename(row['file_path']) for i, row in by_id.items()},
      {7001: 'z_first.safetensors', 7002: 'a_last.SafeTensors'})
check('a hash finds the first file holding it - any kind, any case',
      {h: os.path.basename(row['file_path']) for h, row in by_hash.items()},
      {'aaaaaaaaaa': 'z_first.safetensors', SHA_A: 'z_first.safetensors', 'c' * 64: 'a_last.SafeTensors'})
check('nothing asked, nothing found', db.local_versions_by_key([], []), ({}, {}))

# ------------------------------------------------------------- which files
check('files a hash names come first, in table order, then those a version id names',
      paths(db.versions_named_by([7002], ['AAAAAAAAAA'])), ['z_first.safetensors', 'm_copy.safetensors', 'a_last.SafeTensors'])
check('a file found by hash is not listed again for its version id',
      paths(db.versions_named_by([7001], [SHA_A])), ['z_first.safetensors', 'm_copy.safetensors'])
check('by version id alone, every file of it', paths(db.versions_named_by([7001], [])),
      ['z_first.safetensors', 'm_copy.safetensors'])

# ------------------------------------------------------------ AutoV2 only
found = db.hashes_from_local_models(['cccccccccc', SHA_A, 'C' * 64])
check('the Resources dialog\'s lookup takes AutoV2 alone, in any case',
      sorted(found), ['cccccccccc'])
check('and answers with the version', (found['cccccccccc']['version_id'], found['cccccccccc']['hash']),
      (7002, 'cccccccccc'))

# ----------------------------------------------------------------- by name
check('a name is the file\'s without its extension, in any case',
      {name: paths(rows) for name, rows in db.local_versions_by_name(['A_LAST', 'm_copy', 'nothing', '']).items()},
      {'a_last': ['a_last.SafeTensors'], 'm_copy': ['m_copy.safetensors']})

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
