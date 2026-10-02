"""
What the tabs' headers carry besides their name: the version, beside the
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


# The gear that opens the settings window, which every tab shares. It says
# which tab it is in (TAB, filled by header_actions), so the window opens with
# that tab's sections open.
SETTINGS_BUTTON = """<button type="button" class="mm-settings-btn" data-action="settings.open" data-tab="TAB"
        title="Model Manager settings" aria-label="Model Manager settings">
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none"
         stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"></circle>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
    </svg>
</button>"""


def header_actions(tab: str) -> str:
    """
    The version and the settings gear, together at the right of a header.
    `tab`: "model_manager", "civitai_browser" or "generations".
    """
    gear = SETTINGS_BUTTON.replace("'TAB'", f"'{html.escape(tab)}'")
    return f'<span class="mm-header-actions">{version_link()}{gear}</span>'
