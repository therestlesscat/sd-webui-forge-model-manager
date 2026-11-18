"""
A value as a queued task keeps it, and back: model_manager/scheduler/values.py
(#150, #165).

JSON passes through. An image, an array, a dataclass of enums and arrays -
ControlNet's units are one - a tuple and a dict that looks like a marker
come back as they went in. What cannot be kept, or rebuilt, comes back
MISSING, so its control's default runs instead.
"""
import dataclasses
import enum
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy                                             # noqa: E402
from PIL import Image                                    # noqa: E402

from model_manager.scheduler.values import Keeper, MISSING, NoFiles, files, restore   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_values')
shutil.rmtree(WORK, ignore_errors=True)
# Gradio's upload folder, as get_upload_folder() reads it: a folder of this suite's own, before any keep.
UPLOADS = os.path.join(WORK, 'gradio')
os.environ['GRADIO_TEMP_DIR'] = UPLOADS
FOLDER = os.path.join(WORK, 'task')

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def round_trip(value, name='value'):
    return restore(keeper.keep(value, name))


# ------------------------------------------------------------------ JSON
keeper = Keeper(FOLDER)
plain = {'prompt': 'a red apple', 'steps': 4, 'cfg': 4.5, 'hires': False, 'styles': ['one'], 'none': None}
check('JSON is kept as it is', keeper.keep(plain), plain)
check('and comes back as it went in', round_trip(plain), plain)
check('a value with no file makes no folder', os.path.exists(FOLDER), False)


class Mode(enum.Enum):
    BALANCED = 'Balanced'
    PROMPT = 'My prompt is more important'


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


check('an enum comes back as itself', round_trip(Mode.PROMPT), Mode.PROMPT)
check('an int enum is kept as an enum, not an int', round_trip(Level.HIGH) is Level.HIGH, True)
check('a tuple comes back a tuple', round_trip((1, 'two')), (1, 'two'))
check('a dict holding a marker key is kept apart', round_trip({'__image__': 'not a file'}),
      {'__image__': 'not a file'})

# ---------------------------------------------------------------- images
image = Image.new('RGBA', (8, 6), (200, 10, 10, 255))
image.putpixel((1, 2), (1, 2, 3, 4))
kept = keeper.keep(image, 'init_img')
check('an image is saved as PNG in the task folder', (sorted(kept), kept['__image__'].endswith('.png'),
                                                      os.path.dirname(kept['__image__'])),
      (['__image__'], True, FOLDER))
back = restore(kept)
check('and comes back pixel for pixel', (back.mode, back.size, back.tobytes()),
      (image.mode, image.size, image.tobytes()))
check('a second value of the same name gets a file of its own',
      keeper.keep(image, 'init_img')['__image__'] != kept['__image__'], True)

picture = numpy.zeros((5, 7, 3), dtype=numpy.uint8)
picture[1, 2] = (9, 8, 7)
check('an image array comes back the same array', numpy.array_equal(round_trip(picture), picture), True)
check('as PNG', keeper.keep(picture, 'map')['__array__'].endswith('.png'), True)
weights = numpy.linspace(0, 1, 6, dtype=numpy.float32).reshape(2, 3)
again = round_trip(weights)
check('any other array comes back, its type and shape too',
      (again.dtype, again.shape, numpy.array_equal(again, weights)), (weights.dtype, weights.shape, True))


# ---------------------------------------- a dataclass, as ControlNet's units
@dataclasses.dataclass
class Unit:
    enabled: bool = True
    module: str = 'None'
    weight: float = 1.0
    control_mode: Mode = Mode.BALANCED
    image: object = None
    _idx: int = -1
    seen: int = dataclasses.field(default=0, init=False)


unit = Unit(enabled=True, module='canny', weight=0.75, control_mode=Mode.PROMPT,
            image={'image': picture, 'mask': numpy.zeros((5, 7), dtype=numpy.uint8)}, _idx=2)
unit.seen = 5
kept = keeper.keep(unit, 'ControlNet-0')
back = restore(kept)
check('a dataclass is kept by its class and fields', (kept['__dataclass__'], sorted(kept['fields'])),
      ('__main__:Unit', ['_idx', 'control_mode', 'enabled', 'image', 'module', 'seen', 'weight']))
check('and comes back the same class', type(back), Unit)
check('with its fields', (back.enabled, back.module, back.weight, back.control_mode, back._idx),
      (True, 'canny', 0.75, Mode.PROMPT, 2))
check('a field set after construction too', back.seen, 5)
check('its image pair comes back, both arrays',
      (numpy.array_equal(back.image['image'], picture), back.image['mask'].shape), (True, (5, 7)))

kept_files = files(kept)
check('files() names every file a value holds', (len(kept_files), all(os.path.isfile(f) for f in kept_files)),
      (2, True))
check('and every file a keeper wrote is in its list', set(kept_files) <= set(keeper.files), True)

# -------------------------------------------------------- what is missing
check('an object it cannot keep comes back MISSING', round_trip(object()) is MISSING, True)
check('so does a dict whose keys are not all text', round_trip({1: 'one'}) is MISSING, True)
check('so does anything holding one', round_trip([1, object()]) is MISSING, True)
check('a class no imported module has comes back MISSING',
      restore({'__dataclass__': 'not_imported_anywhere:Unit', 'fields': {}}) is MISSING, True)
check('an enum value that no longer exists comes back MISSING',
      restore({'__enum__': '__main__:Mode', 'value': 'gone'}) is MISSING, True)
gone = keeper.keep(image, 'deleted')
os.remove(gone['__image__'])
check('an image whose file is gone comes back MISSING', restore(gone) is MISSING, True)

# --------------------------------------------------------------- uploads
upload = os.path.join(WORK, 'upload.txt')
with open(upload, 'w') as f:
    f.write('batch')
copied = keeper.keep_file(upload)
check('an upload is copied into the task folder', (os.path.dirname(copied['__file__']), os.path.isfile(copied['__file__'])),
      (FOLDER, True))
os.remove(upload)
check('and the copy outlives the original', restore(copied), copied['__file__'])
back = restore(copied)
check('it comes back as Gradio hands an upload: a string with .name, which Forge\'s Batch reads (#396)',
      (isinstance(back, str), getattr(back, 'name', None)), (True, copied['__file__']))
gone = keeper.keep_file(os.path.join(TESTS, 'py', 'queue_values_test.py'))
os.remove(gone['__file__'])
check('an upload whose copy is gone comes back MISSING', restore(gone) is MISSING, True)


def source(folder, name, data):
    """A file to upload, in a folder of its own: as Gradio keeps each upload."""
    path = os.path.join(WORK, 'sources', folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def read(kept):
    with open(kept['__file__'], 'rb') as f:
        return f.read()


names = Keeper(os.path.join(WORK, 'names'))
kept = [names.keep_file(source('1', 'my photo 1.png', b'one')), names.keep_file(source('2', 'café.png', b'two'))]
check("a copy keeps its upload's own name: Forge's Batch reads it, for Filename, a PNG info folder, "
      "an output named after it (#396)", [os.path.basename(k['__file__']) for k in kept],
      ['my photo 1.png', 'café.png'])

cases = Keeper(os.path.join(WORK, 'cases'))
kept = [cases.keep_file(source('3', 'a.png', b'lower')), cases.keep_file(source('4', 'A.png', b'upper'))]
check('two uploads whose names differ only in case are two copies, each its own bytes',
      [read(k) for k in kept], [b'lower', b'upper'])
numbered = Keeper(os.path.join(WORK, 'numbered'))
kept = [numbered.keep_file(source('5', 'x.png', b'first')), numbered.keep_file(source('6', 'x.png', b'second')),
        numbered.keep_file(source('7', 'x-1.png', b'third'))]
check('an upload named as a numbered copy writes over none', [read(k) for k in kept],
      [b'first', b'second', b'third'])
twice = Keeper(os.path.join(WORK, 'twice'))
one = source('8', 'same.png', b'same')
kept = [twice.keep_file(one), twice.keep_file(one)]
check('one file given twice is copied once, named by both values',
      (kept[0] == kept[1], os.listdir(twice.folder)), (True, ['same.png']))

def is_png(kept):
    # The file's bytes, not the picture: an upload written over it must fail a line, not raise.
    with open(kept['__image__'], 'rb') as f:
        return f.read(8) == b'\x89PNG\r\n\x1a\n'


mixed = Keeper(os.path.join(WORK, 'mixed'))
shot = mixed.keep(image, 'init_img')
copy = mixed.keep_file(source('9', 'init_img.png', b'upload'))
check('an upload named as an image already kept writes over neither',
      (copy['__file__'] != shot['__image__'], is_png(shot), read(copy)), (True, True, b'upload'))
mixed = Keeper(os.path.join(WORK, 'mixed-2'))
copy = mixed.keep_file(source('10', 'init_img.png', b'upload'))
shot = mixed.keep(image, 'init_img')
check('nor the other way round', (copy['__file__'] != shot['__image__'], is_png(shot), read(copy)),
      (True, True, b'upload'))
same = Keeper(os.path.join(WORK, 'same'))
check('images are named as before: a name used again is numbered',
      [os.path.basename(same.keep(image, 'x')['__image__']) for _ in range(2)], ['x.png', 'x-1.png'])
same = Keeper(os.path.join(WORK, 'same-2'))
check('and counted by name without extension, an image and an array alike',
      [os.path.basename(p) for p in (same.keep(image, 'x')['__image__'], same.keep(weights, 'x')['__array__'])],
      ['x.png', 'x-1.npy'])
renamed = Keeper(os.path.join(WORK, 'renamed'))
renamed.keep_file(source('11', 'my photo.png', b'upload'))
check('and an image whose name an upload took before, rewritten, is numbered as before',
      os.path.basename(renamed.keep(image, 'my_photo')['__image__']), 'my_photo-1.png')
renamed.keep_file(one)
renamed.keep_file(one)
check('as is one after a file given twice, though it is copied once',
      os.path.basename(renamed.keep(image, 'same')['__image__']), 'same-2.png')

# ------------------------------------------- an upload held inside a value


def uploaded(folder, name, data, root=UPLOADS):
    """A file as Gradio keeps an upload: in a folder of its own, named by a hash."""
    path = os.path.join(root, folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def kept_or_error(keeper, value):
    try:
        return keeper.keep(value)
    except Exception as e:  # a break that copies what it must not fails a line
        return repr(e)


held = Keeper(os.path.join(WORK, 'held'))
up = uploaded('h1', 'held.png', b'held')
kept = kept_or_error(held, up)
back = restore(kept)
check("text naming a file in Gradio's upload folder is copied with the task, under its own name (#396)",
      (isinstance(kept, dict) and os.path.dirname(kept.get('__file__') or '') == held.folder,
       os.path.basename(str(back)), getattr(back, 'name', None) == str(back)), (True, 'held.png', True))


@dataclasses.dataclass
class BatchUnit:
    """As ControlNet's unit in the original Forge: its Batch Upload pictures held as paths."""
    enabled: bool = True
    batch_input_gallery: object = None


def gallery_unit(keeper, tag):
    pictures = [uploaded(f'{tag}-1', 'one.png', b'one'), uploaded(f'{tag}-2', 'two.png', b'two')]
    return pictures, kept_or_error(keeper, BatchUnit(batch_input_gallery=[(p, None) for p in pictures]))


def read_items(unit, folder):
    if unit is MISSING or not isinstance(unit, BatchUnit):
        return repr(unit)
    out = []
    for item in unit.batch_input_gallery:
        try:
            with open(item[0], 'rb') as f:
                out.append((os.path.dirname(item[0]) == folder, f.read()))
        except OSError as e:
            out.append(type(e).__name__)
    return out


gallery = Keeper(os.path.join(WORK, 'gallery'))
pictures, stored = gallery_unit(gallery, 'g')
for p in pictures:
    os.remove(p)                          # Gradio's folder cleared before Start
check("a unit holding uploads in a gallery, as ControlNet's Batch Upload, reads them from the task's copies "
      "once Gradio's folder is cleared (#396)", read_items(restore(stored), gallery.folder), [(True, b'one'), (True, b'two')])

lost = Keeper(os.path.join(WORK, 'lost'))
pictures, stored = gallery_unit(lost, 'l')
copies = files(stored) if isinstance(stored, (dict, list)) else []
check('the unit names a copy of each picture', len(copies), 2)
if copies:
    os.remove(copies[0])
check('and with one copy gone the whole unit comes back MISSING, so its control takes its default',
      restore(stored) is MISSING, True)

plain = Keeper(os.path.join(WORK, 'plain'))
for what, text in (('a file elsewhere', source('12', 'outside.png', b'outside')),
                   ("a path in Gradio's folder naming no file", os.path.join(UPLOADS, 'h6', 'gone.png')),
                   ('a folder in it', os.path.dirname(uploaded('h5', 'in.png', b'in'))),
                   ('a file in a sibling folder named like it', uploaded('h4', 'x.png', b'x', root=UPLOADS + '-old')),
                   ('a relative path to a file in it', os.path.relpath(uploaded('h7', 'relative.png', b'r')))):
    check(f'text naming no upload is kept as text: {what}', kept_or_error(plain, text), text)
recorded = uploaded('h8', 'recorded.png', b'recorded')
check("the recorder keeps text naming an upload as text: a missing part would make a whole unit missing",
      kept_or_error(NoFiles(), recorded), recorded)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
