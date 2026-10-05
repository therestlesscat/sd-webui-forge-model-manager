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

from model_manager.scheduler.values import Keeper, MISSING, files, restore   # noqa: E402

WORK = os.path.join(TESTS, 'work', 'queue_values')
shutil.rmtree(WORK, ignore_errors=True)
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

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
