"""
Hashing: one read per file, and the same answers as two.

The tensor hash used to be a second pass over the whole file, so every sync
read the library twice. It now rides along with the first read, which is only
safe if it lands on exactly the same bytes - including for the files that are
not shaped the way the happy path assumes.
"""

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

WORK = os.path.join(TESTS, 'work', 'hash_test')
import hashlib
import io
import json
import os
import struct
import sys
import types
import zlib


TMP = os.path.join(WORK, 'files')
import shutil
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(TMP)

from model_manager.hashing import BLAKE3_AVAILABLE, HashResult, ModelHasher

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def safetensors(name, header, tensor_bytes, header_size=None):
    """A file shaped like safetensors: 8-byte length, header, then tensors."""
    blob = json.dumps(header).encode('utf-8')
    declared = len(blob) if header_size is None else header_size
    path = os.path.join(TMP, name)
    with io.open(path, 'wb') as f:
        f.write(struct.pack('<Q', declared))
        f.write(blob)
        f.write(tensor_bytes)
    return path


def reference(path):
    """What the hashes are, worked out independently of the implementation."""
    data = io.open(path, 'rb').read()
    out = {
        'sha256': hashlib.sha256(data).hexdigest().upper(),
        'crc32': format(zlib.crc32(data) & 0xFFFFFFFF, '08X'),
    }
    out['autov2'] = out['sha256'][:10]
    if len(data) >= 1048576 + 65536:
        out['autov1'] = hashlib.sha256(
            data[1048576:1048576 + 65536]).hexdigest().upper()[:8]
    else:
        out['autov1'] = None
    if path.endswith('.safetensors') and len(data) >= 8:
        header_size = struct.unpack('<Q', data[:8])[0]
        if header_size > 0:
            tensor = data[8 + header_size:]
            out['tensor_sha256'] = hashlib.sha256(tensor).hexdigest().upper()
            out['autov3'] = out['tensor_sha256'][:12]
        else:
            out['tensor_sha256'] = out['autov3'] = None
    else:
        out['tensor_sha256'] = out['autov3'] = None
    return out


# ------------------------------------------------------- the ordinary shapes
CASES = [
    ('tiny.safetensors', safetensors('tiny.safetensors', {'a': {'shape': [1]}}, b'\x01' * 64)),
    ('empty tensors', safetensors('notensors.safetensors', {'x': 1}, b'')),
    ('past the AutoV1 window',
     safetensors('big.safetensors', {'x': 1}, os.urandom(1048576 + 65536 + 1000))),
    ('exactly at the AutoV1 window',
     safetensors('edge.safetensors', {'x': 1}, b'\x02' * (1048576 + 65536))),
    ('chunk-boundary tensors',
     safetensors('boundary.safetensors', {'x': 'y' * 500}, os.urandom(1024 * 1024 * 3))),
]
for label, path in CASES:
    got = ModelHasher.calculate_all(path)
    want = reference(path)
    for field, expected in want.items():
        check('%s: %s' % (label, field), getattr(got, field), expected)

# --------------------------------------------------------- the awkward ones
awkward = os.path.join(TMP, 'zeroheader.safetensors')
io.open(awkward, 'wb').write(struct.pack('<Q', 0) + b'nothing')
got = ModelHasher.calculate_all(awkward)
check('a zero header size yields no tensor hash', got.tensor_sha256, None)
check('and no AutoV3', got.autov3, None)
check('but the file is still hashed', got.sha256, reference(awkward)['sha256'])

lying = safetensors('lying.safetensors', {'x': 1}, b'\x03' * 100, header_size=10 ** 9)
got = ModelHasher.calculate_all(lying)
check('a header longer than the file leaves an empty tensor hash',
      got.tensor_sha256, hashlib.sha256(b'').hexdigest().upper())

short = os.path.join(TMP, 'short.safetensors')
io.open(short, 'wb').write(b'abc')
got = ModelHasher.calculate_all(short)
check('a file too short for a header still hashes', got.sha256,
      hashlib.sha256(b'abc').hexdigest().upper())
check('and claims no tensor hash', got.tensor_sha256, None)

empty = os.path.join(TMP, 'empty.safetensors')
io.open(empty, 'wb').write(b'')
got = ModelHasher.calculate_all(empty)
check('an empty file hashes to the empty digest', got.sha256,
      hashlib.sha256(b'').hexdigest().upper())

plain = os.path.join(TMP, 'plain.ckpt')
io.open(plain, 'wb').write(os.urandom(5000))
got = ModelHasher.calculate_all(plain)
check('a .ckpt gets no tensor hash', (got.tensor_sha256, got.autov3), (None, None))
check('but does get the rest', got.sha256, reference(plain)['sha256'])

missing = ModelHasher.calculate_all(os.path.join(TMP, 'does_not_exist.safetensors'))
check('a missing file returns empty rather than raising', missing.sha256, None)

# ------------------------------------------------- only one read per file now
opened = []
real_open = io.open
import builtins
builtins_open = builtins.open
def counting_open(path, *a, **k):
    if str(path).endswith(('.safetensors', '.ckpt')):
        opened.append(str(path))
    return builtins_open(path, *a, **k)
builtins.open = counting_open
try:
    ModelHasher.calculate_all(CASES[2][1])
finally:
    builtins.open = builtins_open
check('a safetensors file is opened exactly once', len(opened), 1)

# ------------------------------------------------------------- unknown kinds
stored = {'sha256': 'A' * 64, 'autov2': 'B' * 10, 'sha256_12': 'C' * 12, 'sshs_12': 'D' * 12}
check('unrecognised hash kinds survive a round trip',
      HashResult.from_stored(stored).to_dict(), stored)
check('a named field beats a stray key of the same name',
      HashResult.from_stored({'sha256': 'E' * 64}).to_dict(), {'sha256': 'E' * 64})

# ------------------------------------------------------------ thread setting
shared = types.ModuleType('modules.shared')
class Opts: pass
shared.opts = Opts()
modules = types.ModuleType('modules'); modules.shared = shared
sys.modules['modules'] = modules; sys.modules['modules.shared'] = shared
import model_manager.sync_service as ss
for value, want in ((1, 1), (8, 8), (16, 16), (99, 16), (0, 4), (-3, 1), ('6', 6), (None, 4)):
    shared.opts.model_manager_hash_threads = value
    check('hash threads setting %r' % value, ss.configured_hash_threads(), want)
del shared.opts.model_manager_hash_threads
check('no setting falls back to 4', ss.configured_hash_threads(), 4)
del sys.modules['modules'], sys.modules['modules.shared']

print('blake3 available here: %s' % BLAKE3_AVAILABLE)
print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
