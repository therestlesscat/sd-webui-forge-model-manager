/**
 * Beside the version in every tab's header, "v0.42.0 available", when the
 * server's check (update_check.py) found one - linking where the version
 * does, to the changelog. Asked once a page and hourly after, since the
 * server checks only every 12 hours; again when the setting changes. Gradio
 * redraws the headers, so it is put back after each update.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { once, setText, setTitle } = await shared('core.mjs');

const UPDATE_SETTING = 'model_manager_check_updates';
const UPDATE_HELP = 'To update: Extensions -> Check for updates, then Apply and restart UI.';

let update = null;          // the server's last answer

function showUpdate() {
    const found = update;
    document.querySelectorAll('.mm-header-actions').forEach((actions) => {
        const version = actions.querySelector('.mm-version');
        let notice = actions.querySelector('.mm-update');
        if (!found?.newer || !version) {
            notice?.remove();
            return;
        }
        if (!notice) {
            notice = document.createElement('a');
            notice.className = 'mm-update';
            notice.target = '_blank';
            notice.rel = 'noopener';
            version.after(notice);
        }
        const href = version.getAttribute('href') || '';
        if (notice.getAttribute('href') !== href) notice.href = href;
        // With its build, as the version beside it has this copy's.
        const latest = found.build ? `${found.latest}.${found.build}` : found.latest;
        setText(notice, `v${latest} available`);
        setTitle(notice, `Model Manager ${latest} is out; this is ${found.current}. ${UPDATE_HELP} `
            + 'Click for the changelog.');
    });
}

function askForUpdate() {
    return fetch('/model-manager/update')
        .then((response) => response.json())
        .then((data) => { update = data && data.success ? data : null; })
        .catch(() => { update = null; })
        .then(showUpdate);
}

/** Asked by the first tab that starts this module, and hourly after (#182). */
export const start = once(() => {
    if (typeof window === 'undefined' || typeof fetch !== 'function') return;
    askForUpdate();
    setInterval(askForUpdate, 60 * 60 * 1000);
    // Turned on, the server checks at once: ask again once it has had a moment.
    const changed = (keys) => {
        if (keys.includes(UPDATE_SETTING)) [0, 5000].forEach((wait) => setTimeout(askForUpdate, wait));
    };
    window.addEventListener?.('mm-settings-saved', (event) => changed(event.detail?.changed || []));
    window.addEventListener?.('mm-settings-page-applied', (event) => changed(event.detail?.changed || []));
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(showUpdate);
});
