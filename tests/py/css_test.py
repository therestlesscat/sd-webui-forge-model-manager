"""
One stylesheet, one definition per thing.

The two tabs were built separately, each with its own class prefix, so
equivalent components got two definitions. They then drifted: the Civitai
Browser carried a whole parallel filter bar that outranked the shared rules,
which is why fixing the shared ones changed nothing in that tab, twice.

This is the guard. It fails when a `cb-` and an `mm-` rule say the same thing,
so the next component that would have been copied has to be shared instead.
A tab-specific class is fine - the browser's downloads panel, the manager's
sync dialog - as long as only one tab has it.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)

CSS = io.open(os.path.join(ROOT, 'style.css'), encoding='utf-8').read()

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


# Comments hold example selectors; they are not rules.
BARE = re.sub(r'/\*.*?\*/', '', CSS, flags=re.S)
RULES = [(' '.join(m.group(1).split()),
          tuple(sorted(d.strip() for d in m.group(2).split(';') if d.strip())))
         for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', BARE)]

check('the stylesheet parses into rules', len(RULES) > 100, True)
check('and its braces balance', CSS.count('{'), CSS.count('}'))

# ------------------------------------------------- no rule written out twice
bodies = {}
for selector, body in RULES:
    if not body:
        continue
    bodies.setdefault(body, []).append(selector)

twins = []
for body, selectors in bodies.items():
    prefixed = [s for s in selectors if '.cb-' in s or '.mm-' in s]
    if len(prefixed) < 2:
        continue
    # The same declarations under a cb- selector and an mm- selector: one
    # component, written twice. Selectors that already name both are one rule.
    cb = [s for s in prefixed if '.cb-' in s and '.mm-' not in s]
    mm = [s for s in prefixed if '.mm-' in s and '.cb-' not in s]
    if cb and mm and len(body) > 2:
        twins.append((cb[0], mm[0], len(body)))

check('no component is defined once per tab',
      ['%s and %s share %d declarations' % t for t in twins], [])

# ---------------------------------------- and the shared pieces stay shared
def without_media(css):
    """Drop @media blocks: a responsive override is not a second definition."""
    out, i = [], 0
    while True:
        at = css.find('@media', i)
        if at == -1:
            out.append(css[i:])
            return ''.join(out)
        out.append(css[i:at])
        depth, j = 0, css.index('{', at)
        while True:
            if css[j] == '{':
                depth += 1
            elif css[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


TOP = [' '.join(m.group(1).split())
       for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', without_media(BARE))]

for shared in ('.filter-row', '.filter-group', '.filter-group label',
               '.filter-group-bordered', '.filter-group-half'):
    check('%s is defined once' % shared,
          [s for s in TOP if s == shared], [shared])

# The browser must not scope a copy of any of them to itself, which is how it
# came to outrank the shared rules: same specificity, later in the file.
for scoped in ('.cb-filters .filter-row', '.cb-filters .filter-group',
               '.cb-filters .filter-group-bordered', '.cb-filters .filter-group-half'):
    check('%s does not exist' % scoped, scoped in BARE, False)

# ------------------------------------------------- the button box is one box
buttons = [s for s, _ in RULES if re.match(r'^\.(mm|cb|action)-btn[,{ ]', s + ' ')]
base = [s for s in buttons if '.mm-btn,' in s]
check('every button family shares one base rule', len(base), 1)
check('which names all of them',
      all(name in base[0] for name in ('.mm-btn', '.cb-btn', '.action-btn')), True)

# ------------------------------------------- controls are one height, stated
control = [body for selector, body in RULES
           if selector.startswith('.filter-group input:not')]
check('the control box is defined once', len(control), 1)
check('it states a height',
      any(d.startswith('height:') for d in control[0]), True)
check('and measures it from the border', 'box-sizing: border-box' in control[0], True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
