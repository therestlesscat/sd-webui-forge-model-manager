/**
 * What each runs with (#400, #406): the column beside a list of ticked
 * checkpoints, a line per checkpoint. The Resources dialog and Change's window
 * draw it alike. Change's window asks for it here - POST
 * /model-manager/queue/several/runs, answered by the press's own decision
 * (scheduler/several.py) - and hands how it names a checkpoint, what the
 * families are compared with, and whether it is still open. Also the settings'
 * names and how a value is written, which the dialog's usual settings of one
 * pick (resources.mjs, #378) take too.
 *
 * Imports core.mjs alone: resources.mjs, which draws the dialog, and
 * several.mjs, which draws Change's window and imports resources.mjs, both
 * import this, and two modules waiting on each other never load.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');

// The settings the column gives by value alone: "Euler a", "Karras" say what they are.
const UNNAMED_IN_SEVERAL = new Set(['sampler', 'schedule_type']);

// Each setting's name, as the column, the dialog's usual settings and Forge's controls name it.
export const USUAL_NAMES = { sampler: 'Sampler', schedule_type: 'Schedule type', steps: 'Steps', cfg: 'CFG scale',
                             distilled_cfg: 'Distilled CFG Scale', shift: 'Shift' };

/** A value as the column and the dialog's usual settings show it; a dash for none. */
export const shownValue = (value) => (value === null || value === undefined || value === '' ? '–' : String(value));

/**
 * A checkpoint's usual settings as its line says them, by key in their order:
 * "DPM++ 2M · Karras · Steps 30 · CFG scale 5".
 */
export function usualValuesText(values) {
    return Object.entries(values || {})
        // A sampler and a schedule type read as themselves; a number needs its name.
        .map(([key, value]) => `${UNNAMED_IN_SEVERAL.has(key) ? '' : `${USUAL_NAMES[key] || key} `}${shownValue(value)}`)
        .join(' · ');
}

/**
 * The column's markup from the lines it is handed: the heading, a line
 * per ticked checkpoint - `{name, another, what}`, marked when of another
 * family - then `after`, lines of its own under them, the family note, and
 * what stays as you set it. The Resources dialog's and Change's window's
 * (#406) alike.
 */
export function severalEachHtml({ entries = [], note = '', after = [] } = {}) {
    const each = entries.map(({ name, another, what }) => {
        const mark = another ? '<span class="mm-usual-each-family"> · another family</span>' : '';
        return `<div class="mm-usual-each"><span class="mm-usual-each-name">${escapeHtml(name)}${mark}</span>`
            + `<span class="mm-usual-each-what">${escapeHtml(what)}</span></div>`;
    }).join('');
    const below = after.map((text) => `<div class="mm-usual-note">${escapeHtml(text)}</div>`).join('');
    return `<div class="mm-usual-head">What each runs with</div>${each}${below}${
        note ? `<div class="mm-usual-note mm-usual-family" data-family-note>${escapeHtml(note)}</div>` : ''}`
        + '<div class="mm-usual-from">A setting too few uses record, or one this WebUI lacks, stays as you set it. '
        + 'Hires fix follows each run\'s sampler, schedule type, CFG, and Distilled CFG or Shift.</div>';
}

/**
 * Ask the server what each ticked checkpoint of a list would run with, were it
 * pressed now: the whole list at once, so one answer says it all alike - which
 * checkpoint the families are compared with, whether the task is gone, the
 * marks. Each request is numbered, and an older answer, or one for a window
 * since closed, is dropped; a failure is drawn and not kept - the next tick
 * asks again. `body`: what the press would hand over, {names, source}, as
 * JSON: apiCall sends GETs. `open`: whether the window that asked is still
 * the one open. `drawn`: draws the column. The holder keeps `asking`, the
 * request's number, `waiting`, and `runs`, the answer.
 */
export async function askRuns(holder, { body, open, drawn }) {
    const asking = ++holder.asking;
    holder.waiting = body.names.length > 0;
    drawn();
    if (!body.names.length) return;
    let answer;
    try {
        const response = await fetch('/model-manager/queue/several/runs', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        answer = await response.json();
        if (!answer?.success) throw new Error(answer?.error || 'the server did not answer');
    } catch (failure) {
        answer = { failed: String(failure?.message || failure) };
    }
    if (!open() || asking !== holder.asking) return;
    holder.waiting = false;
    holder.runs = answer;
    drawn();
}

/** What one ticked checkpoint's line says, from its entry in the answer (several.runs_preview). */
function runWhat(entry, task) {
    if (entry.problem) return `Queuing stops on it: ${entry.problem}`;
    const values = entry.usual ? usualValuesText(entry.usual) : '';
    let what = {
        yours: 'Runs with your settings: Forge\'s selected checkpoint.',
        as_made: 'Runs as made, with the image\'s settings.',
        held: values ? `${values} · as in task #${task}` : `Runs with your settings, as in task #${task}.`,
        usual: values,
        thin: 'Runs with your settings: too few uses record its own.',
        plain: 'Runs with your settings.',
        error: 'Could not read its usual settings: it runs with your settings.',
    }[entry.how] ?? 'Runs with your settings.';
    if (entry.family_state === 'not_read') what += ' Its family is read when you queue.';
    if (entry.family_state === 'unrecognised') {
        what += ' Its family was not recognised when last read: it is read again when you queue.';
    }
    return what;
}

/**
 * The column: a line per ticked checkpoint, in tick order, the lines under
 * them, and the family note. `nameOf`: a checkpoint as the window names it.
 * `task`: the task the list came from, if any. `subject`: what the families
 * are compared with, as a sentence starts with it; `than`: as the note names
 * it - nothing where the window knows none, and says so.
 */
export function runsHtml(holder, { nameOf, task, subject, than }) {
    const answer = holder.runs;
    if (!holder.ticked.length) return severalEachHtml({ after: ['Tick a checkpoint to see what it runs with.'] });
    const entries = holder.ticked.map((name) => {
        const entry = answer?.runs?.[name];
        let what;
        if (entry) what = runWhat(entry, task);
        else if (answer?.failed && !holder.waiting) {
            what = `Could not read what it runs with: ${answer.failed.replace(/[.\s]+$/, '')}.`;
        }
        else what = 'Reading its usual settings…';
        return { name: nameOf(name), another: entry?.another_family === true, what };
    });
    const after = [];
    if (answer?.gone_task) after.push(`Task #${answer.gone_task} is gone: each takes its usual settings.`);
    const state = answer?.selected?.state;
    if (state === 'not_read') {
        after.push(`${subject} is not read yet: a checkpoint of another family is told when you queue.`);
    } else if (state === 'unrecognised') {
        after.push(`${subject} was not recognised when last read: a checkpoint of another family `
                   + 'is told when you queue.');
    }
    const stay = 'the size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them.';
    const note = !entries.some((e) => e.another) ? ''
        : than ? `Of another family than ${than}: ${stay}`
            : `Forge has no checkpoint selected that it lists, so each is of another family: ${stay}`;
    return severalEachHtml({ entries, note, after });
}
