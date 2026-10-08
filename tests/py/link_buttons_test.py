"""
A button that opens a page is a <button data-open-url>, never an <a> dressed
as one (AGENTS.md, "What the WebUI does to our markup").

Gradio resets a <button>'s font inside its container, and not a link's: View
on Civitai on an image card and in the Civitai Browser's details drew its text
at 12.6 px and weight 500, beside buttons at 14 px and 400 (7870, both modes,
2026-10-08). The same markup in a dialog, outside the container, matched - so
the rule holds everywhere, not only where it shows (#144).
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


# An <a ...> tag, across lines, whose class names one of the button classes.
LINK_BUTTON = re.compile(r'<a\b[^>]*\bclass="[^"]*\b(?:mm|cb)-btn\b[^"]*"', re.S)
found = []
for base, ends in (('javascript', ('.mjs', '.js')), ('model_manager', ('.py',)), ('scripts', ('.py',))):
    for folder, _, names in os.walk(os.path.join(ROOT, base)):
        for name in names:
            if not name.endswith(ends):
                continue
            path = os.path.join(folder, name)
            text = io.open(path, encoding='utf-8').read()
            for m in LINK_BUTTON.finditer(text):
                found.append('%s:%d' % (os.path.relpath(path, ROOT).replace(os.sep, '/'),
                                        text.count('\n', 0, m.start()) + 1))
check('no link is dressed as a button: each is a <button data-open-url>', found, [])

# The check itself: it finds one, on one line or across two.
check('the check finds a link button on one line',
      bool(LINK_BUTTON.search('<a class="mm-btn secondary" href="x">View</a>')), True)
check('and across lines',
      bool(LINK_BUTTON.search('<a class="mm-btn secondary mm-btn-small" href="${u}" target="_blank"\n rel="noopener">')), True)
check('and leaves a plain link and a button alone',
      [bool(LINK_BUTTON.search('<a class="file-link" href="x">')),
       bool(LINK_BUTTON.search('<button class="mm-btn" data-open-url="x">'))], [False, False])

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
