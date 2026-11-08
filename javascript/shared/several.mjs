/**
 * Several mode (#400): txt2img holding a list of checkpoints, to queue one
 * task that makes the generation with each in turn. Generate is hidden and
 * Generate for N checkpoints stands in its place, Queue for N checkpoints in
 * the Queue button's - both made beside it as the WebUI starts
 * (scheduler/capture.py), hidden by the stylesheet until this shows them. A
 * strip under them names the list, with Change and Leave.
 *
 * The press is the server's: as it is clicked, its page code reads the list
 * from the strip's data-checkpoints (capture._READ_SEVERAL) - the names, and
 * where they came from: the image Send was given, or the task Load to UI
 * loaded - and the server works out each checkpoint's settings from them.
 * Pressed, the mode stays, to change something and queue again.
 *
 * Entered by `several.enter` - Load to UI of a task of several checkpoints,
 * or a Send with several ticked in the Resources dialog - with two names or
 * more, while the button was made at this start; or by Several
 * checkpoints…, under Generate's box while the mode is off, which opens
 * Change's window with Forge's loaded checkpoint ticked. The setting Queue a
 * generation with several checkpoints only starts the dialog's box. The strip's
 * Change opens your checkpoint list in a window of its own, ticked as the
 * mode holds it - the Resources dialog's list, its search and family tabs
 * (resources.mjs) - whose Use these changes the list and sends nothing:
 * nothing on screen changes. Beside the list, what each ticked checkpoint will
 * run with, as the server works it out from the press's own rule (#406,
 * POST /model-manager/queue/several/runs). Ended by Leave,
 * `several.leave` - every plain Send calls it - or the Queue switched off:
 * this service stops with the Queue tab, and its scope
 * takes the mode back. A reload ends it too: nothing is kept.
 *
 * Generate's click is caught on the way down, only while txt2img shows and
 * nothing is generating: a click the person made, or the one Forge's
 * Ctrl+Enter makes for them, becomes Generate for N checkpoints. Every other
 * click passes - Generate forever's. The listener is added before the Queue
 * tab's large-batch one, which it stops: in the mode, the "Generate N
 * images?" question never comes to offer Generate.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { apiCall, setText, setTitle } = await shared('core.mjs');
const { tabShowing } = await shared('tabs.mjs');
const { addPickList, pickListHtml, pickRowName, pickRows, severalEachHtml, usualValuesText, withUnlisted } =
    await shared('resources.mjs');
const { openDialog } = await shared('dialog.mjs');

// What this uses that has a start(): the actions' listener, ui-options, and
// the list's search, tabs and picks, which Change's window draws.
export const STARTS = ['calls.mjs', 'ui_options.mjs', 'resources.mjs'];

// Queue for N checkpoints (capture.SEVERAL_BUTTON), Generate for N checkpoints
// (capture.SEVERAL_GO_BUTTON), and the strip their page code reads.
const BUTTON = 'txt2img_queue_several';
const GO = 'txt2img_generate_several';
const STRIP = 'mm_several_strip';
// Several checkpoints…, under Generate's box while the mode is off.
const ENTRY = 'mm_several_entry';
// On the page's body while the mode holds a list: the stylesheet hides
// Generate and shows the button by it.
const MODE_CLASS = 'mm-several';
// Forge's Ctrl+Enter clicks Generate for the person: a click this soon after
// the keys is theirs, as the Queue tab's large-batch question counts it.
const KEYS_CLICK_MS = 1000;

let list = null;            // { names, source, labels, listParams } while in the mode
// Change's window while open: its element, how to close it, and the list it draws from.
let changing = null;
let keys = null;            // the last Ctrl+Enter: { at, queues }
let running = false;        // started, and not stopped: the entry is drawn only then

const byId = (id) => document.getElementById(id);

/** A checkpoint as the strip says it: its file, without its folder, its extension or Forge's hash. */
export function checkpointLabel(name) {
    return String(name || '').replace(/\s*\[[0-9a-f]+\]$/i, '').split(/[\\/]/).pop()
        .replace(/\.(safetensors|ckpt|gguf|pt|pth|bin|sft)$/i, '');
}

/** Words as a sentence lists them: "a", "a and b", "a, b and c". */
function listed(words) {
    return words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0] || '';
}

/** Whether a generation runs in txt2img: Forge shows Interrupt, or Interrupting…, while it does. */
function generating() {
    return ['txt2img_interrupt', 'txt2img_interrupting'].some((id) => byId(id)?.style.display === 'block');
}

/**
 * Hold these checkpoints: `names` by Forge's name, in order, a name twice
 * once; `source` where they came from, as the press hands it to the server -
 * `{task}` or `{image}`; `labels`, how the strip names each, where known;
 * `listParams`, what Change asks the list of your checkpoints with, so it
 * suggests as the Resources dialog did. Answers true once held; otherwise
 * the mode is left, and it answers false: fewer than two names, or no button
 * made at this start.
 */
async function enter({ names, source = null, labels = null, listParams = null } = {}) {
    const unique = [...new Set((Array.isArray(names) ? names : []).filter((n) => typeof n === 'string' && n))];
    if (unique.length < 2 || !byId(BUTTON)) {
        leave();
        return false;
    }
    const object = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : null);
    list = { names: unique, source: object(source), labels: { ...object(labels) }, listParams: { ...object(listParams) } };
    draw();
    return true;
}

/**
 * Several checkpoints…, under Generate's box while the mode is off and the
 * button was made at this start: Change's window, outside the mode.
 */
function drawEntry(button, shown) {
    let entry = byId(ENTRY);
    if (!shown || !running || !button) {
        entry?.remove();
        return;
    }
    if (!entry) {
        entry = document.createElement('div');
        entry.id = ENTRY;
        entry.className = 'mm-several-strip';
        entry.innerHTML = '<button type="button" class="mm-btn mm-btn-small" data-action="several.change"'
            + ' title="Tick several of your checkpoints, to queue one generation with each in turn.">'
            + 'Several checkpoints…</button>';
    }
    const box = button.closest('#txt2img_generate_box') || button.parentElement;
    if (box && entry.previousElementSibling !== box) box.after(entry);
}

/** Generate back, the strip gone, Change's window closed. */
function leave() {
    list = null;
    changing?.handle.close('code');
    draw();
}

/** A checkpoint as the strip names it: its model and version where known, else its file. */
const labelOf = (name) => list?.labels?.[name] || checkpointLabel(name);

/**
 * The page as the mode says: the body's class, the button's words, and the
 * strip - made, placed under Generate's box, its list and names - or gone.
 * Run again after every update Gradio makes, so it writes only what differs.
 */
function draw() {
    const button = byId(BUTTON);
    const on = Boolean(list && button);
    if (document.body.classList.contains(MODE_CLASS) !== on) document.body.classList.toggle(MODE_CLASS, on);
    let strip = byId(STRIP);
    drawEntry(button, !on);
    if (!on) {
        strip?.remove();
        return;
    }
    setText(button, `Queue for ${list.names.length} checkpoints`);
    setTitle(button, 'Queue one task that makes this generation with each checkpoint in turn. '
                     + 'The queue does not start.');
    const go = byId(GO);
    setText(go, `Generate for ${list.names.length} checkpoints`);
    setTitle(go, 'Queue one task that makes this generation with each checkpoint in turn, and run it next: '
                 + 'after the task the queue is on, if any. The queue does not resume.');
    if (!strip) {
        strip = document.createElement('div');
        strip.id = STRIP;
        strip.className = 'mm-several-strip';
        strip.innerHTML = '<span class="mm-several-names"></span>'
            + '<button type="button" class="mm-btn mm-btn-small" data-action="several.change"'
            + ' title="Tick the checkpoints to queue with, and see what each runs with.">Change</button>'
            + '<button type="button" class="mm-btn mm-btn-small" data-action="several.leave"'
            + ' title="Generate comes back, and the list is let go.">Leave</button>';
    }
    const box = button.closest('#txt2img_generate_box') || button.parentElement;
    if (box && strip.previousElementSibling !== box) box.after(strip);
    const data = JSON.stringify({ names: list.names, source: list.source });
    if (strip.dataset.checkpoints !== data) strip.dataset.checkpoints = data;
    const names = strip.querySelector('.mm-several-names');
    setText(names, `Queues with ${listed(list.names.map(labelOf))}`);
    setTitle(names, list.names.join('\n'));
}

// ------------------------------------------------------- Change's window

/**
 * Change: your checkpoint list in a window of its own, ticked as the mode
 * holds it, asked of the server as the Resources dialog asks it. Cancel, Esc
 * or a click beside it changes nothing; Use these takes the ticks, in the
 * order they were ticked, and sends nothing.
 */
async function openChange() {
    if (changing) return;
    // Outside the mode, Forge's loaded checkpoint ticked once the list says which.
    const outside = !list;
    // `runs`: the server's answer of what each runs with, its request numbered (askRuns).
    const holder = { pickList: { loading: true, search: '', tab: null }, ticked: outside ? [] : [...list.names],
                     source: list?.source ?? null, runs: null, asking: 0, waiting: false, drawn: '' };
    const element = document.createElement('dialog');
    element.className = 'mm-question mm-several-change';
    element.setAttribute('aria-labelledby', 'mm_several_change_title');
    element.innerHTML = `<div class="mm-dialog mm-question-box">
            <h3 id="mm_several_change_title">Checkpoints to queue with</h3>
            <p class="mm-question-message">Tick each checkpoint to make your generation with; they run in the
                order you tick them. Your prompt stays as it is; what each one runs with is shown with the list.</p>
            <div class="mm-pick-area">${pickListHtml(holder, 'several')}<div class="mm-usual" data-several-runs></div></div>
            <div class="mm-dialog-buttons">
                <span class="mm-several-ticked" data-several-ticked></span>
                <button type="button" class="mm-btn secondary" data-several-cancel>Cancel</button>
                <button type="button" class="mm-btn primary" data-several-use>Use these</button>
            </div>
        </div>`;
    const handle = openDialog(element, { onClose: () => {
        element.remove();
        if (changing?.element === element) changing = null;
    } });
    changing = { element, handle, holder };
    // On its own buttons: they go with it.
    element.addEventListener('click', (event) => {
        if (event.target.closest?.('[data-several-cancel]')) handle.close('cancel');
        else if (event.target.closest?.('[data-several-use]')) useTicked();
    });
    drawTicked();
    drawRuns();
    // In the mode the ticks are known: asked beside the list. Outside it, once the list says which is loaded.
    if (!outside) askRuns(holder);
    let data = null;
    let error = '';
    try {
        data = await apiCall({ endpoint: '/model-manager/send/checkpoints', params: list?.listParams || {} });
        if (!data?.success) throw new Error(data?.error || 'the server did not answer');
    } catch (failure) {
        error = `Could not read your checkpoints: ${failure.message || failure}`;
    }
    if (changing?.holder !== holder) return;
    if (outside && data?.loaded && !holder.ticked.length) holder.ticked = [data.loaded];
    holder.pickList = error ? { loading: false, error, search: '', tab: null }
        : { loading: false, error: '', data: withUnlisted(data, holder.ticked), search: '', tab: 'all' };
    element.querySelector('[data-pick-list="several"]')?.replaceWith(listElement(holder));
    drawTicked();
    if (outside) askRuns(holder);
    else drawRuns();
}

/** The list drawn afresh, as an element. */
function listElement(holder) {
    const wrap = document.createElement('div');
    wrap.innerHTML = pickListHtml(holder, 'several');
    return wrap.firstElementChild;
}

/** How many are ticked, and Use these, which needs two. */
function drawTicked() {
    if (!changing) return;
    const count = changing.holder.ticked.length;
    setText(changing.element.querySelector('[data-several-ticked]'), `${count} ticked`);
    const use = changing.element.querySelector('[data-several-use]');
    if (!use) return;
    use.disabled = count < 2;
    if (count < 2) {
        use.title = list ? 'Tick two checkpoints or more. To generate with one, press Leave and use Generate.'
            : 'Tick two checkpoints or more. To generate with one, use Generate.';
    }
    else use.removeAttribute('title');
}

/** A tick in Change's window: the window's list alone, its rows left as they are - their scroll stays. */
function tickInChange(name, input) {
    const holder = changing?.holder;
    if (!holder) return;
    const ticked = holder.ticked.filter((n) => n !== name);
    if (input?.checked) ticked.push(name);
    holder.ticked = ticked;
    input?.closest('.mm-pick-row')?.classList.toggle('picked', Boolean(input?.checked));
    drawTicked();
    askRuns(holder);
}

// ------------------------------------------- what each ticked one runs with (#406)

/**
 * Ask the server what each ticked checkpoint would run with, were it pressed
 * now: the whole list at once, so one answer says it all alike - which
 * checkpoint Forge has selected, whether the task is gone, the marks. Each
 * request is numbered, and an older answer, or one for a window since
 * closed, is dropped; a failure is drawn and not kept - the next tick asks
 * again. The press's own {names, source}, as a JSON body: apiCall sends GETs.
 */
async function askRuns(holder) {
    const asking = ++holder.asking;
    const names = [...holder.ticked];
    holder.waiting = names.length > 0;
    drawRuns();
    if (!names.length) return;
    let answer;
    try {
        const response = await fetch('/model-manager/queue/several/runs', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ names, source: holder.source }) });
        answer = await response.json();
        if (!answer?.success) throw new Error(answer?.error || 'the server did not answer');
    } catch (failure) {
        answer = { failed: String(failure?.message || failure) };
    }
    if (changing?.holder !== holder || asking !== holder.asking) return;
    holder.waiting = false;
    holder.runs = answer;
    drawRuns();
}

/** The column again, in place, only where it differs: the rows, their scroll and the search box are not touched. */
function drawRuns() {
    if (!changing) return;
    const block = changing.element.querySelector('[data-several-runs]');
    const html = runsHtml(changing.holder);
    if (block && html !== changing.holder.drawn) {
        block.innerHTML = html;
        changing.holder.drawn = html;
    }
}

/** A checkpoint as the column names it: as its row in the list does, else by its file. */
function runName(holder, name) {
    const row = pickRows(holder).find((r) => r.name === name);
    return row && !row.unlisted ? pickRowName(row) : list?.labels?.[name] || checkpointLabel(name);
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

/** The column: a line per ticked checkpoint, in tick order, the lines under them, and the family note. */
function runsHtml(holder) {
    const answer = holder.runs;
    if (!holder.ticked.length) return severalEachHtml({ after: ['Tick a checkpoint to see what it runs with.'] });
    const task = holder.source?.task;
    const entries = holder.ticked.map((name) => {
        const entry = answer?.runs?.[name];
        let what;
        if (entry) what = runWhat(entry, task);
        else if (answer?.failed && !holder.waiting) {
            what = `Could not read what it runs with: ${answer.failed.replace(/[.\s]+$/, '')}.`;
        }
        else what = 'Reading its usual settings…';
        return { name: runName(holder, name), another: entry?.another_family === true, what };
    });
    const after = [];
    if (answer?.gone_task) after.push(`Task #${answer.gone_task} is gone: each takes its usual settings.`);
    const selected = answer?.selected;
    if (selected?.state === 'not_read') {
        after.push('Forge\'s selected checkpoint is not read yet: a checkpoint of another family is told when you queue.');
    } else if (selected?.state === 'unrecognised') {
        after.push('Forge\'s selected checkpoint was not recognised when last read: a checkpoint of another family '
                   + 'is told when you queue.');
    }
    const stay = 'the size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them.';
    // Forge's option names the selected one as Forge spells it; the list's `loaded` is the same file by its row.
    const listed = pickRows(holder).some((r) => r.name === selected?.name);
    const selectedName = listed ? selected?.name : holder.pickList?.data?.loaded || selected?.name;
    const note = !entries.some((e) => e.another) ? ''
        : selected?.name ? `Of another family than Forge's selected checkpoint, ${runName(holder, selectedName)}: ${stay}`
            : `Forge has no checkpoint selected that it lists, so each is of another family: ${stay}`;
    return severalEachHtml({ entries, note, after });
}

/** Use these: the mode holds the ticks, named as the list names them - entered, outside it; nothing is sent. */
function useTicked() {
    if (!changing || changing.holder.ticked.length < 2) return;
    const rows = new Map(pickRows(changing.holder).map((row) => [row.name, row]));
    const labels = { ...list?.labels };
    for (const name of changing.holder.ticked) {
        if (rows.has(name) && !rows.get(name).unlisted) labels[name] = pickRowName(rows.get(name));
    }
    // Outside the mode, it is entered: no image or task behind the list, so
    // the loaded checkpoint runs with your settings (scheduler/several.py).
    list = list ? { ...list, names: [...changing.holder.ticked], labels }
        : { names: [...changing.holder.ticked], source: null, labels, listParams: {} };
    changing.handle.close('use');
    draw();
}

/**
 * Generate's click, on its way down: in the mode, the person's becomes Queue
 * for N checkpoints. The one Ctrl+Enter makes while Change's window is open
 * does nothing: the list is being changed, and Generate is not the mode's.
 */
function onGenerate(event) {
    if (!list || !event.target?.closest?.('#txt2img_generate')) return;
    if (!event.isTrusted && keys?.held && Date.now() - keys.at <= KEYS_CLICK_MS) {
        keys = null;
        event.stopImmediatePropagation();
        event.preventDefault();
        return;
    }
    const queues = event.isTrusted ? tabShowing('txt2img') && !generating()
        : Boolean(keys?.queues) && Date.now() - keys.at <= KEYS_CLICK_MS;
    if (!queues) return;
    keys = null;
    event.stopImmediatePropagation();
    event.preventDefault();
    (byId(GO) || byId(BUTTON))?.click();
}

/**
 * Ctrl+Enter, before Forge's own listener hears it: whether the click it
 * makes is to queue - while txt2img shows and nothing generates. While a
 * generation runs, Forge interrupts it and generates after, as ever.
 */
function onKeys(event) {
    if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey)) return;
    if (list && changing) {
        keys = { at: Date.now(), queues: false, held: true };
        return;
    }
    keys = { at: Date.now(), queues: Boolean(list) && tabShowing('txt2img') && !generating() };
}

/** What a suite reads: the list held, or null. */
export function severalList() {
    return list ? { names: [...list.names], source: list.source } : null;
}

export function start(scope) {
    running = true;
    scope.provide('several.enter', (args) => enter(args));
    scope.provide('several.leave', () => leave());
    scope.provide('several.change', () => openChange());
    scope.onStop(addPickList('several', { holder: () => changing?.holder || null, picked: tickInChange }));
    // Caught on the way down, before Forge's own listeners and the Queue tab's.
    scope.listen(document, 'keydown', onKeys, true);
    scope.listen(document, 'click', onGenerate, true);
    scope.afterUpdate(draw);
    // The Queue switched off: Generate back at once, Change's window closed.
    scope.onStop(() => {
        running = false;
        list = null;
        changing?.handle.close('code');
        draw();
    });
}
