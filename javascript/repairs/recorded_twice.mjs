/**
 * Generations recorded twice (#241, #364): the review of the early copies a
 * press left before 0.70.5 - each listed beside the generation that keeps its
 * images, and removed only when ticked and confirmed, never its files.
 *
 * A repair's script (model_manager/repairs/recorded_twice.py on the server):
 * the loading module imports it only where the server says the library holds
 * early copies, and stops it with the Generations tab. It does nothing as it
 * is imported. Started, it offers its window - the note's Review opens it -
 * and draws its line in the settings window's database box, in the place the
 * box keeps for repairs.
 */

// The shared modules, under the version this script was asked for under (loader.mjs).
const shared = (name) => import(new URL(`../shared/${name}${new URL(import.meta.url).search}`, import.meta.url).href);
// Asked for at once, then awaited in turn: each awaited before the next was asked
// waited a round trip.
const SHARED_MODULES = ['core.mjs', 'calls.mjs', 'dialog.mjs', 'loading.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { apiCall, escapeHtml } = await shared('core.mjs');
const { call, ready } = await shared('calls.mjs');
const { openDialog } = await shared('dialog.mjs');
const { open } = await shared('loading.mjs');

const ROUTE = '/model-manager/repairs/recorded-twice';
let left = 0;              // early copies left, as the server last said
let showing = null;        // the window, while it is open

/**
 * Start it: `count` is how many early copies the server found. Its window is
 * offered as `repairs.recorded_twice`, the name the note's action calls.
 */
export function start(scope, { count = 0 } = {}) {
    left = count;
    scope.provide('repairs.recorded_twice', () => review(scope));
    scope.listen(window, 'mm-upkeep-drawn', (event) => drawLine(event.detail?.slot));
    // The settings window may be open already: its box drawn before this started.
    drawLine(document.querySelector('[data-repairs-slot]'));
    scope.onStop(() => {
        document.querySelector('[data-repair="recorded_twice"]')?.remove();
        showing?.close('code');
    });
}

/** Its line in the database box's place for repairs: while early copies are left. */
function drawLine(slot) {
    if (!slot) return;
    let line = slot.querySelector('[data-repair="recorded_twice"]');
    if (!left) {
        line?.remove();
        return;
    }
    if (!line) {
        line = document.createElement('div');
        line.className = 'mm-upkeep-row';
        line.dataset.repair = 'recorded_twice';
        slot.appendChild(line);
    }
    line.innerHTML = `<span class="mm-upkeep-line">Recorded twice: ${left} ${left === 1 ? 'generation' : 'generations'}</span>
        <button type="button" class="mm-btn mm-btn-small" data-action="repairs.recorded_twice">Review</button>`;
}

/** A press's time as a person reads it: "22 Oct 2026, 12:24". */
function when(createdAt) {
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) return createdAt || '';
    return date.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric',
                                          hour: '2-digit', minute: '2-digit' });
}

function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
}

function rowHtml(row) {
    const preview = row.image_id != null
        ? `<img class="mm-repair-preview" loading="lazy" alt=""
               src="/model-manager/generations/images/${encodeURIComponent(row.image_id)}/thumb">`
        : `<span class="mm-repair-preview mm-repair-hidden" title="Rated ${escapeHtml(row.hidden_level || '')
            }: hidden, as the Generations tab hides it">${escapeHtml(row.hidden_level || '')}</span>`;
    const batch = row.same_press > 1 && row.batch_count > 1 ? `, batch count ${row.batch_count}` : '';
    const prompt = row.prompt == null
        ? `Rated ${row.hidden_level}: hidden, as the Generations tab hides it`
        : (row.prompt || 'No prompt');
    const kept = row.same_press > 1 ? 'the last generation of the press' : 'the generation after it';
    return `<label class="mm-repair-row">
            <input type="checkbox" data-repair-id="${escapeHtml(row.id)}" checked>
            ${preview}
            <span class="mm-repair-text">
                <span class="mm-repair-when">${escapeHtml(when(row.created_at))} · ${escapeHtml(row.mode || '')}${batch}</span>
                <span class="mm-repair-prompt" title="${escapeHtml(prompt)}">${escapeHtml(prompt)}</span>
                <span>${plural(row.images, 'image', 'images')}, all in ${kept}, which has ${row.kept_images}</span>
            </span>
        </label>`;
}

/**
 * The review window: every early copy, ticked to begin with; Remove removes
 * the ticked ones, Cancel nothing. While it removes it cannot be closed, so a
 * removal half-done is never out of sight.
 */
async function review(scope) {
    if (showing) return;
    const element = document.createElement('dialog');
    element.className = 'mm-question mm-repair';
    element.setAttribute('aria-labelledby', 'mm_repair_recorded_twice');
    let busy = false;
    const frame = (body, buttons) => `<div class="mm-dialog mm-question-box">
            <h3 id="mm_repair_recorded_twice">Generations recorded twice</h3>
            ${body}
            <div class="mm-dialog-buttons">${buttons}</div>
        </div>`;
    const closeOnly = '<button type="button" class="mm-btn primary" data-repair-close>Close</button>';
    element.innerHTML = frame('<p class="mm-question-message">Looking for them...</p>', closeOnly);
    showing = openDialog(element, {
        beforeClose: () => !busy,
        onClose: () => { element.remove(); showing = null; },
    });
    // On its own elements: they go with it.
    element.addEventListener('click', (event) => {
        if (event.target.closest('[data-repair-close], [data-repair-cancel]')) showing?.close('cancel');
    });

    let rows;
    try {
        const answer = await apiCall({ endpoint: ROUTE });
        if (!answer?.success) throw new Error(answer?.error || 'the server did not say why');
        rows = answer.early || [];
    } catch (error) {
        element.innerHTML = frame(`<p class="mm-question-message">Could not list them: ${escapeHtml(error.message)}.</p>`,
                                  closeOnly);
        return;
    }
    if (!scope.live || !element.isConnected) return;
    left = rows.length;
    drawLine(document.querySelector('[data-repairs-slot]'));
    if (!rows.length) {
        element.innerHTML = frame('<p class="mm-question-message">No generation is recorded twice any more.</p>',
                                  closeOnly);
        return;
    }
    element.innerHTML = frame(`
            <p class="mm-question-message">Each was written early, during the press that made it: every image
                in it is also in the generation recorded after it. Removing one deletes its record; the image
                files stay.</p>
            <div class="mm-repair-head">
                <label class="mm-question-tick"><input type="checkbox" data-repair-all checked> Select all</label>
                <span class="mm-repair-count" data-repair-count></span>
            </div>
            <div class="mm-repair-list">${rows.map(rowHtml).join('')}</div>
            <p class="mm-question-note" role="status" data-repair-status>Image files are not deleted.</p>`,
        `<button type="button" class="mm-btn secondary" data-repair-cancel>Cancel</button>
            <button type="button" class="mm-btn secondary" data-repair-view
                    title="Show each one and the generation kept beside it in the Generations tab">View all</button>
            <button type="button" class="mm-btn danger" data-repair-remove></button>`);

    const boxes = () => [...element.querySelectorAll('[data-repair-id]')];
    const all = element.querySelector('[data-repair-all]');
    const remove = element.querySelector('[data-repair-remove]');
    const status = element.querySelector('[data-repair-status]');
    const tally = () => {
        const ticked = boxes().filter((box) => box.checked).length;
        all.checked = ticked === rows.length;
        all.indeterminate = ticked > 0 && ticked < rows.length;
        element.querySelector('[data-repair-count]').textContent = `${ticked} of ${rows.length} ticked`;
        remove.textContent = `Remove ${ticked}`;
        remove.disabled = ticked === 0;
        remove.title = ticked === 0 ? 'Nothing ticked' : '';
    };
    tally();
    // Every one listed and the generation each is kept in, ticked or not: to
    // look before choosing. The window closes; the list is asked again when
    // it opens again.
    element.querySelector('[data-repair-view]').addEventListener('click', () => {
        const ids = [...new Set(rows.flatMap((row) => [row.id, row.kept]))].sort((a, b) => a - b);
        showing?.close('code');
        open('generations', 'showSearch', `generation:${ids.join(',')}`);
    });
    element.addEventListener('change', (event) => {
        if (event.target === all) {
            // Some or none ticked: all of them; all ticked: none.
            const tick = boxes().some((box) => !box.checked);
            boxes().forEach((box) => { box.checked = tick; });
        }
        if (event.target.matches?.('[data-repair-id], [data-repair-all]')) tally();
    });
    remove.addEventListener('click', async () => {
        const ids = boxes().filter((box) => box.checked).map((box) => box.dataset.repairId);
        if (!ids.length || busy) return;
        busy = true;
        element.querySelectorAll('input, button').forEach((control) => { control.disabled = true; });
        status.textContent = `Removing ${ids.length}...`;
        let answer;
        try {
            const response = await fetch(`${ROUTE}/remove`, { method: 'POST',
                                                              body: new URLSearchParams({ ids: ids.join(',') }) });
            answer = await response.json();
            if (!answer?.success) throw new Error(answer?.error || 'the server did not say why');
        } catch (error) {
            busy = false;
            element.querySelectorAll('input, button').forEach((control) => { control.disabled = false; });
            tally();
            status.textContent = `Could not remove them: ${error.message}. Nothing more was removed.`;
            status.classList.add('mm-question-error');
            return;
        }
        busy = false;
        const removed = answer.removed || [];
        const skipped = answer.skipped || [];
        // A skipped one is no early copy any more either.
        left = Math.max(0, left - removed.length - skipped.length);
        drawLine(document.querySelector('[data-repairs-slot]'));
        const said = [`Removed ${removed.length}.`].concat(skipped.map((s) => `1 was skipped: ${s.why}.`));
        element.innerHTML = frame(said.map((line) => `<p class="mm-question-message">${escapeHtml(line)}</p>`).join(''),
                                  closeOnly);
        element.querySelector('[data-repair-close]')?.focus();
        // The Generations tab shows the rows as they now are, as after its own delete.
        if (removed.length && ready('generations.refresh')) call('generations.refresh');
    });
}
