/**
 * Helpers shared by the Model Manager and Civitai Browser tabs.
 *
 * Both tabs render the same image cards, paginate them the same way and talk to
 * the same API, so the helpers that were identical in both scripts live here
 * instead of being maintained twice.
 *
 * An ES module, so the two tab scripts import what they need by name rather
 * than reaching for a global and depending on load order.
 */

/**
 * How long the page waits, and how often it asks the server how something is
 * going - in one place, so a test can shorten them all before the page loads,
 * with window.mmTiming. In the WebUI they are these.
 */
export const TIMING = Object.freeze({
    poll: 1000,           // downloads and sync progress
    scanPoll: 500,        // Scan Disk progress
    presetSettle: 600,    // no server call after a preset switch this long: done in the page alone
    presetQuiet: 400,     // quiet this long after the last call: Forge has nothing more to send
    presetMax: 15000,     // a server this slow is not waited on further
    estimate: 120,        // the sync dialog's cost, asked once its controls stop changing
    modulesCheck: 300,    // between asks whether Forge took a VAE / Text Encoder change
    modulesCheckMax: 3000, // and how long it is given to
    ...(typeof window !== 'undefined' && window.mmTiming) || {},
});

/**
 * Show a tab's "no Civitai API key" banner, once both halves exist.
 *
 * Without a key the rate limit is 0.5 requests a second rather than 6, the
 * tRPC endpoint carrying image prompts refuses outright, and some models will
 * not download - so most of what this extension does either crawls or quietly
 * fails, and both tabs need to say so.
 *
 * Nothing orders the two things this needs. The answer comes from a fetch
 * started at import, from a <script type="module"> in the head; the markup
 * appears when Gradio renders the tab. Applying it at fixed moments failed,
 * because whichever ran first found the other half missing. So it waits for
 * both, briefly, rather than guessing when they will be ready.
 *
 * The answer is fetched once however many tabs ask for it.
 */
const API_KEY_BANNER_TRIES = 20;        // 5 seconds, at 250ms apart

let apiKeyMissing = null;
let apiKeyRequest = null;
let uiOptionsRequest = null;

/** The server's ui-options, as they are now. A failed call answers null. */
function fetchUiOptions() {
    return fetch('/model-manager/ui-options', { cache: 'no-store' })
        .then((r) => r.json())
        .catch(() => null);
}

/**
 * The same, asked once for the page: whether there is an API key, and which
 * judges NSFW.
 */
function uiOptions() {
    uiOptionsRequest ||= fetchUiOptions();
    return uiOptionsRequest;
}

export function apiKeyStatus() {
    if (apiKeyMissing !== null) return Promise.resolve(apiKeyMissing);
    if (!apiKeyRequest) {
        apiKeyRequest = uiOptions()
            .then((data) => {
                if (!data) throw new Error('ui-options did not answer');
                // Answered even when the rest of that call failed.
                apiKeyMissing = data.has_api_key === false;
                return apiKeyMissing;
            })
            .catch(() => {
                // Unreachable is not the same as unconfigured; say nothing
                // rather than blame the key for a WebUI that is not answering.
                apiKeyMissing = false;
                return false;
            });
    }
    return apiKeyRequest;
}

const apiKeyBanners = new Set();

/**
 * Forget what the page was told by ui-options, after the settings window
 * saved: the API key banner and the NSFW note are asked again. Each tab has
 * its own copy of this module, and each calls this for its own.
 */
export function refreshUiOptions() {
    uiOptionsRequest = null;
    apiKeyMissing = null;
    apiKeyRequest = null;
    nsfwDetectionAsked = null;
    apiKeyBanners.forEach((bannerId) => showApiKeyBanner(bannerId));
    return loadNsfwDetection();
}

export function showApiKeyBanner(bannerId, attempt = 0) {
    apiKeyStatus();                     // starts the one fetch, if needed
    apiKeyBanners.add(bannerId);

    const banner = document.getElementById(bannerId);
    if (apiKeyMissing === null || !banner) {
        if (attempt < API_KEY_BANNER_TRIES) {
            setTimeout(() => showApiKeyBanner(bannerId, attempt + 1), 250);
        }
        return;
    }

    banner.style.display = apiKeyMissing ? 'flex' : 'none';
}

/**
 * Put the banners back after Gradio has redrawn the page.
 *
 * Gradio re-renders a gr.HTML block wholesale, and an inline style set on
 * something inside it does not survive that - the element comes back as the
 * markup declares it, which is hidden. Setting it once during startup is
 * therefore not enough: it has to be reasserted whenever the UI is rebuilt,
 * which is what this hook is for.
 */
if (typeof onAfterUiUpdate === 'function') {
    onAfterUiUpdate(() => {
        if (apiKeyMissing === null) return;
        apiKeyBanners.forEach((bannerId) => {
            const banner = document.getElementById(bannerId);
            if (banner) banner.style.display = apiKeyMissing ? 'flex' : 'none';
        });
    });
}

// ------------------------------------------------------ loading a gallery
// A model's images come from Civitai through the server, and take seconds;
// nothing used to show meanwhile - the old gallery stayed, and a switch
// changed looked ignored. So, from the moment it starts: a bar at the top of
// the gallery, over an empty one saying so when a model or version is opened,
// or over the current images, dimmed and not answering, when a switch changes.
// Both tabs' galleries.

const LOADING_BAR = '<div class="mm-loading-bar" role="progressbar" aria-label="Loading images"></div>';

/** A gallery about to be replaced: cleared, saying it is loading. */
export function showGalleryLoading(containerId, text = 'Loading images...') {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.classList.remove('mm-gallery-loading');
    container.innerHTML = `${LOADING_BAR}<div class="mm-images-loading">${escapeHtml(text)}</div>`;
    container.style.display = 'block';
}

/** A gallery as it is, while its first page is fetched again: dimmed, its switches off. */
export function dimGalleryWhileLoading(containerId, on) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.classList.toggle('mm-gallery-loading', on);
    container.querySelector(':scope > .mm-loading-bar')?.remove();
    if (on) container.insertAdjacentHTML('afterbegin', LOADING_BAR);
    container.querySelectorAll('input[type="checkbox"]').forEach((box) => { box.disabled = on; });
}

// ------------------------------------------------------ selecting to delete
// "Select", beside "Rate", where your generations are shown (the Generations
// tab, a model's Your generations): a tick on each batch and image, and one
// Delete for all of them - asked once. A batch's tick is the whole
// generation, as its own Delete: every image, those the NSFW filter hides
// too, which the question counts.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * The bar Select shows: how many images, Select all loaded, Clear, Delete.
 * `calls` names the window functions each button runs.
 */
export function selectBarHtml(images, calls) {
    return `<span class="mm-select-count">${plural(images, 'image')} selected</span>
        <button type="button" class="mm-btn secondary mm-btn-small" onclick="${calls.all}">Select all loaded</button>
        <button type="button" class="mm-btn secondary mm-btn-small" onclick="${calls.clear}"
                ${images ? '' : 'disabled'}>Clear</button>
        <button type="button" class="mm-btn danger mm-btn-small" onclick="${calls.delete}"
                ${images ? '' : 'disabled'}>Delete...</button>`;
}

/** What the one Delete asks: "Delete 37 images of 12 generations? (3 of them hidden by the NSFW filter)". */
export function bulkDeleteQuestion(images, generations, hidden = 0) {
    return `Delete ${plural(images, 'image')} of ${plural(generations, 'generation')}?`
        + (hidden ? ` (${hidden} of them hidden by the NSFW filter)` : '');
}

/**
 * Delete these generations whole and these images, in one request; the
 * server's answer ({success, images, deleted_files, failed}), or
 * {success: false, error}.
 */
export async function deleteManyGenerations({ generationIds = [], imageIds = [], withFiles = false }) {
    try {
        const response = await fetch('/model-manager/generations/delete-many', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ generation_ids: generationIds.join(','), image_ids: imageIds.join(','),
                                        delete_files: String(Boolean(withFiles)) }) });
        return await response.json();
    } catch (error) {
        return { success: false, error: error.message };
    }
}

/** What a finished Delete says. */
export function bulkDeleteReport(data, withFiles) {
    const failed = (data.failed || []).length;
    return `Deleted ${plural(data.images || 0, 'image')}`
        + (withFiles ? ` and ${plural(data.deleted_files || 0, 'file')}` : '; the image files are still on disk')
        + (failed ? `; ${failed} file${failed === 1 ? '' : 's'} could not be deleted` : '');
}

// ------------------------------------------------------ saved searches
// A tab's Save Search: one set of filters, kept in the database (the same in
// every browser, and in both WebUIs when they share it).

/** A tab's saved filters, or null: none saved, or the server not answering. */
export async function savedSearch(tab) {
    try {
        const data = await (await fetch(`/model-manager/saved-search?tab=${encodeURIComponent(tab)}`,
                                        { cache: 'no-store' })).json();
        return data && data.success ? data.filters : null;
    } catch (e) {
        return null;
    }
}

/** Save a tab's filters, or forget them with null. Whether the server kept it. */
export async function saveSearch(tab, filters) {
    try {
        const data = await (await fetch('/model-manager/saved-search', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tab, filters }) })).json();
        return Boolean(data && data.success);
    } catch (e) {
        return false;
    }
}

// ------------------------------------------------------ your generations
// "Your generations" off: nothing is recorded, and every tab of them goes -
// at once, without a restart: the Generations tab's button is hidden (from
// the next start the tab is not created at all), and each model's gallery
// shows only its Civitai images. What was recorded is kept. Known from
// ui-options, and again when the setting is saved, in the settings window or
// on the Settings page. Once for the page, on window: each tab has its copy
// of this module.

/** Whether your generations are shown: false only once the server said so. */
export function generationsEnabled() {
    return window.mmGenerationsEnabled !== false;
}

function tabButton(label) {
    const root = typeof gradioApp === 'function' ? gradioApp() : document;
    return Array.from(root.querySelectorAll('#tabs button')).find((b) => b.textContent.trim() === label) || null;
}

function applyGenerationsEnabled() {
    const button = tabButton('Generations');
    if (!button) return;
    const off = !generationsEnabled();
    button.style.display = off ? 'none' : '';
    // Off while its tab shows: to the Model Manager, rather than a tab whose button is gone.
    if (off && (button.classList.contains('selected') || button.getAttribute('aria-selected') === 'true')) {
        tabButton('Model Manager')?.click();
    }
}

/** Take a new answer: hide or show, and tell the tabs (the gallery listens). */
export function setGenerationsEnabled(enabled) {
    const changed = window.mmGenerationsEnabled !== undefined && window.mmGenerationsEnabled !== enabled;
    window.mmGenerationsEnabled = enabled;
    applyGenerationsEnabled();
    if (changed) window.dispatchEvent(new CustomEvent('mm-generations-enabled', { detail: { enabled } }));
}

if (typeof window !== 'undefined' && typeof fetch === 'function' && !window.mmGenerationsWatched) {
    window.mmGenerationsWatched = true;
    uiOptions().then((data) => {
        if (data && typeof data.generations_enabled === 'boolean') setGenerationsEnabled(data.generations_enabled);
    });
    // Saved in the settings window: its answer says the setting's new value.
    window.addEventListener?.('mm-settings-saved', (event) => {
        const value = event.detail?.settings?.model_manager_record_generations?.value;
        if (typeof value === 'boolean') setGenerationsEnabled(value);
    });
    // Applied on the Settings page: which keys changed is known, not their values.
    window.addEventListener?.('mm-settings-page-applied', (event) => {
        if (!(event.detail?.changed || []).includes('model_manager_record_generations')) return;
        fetchUiOptions().then((data) => {
            if (data && typeof data.generations_enabled === 'boolean') setGenerationsEnabled(data.generations_enabled);
        });
    });
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(applyGenerationsEnabled);
}

// ------------------------------------------------------ a newer version
// Beside the version in every tab's header, "v0.42.0 available", when the
// server's check (update_check.py) found one - linking where the version
// does, to the changelog. Asked once a page and hourly after, since the
// server checks only every 12 hours; again when the setting changes. Gradio
// redraws the headers, so it is put back after each update.

const UPDATE_SETTING = 'model_manager_check_updates';
const UPDATE_HELP = 'To update: Extensions -> Check for updates, then Apply and restart UI.';

function showUpdate() {
    const found = window.mmUpdate;
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
        notice.href = version.getAttribute('href') || '';
        notice.textContent = `v${found.latest} available`;
        notice.title = `Model Manager ${found.latest} is out; this is ${found.current}. ${UPDATE_HELP} `
            + 'Click for the changelog.';
    });
}

function askForUpdate() {
    return fetch('/model-manager/update')
        .then((response) => response.json())
        .then((data) => { window.mmUpdate = data && data.success ? data : null; })
        .catch(() => { window.mmUpdate = null; })
        .then(showUpdate);
}

if (typeof window !== 'undefined' && typeof fetch === 'function' && !window.mmUpdateWatched) {
    window.mmUpdateWatched = true;
    askForUpdate();
    setInterval(askForUpdate, 60 * 60 * 1000);
    // Turned on, the server checks at once: ask again once it has had a moment.
    const changed = (keys) => {
        if (keys.includes(UPDATE_SETTING)) [0, 5000].forEach((wait) => setTimeout(askForUpdate, wait));
    };
    window.addEventListener?.('mm-settings-saved', (event) => changed(event.detail?.changed || []));
    window.addEventListener?.('mm-settings-page-applied', (event) => changed(event.detail?.changed || []));
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(showUpdate);
}

// ------------------------------------------------------ notes to the user
// Per release, what is new and what to do after updating
// (model_manager/release_notes.py): at the top of each tab, a pile - one
// note in full, the edges of the rest showing under it, stepped through with
// its arrows, or spread into rows with a click on the edges. Each note is
// dismissed once for every browser using the database.

// What a note's button does, by the id its note names - with the action, for
// the settings section it is about.
const NOTE_ACTIONS = {
    reread_headers: () => window.mmOpenScanDialog?.({ rereadHeaders: true }),
    settings: (action) => window.mmOpenSettings?.({ section: action.section || null }),
    scan_disk: () => window.mmOpenScanDialog?.(),
    sync_unidentified: () => window.mmOpenSyncDialog?.({ force: 'unidentified' }),
};
const NOTE_ICONS = { feature: 'i', action: '!', warning: '!', intro: 'i' };
// On top: a tab's introduction, for someone new; then the important ones,
// then what needs doing, then warnings, then features - each newest first,
// as the server sends them.
const NOTE_ORDER = { intro: -2, action: 0, warning: 1, feature: 2 };
// How many edges show under the top note, however many notes there are.
const NOTE_EDGES = 2;
const noteTabs = {};        // tab -> { containerId, notes }

/**
 * Show a tab's notes in its container, once the server has said which -
 * the markup and the answer in whichever order they come - and again after
 * Gradio redraws the page, which empties the container.
 */
export function showNotes(tab, containerId) {
    if (!noteTabs[tab]) {
        noteTabs[tab] = { containerId, notes: null };
        // The page-wide click handler redraws a tab's pile through this: the
        // tab's copy of this module is the one that holds its notes.
        window.mmNoteRedraw[tab] = () => drawNotes(tab);
        fetch(`/model-manager/notes?tab=${encodeURIComponent(tab)}`)
            .then((response) => response.json())
            .then((data) => { noteTabs[tab].notes = (data && data.success && data.notes) || []; })
            .catch(() => { noteTabs[tab].notes = []; })
            .then(() => drawNotes(tab));
    }
    drawNotes(tab);
}

function drawNotes(tab, attempt = 0) {
    const state = noteTabs[tab];
    if (!state || !state.notes) return;
    const box = document.getElementById(state.containerId);
    if (!box) {
        if (attempt < API_KEY_BANNER_TRIES) setTimeout(() => drawNotes(tab, attempt + 1), 250);
        return;
    }
    const rank = (note) => (note.kind === 'intro' ? NOTE_ORDER.intro
        : note.important ? -1 : NOTE_ORDER[note.kind] ?? NOTE_ORDER.feature);
    const shown = state.notes.filter((note) => !window.mmNotesDismissed.has(note.id))
        .map((note, at) => ({ note, at }))
        .sort((a, b) => rank(a.note) - rank(b.note) || a.at - b.at)
        .map(({ note }) => note);
    const pile = (window.mmNotePiles[tab] ||= { index: 0, spread: false });
    pile.index = Math.max(0, Math.min(pile.index, shown.length - 1));
    if (!shown.length) {
        box.innerHTML = '';
        return;
    }
    // A note alone is still a pile, "1 of 1": its arrows stay, off.
    if (pile.spread && shown.length > 1) {
        box.innerHTML = shown.map((note) => noteHtml(note)).join('')
            + `<button type="button" class="mm-note-gather" data-note-pile="${escapeHtml(tab)}"
                       data-note-spread="false">Pile them up</button>`;
        return;
    }
    const edges = Math.min(NOTE_EDGES, shown.length - 1);
    box.innerHTML = `
        <div class="mm-note-pile" data-note-pile="${escapeHtml(tab)}">
            ${noteHtml(shown[pile.index], { at: pile.index + 1, of: shown.length, tab })}
            ${Array.from({ length: edges }, (_, i) => `
                <button type="button" class="mm-note-edge mm-note-edge-${i + 1}" data-note-spread="true"
                        title="Show all ${shown.length} notes" aria-label="Show all ${shown.length} notes"></button>`).join('')}
        </div>`;
}

function noteHtml(note, { at = 0, of = 0, tab = '' } = {}) {
    const kind = NOTE_ICONS[note.kind] ? note.kind : 'feature';
    const actions = (note.actions || (note.action ? [note.action] : []))
        .filter((action) => action && NOTE_ACTIONS[action.id])
        .map((action) => `<button type="button" class="mm-btn primary mm-btn-small" data-note-action="${escapeHtml(action.id)}"
                   data-note-section="${escapeHtml(action.section || '')}">${escapeHtml(action.label || 'Do it')}</button>`)
        .join('');
    // The arrows are always there - "1 of 1" on the last note, and their room
    // kept empty in the spread rows - and both they and Dismiss a set width
    // (style.css): so Dismiss stays where it was as the pile is stepped
    // through or dismissed. The arrows' is as wide as the count needs - "3 of
    // 12" two digits a side.
    const steps = of > 0 ? `
        <span class="mm-note-steps" data-note-pile="${escapeHtml(tab)}" style="--mm-note-digits: ${String(of).length}">
            <button type="button" class="mm-note-step" data-note-step="-1" title="Previous note"
                    ${at <= 1 ? 'disabled' : ''}>&lsaquo;</button>
            <span class="mm-note-count">${at} of ${of}</span>
            <button type="button" class="mm-note-step" data-note-step="1" title="Next note"
                    ${at >= of ? 'disabled' : ''}>&rsaquo;</button>
        </span>` : '<span class="mm-note-steps mm-note-steps-none" aria-hidden="true"></span>';
    return `
        <div class="mm-banner mm-note mm-note-${kind}" data-note="${escapeHtml(note.id)}">
            <span class="mm-banner-icon">${NOTE_ICONS[kind]}</span>
            <span class="mm-note-body">
                <strong>${note.important ? '[Important] ' : ''}${escapeHtml(note.title)}</strong>
                <span class="mm-note-version">${escapeHtml(note.version)}</span>
                <span class="mm-banner-note">${escapeHtml(note.text)}</span>
            </span>
            <span class="mm-note-buttons">
                ${actions}
                <button type="button" class="mm-btn secondary mm-btn-small mm-note-dismiss" data-note-dismiss
                        title="Hide this note; the settings window's What's new keeps it">Dismiss</button>
                ${steps}
            </span>
        </div>`;
}

// Once for the page, not once per copy of this module: a click would
// otherwise dismiss a note once for every tab.
if (typeof window !== 'undefined' && !window.mmNotesDismissed) {
    window.mmNotesDismissed = new Set();
    window.mmNotePiles = {};        // tab -> { index, spread }
    window.mmNoteRedraw = {};       // tab -> redraw its pile
    const redrawAll = () => Object.values(window.mmNoteRedraw).forEach((redraw) => redraw());
    document.addEventListener?.('click', (event) => {
        const target = event.target;
        const pileTab = target.closest?.('[data-note-pile]')?.dataset.notePile;
        const pile = pileTab && (window.mmNotePiles[pileTab] ||= { index: 0, spread: false });
        if (pile && target.closest('[data-note-step]')) {
            pile.index += Number(target.closest('[data-note-step]').dataset.noteStep);
            window.mmNoteRedraw[pileTab]?.();
            return;
        }
        if (pile && target.closest('[data-note-spread]')) {
            pile.spread = target.closest('[data-note-spread]').dataset.noteSpread === 'true';
            window.mmNoteRedraw[pileTab]?.();
            return;
        }
        const note = target.closest?.('[data-note]');
        if (!note) return;
        const button = target.closest('[data-note-action]');
        if (button) {
            NOTE_ACTIONS[button.dataset.noteAction]?.({ section: button.dataset.noteSection });
            return;
        }
        if (!target.closest('[data-note-dismiss]')) return;
        const id = note.dataset.note;
        window.mmNotesDismissed.add(id);
        redrawAll();                // the next note comes up; in other tabs too
        fetch('/model-manager/notes/dismiss', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ id }) })
            .catch((error) => console.warn('[ModelManager] Could not dismiss the note:', error));
    });
}
if (typeof onAfterUiUpdate === 'function') {
    onAfterUiUpdate(() => Object.keys(noteTabs).forEach((tab) => {
        const box = document.getElementById(noteTabs[tab].containerId);
        if (box && !box.children.length) drawNotes(tab);
    }));
}

// Shared across both tabs - only one tab renders images at a time
export let lazyMediaObserver = null;

export function onReady(callback) {
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(callback, 100);
    } else {
        document.addEventListener('DOMContentLoaded', callback);
    }
}

export async function apiCall({ endpoint, params = {} }) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.append(key, value);
        }
    });
    const response = await fetch(url);
    return response.json();
}

/**
 * Make text safe to place in HTML - as content, or inside a quoted attribute.
 *
 * This used to serialize a text node, which escapes & < > and, per the HTML
 * spec, nothing else. Almost every caller puts the result inside a quoted
 * attribute, and a Civitai prompt containing `"` then closed the attribute and
 * added one of its own: `onmouseover`, say. Prompts, tags, trigger words and
 * file names are all written by whoever uploaded them, so quotes are escaped
 * too.
 *
 * Not enough for a script context. An attribute is decoded before its handler
 * runs, so `&#39;` inside an onclick is a quote again by the time JavaScript
 * sees it. Data never goes inside an inline handler: see data-copy and
 * data-open-url below.
 */
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/**
 * An id from Civitai, as a number, or null if it is not one.
 *
 * Ids go into URLs and handler calls unquoted, so a string arriving where a
 * number was expected would be code. Civitai sends numbers today; this is so
 * that stays true of what reaches the page, whatever it sends tomorrow.
 */
export function safeId(value) {
    const n = Number(value);
    return Number.isSafeInteger(n) && n > 0 ? n : null;
}

/**
 * The http(s) URL in `value`, or null.
 *
 * Relative URLs are read against Civitai, since that is where the text they
 * come from was written.
 */
export function safeUrl(value, protocols = ['http:', 'https:']) {
    if (!value) return null;
    try {
        const url = new URL(String(value), 'https://civitai.com');
        return protocols.includes(url.protocol) ? url.href : null;
    } catch (e) {
        return null;
    }
}

/**
 * A model description, reduced to formatting.
 *
 * Descriptions are HTML by design, so they cannot be escaped - but they were
 * inserted raw, and the scan also reads them from .civitai.info files other
 * tools write. Anything not on the list goes: tags are unwrapped to their text,
 * and script-bearing ones are dropped with their contents. Only a link's href,
 * an image's src and a title survive as attributes, and only as http(s).
 *
 * Parsed with DOMParser, which is inert. Setting innerHTML on a detached
 * element is not: an <img onerror> fires there too.
 */
const DESCRIPTION_TAGS = new Set([
    'A', 'ABBR', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'DIV', 'EM', 'H1', 'H2',
    'H3', 'H4', 'H5', 'H6', 'HR', 'I', 'IMG', 'LI', 'OL', 'P', 'PRE', 'S', 'SMALL',
    'SPAN', 'STRIKE', 'STRONG', 'SUB', 'SUP', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD',
    'TR', 'U', 'UL',
]);
const DESCRIPTION_DROPPED = new Set([
    'SCRIPT', 'STYLE', 'IFRAME', 'FRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE',
    'FORM', 'INPUT', 'BUTTON', 'TEXTAREA', 'SELECT', 'SVG', 'MATH', 'NOSCRIPT',
    'TEMPLATE', 'AUDIO', 'VIDEO', 'SOURCE',
]);

function cleanDescriptionNode(node) {
    for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === 3) continue;               // text
        if (child.nodeType !== 1) { child.remove(); continue; }   // comments and the rest

        const tag = child.tagName.toUpperCase();
        if (DESCRIPTION_DROPPED.has(tag)) { child.remove(); continue; }

        cleanDescriptionNode(child);

        if (!DESCRIPTION_TAGS.has(tag)) {
            child.replaceWith(...Array.from(child.childNodes));
            continue;
        }

        for (const attr of Array.from(child.attributes)) {
            const name = attr.name.toLowerCase();
            const kept = name === 'title'
                || (tag === 'A' && name === 'href')
                || (tag === 'IMG' && (name === 'src' || name === 'alt'));
            if (!kept) child.removeAttribute(attr.name);
        }

        if (tag === 'A') {
            const href = safeUrl(child.getAttribute('href'), ['http:', 'https:', 'mailto:']);
            if (href) child.setAttribute('href', href);
            else child.removeAttribute('href');
            child.setAttribute('target', '_blank');
            child.setAttribute('rel', 'noopener noreferrer');
        } else if (tag === 'IMG') {
            const src = safeUrl(child.getAttribute('src'));
            if (src) child.setAttribute('src', src);
            else child.remove();
        }
    }
}

export function sanitizeHtml(html) {
    if (!html) return '';
    // A whole document rather than the bare fragment: browsers put a fragment
    // into <body> either way, but not every DOM implementation does.
    const doc = new DOMParser().parseFromString(
        '<!doctype html><html><body>' + String(html) + '</body></html>', 'text/html');
    cleanDescriptionNode(doc.body);
    return doc.body.innerHTML;
}

/**
 * Copying and opening, without putting data inside an onclick.
 *
 * Buttons that used to carry the text in their handler -
 * `writeText(\`${prompt}\`)` ran any ${...} in a prompt - now carry it in a
 * data attribute, which is never executed, and this one listener acts on it.
 * Installed once, on the document, so it covers markup rendered later.
 */
if (typeof document !== 'undefined'
        && typeof document.addEventListener === 'function'
        && !globalThis.__mmDelegatedClicks) {
    globalThis.__mmDelegatedClicks = true;
    document.addEventListener('click', (event) => {
        const target = event.target && event.target.closest
            ? event.target.closest('[data-copy], [data-open-url]')
            : null;
        if (!target) return;

        if (target.hasAttribute('data-open-url')) {
            const url = safeUrl(target.getAttribute('data-open-url'));
            if (url) window.open(url, '_blank', 'noopener');
            return;
        }

        const text = target.getAttribute('data-copy') || '';
        if (navigator.clipboard) navigator.clipboard.writeText(text);

        if (target.tagName === 'BUTTON') {
            const label = target.textContent;
            target.textContent = 'Copied!';
            setTimeout(() => { target.textContent = label; }, 1500);
        } else {
            target.classList.add('mm-copied');
            setTimeout(() => target.classList.remove('mm-copied'), 600);
        }
    });
}

export function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

/**
 * A model's reception, as Civitai reports it since star ratings went away.
 *
 * Renders nothing when nobody has voted, so a card is not cluttered with
 * two zeroes. A down count of zero still shows once there are up votes,
 * because "52.9K up, 0 down" is worth knowing.
 */
export function renderThumbs(up, down) {
    const ups = Number(up) || 0;
    const downs = Number(down) || 0;
    if (!ups && !downs) return '';

    const total = ups + downs;
    const share = Math.round((ups / total) * 100);
    const title = `${ups.toLocaleString()} up, ${downs.toLocaleString()} down (${share}% positive)`;

    return `<span class="mm-thumbs" title="${escapeHtml(title)}">`
         + `<span class="mm-thumbs-up">▲ ${formatNumber(ups)}</span>`
         + `<span class="mm-thumbs-down">▼ ${formatNumber(downs)}</span>`
         + `</span>`;
}

/**
 * How explicit an image is, on Civitai's scale:
 *   PG 1 · PG-13 2 · R 4 · X 8 · XXX 16 · Blocked 32 · Unknown 64
 * The judging is the server's (nsfw.py); the page reads what it sends.
 */
export const NSFW_UNKNOWN = 64;
export const NSFW_SFW_MAX = 3;  // PG | PG-13

/**
 * How explicit an image is - as the server judged it. Every image the page
 * shows comes through the server, which stamps mm_level on it (stamp_levels()
 * in nsfw.py). The page used to judge for itself, with a copy of the rule and
 * the words fetched to feed it. An image without a stamp is Unknown - so
 * hidden where anything unsafe is - rather than judged here on less.
 */
export function nsfwImageLevel(image) {
    return typeof image?.mm_level === 'number' ? image.mm_level : NSFW_UNKNOWN;
}

/**
 * The NSFW badge's text for an image: "X · prompt" when its prompt is what
 * made it NSFW, so an image hidden or badged against its rating says why;
 * otherwise the rating label the gallery would show.
 */
export function nsfwBadgeLabel(image, ratingLabel) {
    return image?.mm_level_from_prompt ? 'X · prompt' : ratingLabel;
}

// The lowest level a Civitai image's card badges: what the work-safe view
// lets through (PG, PG-13) goes unmarked.
const NSFW_BADGE_MIN = 4;   // R

/**
 * The badge on a Civitai image's card, or '' for none: its level as the
 * server judged it (mm_level), from R up. Both galleries once badged
 * Civitai's own `nsfw` field, which on most images is a boolean - 64,903 of
 * one library's 95,810 showed "true", whatever their rating, and the 34,744
 * with false showed nothing.
 */
export function nsfwBadge(image) {
    const level = nsfwImageLevel(image);
    if (level < NSFW_BADGE_MIN || level >= NSFW_UNKNOWN) return '';
    const named = [...RATING_LEVELS, [32, 'Blocked']].filter(([value]) => value <= level).pop();
    return nsfwBadgeLabel(image, named[1]);
}

/** Is this image safe for a work-safe view? */
export function isImageSafe(image) {
    return nsfwImageLevel(image) <= NSFW_SFW_MAX;
}

/**
 * The shortest prompt worth showing, in characters after trimming.
 *
 * Measured against a library of 101,369 images: 10,476 carry no prompt at all,
 * and everything from one to ten characters together is 627. There is a cliff
 * rather than a slope, so the exact number matters far less than having one.
 * Below four is "1", ".", "???" - never a prompt someone wrote.
 */
export const MIN_PROMPT_LENGTH = 4;

/** Does this image carry a prompt worth reading? */
export function hasReadablePrompt(image) {
    const meta = image?.meta || {};
    return (meta.prompt || '').trim().length >= MIN_PROMPT_LENGTH;
}

/**
 * Does this image carry a prompt you could reproduce it from?
 *
 * A prompt on its own is not enough - "Send to txt2img" without steps, sampler
 * and CFG produces something unrelated. Built on hasReadablePrompt() rather
 * than beside it, so the length floor cannot apply to one and not the other:
 * before it did, this accepted a prompt of "1" as long as the settings were
 * present.
 */
export function hasUsablePrompt(image) {
    if (!hasReadablePrompt(image)) return false;
    const meta = image?.meta || {};
    if (!meta.steps) return false;
    if (!(meta.sampler || meta.Sampler)) return false;
    if (!(meta.cfgScale || meta['CFG scale'])) return false;
    return true;
}

/**
 * The widths Civitai's image server makes copies at. Asked for a width in
 * between, it sends the next one up - 128 to 320 all came back 320 wide,
 * 400 and 450 came back 450 - so these are the only sizes there are
 * (measured on 8 images, 28 September 2026). It enlarges as readily: an
 * 832-wide upload asked for at 1600 came back 1600 wide.
 */
export const CIVITAI_WIDTHS = [320, 450, 512, 800, 1200, 1600, 2200];

/** The segment before a Civitai image URL's file name: what to send. */
const CIVITAI_OPTIONS = /\/[a-z]+=[^/]*\/([^/]+)$/i;

/** The smallest of Civitai's widths at least `pixels` wide. */
export function civitaiWidth(pixels) {
    const needed = Math.ceil(Number(pixels) || 0);
    return CIVITAI_WIDTHS.find((width) => width >= needed) || CIVITAI_WIDTHS[CIVITAI_WIDTHS.length - 1];
}

/** How many image pixels show `cssWidth` CSS pixels sharply on this screen - twice as many on a 2x one. */
function screenPixels(cssWidth) {
    const density = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    return (Number(cssWidth) || 0) * density;
}

/**
 * The URL to load a Civitai image or video from, to show it `cssWidth` CSS
 * pixels wide - or, given `pixels`, that many image pixels whatever the
 * screen: a copy at the width civitaiWidth() picks, not the upload.
 *
 * The segment before the file name tells Civitai's image server what to
 * send: original=true is the file as uploaded, width=N a copy it makes on
 * the first request and keeps. Originals ran from 107 KB to 2.9 MB where a
 * 450-wide copy was 86 KB, and a gallery page holds up to 100 of them.
 * Images were asked for as uploaded until 0.30.1, lest Civitai throttle so
 * many copies; 130 requests at five a second met no limit, and a copy that
 * fails to load falls back to the upload (mediaFallback).
 *
 * An image is never asked for wider than it was uploaded - Civitai would
 * enlarge it, larger and no sharper - but as uploaded instead. A video is
 * always asked for as a copy: an animated upload stays the GIF it was, even
 * under a .mp4 name, and original=true sent a 17 MB GIF that a card read as
 * video by its name, could not play, and left blank. A copy is a real MP4.
 *
 * Anything that is not a Civitai image URL with such a segment is returned
 * as it is.
 */
export function sizedMediaUrl(url, { cssWidth, pixels = null, originalWidth = null, type = null } = {}) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    const width = civitaiWidth(pixels ?? screenPixels(cssWidth));
    if (!isVideoUrl({ url, type }) && originalWidth && width >= Number(originalWidth)) {
        return originalMediaUrl(url);
    }
    return url.replace(CIVITAI_OPTIONS, `/width=${width}/$1`);
}

/**
 * A still of a Civitai video: its first frame as a JPEG, shown until it is
 * played. Civitai makes these at the video's own size, whatever width is
 * asked - 92 and 232 KB for two videos of 0.9 and 3.6 MB.
 */
export function videoStillUrl(url) {
    if (!url || !url.includes('image.civitai.com')) return '';
    return url.replace(CIVITAI_OPTIONS, '/anim=false/$1');
}

/**
 * How wide a gallery card's image is drawn, in CSS pixels, when it cannot be
 * measured: style.css's --mm-card-image-width on a wide window.
 */
export const GALLERY_IMAGE_WIDTH = 200;

/**
 * How wide a gallery card's image is drawn in this container, in CSS pixels,
 * measured rather than assumed: the stylesheet decides it, and narrows it -
 * 150px under 900px, the full width under 600px - where a fixed number here
 * would drift from it. A card is drawn out of sight, measured and removed.
 * GALLERY_IMAGE_WIDTH when nothing can be measured: a hidden container, or
 * no layout at all.
 */
export function galleryImageWidth(container) {
    if (!container || typeof container.appendChild !== 'function') return GALLERY_IMAGE_WIDTH;
    const probe = document.createElement('div');
    probe.className = 'mm-image-card';
    probe.style.cssText = 'position:absolute;visibility:hidden;left:0;right:0;pointer-events:none';
    probe.innerHTML = '<div class="mm-image-left"></div>';
    container.appendChild(probe);
    const width = probe.firstElementChild?.getBoundingClientRect?.().width || 0;
    probe.remove();
    return width > 0 ? width : GALLERY_IMAGE_WIDTH;
}

/** How wide a model card is drawn when a tab has not said otherwise. */
const DEFAULT_CARD_WIDTH = 200;

/** The URL a model card loads its Civitai image or video from, at the card's width. */
export function cardMediaUrl(url, type, cardWidth = DEFAULT_CARD_WIDTH, originalWidth = null) {
    return sizedMediaUrl(url, { cssWidth: cardWidth, originalWidth, type });
}

/** What a gallery image shows when it does not load. */
export const IMAGE_PLACEHOLDER_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200'%3E%3Crect fill='%23222933' width='320' height='200'/%3E%3Cg fill='%236b7280'%3E%3Cpath d='M130 78h60v44h-60z'/%3E%3Cpath d='M92 132l34-30 28 24 18-14 56 44H92z'/%3E%3Ccircle cx='208' cy='82' r='10'/%3E%3C/g%3E%3Ctext x='160' y='176' text-anchor='middle' fill='%239ca3af' font-size='14'%3EImage unavailable%3C/text%3E%3C/svg%3E";

/**
 * The attributes that make a Civitai image or video fall back when a copy
 * does not load: to the upload, then to the placeholder, if one is given.
 * The placeholder is an attribute, not written into the handler: its SVG
 * holds quotes, and inside onerror's string it broke the handler.
 */
export function mediaFallback(original, placeholder = '') {
    return `data-original="${escapeHtml(original || '')}" data-placeholder="${escapeHtml(placeholder)}"`
        + ' onerror="window.mmMediaFallback(this)"';
}

/**
 * The shape a gallery image or video holds before it loads, from the size
 * Civitai gives: the lazy placeholder is a 1x1 GIF, drawn at the card's width
 * as a square, and a portrait image grew by half its width when it arrived -
 * moving everything below it, and a scroll to a card on the way stopped short
 * by a card or two. Nothing, when the size is not known.
 */
export function mediaShape(img) {
    const width = Number(img?.width), height = Number(img?.height);
    return width > 0 && height > 0 ? `style="aspect-ratio: ${width} / ${height}"` : '';
}

// The handler itself, on window: the markup is strings, and each tab imports
// this module under its own ?mtime, so a module-level function would be two.
if (typeof window !== 'undefined' && !window.mmMediaFallback) {
    window.mmMediaFallback = (node) => {
        const original = node.getAttribute('data-original');
        if (original && node.getAttribute('src') !== original) {
            node.setAttribute('src', original);
            if (node.tagName === 'VIDEO') node.load();
            return;
        }
        node.onerror = null;
        const placeholder = node.getAttribute('data-placeholder');
        if (placeholder && node.tagName === 'IMG') node.setAttribute('src', placeholder);
    };
}

/**
 * The URL of a Civitai image or video exactly as uploaded - full size, where
 * cardMediaUrl() asks for a card's copy. Anything else is returned as it is.
 */
export function originalMediaUrl(url) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    return url.replace(CIVITAI_OPTIONS, '/original=true/$1');
}

// Wan generates at 16 frames a second, and Forge Neo's Frames slider stops at
// fifteen seconds of them (modules_forge/presets.py).
export const WAN_FPS = 16;
export const WAN_MAX_FRAMES = WAN_FPS * 15 + 1;

/**
 * How many frames Wan needs for a video this many seconds long, or null if
 * the length is unknown. By length rather than by frame count: an uploader
 * who interpolated to 32 frames a second kept the length, not the count.
 * Wan's latent packs four frames to one after the first, so it takes 4n + 1
 * and would round anything else itself (processing.py).
 */
export function videoFrames(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return null;
    const frames = 4 * Math.round((seconds * WAN_FPS - 1) / 4) + 1;
    return Math.min(Math.max(frames, 1), WAN_MAX_FRAMES);
}

/** A video's size as Wan can make it: its 2x2 patches of 8x latents, 16 px. */
export function videoSize(width, height) {
    const snap = (v) => Math.max(16, Math.round(v / 16) * 16);
    return { width: snap(width), height: snap(height) };
}

export function isVideoUrl({ url, type }) {
    if (!url) return false;
    if (type === 'video') return true;
    const lowerUrl = url.toLowerCase();
    return lowerUrl.endsWith('.mp4') ||
           lowerUrl.endsWith('.webm') ||
           lowerUrl.includes('.mp4?') ||
           lowerUrl.includes('.webm?');
}

export function setupLazyMedia(container) {
    if (!container) return;

    const lazyNodes = container.querySelectorAll('.mm-lazy-media[data-src]');
    if (lazyNodes.length === 0) return;

    const loadNode = (node) => {
        const src = node.getAttribute('data-src');
        if (!src) return;
        // A video's still, lazily as well: every video's at once was one
        // request per card before any came into view.
        const poster = node.getAttribute('data-poster');
        if (poster) {
            node.setAttribute('poster', poster);
            node.removeAttribute('data-poster');
        }
        node.setAttribute('src', src);
        node.removeAttribute('data-src');
        node.classList.remove('mm-lazy-media');
        if (node.tagName === 'VIDEO') {
            node.load();
        }
    };

    if (!('IntersectionObserver' in window)) {
        lazyNodes.forEach(loadNode);
        return;
    }

    if (!lazyMediaObserver) {
        lazyMediaObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                loadNode(entry.target);
                lazyMediaObserver.unobserve(entry.target);
            });
        }, {
            root: null,
            rootMargin: '350px 0px',
            threshold: 0.01,
        });
    }

    lazyNodes.forEach((node) => lazyMediaObserver.observe(node));
}

/**
 * Base model names in the order a filter lists them: alphabetical, with
 * 'Other' - a catch-all - at the bottom rather than in the middle.
 */
export function sortBaseModels(values) {
    const named = values.filter(v => v !== 'Other');
    named.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    return values.includes('Other') ? named.concat('Other') : named;
}

// ---------------------------------------------------- which judges prompts
// The settings' NSFW detection: a trained model, or the word
// list alone. The model is sometimes wrong in ways nobody can point at, so
// wherever it decides what is hidden, the page says so and where to switch.
// The word list says nothing: it does exactly what it says.

// Text, not markup: some pages set it as textContent. So it says where the
// setting is rather than linking to it.
export const NSFW_MODEL_NOTE = 'NSFW is judged by a trained model, which can be wrong. '
    + 'NSFW detection, in the settings (\u2699 at the top right of the tab), switches to a simple word list.';

let nsfwDetection = null;
let nsfwDetectionAsked = null;

/** Ask the server which judges prompts; once per page. */
export function loadNsfwDetection() {
    nsfwDetectionAsked ||= uiOptions()
        .then((data) => { nsfwDetection = data?.nsfw_detection === 'model' ? 'model' : 'words'; });
    return nsfwDetectionAsked;
}

/**
 * How a model's gallery opens, as the settings say now: asked each time a
 * model is opened, not once per page, so a change on the Settings page applies
 * to the next model without a reload. Hidden, both, if the server cannot say.
 *
 * @returns {Promise<{hideNsfw: boolean, hidePromptless: boolean}>}
 */
export async function galleryDefaults() {
    const data = await fetchUiOptions();
    return { hideNsfw: data?.gallery_hide_nsfw !== false,
             hidePromptless: data?.hide_promptless_images !== false };
}

// The NSFW levels one can give an image of one's own, as nsfw.USER_LEVELS on
// the server, which checks them: [value, name].
export const RATING_LEVELS = [[1, 'PG'], [2, 'PG-13'], [4, 'R'], [8, 'X'], [16, 'XXX']];

/**
 * A row of the levels one can rate an image of one's own, the one it has
 * marked: outlined when it is its prompt's, filled when it is a person's
 * rating. `of` is an image - its mm_level and user_level - or something
 * holding several, with the level and user_level they share, if they do.
 * `call` is the click, % standing for the level. Both tabs that show your
 * generations draw it.
 */
export function ratingRowHtml(of, call) {
    const level = of.mm_level ?? of.level;
    const mine = of.user_level;
    return `<div class="mm-rate" title="NSFW level: click to rate, click your rating again to clear it">
        ${RATING_LEVELS.map(([value, name]) => `<button type="button" class="mm-rate-chip${
            level === value ? ' mm-rate-current' : ''}${mine === value ? ' mm-rate-mine' : ''}"
            onclick="event.stopPropagation(); ${call.replace('%', value)}">${name}</button>`).join('')}
    </div>`;
}

/** The note, while the trained model is in force; '' otherwise, or before the answer. */
export function nsfwModelNote() {
    return nsfwDetection === 'model' ? NSFW_MODEL_NOTE : '';
}

/**
 * The gallery's filter banner: one sentence, and a switch for each filter.
 *
 *   300 images stored · 168 match the filters (100 shown) · 132 hidden due to unusable prompt
 *                                             [ ] Show unusable prompts (132)
 *
 * Three numbers, kept apart because they were once confused: what is stored,
 * what the filters let through, and what is on screen - a page at a time, so
 * fewer than match until Show More or the page buttons bring the rest. It
 * used to read "Showing 168 of 300", with 100 on screen.
 *
 * The hidden figures add up with what matches to the total, so an image both
 * filters would hide is counted once - by the first filter to hide it, which
 * the caller decides by the order it applies them. Each switch states the same
 * number as its clause while it hides; once ticked its clause drops out, since
 * it hides nothing, and the switch says how many of its kind it now shows. A
 * switch with nothing to hide or show is left out.
 *
 * Drawn whenever anything is stored, filtered or not, since it is where the
 * counts are; it stays in sight as the gallery scrolls. It used to appear only
 * while a filter hid something, and the Civitai Browser drew it again under
 * the list, before it stuck. Both tabs build it here, so the two cannot drift
 * apart.
 *
 * @param {object} options
 * @param {number} options.matching - images the filters let through, loaded or not.
 * @param {number} options.total - images stored, or loaded.
 * @param {number} options.onScreen - images drawn now.
 * @param {string} [options.word] - what `total` counts: 'stored' in the library,
 *     'loaded' from Civitai in the Civitai Browser, which keeps nothing.
 * @param {string} options.bannerClass - the tab's banner class.
 * @param {string} options.labelClass - the tab's switch label class.
 * @param {Array<object>} options.switches - one per filter:
 *     id, onchange (a fixed call, never data), label, reason (for "hidden due
 *     to ..."), showing (ticked), hidden (what it hides now), count (what it
 *     would show once ticked, i.e. its kind among what the other filter lets
 *     through), note (a word on what decides it), and applies (false to leave
 *     it out altogether).
 */
export function renderFilterBanner({ matching, total, onScreen, word = 'stored', bannerClass,
                                     labelClass, switches }) {
    if (!total) return '';
    const active = switches.filter((s) => s.applies !== false);

    const clauses = active
        .filter((s) => !s.showing && s.hidden > 0)
        .map((s) => `${s.hidden} hidden due to ${s.reason}`);

    const offered = active
        .map((s) => ({ ...s, number: s.showing ? s.count : s.hidden }))
        .filter((s) => s.number > 0 || s.showing);

    const counted = `${total} ${total === 1 ? 'image' : 'images'} ${word}`
        + ` · ${matching} match the filters (${onScreen} shown)`
        + (clauses.length ? ` · ${clauses.join(', ')}` : '');
    // A switch can carry a note on what decides it: the NSFW one, while a
    // trained model does.
    const notes = offered.map((s) => s.note).filter(Boolean);
    const sentence = counted + notes.map((n) => `<small class="filter-banner-note">${escapeHtml(n)}</small>`).join('');

    const controls = offered.length
        ? `<div class="filter-banner-switches">${offered.map((s) => `
                <label class="${labelClass}">
                    <input type="checkbox" id="${s.id}" ${s.showing ? 'checked' : ''} onchange="${s.onchange}">
                    ${s.label} (${s.number})
                </label>`).join('')}
           </div>`
        : '';

    return `<div class="${bannerClass} filter-banner-sticky"><span>${sentence}</span>${controls}</div>`;
}

// ------------------------------------------------------------ resource chips
// A send puts an image's LoRAs and embeddings under the prompts as chips: a
// click puts the resource's tag in, or takes it out. Most images list their
// LoRAs as resources without a tag in the prompt, which meant finding each
// one by hand. The rules are here, apart from the page, so they can be tested.

// What Forge loads through <lora:...>, by the file's own type or Civitai's.
const LORA_TYPES = new Set(['lora', 'locon', 'loha', 'lokr', 'dora', 'lycoris', 'lycoris full']);
const EMBEDDING_TYPES = new Set(['textualinversion', 'embedding', 'embed']);

// A LoRA an image gives no weight gets this one.
export const DEFAULT_LORA_WEIGHT = 0.5;

function resourceKind(type) {
    const value = String(type || '').toLowerCase();
    if (LORA_TYPES.has(value)) return 'lora';
    if (EMBEDDING_TYPES.has(value)) return 'embedding';
    return null;
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The text a chip puts in a prompt. */
export function chipTag(chip) {
    return chip.kind === 'lora' ? `<lora:${chip.name}:${chip.weight}>` : chip.name;
}

// A LoRA's tag at any weight - one edited by hand is still that LoRA's - and
// an embedding as a word of its own, not part of a longer one.
function chipPattern(chip) {
    const name = escapeRegExp(chip.name);
    return chip.kind === 'lora' ? `<lora:${name}(?::[^>]*)?>` : `(?<![\\w-])${name}(?![\\w-])`;
}

/** Whether a prompt holds a chip's resource. */
export function promptHasChip(prompt, chip) {
    return new RegExp(chipPattern(chip), 'i').test(prompt || '');
}

/**
 * A prompt with a chip's resource taken out if it is there - every copy, and
 * the comma that separated it - or put at the end if it is not.
 */
export function toggleChip(prompt, chip) {
    const text = prompt || '';
    if (!promptHasChip(text, chip)) {
        const kept = text.replace(/[\s,]+$/, '');
        return kept ? `${kept}, ${chipTag(chip)}` : chipTag(chip);
    }
    const tag = chipPattern(chip);
    return text
        .replace(new RegExp(`\\s*,\\s*${tag}`, 'gi'), '')
        .replace(new RegExp(`${tag}\\s*,?\\s*`, 'gi'), '');
}

/** A prompt with <lora:from...> tags naming the same file as <lora:to...>. */
export function renameLoraTags(prompt, from, to) {
    if (!prompt || !from || !to || from === to) return prompt;
    return prompt.replace(new RegExp(`<lora:${escapeRegExp(from)}(?=[:>])`, 'gi'), `<lora:${to}`);
}

/**
 * The chips for an image, and the LoRA tags its prompts use under a name
 * that is not the local file's.
 *
 * Its resources come twice: Civitai's list, by version id, and the
 * infotext's, by hash and under the name the prompt used. `files` is the
 * server's answer for both (/model-manager/image-resources); a resource with
 * no file there is shown, but cannot be put in. `gallery` is the file whose
 * gallery the image is in: an image often does not list the LoRA it was
 * posted to show. One chip per file, whichever list named it, with the
 * image's weight where either gives one.
 *
 * Returns { chips, renames }: a chip is { key, kind, name, weight,
 * installed, where, title, versionId, modelId, hash }, `name` being what goes
 * in the prompt - the file's stem, which Forge always knows it by. `where` is
 * the prompt the image had it in, else the positive one. versionId, modelId
 * and hash are what the image names it by, for downloading one that is not
 * installed; any may be null. renames: [{ from, to }].
 *
 * `missing` is what Civitai says of the ones the library lacks
 * (/model-manager/missing-resources), once it has answered: a missing one is
 * then named as its file will be once downloaded, so a download does not
 * rename it, and one the infotext knows only by hash is its version - one
 * chip with the same version from Civitai's list, not two. A hash Civitai
 * does not know, or a model it no longer has, is `notOnCivitai`.
 */
export function collectResourceChips(meta, files, gallery = null, missing = null) {
    const byVersion = (files && files.versions) || {};
    const byHash = (files && files.hashes) || {};
    // Found by the file's name, where no id or hash found it: see
    // resourceNames(). A chip found only so says so, under the chips.
    const byName = (files && files.names) || {};
    const chips = new Map();
    const renames = [];

    const add = ({ file, type, label, weight, versionId, modelId, hash, alias, named = false }) => {
        let notOnCivitai = false;
        let future = null;
        if (!file && missing) {
            const byHashAnswer = missing.hashes || {};
            if (!versionId && hash && Object.prototype.hasOwnProperty.call(byHashAnswer, hash)) {
                versionId = byHashAnswer[hash] || null;
                notOnCivitai = !versionId;
            }
            future = versionId ? (missing.versions || {})[String(versionId)] || null : null;
            if (future && future.gone) notOnCivitai = true;
            modelId = modelId || (future && future.model_id) || null;
        }
        const kind = resourceKind((file && file.file_type) || type || (future && future.file_type));
        if (!kind) return;
        const name = file ? file.file_stem : (future && future.file_stem) || label;
        if (!name) return;
        let key = file ? `file:${name.toLowerCase()}`
            : versionId ? `version:${versionId}` : `name:${name.toLowerCase()}`;
        // One version is one chip, whichever list found its file and
        // whichever did not: after a download the infotext's hash may not
        // lead to the file yet, while Civitai's version id does.
        const version = versionId || (file && file.version_id) || null;
        const sameVersion = !chips.has(key) && version
            && [...chips.values()].find((chip) => chip.versionId === version);
        if (sameVersion) key = sameVersion.key;
        const known = chips.get(key);
        if (known) {
            if (file && !known.installed) Object.assign(known, { installed: true, name, byName: named });
            if (file && !named) known.byName = false;
            if (known.weight === null && weight !== undefined && weight !== null) known.weight = weight;
            known.versionId = known.versionId || versionId || (file && file.version_id) || null;
            known.modelId = known.modelId || modelId || null;
            known.hash = known.hash || hash || null;
            known.notOnCivitai = known.notOnCivitai && notOnCivitai;
        } else {
            chips.set(key, { key, kind, name, weight: weight ?? null, installed: !!file,
                             aliases: new Set(), title: label || name,
                             versionId: versionId || (file && file.version_id) || null,
                             modelId: modelId || null, hash: hash || null, byName: !!file && named,
                             notOnCivitai });
        }
        if (file && alias && alias !== name) {
            chips.get(key).aliases.add(alias);
            if (kind === 'lora') renames.push({ from: alias, to: name });
        }
    };

    if (gallery && gallery.file_stem) {
        add({ file: gallery, type: gallery.file_type, label: gallery.file_stem });
    }
    for (const r of (meta && meta.civitaiResources) || []) {
        const id = r.modelVersionId;
        add({ file: id ? byVersion[String(id)] : null, type: r.type, versionId: id, modelId: r.modelId,
              label: [r.name || r.modelName, r.modelVersionName].filter(Boolean).join(' - '),
              weight: r.weight });
    }
    for (const r of (meta && meta.resources) || []) {
        const hash = String(r.hash || resourceHash(meta, r) || '').toLowerCase();
        const found = hash ? byHash[hash] : null;
        const named = !found && r.name ? byName[String(r.name).toLowerCase()] : null;
        add({ file: found || named, type: r.type, label: r.name, named: !!named,
              weight: r.weight, alias: r.name, hash: hash || null });
    }

    let negative = (meta && meta.negativePrompt) || '';
    for (const { from, to } of renames) negative = renameLoraTags(negative, from, to);
    const result = [...chips.values()].map(({ aliases, ...chip }) => {
        chip.weight = chip.weight ?? (chip.kind === 'lora' ? DEFAULT_LORA_WEIGHT : null);
        const named = [chip.name, ...aliases].some((n) => promptHasChip(negative, { ...chip, name: n }));
        chip.where = named ? 'negative' : 'positive';
        return chip;
    });
    return { chips: result, renames };
}

/**
 * A resource's hash from the image's `hashes`, where its own entry has none:
 * Forge writes {"lora:Ghibli_v6": "58549cc3d3"} there and leaves the
 * resources list without them.
 */
function resourceHash(meta, resource) {
    const hashes = (meta && meta.hashes) || {};
    const kind = resourceKind(resource.type);
    const prefixes = kind === 'lora' ? ['lora', 'lyco'] : kind === 'embedding' ? ['embed'] : [];
    for (const prefix of prefixes) {
        const hash = hashes[`${prefix}:${resource.name}`];
        if (hash) return hash;
    }
    return '';
}

/**
 * What to ask the library to find by name: the image's LoRAs and embeddings,
 * each with the hash the image gives for it, which the file has to match.
 */
export function resourceNames(meta) {
    return ((meta && meta.resources) || [])
        .filter((r) => r.name && resourceKind(r.type))
        .map((r) => ({ name: r.name, hash: String(r.hash || resourceHash(meta, r) || '') }));
}

export function renderResource(resource) {
    const type = resource.type || 'unknown';
    const name = resource.name || 'Unknown';
    const weight = resource.weight !== undefined ? resource.weight : null;

    let typeClass = 'mm-resource-other';
    let typeLabel = type;

    if (type.toLowerCase() === 'lora') {
        typeClass = 'mm-resource-lora';
        typeLabel = 'LoRA';
    } else if (type.toLowerCase() === 'vae') {
        typeClass = 'mm-resource-vae';
        typeLabel = 'VAE';
    } else if (type.toLowerCase() === 'embedding' || type.toLowerCase() === 'ti') {
        typeClass = 'mm-resource-embed';
        typeLabel = 'Embed';
    }

    const weightStr = weight !== null ? ` (${escapeHtml(String(weight))})` : '';

    return `<span class="mm-resource ${typeClass}" title="${escapeHtml(type)}: ${escapeHtml(name)}${weightStr}">
              <span class="mm-resource-type">${escapeHtml(typeLabel)}</span>
              <span class="mm-resource-name">${escapeHtml(name)}${weightStr}</span>
            </span>`;
}

/**
 * How many columns to lay a page of cards out in, so its rows come out even.
 *
 * Use the fewest rows the width allows, then spread the cards across them:
 * ten cards with room for nine is 5 + 5, not 9 + 1, and stays 5 + 5 down to
 * room for five. Only when another row is unavoidable does it change - room
 * for four is 4 + 4 + 2, which is as even as equal columns get.
 */
export function balancedColumns(cardCount, fit) {
    if (cardCount < 1 || fit < 1) return Math.max(fit, 1);
    const rows = Math.ceil(cardCount / fit);
    return Math.ceil(cardCount / rows);
}

/**
 * Keep a card grid's rows even: cap its card list at the balanced column
 * count, so the flex-wrap layout wraps there.
 *
 * Call it after each render. The first call also starts watching the grid's
 * width, so a resize re-balances it. The card width is measured from the
 * cards, so the card size setting needs no wiring of its own; a hidden tab
 * has no width and is left as it was until it is shown.
 *
 * @param {string} gridId - the element holding the .model-grid-inner list.
 */
export function balanceGridRows(gridId) {
    const grid = document.getElementById(gridId);
    const inner = grid?.querySelector('.model-grid-inner');
    if (!inner) return;
    watchGridWidth(gridId, grid);

    const cards = inner.querySelectorAll('.model-card');
    const cardWidth = cards[0]?.getBoundingClientRect().width || 0;
    const available = grid.clientWidth;
    if (!cards.length || !cardWidth || !available) return;

    const gap = parseFloat(window.getComputedStyle(inner).columnGap) || 0;
    const fit = Math.max(1, Math.floor((available + gap) / (cardWidth + gap)));
    const cols = balancedColumns(cards.length, fit);
    inner.style.maxWidth = `${Math.ceil(cols * cardWidth + (cols - 1) * gap)}px`;
    // For what sits over the grid and should line up with its cards - the
    // Model Manager's tabs.
    grid.parentElement?.style.setProperty('--mm-grid-width', inner.style.maxWidth);
}

// One observer per grid element. Capping the inner list's width does not
// change the grid's own, so an observer cannot feed itself.
const gridObservers = new Map();   // gridId -> { grid, observer }
function watchGridWidth(gridId, grid) {
    if (gridObservers.get(gridId)?.grid === grid || typeof ResizeObserver !== 'function') return;
    gridObservers.get(gridId)?.observer.disconnect();   // the tab's markup was replaced
    let lastWidth = -1;
    const observer = new ResizeObserver(() => {
        if (grid.clientWidth === lastWidth) return;
        lastWidth = grid.clientWidth;
        balanceGridRows(gridId);
    });
    observer.observe(grid);
    gridObservers.set(gridId, { grid, observer });
}

/**
 * Push a card size onto a container. Every card is sized by one rule from
 * --mm-card-width and --mm-card-height, so a card takes the size of the
 * container it is in: a tab, or the settings window's preview row.
 */
export function applyCardSize({ width, height, containerId, logTag }) {
    const container = document.getElementById(containerId);
    if (!container) return;
    setCardSize(container, width, height);
    console.log(`[${logTag}] Card size set to ${width}x${height}`);
}

/** The same, on an element already in hand. */
export function setCardSize(element, width, height) {
    element.style.setProperty('--mm-card-width', `${width}px`);
    element.style.setProperty('--mm-card-height', `${height}px`);
}

// -------------------------------------------------------------- model grids
// Both tabs' grids, and the settings window's card previews, are drawn here:
// a card, the page strip under the grid, and the grid itself. They take what
// to show and read no setting; each tab turns its own data into that.

// -------------------------------------------------------------- gallery pages
// A gallery is a list of pages, each a slice of what is stored before the
// switches filter it (model_manager/gallery.py). Both tabs draw a page the
// same way: its separator, after the first, its cards, and its note.

/** Where a page starts in the continuous list: a rule with its number on it. */
export function pageSeparator(page) {
    return `<div class="mm-page-separator" role="separator"><span>Page ${page}</span></div>`;
}

/**
 * What a page held, under its images: "Displaying 30 images for page 1 ·
 * 50 hidden due to NSFW filter · 20 hidden due to unusable prompt", the
 * switches' own words for why. The last page says there is no more - `end`,
 * which a gallery that does not come from Civitai leaves out - and a page
 * Civitai failed to fill says so.
 */
export function pageNoteHtml(page, { end = 'no more images on Civitai' } = {}) {
    const shown = page.shown || 0;
    const parts = [`Displaying ${shown} ${shown === 1 ? 'image' : 'images'} for page ${page.number}`];
    if (page.hidden_nsfw) parts.push(`${page.hidden_nsfw} hidden due to NSFW filter`);
    if (page.hidden_promptless) parts.push(`${page.hidden_promptless} hidden due to unusable prompt`);
    if (page.error) parts.push(`more could not be fetched from Civitai: ${page.error}`);
    else if (!page.more && end) parts.push(end);
    return `<div class="mm-page-note">${escapeHtml(parts.join(' · '))}</div>`;
}

/** What a card shows when it has no image, or its image does not load. */
export const CARD_PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect fill='%23333' width='100' height='100'/%3E%3Ctext x='50' y='50' text-anchor='middle' dy='.3em' fill='%23666' font-size='10'%3ENo Image%3C/text%3E%3C/svg%3E";

// A card's name is cut to this many characters, with "..." after.
const CARD_NAME_LENGTH = 30;

/**
 * One model card.
 *
 * Every text is escaped here, and a name is cut before it is escaped, so an
 * entity is never cut in half. The markup - its classes and their nesting -
 * is what the stylesheet, balanceGridRows(), the selection highlight and the
 * bookmark star patched in place all look for.
 *
 * @param {object} card
 * @param {number} card.index - its place in the grid, as data-index.
 * @param {string} card.onclick - what a click runs, e.g. "window.mmSelectModel(3)".
 * @param {string} card.name - the model's name, in full; the card cuts it.
 * @param {{src: string, video: boolean, original?: string}} [card.media] - the
 *     card image's URL, as cardMediaUrl() gives it, and the upload's, to fall
 *     back to; none, or an empty src, shows the placeholder.
 * @param {string[]} [card.classes] - added to model-card: owned, nsfw-x, ...
 * @param {Object<string, string|number>} [card.data] - data- attributes.
 * @param {{cls: string, text: string, title?: string, onclick?: string}[]} [card.overlays] -
 *     on the image: Owned, No Civitai Data, the bookmark star. One with an
 *     onclick is a button, whose click is its own, not the card's.
 * @param {{cls: string, text: string, title?: string}[]} [card.badges] -
 *     under the name: type, base model, versions.
 * @param {({text: string, title?: string}|{html: string})[]} [card.stats] -
 *     the bottom row. `html` is for renderThumbs(), which escapes its own.
 * @returns {string} the card's HTML.
 */
export function renderModelCard({ index, onclick, name, media, classes = [], data = {},
                                  overlays = [], badges = [], stats = [] }) {
    const full = name || 'Unknown';
    const shown = full.length > CARD_NAME_LENGTH ? full.substring(0, CARD_NAME_LENGTH) + '...' : full;
    const title = (item) => (item.title ? ` title="${escapeHtml(item.title)}"` : '');
    const src = media?.src || '';
    const image = !src
        ? `<img src="${CARD_PLACEHOLDER}" alt="${escapeHtml(full)}">`
        : media.video
            ? `<video src="${escapeHtml(src)}" loop muted autoplay playsinline ${mediaFallback(media.original)}></video>`
            : `<img src="${escapeHtml(src)}" alt="${escapeHtml(full)}" loading="lazy" ${mediaFallback(media.original, CARD_PLACEHOLDER)}>`;
    const attributes = Object.entries(data)
        .map(([key, value]) => ` data-${key}="${escapeHtml(value ?? '')}"`).join('');
    return `
        <div class="${['model-card', ...classes.filter(Boolean)].join(' ')}" data-index="${Number(index)}"${attributes} onclick="${escapeHtml(onclick)}">
            <div class="model-card-image">
                ${image}
                ${overlays.map((o) => (o.onclick
                    ? `<button type="button" class="${escapeHtml(o.cls)}"${title(o)} onclick="event.stopPropagation(); ${escapeHtml(o.onclick)}">${escapeHtml(o.text)}</button>`
                    : `<div class="${escapeHtml(o.cls)}"${title(o)}>${escapeHtml(o.text)}</div>`)).join('')}
            </div>
            <div class="model-card-info">
                <div class="model-card-name" title="${escapeHtml(full)}">${escapeHtml(shown)}</div>
                <div class="model-card-meta">
                    ${badges.map((b) => `<span class="badge ${escapeHtml(b.cls)}"${title(b)}>${escapeHtml(b.text)}</span>`).join('')}
                </div>
                <div class="model-card-stats">
                    ${stats.map((s) => (s.html !== undefined ? s.html : `<span${title(s)}>${escapeHtml(s.text)}</span>`)).join('')}
                </div>
            </div>
        </div>
    `;
}

/**
 * The page strip under a grid: Prev, five page numbers around the current
 * one with the first and last beyond them, Next.
 *
 * It shows only the pages it is told exist and never works out a count: the
 * Model Manager knows its last page, the Civitai Browser only how far it has
 * been, and whether Civitai has more. Prev is disabled on page 1, Next when
 * there is no page after this one.
 *
 * @param {object} p
 * @param {number} p.current - the page shown.
 * @param {number} p.last - the highest page there is to go to.
 * @param {boolean} p.hasNext - whether there is a page after this one; it may
 *     not be numbered yet.
 * @param {string} p.goTo - the window function a page number calls, with it.
 * @param {string} p.prev - the window function Prev calls.
 * @param {string} p.next - the window function Next calls.
 */
export function renderGridPagination({ current, last, hasNext, goTo, prev, next }) {
    const visible = 5;
    let start = Math.max(1, current - Math.floor(visible / 2));
    const end = Math.min(last, start + visible - 1);
    if (end - start < visible - 1) start = Math.max(1, end - visible + 1);

    const pages = [];
    if (start > 1) {
        pages.push(1);
        if (start > 2) pages.push(null);
    }
    for (let page = start; page <= end; page++) pages.push(page);
    if (end < last) {
        if (end < last - 1) pages.push(null);
        pages.push(last);
    }

    const numbers = pages.map((page) => (page === null
        ? '<span class="mm-page-ellipsis">...</span>'
        : `<button class="mm-page-num ${page === current ? 'active' : ''}" onclick="window.${goTo}(${page})">${page}</button>`
    )).join('');
    return `
        <div class="mm-pagination">
            <button class="mm-btn mm-page-btn" onclick="window.${prev}()" ${current <= 1 ? 'disabled' : ''}>
                ← Prev
            </button>
            <div class="mm-page-numbers">
                ${numbers}
            </div>
            <button class="mm-btn mm-page-btn" onclick="window.${next}()" ${hasNext ? '' : 'disabled'}>
                Next →
            </button>
        </div>
    `;
}

/**
 * A grid: its cards and the page strip under them, or a line saying why
 * there are none. Its rows are then balanced.
 *
 * @param {object} g
 * @param {string} g.gridId - the element to draw into.
 * @param {string[]} g.cards - renderModelCard()'s HTML, one per card.
 * @param {string} g.empty - the line shown when there are no cards.
 * @param {string} [g.pagination] - renderGridPagination()'s HTML, if the tab shows it.
 */
export function renderModelGrid({ gridId, cards, empty, pagination = '' }) {
    const grid = document.getElementById(gridId);
    if (!grid) return;
    if (!cards.length) {
        grid.innerHTML = `<div class="model-grid-empty">${escapeHtml(empty)}</div>`;
        return;
    }
    grid.innerHTML = `<div class="model-grid-inner">${cards.join('')}</div>${pagination}`;
    balanceGridRows(gridId);
}

// ------------------------------------------------------ a version to download
// Both tabs show a version that is not in the library the same way: what it
// is, what it costs, which of its files a download produces. The Civitai
// Browser shows every version of a search result; the Model Manager shows the
// versions of a local model that were never downloaded.

/** Bytes as a version's files read: "1.99 GB". */
export function formatBytes(bytes) {
    if (!bytes) return 'Unknown';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return bytes + ' B';
}

/** A date as a version's details read it: "Mar 1, 2025". */
export function formatDay(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

/**
 * Describe a version's paywall, or '' when it is free.
 *
 * `paid_access` is attached by the backend: Civitai leaves `availability`
 * as "Public" for paid versions, so the field is the only marker.
 */
export function paidAccessLabel(version) {
    const paid = version?.paid_access;
    if (!paid) return '';
    if (paid.permanent) return 'Paid';
    return paid.ends_at ? `Early Access until ${formatDay(paid.ends_at)}` : 'Early Access';
}

export function isPaid(version) {
    return !!version?.paid_access;
}

/**
 * Index of the file a download of this version will produce.
 *
 * Mirrors DownloadService.pick_file_index: files[0] is often the full
 * fp32 weights, roughly twice the size of the pruned file Civitai marks
 * primary, so the primary one is the default rather than the first.
 */
export function primaryFileIndex(version) {
    const files = version?.files || [];
    const primary = files.findIndex(f => f.primary);
    return primary === -1 ? 0 : primary;
}

/**
 * How a file reads in the picker: "pruned fp16 - 1.99 GB".
 *
 * metadata carries format/size/fp for model files; anything without it
 * (a VAE, a config, training data) falls back to its name and type.
 */
export function describeFile(file) {
    const meta = file?.metadata || {};
    const parts = [meta.size, meta.fp].filter(Boolean);

    if (!parts.length) {
        const type = file?.type && file.type !== 'Model' ? file.type : '';
        parts.push(type || file?.name || 'File');
    } else if (file?.type && file.type !== 'Model') {
        parts.push(file.type);
    }

    const size = file?.sizeKB ? formatBytes(file.sizeKB * 1024) : '';
    return size ? `${parts.join(' ')} - ${size}` : parts.join(' ');
}

// What a Download button says while its version is on its way, and is
// disabled for: one click, one download.
const DOWNLOAD_BUTTON_BUSY = {
    starting: 'Starting...', pending: 'Queued', downloading: 'Downloading...',
    finishing: 'Adding to library...', complete: 'Downloaded',
};

/** A Download button's label and whether it is disabled, from its version's download. */
function downloadButtonState(versionId) {
    const busy = DOWNLOAD_BUTTON_BUSY[downloads().status(versionId)];
    return { disabled: !!busy, label: busy || 'Download' };
}

/**
 * The Download button and, when there is a choice, the file picker.
 *
 * `prefix` is the tab's: the button is `<prefix>_download_btn` and calls
 * window.<prefix>Download(modelId, versionId, fileId), the picker calls
 * window.<prefix>SelectFile(index). A paid version answers the download URL
 * with 401/403 until it is bought on Civitai, so it is not offered. While
 * the version is downloading - from the click until it is in the library - the
 * button says so and takes no clicks: a second click started it again.
 */
export function renderDownloadControls({ prefix, modelId, version, fileIndex, owned }) {
    const files = version?.files || [];
    const file = files[fileIndex];
    const paidLabel = paidAccessLabel(version);

    let button = '';
    if (owned) {
        button = `<button class="mm-btn secondary" disabled>Already Owned</button>`;
    } else if (paidLabel) {
        button = `<button class="mm-btn secondary" disabled `
            + `title="Buy it on Civitai first">${escapeHtml(paidLabel)}</button>`;
    } else if (file) {
        const state = downloadButtonState(version?.id);
        button = `<button class="mm-btn primary" id="${prefix}_download_btn" `
            + `data-download-version="${safeId(version?.id)}" ${state.disabled ? 'disabled' : ''} `
            + `onclick="window.${prefix}Download(${safeId(modelId)}, ${safeId(version?.id)}, ${safeId(file?.id)})">`
            + `${state.label}</button>`;
    }

    // Only worth a control when there is something to choose between.
    const picker = files.length > 1
        ? `<select class="${prefix}-file-select" onchange="window.${prefix}SelectFile(this.value)"
                   title="Which file to download">
             ${files.map((f, i) => `<option value="${i}" ${i === fileIndex ? 'selected' : ''}
                    title="${escapeHtml(f.name || '')}">${escapeHtml(describeFile(f))}`
                    + `${f.primary ? ' (default)' : ''}</option>`).join('')}
           </select>`
        : '';

    return `${button}\n${picker}`;
}

/**
 * Point the File and File Size rows and the Download button at another file.
 *
 * In place rather than re-rendering the panel, which would scroll the reader
 * back to the top. The rows are `<prefix>_file_name` and `<prefix>_file_size`.
 */
export function showChosenFile(prefix, modelId, version, file) {
    const nameCell = document.getElementById(`${prefix}_file_name`);
    if (nameCell) nameCell.textContent = file.name || 'Unknown';

    const sizeCell = document.getElementById(`${prefix}_file_size`);
    if (sizeCell) {
        sizeCell.textContent = file.sizeKB ? formatBytes(file.sizeKB * 1024) : 'Unknown';
    }

    const button = document.getElementById(`${prefix}_download_btn`);
    if (button) {
        button.setAttribute('onclick',
            `window.${prefix}Download(${safeId(modelId)}, ${safeId(version?.id)}, ${safeId(file.id)})`);
    }
}

// ---------------------------------------------------------------- downloads
// A download takes minutes, and neither tab should make anyone stay in it to
// see how it is going. So there is one list, polled once, and each tab draws
// it in a panel of its own: a download started in either shows in both.
//
// Each tab imports this module under its own ?mtime (see the top of either
// tab script), so the two get separate copies of it and module state would
// not be shared. The list lives on window instead.

/**
 * Tell the WebUI about newly downloaded files.
 *
 * Downloading writes the file but the WebUI has already listed its model
 * directories, so a new checkpoint does not appear in the native dropdown
 * until something re-scans. Click the refresh control next to that
 * dropdown - the same one a user would press. Forge and Forge Neo both
 * expose it as #forge_refresh_checkpoint, and both hand back only new
 * choices, so the current selection is left alone.
 */
export function refreshWebUiModelList() {
    const root = (typeof gradioApp === 'function') ? gradioApp() : document;
    const refreshButton = root.querySelector('#forge_refresh_checkpoint');

    if (refreshButton) {
        refreshButton.click();
        console.log('[ModelManager] Refreshed the WebUI model list');
    } else {
        console.warn('[ModelManager] Could not find the checkpoint refresh button; '
            + 'the new model may need a manual refresh');
    }
}

const DOWNLOAD_STATUS_TEXT = {
    downloading: 'Downloading', pending: 'Queued', finishing: 'Adding to library',
    complete: 'Complete', error: 'Error', cancelled: 'Cancelled',
};

/** One download, as a panel shows it. Classes are the tab's own: `<prefix>-download-*`. */
function renderDownloadItem(dl, prefix) {
    const status = dl.status || 'pending';
    const percent = dl.percent?.toFixed(1) || 0;
    const downloaded = formatBytes(dl.downloaded_bytes || 0);
    const total = formatBytes(dl.total_bytes || 0);
    // finishing: on disk, being added to the library. Not complete until
    // it is, so that Complete and "Show in MM" arrive together.
    const showProgress = status === 'downloading' || status === 'pending' || status === 'finishing';
    const showCancel = status === 'downloading' || status === 'pending';
    const showDismiss = status === 'complete' || status === 'error' || status === 'cancelled';
    const p = prefix;

    return `
        <div class="${p}-download-item ${status}">
            <div class="${p}-download-item-header">
                <div class="${p}-download-name" title="${escapeHtml(dl.file_name || 'Unknown')}">${escapeHtml(dl.file_name || 'Unknown')}</div>
                <span class="${p}-download-status-badge ${status}">${DOWNLOAD_STATUS_TEXT[status] || status}</span>
            </div>
            ${showProgress ? `
                <div class="${p}-download-progress">
                    <div class="${p}-download-bar" style="width: ${status === 'pending' || status === 'finishing' ? 100 : percent}%"></div>
                </div>
            ` : ''}
            <div class="${p}-download-info">
                <span class="${p}-download-percent">
                    ${status === 'downloading' ? `${percent}% - ${downloaded} / ${total}` : ''}
                    ${status === 'pending' ? 'Waiting...' : ''}
                    ${status === 'finishing' ? `Adding to library... ${total}` : ''}
                    ${status === 'complete' ? `${total}` : ''}
                    ${status === 'error' ? escapeHtml(dl.error || 'Download failed') : ''}
                    ${status === 'cancelled' ? 'Download cancelled' : ''}
                </span>
                <div class="${p}-download-actions">
                    ${showCancel ? `
                        <button class="mm-btn mm-btn-small danger" onclick="window.mmCancelDownload(${safeId(dl.version_id)})">Cancel</button>
                    ` : ''}
                    ${showDismiss ? `
                        <button class="mm-btn mm-btn-small secondary" onclick="window.mmDismissDownload(${safeId(dl.version_id)})">Dismiss</button>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

function createDownloads() {
    const items = {};          // version id -> the server's progress
    const panels = new Set();  // tab prefixes with a panel on the page
    const completed = [];      // callbacks, each given a download once it is in the library
    const batchDone = [];      // callbacks, once nothing is left running
    // Dismissed here, and asked of the server to forget. A poll already on its
    // way can still carry one; it is not taken back unless it starts again.
    const dismissed = new Set();
    let poll = null;
    let landed = false;        // a download reached the library in this batch
    const finished = (dl) => ['complete', 'error', 'cancelled'].includes(dl.status);

    const running = (dl) => dl.status === 'downloading' || dl.status === 'pending'
        || dl.status === 'finishing' || (dl.status === 'complete' && !dl.synced);
    const starting = new Set();  // clicked, and the server has not answered yet

    /** Every Download button on the page, as its version's download stands. */
    function renderButtons() {
        for (const button of document.querySelectorAll('[data-download-version]')) {
            const state = downloadButtonState(Number(button.getAttribute('data-download-version')));
            button.disabled = state.disabled;
            button.textContent = state.label;
        }
    }

    function render() {
        const downloads = Object.values(items);
        // Downloading first, then queued, then whatever has finished.
        const order = { downloading: 0, finishing: 0, pending: 1, complete: 2, error: 3, cancelled: 4 };
        downloads.sort((a, b) => (order[a.status] ?? 5) - (order[b.status] ?? 5));

        const active = downloads.filter(d => d.status === 'downloading' || d.status === 'finishing').length;
        const queued = downloads.filter(d => d.status === 'pending').length;
        const done = downloads.filter(finished).length;
        const summary = [active && `${active} downloading`, queued && `${queued} pending`,
                         done && `${done} finished`].filter(Boolean).join(', ')
            || `${downloads.length} total`;

        renderButtons();
        for (const prefix of panels) {
            const panel = document.getElementById(`${prefix}_downloads`);
            const list = document.getElementById(`${prefix}_download_list`);
            const summaryEl = document.getElementById(`${prefix}_downloads_summary`);
            const dismissAll = document.getElementById(`${prefix}_downloads_dismiss_all`);
            if (panel) panel.style.display = downloads.length ? 'block' : 'none';
            if (dismissAll) dismissAll.style.display = done ? '' : 'none';
            if (!list) continue;
            if (summaryEl) summaryEl.textContent = summary;
            list.innerHTML = downloads.map(dl => renderDownloadItem(dl, prefix)).join('');
        }
    }

    async function tick() {
        try {
            const result = await apiCall({ endpoint: '/model-manager/civitai/download/progress' });
            if (!result.success || !result.downloads) return;
            // The list is the server's: one it no longer has is gone here too.
            const listed = new Set(result.downloads.map((dl) => dl.version_id));
            for (const id of Object.keys(items)) {
                if (!listed.has(items[id].version_id)) delete items[id];
            }
            for (const dl of result.downloads) {
                if (dismissed.has(dl.version_id)) {
                    if (finished(dl)) continue;
                    dismissed.delete(dl.version_id);         // started again
                }
                const prev = items[dl.version_id];
                // The file lands well before its database row does; until
                // `synced` the model is not in the library yet.
                const arrived = dl.status === 'complete' && dl.synced && !(prev && prev.synced);
                items[dl.version_id] = dl;
                if (arrived) {
                    landed = true;
                    for (const callback of completed) {
                        try { callback(dl); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
            render();

            if (!Object.values(items).some(running)) {
                clearInterval(poll);
                poll = null;
                // Once per batch - re-scanning walks every model directory,
                // so there is no point doing it per file.
                if (landed) {
                    landed = false;
                    refreshWebUiModelList();
                    for (const callback of batchDone) {
                        try { callback(); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
        } catch (e) {
            console.error('[ModelManager] Download poll error:', e);
        }
    }

    const store = {
        /** Draw the list in this tab's panel: `<prefix>_downloads` and the ids inside it. */
        addPanel: (prefix) => { panels.add(prefix); render(); },
        onComplete: (callback) => { completed.push(callback); },
        onBatchDone: (callback) => { batchDone.push(callback); },

        /** Follow a download the server has accepted. */
        track: (progress) => {
            if (!progress || progress.version_id == null) return;
            dismissed.delete(progress.version_id);
            items[progress.version_id] = progress;
            render();
            if (!poll) poll = setInterval(tick, TIMING.poll);
        },

        /** Ask for a version, and follow it. Returns the server's answer. */
        start: async function start(modelId, versionId, fileId) {
            if (downloadButtonState(versionId).disabled) return { success: false, error: 'Already downloading' };
            starting.add(Number(versionId));
            renderButtons();
            try {
                const form = new FormData();
                if (modelId) form.append('model_id', modelId);
                form.append('version_id', versionId);
                // Omitted when unknown, which leaves the backend on the primary.
                if (fileId !== undefined && fileId !== null) form.append('file_id', fileId);
                const response = await fetch('/model-manager/civitai/download', { method: 'POST', body: form });
                const result = await response.json();
                starting.delete(Number(versionId));
                if (result.success && result.progress) store.track(result.progress);
                return result;
            } finally {
                starting.delete(Number(versionId));
                renderButtons();
            }
        },

        /** Where a version's download stands: 'starting', the server's status, or undefined. */
        status: (versionId) => (starting.has(Number(versionId)) ? 'starting'
            : items[versionId]?.status),

        cancel: async function cancel(versionId) {
            try {
                const form = new FormData();
                form.append('version_id', versionId);
                await fetch('/model-manager/civitai/download/cancel', { method: 'POST', body: form });
            } catch (e) {
                console.error('[ModelManager] Cancel error:', e);
            }
        },

        /** Take a finished download off the list, here and on the server. */
        dismiss: (versionId) => store.forget([versionId], versionId),

        /** Take every finished download off the list. */
        dismissFinished: () => store.forget(
            Object.values(items).filter(finished).map((dl) => dl.version_id), 0),

        // The server forgets them too: it kept every download until the WebUI
        // restarted, and the next poll brought back what was dismissed here.
        forget: async function forget(versionIds, asked) {
            for (const id of versionIds) {
                dismissed.add(id);
                delete items[id];
            }
            render();
            try {
                const form = new FormData();
                form.append('version_id', asked);
                await fetch('/model-manager/civitai/download/dismiss', { method: 'POST', body: form });
            } catch (e) {
                console.error('[ModelManager] Dismiss error:', e);
            }
        },

        get: (versionId) => items[versionId],
    };

    window.mmCancelDownload = (versionId) => store.cancel(versionId);
    window.mmDismissDownload = (versionId) => store.dismiss(versionId);
    window.mmDismissFinishedDownloads = () => store.dismissFinished();
    return store;
}

/** The downloads both tabs show. See above. */
export function downloads() {
    if (!window.mmDownloads) window.mmDownloads = createDownloads();
    return window.mmDownloads;
}
