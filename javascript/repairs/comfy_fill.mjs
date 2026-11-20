/**
 * Civitai images filled from their ComfyUI workflows (#232): the Fill notice's
 * window. A library from before 0.81.5 stored its Civitai images' prompt rows,
 * settings rows and levels from Civitai's own fields; Fill makes them from what
 * each image's workflow holds where Civitai left a field out, on the press.
 *
 * A repair's script (model_manager/repairs/comfy_fill.py on the server): the
 * loading module imports it only where the server says the library has not
 * been filled, and stops it with the last of its two tabs - the Model Manager
 * and the Civitai Images tab. It does nothing as it is imported. Started, it
 * offers its window - the note's Review opens it - and draws its line in the
 * settings window's database box, in the place the box keeps for repairs.
 * Fill runs on the server as a long job: Close leaves it running, and the
 * window opened again, or in another page, shows where it is.
 */

// The shared modules, under the version this script was asked for under (loader.mjs).
const shared = (name) => import(new URL(`../shared/${name}${new URL(import.meta.url).search}`, import.meta.url).href);
// Asked for at once, then awaited in turn: each awaited before the next was asked
// waited a round trip.
const SHARED_MODULES = ['core.mjs', 'dialog.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { apiCall, escapeHtml } = await shared('core.mjs');
const { openDialog } = await shared('dialog.mjs');

const ROUTE = '/model-manager/repairs/comfy-fill';
// How often a running Fill is asked where it is.
const POLL_MS = 1000;
let fill = { state: 'idle' };   // the latest run, as the server last said
let left = true;                // whether the library is still to be filled
let newer = false;              // a newer copy sharing the database filled it
let refusal = null;             // why the server refused the last press, until the next answer
let lost = false;               // the last press went unanswered: Fill may be running
let showing = null;             // the window, while it is open
let drawn = '';                 // which of the window's states it shows
let polling = null;             // the timer asking a running Fill where it is
let asking = false;             // a question out: the poll skips its turn
let pressing = false;           // Fill pressed, its answer not yet in: the window shows it running
let presses = 0;                // Fill's presses so far: an answer to a question asked before
                                // the latest press is the server as it was before it

/** Start it. Its window is offered as `repairs.comfy_fill`, the name the note's action calls. */
export function start(scope) {
    scope.provide('repairs.comfy_fill', () => review(scope));
    scope.listen(window, 'mm-upkeep-drawn', (event) => drawLine(event.detail?.slot));
    // The settings window may be open already: its box drawn before this started.
    drawLine(document.querySelector('[data-repairs-slot]'));
    scope.onStop(() => {
        document.querySelector('[data-repair="comfy_fill"]')?.remove();
        showing?.close('code');
        polling = null;
    });
    // A run started from another page shows here too.
    ask(scope);
}

function number(n) {
    return Number(n || 0).toLocaleString('en-US');
}

function plural(n, one, many) {
    return `${number(n)} ${Number(n) === 1 ? one : many}`;
}

function running() {
    return fill.state === 'running';
}

function reading() {
    return running() && fill.step === 'filling' && fill.total != null;
}

/** A reason as a clause: its own full stop taken off, as the sentence ends it. */
function reason(text) {
    return String(text || 'the server did not say why').replace(/\.+\s*$/, '');
}

/** Where a running Fill is, in a sentence. */
function progressText() {
    if (reading()) {
        return `Reading ${number(fill.done)} of ${plural(fill.total, 'image', 'images')} that may hold a workflow. `
            + `${plural(fill.gained, 'image has', 'images have')} changed so far.`;
    }
    if (fill.step === 'waiting') return 'Waiting for the NSFW levels being judged again to finish...';
    return 'Finding the images that hold a workflow...';
}

/** What Fill did, in sentences. */
function resultText() {
    if (!fill.read) return 'No stored image holds a workflow that adds anything.';
    if (!fill.gained) return 'Every stored image that holds a workflow was filled already.';
    const said = [`${plural(fill.gained, 'image', 'images')} changed`
        + (fill.prompts ? `, ${number(fill.prompts)} of them gaining a prompt from the workflow.` : '.')];
    said.push(fill.levels
        ? `${plural(fill.levels, 'image is', 'images are')} judged at another NSFW level now.`
        : 'None is judged at another NSFW level.');
    if (fill.covers) {
        said.push(`${plural(fill.covers, 'version\'s cover', 'versions\' covers')}, shown while NSFW is hidden, `
            + 'went back to a safe image.');
    }
    return said.join(' ');
}

/** Its line in the database box's place for repairs: while the library is still to be filled. */
function drawLine(slot) {
    if (!slot) return;
    let line = slot.querySelector('[data-repair="comfy_fill"]');
    if (!left) {
        line?.remove();
        return;
    }
    if (!line) {
        line = document.createElement('div');
        line.className = 'mm-upkeep-row';
        line.dataset.repair = 'comfy_fill';
        slot.appendChild(line);
    }
    // A count only once Fill reads: before, it has none ("0 of 0").
    const text = reading()
        ? `Filling Civitai images from their workflows: ${number(fill.done)} of ${number(fill.total)}`
        : running() ? 'Filling Civitai images from their workflows: finding them...'
            : 'Civitai images can be filled from their ComfyUI workflows';
    line.innerHTML = `<span class="mm-upkeep-line">${escapeHtml(text)}</span>
        <button type="button" class="mm-btn mm-btn-small" data-action="repairs.comfy_fill">Review</button>`;
}

/** Ask the server where Fill is; keep asking while it runs, one question at a time. */
async function ask(scope) {
    if (asking) return;
    asking = true;
    const asked = presses;
    let answer = null;
    try {
        answer = await apiCall({ endpoint: ROUTE });
    } catch (error) {
        console.warn('[ModelManager] Could not ask where Fill is:', error);
    } finally {
        asking = false;
    }
    if (!scope.live || !answer?.success) return;
    // Asked before the latest press: it may say "idle" over a job the press
    // began. Asked again instead.
    if (asked !== presses) {
        ask(scope);
        return;
    }
    taken(scope, answer);
}

/** An answer taken in: the line and the window drawn again, the poll kept while it runs. */
function taken(scope, answer) {
    fill = answer.fill || { state: 'idle' };
    newer = Boolean(answer.newer);
    refusal = null;
    lost = false;
    if (fill.state === 'done') left = false;
    else if (answer.needed !== undefined) left = Boolean(answer.needed);
    drawLine(document.querySelector('[data-repairs-slot]'));
    if (showing) drawWindow();
    if (running() && !polling) {
        polling = scope.every(() => ask(scope), POLL_MS);
    } else if (!running() && polling) {
        clearInterval(polling);
        polling = null;
    }
    // Filled: its note has nothing left to offer.
    if (!left) window.dispatchEvent(new CustomEvent('mm-repair-done', { detail: { repair: 'comfy_fill' } }));
}

const BEFORE = `
    <p class="mm-question-message">Some Civitai images hold the ComfyUI workflow they were made with, while
        Civitai's own fields leave out their prompt, seed or other settings. The Model Manager shows and sends
        those from the workflow. Fill makes the images stored before this version searched, filtered and judged
        by them too, and the images stored later are the same.</p>
    <p class="mm-question-message">An image whose prompt was only in its workflow becomes searchable by it and
        stops counting as one with no prompt. Its NSFW level is judged from that prompt too, which can hide it
        under a lower NSFW maximum. Civitai's own data is kept as it is, and nothing is deleted.</p>
    <p class="mm-question-note">If two WebUIs share this database, update the extension in the other one first:
        an older copy stores what it refreshes without the workflow.</p>`;

function status(text, error = false) {
    return `<p class="mm-question-message${error ? ' mm-question-error' : ''}" role="status" data-repair-status>${
        escapeHtml(text)}</p>`;
}

/** Which of its states the window shows: its name, its body, and whether Fill is offered. */
function windowState() {
    if (pressing || running()) {
        return ['running', `${status(progressText())}
            <p class="mm-question-note">Close leaves it running, as a sync runs on.</p>`, 'disabled'];
    }
    if (lost) {
        return ['lost', status('The server did not answer the press. Fill may be running: '
            + 'this window asks the server again.'), false];
    }
    if (refusal) {
        return ['refused', status(`Fill was not started: ${reason(refusal)}.`, true), !newer];
    }
    if (fill.state === 'done' && !left) return ['done', status(resultText()), false];
    if (!left) {
        return ['filled', status(newer
            ? 'A newer copy of the extension sharing this database has filled the stored images already. Update this copy.'
            : 'The stored images are filled from their workflows already.'), false];
    }
    if (fill.state === 'failed') {
        return ['failed', status(`Fill stopped: ${reason(fill.error)}. What it filled is kept; `
            + 'press Fill to go on with the rest.', true) + BEFORE, true];
    }
    return ['before', BEFORE, true];
}

/**
 * The window's body and buttons, as Fill stands. Within one state only its
 * status line is written again: the window rebuilt every second while Fill
 * ran took the focus off Close.
 */
function drawWindow() {
    const element = showing?.element;
    if (!element) return;
    const [state, body, offered] = windowState();
    if (state === drawn && state === 'running') {
        const line = element.querySelector('[data-repair-status]');
        if (line && line.textContent !== progressText()) line.textContent = progressText();
        return;
    }
    drawn = state;
    const close = `<button type="button" class="mm-btn ${offered ? 'secondary' : 'primary'}" data-repair-close>Close</button>`;
    const fillButton = offered
        ? `<button type="button" class="mm-btn primary" data-repair-fill${offered === 'disabled' ? ' disabled' : ''}>Fill</button>`
        : '';
    element.innerHTML = `<div class="mm-dialog mm-question-box">
            <h3 id="mm_repair_comfy_fill">Fill Civitai images from their workflows</h3>
            ${body}
            <div class="mm-dialog-buttons">${close}${fillButton}</div>
        </div>`;
}

/** Fill pressed: started on the server, or joined where it runs. */
async function press(scope) {
    if (pressing) return;
    pressing = true;
    presses += 1;
    refusal = null;
    lost = false;
    drawWindow();
    let answer = null;
    try {
        const response = await fetch(`${ROUTE}/start`, { method: 'POST' });
        answer = await response.json()
            .catch(() => ({ success: false, error: `the server answered ${response.status}, not what it says` }));
    } catch (error) {
        console.warn('[ModelManager] Fill\'s press went unanswered:', error);
    }
    pressing = false;
    if (!scope.live) return;
    if (!answer) {
        // Sent, and perhaps started: what the server says now decides.
        lost = true;
        drawWindow();
        ask(scope);
        return;
    }
    if (!answer.success) {
        refusal = answer.error;
        newer = Boolean(answer.newer);
        drawWindow();
        return;
    }
    taken(scope, answer);
}

/** The window: what Fill does, before the press; where it is, while it runs; what it did, after. */
function review(scope) {
    if (showing) return;
    const element = document.createElement('dialog');
    element.className = 'mm-question mm-repair';
    element.setAttribute('aria-labelledby', 'mm_repair_comfy_fill');
    drawn = '';
    showing = openDialog(element, { onClose: () => { element.remove(); showing = null; } });
    // On its own elements: they go with it.
    element.addEventListener('click', (event) => {
        if (event.target.closest('[data-repair-close]')) showing?.close('cancel');
        else if (event.target.closest('[data-repair-fill]')) press(scope);
    });
    drawWindow();
    ask(scope);
}
