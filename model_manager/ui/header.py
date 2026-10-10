"""
What the tabs draw alike: the version and the settings gear at the right of
each header - one window, one gear - and the downloads panel, one list shown
in two tabs (#85). Each tab wrote its own copy; the Generations tab's gear,
the one drawn from here, opened on a tab called "TAB" in 0.44.21.
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
# which tab it is in ({tab}, filled by header_actions), so the window opens
# with that tab's sections open.
SETTINGS_BUTTON = """<button type="button" class="mm-settings-btn" data-action="settings.open" data-tab="{tab}"
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
    `tab`: "model_manager", "civitai_browser", "generations", "gallery" or "queue".
    """
    gear = SETTINGS_BUTTON.replace("{tab}", html.escape(tab))
    return f'<span class="mm-header-actions">{version_link()}{gear}</span>'


def downloads_panel(prefix: str) -> str:
    """
    The downloads panel, between a tab's grid and its details: one list, which
    javascript/shared/downloads.mjs draws into each tab's (`prefix` "mm" or
    "cb", the tab's ids and classes), with Pause all, Resume all and Dismiss
    all, each shown only while it has something to do.
    """
    p = html.escape(prefix)
    return f"""<div id="{p}_downloads" class="{p}-downloads-inline" style="display: none;">
    <div class="{p}-downloads-header">
        <h4>Downloads</h4>
        <div class="{p}-downloads-header-end">
            <span class="{p}-downloads-summary" id="{p}_downloads_summary"></span>
            <button class="mm-btn mm-btn-small secondary" id="{p}_downloads_pause_all"
                    title="Pause every download, running or waiting" style="display: none;"
                    data-action="downloads.control" data-control="pause_all">Pause all</button>
            <button class="mm-btn mm-btn-small secondary" id="{p}_downloads_resume_all"
                    title="Resume every paused download, in order" style="display: none;"
                    data-action="downloads.control" data-control="resume_all">Resume all</button>
            <button class="mm-btn mm-btn-small secondary" id="{p}_downloads_dismiss_all"
                    title="Take every finished download off the list" style="display: none;"
                    data-action="downloads.dismissFinished">Dismiss all</button>
        </div>
    </div>
    <div id="{p}_download_list" class="{p}-downloads-list"></div>
</div>"""
