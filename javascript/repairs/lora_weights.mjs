/**
 * LoRA weights saved as 1 (#392): the review of the generations whose LoRAs
 * the recorder saved at weight 1 before 0.78.9, whatever their tags said -
 * each listed with what would change, and corrected only when ticked.
 *
 * A repair's script (model_manager/repairs/lora_weights.py on the server):
 * the loading module imports it only where the server says the library holds
 * such generations, and stops it with the Generations tab. It does nothing as
 * it is imported. Started, it offers its window - the note's Review opens it -
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

const ROUTE = '/model-manager/repairs/lora-weights';
let left = 0;              // generations left to correct, as the server last said
let showing = null;        // the window, while it is open

/**
 * Start it: `count` is how many generations the server found. Its window is
 * offered as `repairs.lora_weights`, the name the note's action calls.
 */
export function start(scope, { count = 0 } = {}) {
    left = count;
    scope.provide('repairs.lora_weights', () => review(scope));
    scope.listen(window, 'mm-upkeep-drawn', (event) => drawLine(event.detail?.slot));
    // The settings window may be open already: its box drawn before this started.
    drawLine(document.querySelector('[data-repairs-slot]'));
    scope.onStop(() => {
        document.querySelector('[data-repair="lora_weights"]')?.remove();
        showing?.close('code');
    });
}

function plural(n, one, many) {
    return `${n} ${n === 1 ? one : many}`;
}

/** Its line in the database box's place for repairs: while any is left. */
function drawLine(slot) {
    if (!slot) return;
    let line = slot.querySelector('[data-repair="lora_weights"]');
    if (!left) {
        line?.remove();
        return;
    }
    if (!line) {
        line = document.createElement('div');
        line.className = 'mm-upkeep-row';
        line.dataset.repair = 'lora_weights';
        slot.appendChild(line);
    }
    line.innerHTML = `<span class="mm-upkeep-line">LoRA weights saved as 1: ${plural(left, 'generation', 'generations')}</span>
        <button type="button" class="mm-btn mm-btn-small" data-action="repairs.lora_weights">Review</button>`;
}

/** A press's time as a person reads it: "22 Oct 2026, 12:24". */
function when(createdAt) {
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) return createdAt || '';
    return date.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric',
                                          hour: '2-digit', minute: '2-digit' });
}

/** A weight as the server sent it, drawn as a number or nothing. */
function number(value) {
    const n = Number(value);
    return Number.isFinite(n) ? String(n) : '';
}

/**
 * One LoRA's change, from the 1 it holds to its tag's: "example 1 → 0.7";
 * both weights named where they differ ("1 → text encoder 1, UNet 0.4" - the
 * UNet's alone may be what changes); and a tag with no fixed weight - a
 * weight schedule - said so.
 */
function changeText(change) {
    const known = (value) => value !== null && value !== undefined;
    const to = !known(change.te) ? 'no fixed weight'
        : known(change.unet) && change.unet !== change.te
            ? `text encoder ${number(change.te)}, UNet ${number(change.unet)}`
            : number(change.te);
    return `${change.name} ${number(change.from) || '1'} → ${to}`;
}

function rowHtml(row) {
    const preview = row.image_id != null
        ? `<img class="mm-repair-preview" loading="lazy" alt=""
               src="/model-manager/generations/images/${encodeURIComponent(row.image_id)}/thumb">`
        : `<span class="mm-repair-preview mm-repair-hidden" title="Rated ${escapeHtml(row.hidden_level || '')
            }: hidden, as the Generations tab hides it">${escapeHtml(row.hidden_level || '')}</span>`;
    const batches = Number(row.batch_count);
    const batch = Number.isFinite(batches) && batches > 1 ? `, batch count ${batches}` : '';
    const prompt = row.prompt == null
        ? `Rated ${row.hidden_level}: hidden, as the Generations tab hides it`
        : (row.prompt || 'No prompt');
    const images = Number(row.images);
    const changes = (row.changes || []).map(changeText).join('; ');
    return `<label class="mm-repair-row">
            <input type="checkbox" data-repair-id="${escapeHtml(row.id)}" checked>
            ${preview}
            <span class="mm-repair-text">
                <span class="mm-repair-when">${escapeHtml(when(row.created_at))} · ${escapeHtml(row.mode || '')}${batch}</span>
                <span class="mm-repair-prompt" title="${escapeHtml(prompt)}">${escapeHtml(prompt)}</span>
                <span>${Number.isFinite(images) ? plural(images, 'image', 'images') : ''}: ${escapeHtml(changes)}</span>
            </span>
        </label>`;
}

/**
 * The review window: every generation to correct, ticked to begin with;
 * Correct corrects the ticked ones, Cancel nothing. While it corrects it
 * cannot be closed, so a correction half-done is never out of sight.
 */
async function review(scope) {
    if (showing) return;
    const element = document.createElement('dialog');
    element.className = 'mm-question mm-repair';
    element.setAttribute('aria-labelledby', 'mm_repair_lora_weights');
    let busy = false;
    const frame = (body, buttons) => `<div class="mm-dialog mm-question-box">
            <h3 id="mm_repair_lora_weights">LoRA weights saved as 1</h3>
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
        rows = answer.generations || [];
    } catch (error) {
        element.innerHTML = frame(`<p class="mm-question-message">Could not list them: ${escapeHtml(error.message)}.</p>`,
                                  closeOnly);
        return;
    }
    if (!scope.live || !element.isConnected) return;
    left = rows.length;
    drawLine(document.querySelector('[data-repairs-slot]'));
    if (!rows.length) {
        element.innerHTML = frame('<p class="mm-question-message">No generation holds LoRA weights saved as 1 any more.</p>',
                                  closeOnly);
        return;
    }
    element.innerHTML = frame(`
            <p class="mm-question-message">Before version 0.78.9, the recorder saved each LoRA of an image's
                first pass at weight 1, whatever its tag in the prompt said. Correct sets each ticked LoRA to its tag's weight, or to
                no fixed weight where its tag gives a weight schedule. The prompts and image files stay as
                they are.</p>
            <div class="mm-repair-head">
                <label class="mm-question-tick"><input type="checkbox" data-repair-all checked> Select all</label>
                <span class="mm-repair-count" data-repair-count></span>
            </div>
            <div class="mm-repair-list">${rows.map(rowHtml).join('')}</div>
            <p class="mm-question-note" role="status" data-repair-status>LoRA weights only: nothing else is changed.</p>`,
        `<button type="button" class="mm-btn secondary" data-repair-cancel>Cancel</button>
            <button type="button" class="mm-btn secondary" data-repair-view
                    title="Show every one listed in the Generations tab">View all</button>
            <button type="button" class="mm-btn primary" data-repair-correct></button>`);

    const boxes = () => [...element.querySelectorAll('[data-repair-id]')];
    const all = element.querySelector('[data-repair-all]');
    const correct = element.querySelector('[data-repair-correct]');
    const status = element.querySelector('[data-repair-status]');
    const tally = () => {
        const ticked = boxes().filter((box) => box.checked).length;
        all.checked = ticked === rows.length;
        all.indeterminate = ticked > 0 && ticked < rows.length;
        element.querySelector('[data-repair-count]').textContent = `${ticked} of ${rows.length} ticked`;
        correct.textContent = `Correct ${ticked}`;
        correct.disabled = ticked === 0;
        correct.title = ticked === 0 ? 'Nothing ticked' : '';
    };
    tally();
    // Every one listed, ticked or not: to look before choosing. The window
    // closes; the list is asked again when it opens again.
    element.querySelector('[data-repair-view]').addEventListener('click', () => {
        const ids = rows.map((row) => row.id).sort((a, b) => a - b);
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
    correct.addEventListener('click', async () => {
        const ids = boxes().filter((box) => box.checked).map((box) => box.dataset.repairId);
        if (!ids.length || busy) return;
        busy = true;
        element.querySelectorAll('input, button').forEach((control) => { control.disabled = true; });
        status.textContent = `Correcting ${ids.length}...`;
        let answer = null;
        let failure = null;
        try {
            const response = await fetch(`${ROUTE}/correct`, { method: 'POST',
                                                               body: new URLSearchParams({ ids: ids.join(',') }) });
            answer = await response.json();
        } catch (error) {
            failure = error;
        }
        if (!answer?.success) {
            busy = false;
            element.querySelectorAll('input, button').forEach((control) => { control.disabled = false; });
            tally();
            // The server's own failure is rolled back whole; a lost answer may
            // have come after the server finished.
            status.textContent = failure
                ? `Could not hear back from the server: ${failure.message}. It may have finished: close this and press Review again to see what is left.`
                : `Could not correct them: ${answer?.error || 'the server did not say why'}. Nothing was changed.`;
            status.classList.add('mm-question-error');
            return;
        }
        busy = false;
        const corrected = answer.corrected || [];
        const skipped = answer.skipped || [];
        // A skipped one has nothing left to correct either.
        left = Math.max(0, left - corrected.length - skipped.length);
        drawLine(document.querySelector('[data-repairs-slot]'));
        const named = new Map(rows.map((row) => [String(row.id), when(row.created_at)]));
        const said = [`Corrected ${plural(corrected.length, 'generation', 'generations')}.`].concat(skipped.map((s) =>
            `The generation of ${named.get(String(s.id)) || 'an earlier list'} was skipped: ${s.why}.`));
        element.innerHTML = frame(said.map((line) => `<p class="mm-question-message">${escapeHtml(line)}</p>`).join(''),
                                  closeOnly);
        element.querySelector('[data-repair-close]')?.focus();
        // The Generations tab shows the images as they now are.
        if (corrected.length && ready('generations.refresh')) call('generations.refresh');
    });
}
