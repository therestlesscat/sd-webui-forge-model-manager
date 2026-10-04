/**
 * Notes to the user. Per release, what is new and what to do after updating
 * (model_manager/release_notes.py): at the top of each tab, a pile - one
 * note in full, the edges of the rest showing under it, stepped through with
 * its arrows, or spread into rows with a click on the edges. Each note is
 * dismissed once for every browser using the database.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, escapeHtml } = await shared('core.mjs');
const { call } = await shared('calls.mjs');
const { showSyncDialog, showScanDialog } = await shared('jobs.mjs');

// What a note's button does, by the id its note names - with the action, for
// the settings section it is about.
const NOTE_ACTIONS = {
    reread_headers: () => showScanDialog({ rereadHeaders: true }),
    settings: (action) => call('settings.open', { section: action.section || null }),
    scan_disk: () => showScanDialog(),
    sync_unidentified: () => showSyncDialog({ force: 'unidentified' }),
};
const NOTE_ICONS = { feature: 'i', action: '!', warning: '!', intro: 'i' };
// On top: a tab's introduction, for someone new; then the important ones,
// then what needs doing, then warnings, then features - each newest first,
// as the server sends them.
const NOTE_ORDER = { intro: -2, action: 0, warning: 1, feature: 2 };
// How many edges show under the top note, however many notes there are.
const NOTE_EDGES = 2;
// How long a tab's notes wait for its container, which Gradio draws after
// the scripts run: 5 seconds, at 250ms apart.
const DRAW_TRIES = 20;
const noteTabs = {};        // tab -> { containerId, notes }
const notePiles = {};       // tab -> { index, spread }
const notesDismissed = new Set();

/**
 * Show a tab's notes in its container, once the server has said which -
 * the markup and the answer in whichever order they come - and again after
 * Gradio redraws the page, which empties the container.
 */
export function showNotes(tab, containerId) {
    if (!noteTabs[tab]) {
        noteTabs[tab] = { containerId, notes: null };
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
        if (attempt < DRAW_TRIES) setTimeout(() => drawNotes(tab, attempt + 1), TIMING.drawRetry);
        return;
    }
    const rank = (note) => (note.kind === 'intro' ? NOTE_ORDER.intro
        : note.important ? -1 : NOTE_ORDER[note.kind] ?? NOTE_ORDER.feature);
    const shown = state.notes.filter((note) => !notesDismissed.has(note.id))
        .map((note, at) => ({ note, at }))
        .sort((a, b) => rank(a.note) - rank(b.note) || a.at - b.at)
        .map(({ note }) => note);
    const pile = (notePiles[tab] ||= { index: 0, spread: false });
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

// One click handler for every tab's notes - this module runs once a page.
if (typeof window !== 'undefined') {
    const redrawAll = () => Object.keys(noteTabs).forEach((tab) => drawNotes(tab));
    document.addEventListener?.('click', (event) => {
        const target = event.target;
        const pileTab = target.closest?.('[data-note-pile]')?.dataset.notePile;
        const pile = pileTab && (notePiles[pileTab] ||= { index: 0, spread: false });
        if (pile && target.closest('[data-note-step]')) {
            pile.index += Number(target.closest('[data-note-step]').dataset.noteStep);
            drawNotes(pileTab);
            return;
        }
        if (pile && target.closest('[data-note-spread]')) {
            pile.spread = target.closest('[data-note-spread]').dataset.noteSpread === 'true';
            drawNotes(pileTab);
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
        notesDismissed.add(id);
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
