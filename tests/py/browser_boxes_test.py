"""
No browser box: every question the page asks is the dialog module's (#292).

The browser's confirm() is not the extension's: grey, headed with the page's
address, in the browser's light or dark rather than the theme's; while it is
open every script on the page stops - the downloads list froze under "Keep
loading?"; and a browser may stop a page's further boxes, after which confirm()
answers no without showing anything. Five were left in the page's scripts;
they are questions now (shared/dialog.mjs), and so is the sync's progress
popup, which drew its own overlay.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# A call to one of the browser's boxes, bare or through window - not a method
# of something else (a dialog's own .confirm), and not a word in a comment.
BOX = re.compile(r'(?<![\w.$])(?:window\.|globalThis\.)?(?:confirm|alert|prompt)\s*\(')
COMMENT = re.compile(r'^\s*(?://|\*|/\*)')
# A backdrop drawn by hand: the sync's own popup's, and the overlays the
# questions and the windows drew before the dialog container (#292).
OWN_OVERLAY = re.compile(r'\b(?:mm-sync-overlay|mm-dialog-backdrop|mm-modal-overlay)\b')


def files(where):
    for base, ends in where:
        for folder, _, names in os.walk(os.path.join(ROOT, base)):
            for name in names:
                if name.endswith(ends):
                    yield os.path.join(folder, name)


def scan(pattern, skip_comments=True, where=(('javascript', ('.mjs', '.js')),)):
    found = []
    for path in files(where):
        for number, line in enumerate(io.open(path, encoding='utf-8'), 1):
            if skip_comments and COMMENT.match(line):
                continue
            if pattern.search(line):
                found.append('%s:%d' % (os.path.relpath(path, ROOT).replace(os.sep, '/'), number))
    return found


check('no browser box in the page\'s scripts: each question is the dialog module\'s', scan(BOX), [])
check('no backdrop drawn by hand: every dialog is in the container, the browser drawing its backdrop',
      scan(OWN_OVERLAY, where=(('javascript', ('.mjs', '.js')), ('model_manager/ui', ('.py',)))), [])
check('nor styled: the stylesheet has no rule for one',
      [line for line in io.open(os.path.join(ROOT, 'style.css'), encoding='utf-8') if OWN_OVERLAY.search(line)], [])

# The check itself: it finds each, and leaves alone what is not one.
check('the check finds a bare confirm, window.confirm, an alert and a prompt',
      [bool(BOX.search('if (!confirm(text)) return;')), bool(BOX.search('window.confirm(`Discard?`)')),
       bool(BOX.search("alert('x')")), bool(BOX.search('const v = prompt("name")'))], [True] * 4)
check('and leaves a method of the same name, and a longer name, alone',
      [bool(BOX.search('dialog.confirm()')), bool(BOX.search('askToConfirm(x)')),
       bool(BOX.search('confirmed(x)'))], [False, False, False])
check('a comment naming confirm() is no call',
      bool(COMMENT.match(" * Before #292 a question was the browser's confirm() - which held every")), True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
