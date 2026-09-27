"""
What both tabs' headers carry besides their name: the version, beside the
settings gear. One definition, as the gear is one window.
"""
import datetime
import html

from ..version import CHANGELOG_URL, describe


def version_link() -> str:
    """The version, linking to the changelog, with the commit on hover."""
    found = describe()
    title = f"Model Manager {found['version']}"
    if found["commit"]:
        when = ""
        try:
            day = datetime.date.fromisoformat(str(found["date"]))
            when = f", {day.day} {day.strftime('%b %Y')}"
        except ValueError:
            pass
        title += f" - commit {found['commit']}{when}"
    if found["modified"]:
        title += ", with local changes"
    title += ". Click for the changelog."
    return (f'<a class="mm-version" href="{html.escape(CHANGELOG_URL)}" target="_blank" '
            f'rel="noopener" title="{html.escape(title)}">v{html.escape(str(found["version"]))}</a>')
