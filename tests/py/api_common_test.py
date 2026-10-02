"""
What the endpoint modules share (model_manager/api/common.py, #78): the one
card-size parser in place of four copies, and the one way a failed request
is logged and answered in place of twenty copied blocks.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                        # noqa: E402
opts = webui_stub.install()

from model_manager.api.common import card_size, failed   # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


for text, want in (('260x364', (260, 364)), (' 160 X 224 ', (160, 224)), ('200x280x9', (200, 280)),
                   ('200x', (200, 280)), ('wide', (200, 280)), ('', (200, 280)), (None, (200, 280))):
    opts.model_manager_card_size = text
    check('a card size of %r reads as %r - as the four copies read it' % (text, want),
          card_size('model_manager_card_size'), want)
check('a setting that is not there reads as the default', card_size('model_manager_no_such_size'), (200, 280))

answer = failed(RuntimeError('it broke'), 'Testing error')
check('a failure is answered 500, success false, with the error',
      (answer.status_code, json.loads(answer.body)), (500, {'success': False, 'error': 'it broke'}))

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
