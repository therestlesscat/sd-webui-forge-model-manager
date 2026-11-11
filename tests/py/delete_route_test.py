"""
The Delete route removes the model file first, and nothing else when it
cannot (#388).

It removed the file and its side files in one loop, wrote a refusal to the
console alone, then deleted the library's rows and answered success whatever
happened: a file Windows would not delete - one another program holds, a
read-only one - stayed on disk with its .civitai.info and previews gone and
its rows forgotten, and the page said Deleted. Now the model file goes first,
alone; refused, the route answers 409 and touches nothing. Once it is gone,
its rows go at once, and a side file or folder that cannot be removed is
named in the answer rather than failing it.

A file is made refused by marking it read-only, which Windows will not
delete (WinError 5); every flag is cleared after, or the next run's fixture
build could not empty the folder.
"""
import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

webui_stub.install()                                    # before model_manager

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    print('fastapi is not installed; run this with the WebUI\'s python')
    sys.exit(0)

import fixtures                                          # noqa: E402
import model_manager.db.database as dbmod                # noqa: E402
from model_manager.api import setup_api                  # noqa: E402

WORK = os.path.join(TESTS, 'work', 'delete_route')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# A run stopped before its `finally` - a time limit ends Windows' python.exe
# outright - leaves read-only files the fixture build cannot remove.
for folder, _, names in os.walk(WORK):
    for name in names:
        try:
            os.chmod(os.path.join(folder, name), stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass

db, facts = fixtures.build(WORK)
dbmod._db_instance = db
app = FastAPI()
setup_api(app)
client = TestClient(app)
LORA = os.path.join(WORK, 'library', 'Lora')
SIDES = ('.civitai.info', '.preview.png')
held = []      # every path made read-only, made writable again at the end


def delete(path):
    r = client.post('/model-manager/models/delete', data={'path': path})
    return r.status_code, r.json()


def model_file(name, version_id, folder=LORA):
    """A LoRA file the library has a row for, with its side files beside it."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(b'x' * 64)
    for suffix in SIDES:
        with open(os.path.splitext(path)[0] + suffix, 'w') as f:
            f.write('{}')
    db.upsert_civitai_model(fixtures._model(version_id // 100, name, 'LORA'), from_civitai=True)
    db.upsert_version({'id': version_id, 'model_id': version_id // 100, 'version_name': 'v1',
                       'base_model': 'SDXL 1.0', 'file_path': path, 'file_name': name, 'file_size': 64,
                       'file_extension': os.path.splitext(name)[1], 'has_civitai_data': True})
    return path


def sides(path):
    return [os.path.exists(os.path.splitext(path)[0] + suffix) for suffix in SIDES]


def read_only(path):
    os.chmod(path, stat.S_IREAD)
    held.append(path)


def refused_here():
    """Whether this system refuses to remove a read-only file: Windows does; Linux asks the folder."""
    probe = os.path.join(WORK, 'probe.txt')
    with open(probe, 'w') as f:
        f.write('x')
    os.chmod(probe, stat.S_IREAD)
    try:
        os.remove(probe)
        return False
    except OSError:
        os.chmod(probe, stat.S_IWRITE | stat.S_IREAD)
        os.remove(probe)
        return True


REFUSES = refused_here()
if not REFUSES:
    print('Read-only files are removed here: the refusal checks are skipped.')


def model_file_refused():
    refused = model_file('refused.safetensors', 900101)
    read_only(refused)
    code, body = delete(refused)
    check('a model file Windows will not delete answers 409, not success', (code, body.get('success')), (409, False))
    # Windows' reason without the path its message adds: the page names the file.
    check('saying why, without the path, and that nothing was removed',
          body.get('error'), 'Could not delete refused.safetensors: [WinError 5] Access is denied. Nothing was removed.')
    check('the file stays', os.path.exists(refused), True)
    check('and so do its side files', sides(refused), [True, True])
    check('and its row', bool(db.get_version(refused)), True)


def side_file_refused():
    kept_side = model_file('kept_side.safetensors', 900201)
    preview = os.path.splitext(kept_side)[0] + '.preview.png'
    read_only(preview)
    code, body = delete(kept_side)
    check('a side file Windows will not delete still lets the model go', (code, body.get('success')), (200, True))
    check('the model file is gone, and its row', [os.path.exists(kept_side), bool(db.get_version(kept_side))],
          [False, False])
    check('the side file that could go went, the refused one stayed', sides(kept_side), [False, True])
    check('and the answer names it, with why, without the path',
          body.get('not_removed'), [{'file': 'kept_side.preview.png', 'reason': '[WinError 5] Access is denied'}])


def rows_failing():
    rows_fail = model_file('rows_fail.safetensors', 900301)
    real_delete_version = db.delete_version

    def locked(file_path):
        raise RuntimeError('database is locked')

    db.delete_version = locked
    try:
        code, body = delete(rows_fail)
    finally:
        db.delete_version = real_delete_version
    check('rows that cannot be removed once the file is gone: still success, the file gone',
          [code, body.get('success'), os.path.exists(rows_fail)], [200, True, False])
    check('with a note naming the file, and that the next sync forgets the record',
          [len(body.get('notes', [])), 'rows_fail.safetensors' in (body.get('notes') or [''])[0],
           'next sync' in (body.get('notes') or [''])[0]], [1, True, True])
    check('and the side files went too', sides(rows_fail), [False, False])


def side_files_shared():
    """Two model files of one name in one folder: their side files are both's (#388)."""
    pt = model_file('demo.pt', 900701)
    safetensors = model_file('demo.safetensors', 900702)
    code, body = delete(pt)
    check('deleting demo.pt beside demo.safetensors keeps the side files they share',
          [code, os.path.exists(pt), sides(safetensors)], [200, False, [True, True]])
    check('named as shared, not as refused', [sorted(body.get('shared', [])), 'not_removed' in body],
          [['demo.civitai.info', 'demo.preview.png'], False])
    code, body = delete(safetensors)
    check('then deleting demo.safetensors takes them: no other demo.* model file is left',
          [code, sides(safetensors), 'shared' in body], [200, [False, False], False])

    if os.path.normcase('A') == os.path.normcase('a'):
        lower = model_file('cased.safetensors', 900801)
        upper = os.path.join(LORA, 'CASED.PT')
        with open(upper, 'wb') as f:
            f.write(b'x' * 64)
        code, body = delete(lower)
        check('where case is ignored, CASED.PT beside it keeps the side files', [code, sides(lower)], [200, [True, True]])
    else:
        print('Names are told apart by case here: the CASED.PT check is skipped.')


def embedding_image():
    """A .png the original Forge loads as an embedding is not a preview (#388)."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    holder = model_file('holder.pt', 900901)
    png = os.path.splitext(holder)[0] + '.png'
    info = PngInfo()
    info.add_text('sd-ti-embedding', 'made-up data')
    Image.new('RGB', (4, 4)).save(png, pnginfo=info)
    code, body = delete(holder)
    check('a .png carrying sd-ti-embedding stays, named as an embedding',
          [code, os.path.exists(png), body.get('embeddings')], [200, True, ['holder.png']])

    plain_holder = model_file('plain_holder.pt', 901001)
    plain_png = os.path.splitext(plain_holder)[0] + '.png'
    Image.new('RGB', (4, 4)).save(plain_png)
    code, body = delete(plain_holder)
    check('a plain .png beside it goes', [code, os.path.exists(plain_png), 'embeddings' in body],
          [200, False, False])


def guards():
    plain = model_file('plain.safetensors', 900401)
    code, body = delete(plain)
    check('a plain delete: success, file, side files and row gone, nothing left to name',
          [code, body.get('success'), os.path.exists(plain), sides(plain), bool(db.get_version(plain)),
           'not_removed' in body, 'notes' in body],
          [200, True, False, [False, False], False, False, False])

    elsewhere = os.path.join(WORK, 'library', 'Other')
    twin_here = model_file('twin.safetensors', 900501)
    twin_there = model_file('twin.safetensors', 900601, folder=elsewhere)
    code, body = delete(twin_here)
    check('a file of one name deleted in one folder: it and its side files go',
          [code, os.path.exists(twin_here), sides(twin_here)], [200, False, [False, False]])
    check('and the file of that name in another folder keeps its own', sides(twin_there), [True, True])


try:
    if REFUSES:
        model_file_refused()
        side_file_refused()
    rows_failing()
    side_files_shared()
    embedding_image()
    guards()
finally:
    # Each on its own: one that cannot be made writable leaves the rest to clear.
    for path in held:
        try:
            if os.path.exists(path):
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
