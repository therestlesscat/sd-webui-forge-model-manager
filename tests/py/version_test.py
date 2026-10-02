"""
The version, the changelog, version.json and the tags agree.

VERSION in model_manager/version.py is written by hand, a line in
CHANGELOG.md with it, the same in version.json - which installs read to learn
a newer version is out - and a tag after the commit: four places, so each
check here is one that a forgotten step fails. See "Versions" in AGENTS.md.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webui_stub                                       # noqa: E402

webui_stub.install()

import model_manager.version as version                 # noqa: E402
from model_manager.ui.header import version_link         # noqa: E402

fails = []
def check(label, got, want=True):
    if got != want:
        fails.append('%s\n   got  %r\n   want %r' % (label, got, want))


def parts(v):
    return tuple(int(n) for n in v.split('.'))


# ---------------------------------------------------------------- the changelog
text = open(os.path.join(ROOT, 'CHANGELOG.md'), encoding='utf-8').read()
entries = re.findall(r'^- \*\*(\d+\.\d+\.\d+)\*\* \(build (\d+)\)', text, re.M)
headings = re.findall(r'^## (\d+\.\d+) - ', text, re.M)
check('the changelog lists versions', len(entries) > 0, True)
check('its newest is this version', entries[0][0] if entries else None, version.VERSION)
check('newest first, every version once',
      [parts(v) for v, _ in entries] == sorted({parts(v) for v, _ in entries}, reverse=True), True)
check('and every build once, newest first',
      [int(b) for _, b in entries] == sorted({int(b) for _, b in entries}, reverse=True), True)
check('each version under the heading of its minor version',
      all(v.rsplit('.', 1)[0] == max((h for h in headings if parts(h) <= parts(v)), key=parts, default=None)
          for v, _ in entries), True)
check('a minor version\'s heading has its .0 entry',
      sorted(h + '.0' for h in headings) == sorted(v for v, _ in entries if v.endswith('.0')), True)

# ----------------------------------------------------------------- version.json
published = json.load(open(os.path.join(ROOT, 'version.json'), encoding='utf-8'))
check('version.json holds this version - what every install is told is out',
      published.get('version'), version.VERSION)
check('with its build, the newest changelog entry\'s - the notice shows it',
      published.get('build'), int(entries[0][1]) if entries else None)
check('and a note, a string, for later', isinstance(published.get('note'), str), True)

# ------------------------------------------------------------------- git, if any
def git(*args):
    try:
        return subprocess.run(['git', '-C', ROOT, *args], capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip()
    except Exception:
        return None


count = git('rev-list', '--count', 'HEAD')
if count:
    found = version.describe()
    check('the build is the commit\'s place in the history', found['build'], int(count))
    check('and follows the version', found['version'], '%s.%s' % (version.VERSION, count))
    tag = git('describe', '--tags', '--exact-match', 'HEAD')
    if tag:
        # The version the tagged commit holds - not the file, which a change
        # being made has already moved on.
        committed = re.search(r'^VERSION = "([^"]+)"', git('show', 'HEAD:model_manager/version.py') or '', re.M)
        check('a tagged commit\'s tag is its version', tag, 'v' + (committed.group(1) if committed else '?'))
    # The newest entry's build is its tagged commit's; before the tag, while
    # its bump is being made, this commit's or the next one. A commit that
    # bumps nothing - tests, docs - comes after it and moves only the build.
    if entries:
        newest_version, newest_build = entries[0][0], int(entries[0][1])
        tagged = git('rev-list', '--count', 'v' + newest_version)
        if tagged:
            check('the newest changelog entry\'s build is its tagged commit\'s',
                  newest_build, int(tagged))
        else:
            check('the newest changelog entry\'s build is this commit, or the one being made',
                  newest_build in (int(count), int(count) + 1), True)

# ---------------------------------------------------------- a copy without git
real = version._git
version._git = lambda *a: None
version._found = None
check('a copy without its history gives the version alone', version.describe()['version'], version.VERSION)
link = version_link()
check('which the header shows, linking to the changelog',
      ['>v%s<' % version.VERSION in link, version.CHANGELOG_URL in link, 'target="_blank"' in link],
      [True, True, True])
version._git = real
version._found = None

from model_manager.ui.header import header_actions
check('the header carries the version, beside the gear', version_link() in header_actions('model_manager'), True)
for tab in ('tab_model_manager.py', 'tab_civitai_browser.py', 'tab_generations.py'):
    source = open(os.path.join(ROOT, 'model_manager', 'ui', tab), encoding='utf-8').read()
    check('%s puts it in its header' % tab,
          '<!-- actions -->' in source and 'replace("<!-- actions -->", header_actions(' in source, True)

print('\n'.join('FAIL ' + f for f in fails) or 'All checks passed.')
sys.exit(1 if fails else 0)
