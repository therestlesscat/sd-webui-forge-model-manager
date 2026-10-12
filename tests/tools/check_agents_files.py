"""
The rules for agents live in one AGENTS.md per folder, and each is found.

The root AGENTS.md holds the working agreement and what spans the repository;
a folder's holds the rules for its own code. Claude Code reads a folder's
only through a CLAUDE.md beside it holding `@AGENTS.md` - the root has a
CLAUDE.md, so a lone AGENTS.md is never read - and a rule named in another
file has to be where that file says. This fails, naming the line, on:

  1. a folder's AGENTS.md with no CLAUDE.md beside it, or a CLAUDE.md that
     holds anything but `@AGENTS.md`, or imports an AGENTS.md that is not
     there;
  2. a reference in an AGENTS.md - `model_manager/db/AGENTS.md`, "Absent is
     not empty" - to a file that is not there, or to a name that file does
     not hold as a heading, a bold lead or the first words of a paragraph,
     list item or table row;
  3. any other file mentioning AGENTS.md without naming the file and the
     rule that way, or naming one it does not hold. A path is the file's
     from the repository's root; "the root AGENTS.md" is the top one.

It reads names, not meaning: a right name on a wrong rule passes.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {'.git', '.claude', 'node_modules', '__pycache__'}
SKIP_PATHS = {os.path.join('tests', 'work')}
TEXT = ('.py', '.mjs', '.js', '.md', '.css', '.json', '.txt', '.yml', '.yaml', '.sh', '.html', '.bat')
THIS = os.path.abspath(__file__)
# `path/AGENTS.md`, "Name" - or the root's, `AGENTS.md` or AGENTS.md - with
# the name allowed to wrap across lines, comment markers and all.
REFERENCE = re.compile(r'`?((?:[\w.-]+/)*)AGENTS\.md`?,\s*(?:(?:#+|//+|\*)\s*)?"([^"]{1,240})"')
WRAP = re.compile(r'\s*\n\s*(?:#+|//+|\*)?\s*')

failures = []


def fail(path, line, why):
    failures.append('%s:%d: %s' % (os.path.relpath(path, ROOT).replace(os.sep, '/'), line, why))


def walk():
    for folder, dirs, files in os.walk(ROOT):
        rel = os.path.relpath(folder, ROOT)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and os.path.normpath(os.path.join(rel, d)) not in SKIP_PATHS)
        for name in sorted(files):
            yield os.path.join(folder, name)


def clean(text):
    return re.sub(r'\s+', ' ', text.replace('`', '').replace('*', '')).strip().lower()


def anchors(path, cache={}):
    """What a reference may name in a file: its headings, bold leads, and the
    first words of each paragraph, list item and table row."""
    if path not in cache:
        found = []
        text = open(path, encoding='utf-8').read()
        for block in re.split(r'\n\s*\n|\n(?=\s*(?:- |\d+\. |\||#))', text):
            block = block.strip()
            heading = re.match(r'#+\s+(.*)', block)
            if heading:
                found.append(clean(heading.group(1)))
                continue
            block = re.sub(r'^(?:- |\d+\. |\|\s*)', '', block)
            lead = re.match(r'\*\*(.+?)\*\*', block, re.S)
            if lead:
                found.append(clean(lead.group(1)))
            found.append(clean(block))
        cache[path] = found
    return cache[path]


def resolve(source, text, match):
    folder, name = match.group(1), WRAP.sub(' ', match.group(2))
    target = os.path.join(ROOT, *folder.rstrip('/').split('/'), 'AGENTS.md') if folder else os.path.join(ROOT, 'AGENTS.md')
    line = text.count('\n', 0, match.start()) + 1
    if not os.path.isfile(target):
        fail(source, line, 'names %sAGENTS.md, which is not there' % folder)
        return
    wanted = clean(name).rstrip('.:')
    if not any(a.startswith(wanted) for a in anchors(target)):
        fail(source, line, '%sAGENTS.md holds no "%s"' % (folder or 'the root ', name))


agents, claudes = [], []
for path in walk():
    name = os.path.basename(path)
    if name == 'AGENTS.md':
        agents.append(path)
    elif name == 'CLAUDE.md':
        claudes.append(path)

# 1. Each AGENTS.md read through a CLAUDE.md beside it, which imports it alone.
for path in agents:
    if not os.path.isfile(os.path.join(os.path.dirname(path), 'CLAUDE.md')):
        fail(path, 1, 'no CLAUDE.md beside it holding @AGENTS.md: Claude Code would never read it')
for path in claudes:
    if open(path, encoding='utf-8').read().strip() != '@AGENTS.md':
        fail(path, 1, 'a CLAUDE.md holds @AGENTS.md alone; what it says belongs in AGENTS.md')
    if not os.path.isfile(os.path.join(os.path.dirname(path), 'AGENTS.md')):
        fail(path, 1, 'imports an AGENTS.md that is not there')

# 2. A reference between the AGENTS.md files names a rule its file holds.
for path in agents:
    text = open(path, encoding='utf-8').read()
    for match in REFERENCE.finditer(text):
        resolve(path, text, match)

# 3. Anything else that cites AGENTS.md names the file and the rule.
for path in walk():
    if os.path.basename(path) in ('AGENTS.md', 'CLAUDE.md') or os.path.abspath(path) == THIS:
        continue
    if not path.endswith(TEXT):
        continue
    try:
        text = open(path, encoding='utf-8').read()
    except UnicodeDecodeError:
        continue
    cited = set()
    for match in REFERENCE.finditer(text):
        resolve(path, text, match)
        cited.add(match.start() + match.group(0).index('AGENTS.md'))
    for mention in re.finditer(r'AGENTS\.md', text):
        if mention.start() not in cited:
            fail(path, text.count('\n', 0, mention.start()) + 1,
                 'cites AGENTS.md without the file and the rule: path/AGENTS.md, "Name"')

print('\n'.join('FAIL ' + f for f in failures) or
      '%d AGENTS.md, each with its CLAUDE.md; every rule named is where it is said to be.' % len(agents))
sys.exit(1 if failures else 0)
