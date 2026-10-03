"""
Label each issue a commit on rc says it fixes, until the fix reaches main.

GitHub acts on "Fixes #N" only on the default branch, main, where it closes
the issue. rc is where a release is tried first: an issue fixed there is done
but not yet released, and stayed open with nothing to say so. Every commit on
rc not yet on main is read - not only the latest push, so a run missed or
started by hand catches up - and each open issue it names with one of
GitHub's closing words gets LABEL and a comment naming the commits. One that
has the label already, or is closed, is left alone; pull requests too.

    python .github/scripts/fixed_in_rc.py            # label (needs gh, GH_TOKEN)
    python .github/scripts/fixed_in_rc.py --dry-run  # say what it would label
"""
import json
import re
import subprocess
import sys

LABEL = "fixed-in-rc"
RANGE = "origin/main..origin/rc"

# GitHub's own closing words, any tense, an optional colon, this repository's
# issue: https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#(\d+)\b", re.IGNORECASE)


def run(*command):
    return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def fixed_on_rc():
    """{issue: [(short sha, subject), ...]}, oldest commit first."""
    named = {}
    log = run("git", "log", "--reverse", "--format=%h%x1f%s%x1f%B%x1e", RANGE)
    for entry in filter(str.strip, log.split("\x1e")):
        sha, subject, body = entry.strip().split("\x1f", 2)
        for number in dict.fromkeys(int(n) for n in CLOSING.findall(body)):
            named.setdefault(number, []).append((sha, subject))
    return named


def main(dry_run):
    named = fixed_on_rc()
    if dry_run:
        for number, commits in sorted(named.items()):
            print(f"#{number}: {', '.join(sha for sha, _ in commits)}")
        print(f"{len(named)} issues named by commits in {RANGE}")
        return
    issues = json.loads(run("gh", "issue", "list", "--state", "open", "--limit", "1000",
                            "--json", "number,labels"))
    waiting = {issue["number"] for issue in issues
               if LABEL not in {label["name"] for label in issue["labels"]}}
    for number, commits in sorted(named.items()):
        if number not in waiting:
            continue
        lines = "\n".join(f"- {sha} {subject}" for sha, subject in commits)
        run("gh", "issue", "edit", str(number), "--add-label", LABEL)
        run("gh", "issue", "comment", str(number), "--body",
            f"Fixed on `rc`, not yet released:\n\n{lines}\n\nIt closes when this reaches `main`.")
        print(f"#{number} labelled {LABEL}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv[1:])
