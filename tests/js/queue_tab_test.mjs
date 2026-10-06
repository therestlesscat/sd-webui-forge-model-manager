// The Queue tab (#156-#158), against a stand-in server.
//
// While the tab shows, its status line says what the queue is doing - the
// task it is on and how far Forge is with it, the counts - and offers what
// can be done now: Start, Pause or Resume, Stop. Nothing is asked while it is
// hidden; opened, both lists are read again. A row says what its task asks
// for, and how many images its run made - never the images: Show images
// opens the Generations tab on them. The running task's row has a bar, as
// far along as Forge says, kept when Forge is done with the run and the queue
// not yet, empty while the run waits for Forge. A click on a row opens its details,
// everything it holds, escaped; Load to UI asks the Queue tab's hidden
// button for the task, after its send plan, and says what kept its value.
// Start that finds tasks whose extensions are gone asks first: Cancel starts
// nothing, Run anyway forces it. Retry asks which seed, Delete whether the
// images go too, once for every task ticked; Select ticks a shift-click's
// range, never a running task; Clear history asks first, saying how many.
import { ROOT, act, checker, mountTab, sharedModule, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
// Gradio's button for the tab, selected while the tab shows.
document.body.insertAdjacentHTML('afterbegin', '<button id="tab_queue_tab-button" class="selected">Queue</button>');
const tabButton = document.getElementById('tab_queue_tab-button');
window.mmTiming = { poll: 40, loadTask: 1000 };

const task = (id, status, extra = {}) => ({
    id, mode: 'txt2img', status, prompt: `task ${id}, a lighthouse`, script: null,
    checkpoint: '_SDXL\\Asgard\\asgard_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'],
    width: 832, height: 1216, hires: null, scale_by: null, sampler: 'Euler a', scheduler: 'Karras', steps: 30,
    batch_size: 1, n_iter: 2, created_at: '2026-10-05T12:50:00', started_at: null, finished_at: null,
    error: null, first_seed: null, retry_of: null, retried_as: null, generations: [],
    image_count: 0, ...extra,
});
const LISTS = {
    active: [task(15, 'running', { hires: { scale: 2 } }), task(16, 'pending', { retry_of: 4, prompt: 'a <b>bold</b> prompt' })],
    history: [
        task(14, 'completed', { finished_at: '2026-10-05T13:05:00', retried_as: 17, script: 'X/Y/Z plot',
                                image_count: 7 }),
        task(13, 'failed', { error: 'RuntimeError: boom', hires: { resize: [2048, 0] } }),
    ],
};
const INPUTS = {
    fixed: [{ name: 'prompt', value: 'task 14, a lighthouse' }, { name: 'negative_prompt', value: 'a <i>blur</i>' },
            { name: 'width', value: 832 }, { name: 'init_img', value: { __kind__: 'image', name: 'init.png' } }],
    script: 'X/Y/Z plot',
    scripts: [
        { title: 'Seed', controls: [{ id: 'txt2img_seed', label: 'Seed', value: -1 }] },
        { title: 'X/Y/Z plot', controls: [{ id: 'x', label: 'X type', value: 'Seed' }] },
        { title: 'ControlNet', controls: [{ id: null, label: null, value: { __kind__: 'object', name: 'Unit',
                                                                            fields: { enabled: true, weight: 0.5 } } },
                                          { id: null, label: null, value: { __kind__: 'missing', name: 'Thing' } }] },
    ],
    loose: [],
};
const PLAN = { success: true, mode: 'txt2img', preset: null, checkpoint: null, checkpoint_missing: null,
               target: [], modules_missing: [] };
let STATUS = { success: true, running: true, counts: { pending: 2, running: 1, completed: 3, stopped: 0, failed: 1 },
               progress: { state: 'running', task_id: 15, job: 'task(mmq-15-1)', completed: 0, failed: 0,
                           stopped: 0, notes: [], error: null } };
// What Forge says of the running task's job.
let FORGE = { active: true, queued: false, progress: 0.45, eta: 12.4, textinfo: null };
const asked = [];
const posted = [];
const bodies = [];
let startAnswers = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (init.method === 'POST' && href.includes('/model-manager/queue/')) {
        posted.push(href.replace(/^https?:\/\/[^/]+/, ''));
        const body = Object.fromEntries(new URLSearchParams(String(init.body || '')));
        bodies.push(body);
        const ids = (body.ids || '').split(',').filter(Boolean).map(Number);
        if (href.includes('/queue/start')) return reply(startAnswers.shift() || { success: true, started: true, missing: [] });
        if (href.includes('/queue/retry')) return reply({ success: true, queued: ids.map((_, i) => 30 + i), skipped: [] });
        if (href.includes('/queue/delete')) {
            return reply({ success: true, deleted: ids, skipped: [], deleted_files: body.with_data === 'true' ? 7 : 0,
                           deleted_inputs: 1, failed: [] });
        }
        if (href.includes('/history/clear')) return reply({ success: true, hidden: 21 });
        return reply({ success: true, acted: true });
    }
    if (href.includes('/internal/progress')) return reply(FORGE);
    if (href.includes('/model-manager/queue/status')) return reply(STATUS);
    const detail = new URL(href, 'http://webui').pathname.match(/\/model-manager\/queue\/tasks\/(\d+)(\/send-plan)?$/);
    if (detail?.[2]) return reply(PLAN);
    if (detail) return reply({ success: true, task: LISTS.history.find((t) => t.id === Number(detail[1])), inputs: INPUTS });
    if (href.includes('/model-manager/queue/tasks')) {
        const params = new URL(href).searchParams;
        const which = params.get('which');
        const page = Number(params.get('page'));
        const all = LISTS[which];
        const pages = which === 'history' ? 2 : 1;
        return reply({ success: true, which, page, pages, page_size: 20, total: which === 'history' ? 21 : all.length,
                       tasks: page === 1 ? all : [task(1, 'completed', { finished_at: '2026-10-05T10:00:00' })] });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [] });
};

await import(`file:///${ROOT}/javascript/queue.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const text = (id) => document.getElementById(id)?.textContent.trim();
const rows = (list) => [...document.querySelectorAll(`#queue_${list} .queue-task`)];
const row = (id) => document.querySelector(`.queue-task[data-task="${id}"]`);
const facts = (id) => [...row(id).querySelectorAll('.queue-fact')].map((f) => f.textContent.trim());

// ------------------------------------------------------------ status line
await waitFor('the status line', () => text('queue_task')?.includes('45%'));
check('the status line says what the queue is doing',
      [text('queue_state'), text('queue_task'), text('queue_counts')],
      ['Running', 'Task #15 · 45% · 12 s left', '2 pending · 3 completed · 1 failed']);
const button = (name) => document.getElementById(`queue_${name}`);
check('running: Pause and Stop are offered, Start and Resume are not',
      [button('start').disabled, button('pause').hidden, button('resume').hidden, button('stop').disabled],
      [true, false, true, false]);

// ------------------------------------------------------------------ lists
await waitFor('both lists', () => rows('active').length && rows('history').length);
// Without them every check below would crash, and hide the failures above.
if (!row(15) || !row(14)) done();
check('Active is drawn in the order the server gives it, History too',
      [rows('active').map((r) => r.dataset.task), rows('history').map((r) => r.dataset.task)],
      [['15', '16'], ['14', '13']]);
check('each list says its size', [text('queue_active_count'), text('queue_history_count')], ['(2)', '(21)']);
check("a row says what its task asks for", facts(15).slice(0, 6),
      ['asgard_v12', 'sdxl_vae', '832×1216 → hires ×2', 'Euler a · Karras', '30 steps', 'batch 1 × 2']);
check('and when it was queued', [facts(15).length, facts(15)[6].startsWith('queued ')], [7, true]);
check('hires fix by its resize, an ended one when it ended, a failed one its error',
      [facts(13)[2], facts(14).some((f) => f.startsWith('ended ')), row(13).querySelector('.queue-error')?.textContent],
      ['832×1216 → hires 2048×auto', true, 'RuntimeError: boom']);
check('a status, a copy, a retried task and its script are labelled',
      [row(15).querySelector('.queue-status').textContent, row(16).querySelector('.queue-copy')?.textContent,
       row(14).querySelector('.queue-requeued')?.textContent, row(14).querySelector('.queue-script')?.textContent],
      ['Running', 'a copy of #4', 'Requeued as #17', 'X/Y/Z plot']);
check('a prompt is text, never markup', [row(16).querySelector('.queue-prompt').textContent,
                                         row(16).querySelector('.queue-prompt b')], ['a <b>bold</b> prompt', null]);
check('a task that made images offers to show them, and shows none',
      [row(14).querySelector('[data-action="queue.showImages"]')?.textContent, row(14).querySelectorAll('img').length],
      ['Show images (7)', 0]);
check('one that made none does not', row(13).querySelector('[data-action="queue.showImages"]'), null);

// ---------------------------------------------------- the running task's bar
const progressBar = (id) => row(id)?.querySelector('.queue-progress');
const along = (id) => [progressBar(id)?.getAttribute('aria-valuenow'), progressBar(id)?.firstElementChild.style.width];
await waitFor('the bar', () => along(15)[0] === '45');
check('the running task has a bar along its row, as far along as Forge says', along(15), ['45', '45%']);
check('no other task has one', [progressBar(16), progressBar(14), progressBar(13)], [null, null, null]);
FORGE = { ...FORGE, progress: 0.8 };
await waitFor('the bar to follow', () => along(15)[0] === '80');
check('it follows Forge', along(15), ['80', '80%']);
// Drawn again with its list alone - Select redraws Active - while no status
// read can draw the bar after it: the tab hidden, nothing is asked.
tabButton.classList.remove('selected');
await new Promise((resolve) => setTimeout(resolve, 150));
const drawn = row(15);
await tick('queue.selecting', true, { list: 'active' });
check('drawn again with its list, it keeps how far along it is', [row(15) !== drawn, ...along(15)], [true, '80', '80%']);
await tick('queue.selecting', false, { list: 'active' });
tabButton.classList.add('selected');
FORGE = { active: false, queued: false, completed: true, textinfo: 'Waiting...' };
await new Promise((resolve) => setTimeout(resolve, 150));
check('Forge done with the run, the queue not yet: it stays', along(15), ['80', '80%']);
FORGE = { active: false, queued: true, completed: false, textinfo: 'In queue: 2/2' };
await waitFor('the bar to empty', () => along(15)[0] === '0');
check("waiting for Forge's lock: empty", along(15), ['0', '0%']);
FORGE = { active: true, queued: false, progress: 0.45, eta: 12.4, textinfo: null };

// ------------------------------------------------------ following the queue
asked.length = 0;
await new Promise((resolve) => setTimeout(resolve, 200));
check('while nothing changes, the lists are not read again',
      asked.filter((a) => a.includes('/queue/tasks')), []);
// Task 15 ends; 16 starts.
LISTS.active = [task(16, 'running')];
LISTS.history = [task(15, 'completed', { finished_at: '2026-10-05T13:10:00' }), ...LISTS.history];
STATUS = { ...STATUS, counts: { ...STATUS.counts, pending: 0, completed: 4 },
           progress: { ...STATUS.progress, task_id: 16, job: 'task(mmq-16-1)' } };
await waitFor('task 15 in History', () => rows('history')[0]?.dataset.task === '15');
check('a task that ends moves to History by itself, the next runs',
      [rows('active').map((r) => r.dataset.task), rows('history').map((r) => r.dataset.task)],
      [['16'], ['15', '14', '13']]);
await waitFor("the next task's bar", () => along(16)[0] === '45');
check('the bar goes with it, to the next task', [progressBar(15), ...along(16)], [null, '45', '45%']);

// ------------------------------------------------------- Show images
const shownTasks = [];
(await sharedModule('calls.mjs')).provide('generations.showTask', (taskId) => shownTasks.push(taskId));
if (row(14).querySelector('[data-action="queue.showImages"]')) await act('queue.showImages', { task: 14 });
check('Show images opens the Generations tab on the task', shownTasks, [14]);

// --------------------------------------------------------------- details
act('queue.details', { task: 14 });
await waitFor('the details', () => document.querySelector('#mm_meta_modal .queue-details'));
const details = document.querySelector('#mm_meta_modal');
const cell = (key) => [...details.querySelectorAll('tr')].find((tr) => tr.querySelector('th')?.textContent === key)
    ?.querySelector('td')?.textContent;
check('a row opens its details: everything the task holds',
      [details.querySelector('h3')?.textContent, cell('Prompt'), cell('Negative prompt'), cell('width'), cell('init_img')],
      ['Task #14 · txt2img · Completed', 'task 14, a lighthouse', 'a <i>blur</i>', '832', 'image: init.png']);
check('as text, never markup', details.querySelector('td i'), null);
const sections = [...details.querySelectorAll('.queue-section')];
check('a section per script, the selected one open',
      sections.map((d) => [d.querySelector('summary').textContent.trim(), d.hasAttribute('open')]),
      [["Generate's settings", true], ['Seed', false], ['X/Y/Z plot the script selected', true], ['ControlNet', false]]);
check('a control by its label, or its place; an object by its fields; a value not kept as such',
      [cell('X type'), cell('#0'), cell('#1')], ['Seed', 'Unit (enabled: true, weight: 0.5)', 'not kept (Thing)']);
check('with Show images, Retry, Delete and Load to UI',
      [...details.querySelectorAll('.mm-modal-footer button')].map((b) => b.textContent.trim()),
      ['Show images (7)', 'Retry...', 'Delete...', 'Load to UI']);

// ------------------------------------------------------------ Load to UI
// The Queue tab's hidden button for txt2img: it answers the nonce it is asked with.
document.body.insertAdjacentHTML('beforeend', `
    <div id="queue_load_txt2img_task"><textarea></textarea></div>
    <div id="queue_load_txt2img_answer"><textarea></textarea></div>
    <button id="queue_load_txt2img"></button>`);
const loads = [];
document.getElementById('queue_load_txt2img').addEventListener('click', () => {
    const request = JSON.parse(document.querySelector('#queue_load_txt2img_task textarea').value);
    loads.push(request.task);
    setTimeout(() => {
        document.querySelector('#queue_load_txt2img_answer textarea').value = JSON.stringify(
            { nonce: request.nonce, task: request.task, skipped: ['ControlNet: 0'], notes: [] });
    }, 30);
});
asked.length = 0;
await act('queue.load', { task: 14 });
check('Load to UI asks for the send plan, then the hidden button for the task',
      [asked.some((a) => a.endsWith('/model-manager/queue/tasks/14/send-plan')), loads], [true, [14]]);
check('the details close', document.getElementById('mm_meta_modal'), null);
check('what kept its value is said', document.querySelector('.mm-notice')?.textContent,
      'Task #14 is loaded. These keep what was on screen, or their defaults: ControlNet: 0.');
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ------------------------------------------- Retry, Delete, Clear history
/** Answer the open question with `label`, after `setup`; what it asked, and its seed choice as it opened. */
async function answer(label, setup = () => {}) {
    await waitFor(`the question for ${label}`, () => document.querySelector('.queue-dialog'));
    const dialog = document.querySelector('.queue-dialog');
    if (!dialog) return {};
    const asked = { text: dialog.textContent.replace(/\s+/g, ' ').trim(),
                    seed: [...dialog.querySelectorAll('input[name="seed"]')].find((r) => r.checked)?.value };
    setup(dialog);
    [...dialog.querySelectorAll('button')].find((b) => b.textContent === label)?.click();
    return asked;
}
const actions = (id) => [...row(id).querySelectorAll('.queue-actions button')].map((b) => b.textContent.trim());
check('an ended task offers Retry and Delete; a running one neither',
      [actions(14), actions(13), actions(16)], [['Show images (7)', 'Retry...', 'Delete...'], ['Retry...', 'Delete...'], []]);

posted.length = 0;
bodies.length = 0;
let doing = act('queue.retry', { task: 14 });
let question = await answer('Retry', (d) => { d.querySelector('input[value="random"]').checked = true; });
await doing;
check("Retry asks which seed, the first run's ticked", [question.text.startsWith('Retry task #14?'), question.seed],
      [true, 'first']);
check('and queues a copy with the one chosen', [posted, bodies[0]],
      [['/model-manager/queue/retry'], { ids: '14', seed: 'random' }]);
await waitFor('the report', () => text('queue_report'));
check('saying how it went', text('queue_report'), 'Queued 1 copy.');

bodies.length = 0;
doing = act('queue.delete', { task: 14 });
question = await answer('Delete', (d) => { d.querySelector('input[name="with_data"]').checked = true; });
await doing;
check('Delete asks whether the images its run made go too',
      [question.text.includes('Also delete the 7 images its run made, files included'), bodies[0]],
      [true, { ids: '14', with_data: 'true' }]);
check('and says how it went', text('queue_report'), 'Deleted 1 task, and 7 image files.');

bodies.length = 0;
doing = act('queue.delete', { task: 13 });
question = await answer('Cancel');
await doing;
check('a task that made no images is not asked about them; Cancel deletes nothing',
      [question.text.includes('Also delete'), bodies], [false, []]);

// Select, in History: a shift-click's range, a row's click, one question for all.
await tick('queue.selecting', true, { list: 'history' });
await waitFor('the ticks', () => document.querySelectorAll('#queue_history [data-queue-pick]').length === 3);
const pickBox = (id) => document.querySelector(`[data-queue-pick="${id}"]`);
const click = (element, shift = false) => {
    const event = new window.Event('click', { bubbles: true });
    Object.defineProperty(event, 'shiftKey', { value: shift });
    element.dispatchEvent(event);
};
pickBox(15).checked = true;
click(pickBox(15));
pickBox(13).checked = true;
click(pickBox(13), true);
const bar = () => document.getElementById('queue_history_select_bar').textContent.replace(/\s+/g, ' ').trim();
check('a shift-click ticks the range', [[15, 14, 13].map((id) => pickBox(id).checked), bar().startsWith('3 tasks selected')],
      [[true, true, true], true]);
asked.length = 0;
await new Promise((resolve) => setTimeout(resolve, 150));
check("a tick does not open the task's details",
      [document.getElementById('mm_meta_modal'), asked.filter((a) => /queue\/tasks\/\d+$/.test(a))], [null, []]);
click(row(14).querySelector('.queue-prompt'));
await new Promise((resolve) => setTimeout(resolve, 150));
// (In a browser Select takes the click on the way down, before the row's action; this DOM has no
// way down, and the action runs too - opening nothing while selecting, as checked here.)
check("selecting, a row's click ticks it rather than opening it",
      [pickBox(14).checked, document.getElementById('mm_meta_modal')], [false, null]);
bodies.length = 0;
const retryTicked = document.querySelector('#queue_history_select_bar [data-action="queue.historyRetrySelected"]');
check("History's bar offers Retry for the ticked", Boolean(retryTicked), true);
if (retryTicked) {
    doing = act('queue.historyRetrySelected');
    question = await answer('Retry');
    await doing;
}
check('Retry asks once for every task ticked', [question.text?.startsWith('Retry 2 tasks?'), bodies[0]],
      [true, { ids: '15,13', seed: 'first' }]);
check('and the ticks go', [...document.querySelectorAll('#queue_history [data-queue-pick]')].some((b) => b.checked), false);
await act('queue.historySelectAll');
check('Select all ticks the page', bar().startsWith('3 tasks selected'), true);
await act('queue.historySelectClear');
check('Clear unticks it', bar().startsWith('0 tasks selected'), true);
// A ticked task the list loses - deleted, hidden elsewhere - is no longer ticked.
await act('queue.historySelectAll');
LISTS.history = LISTS.history.filter((t) => t.id !== 13);
STATUS = { ...STATUS, counts: { ...STATUS.counts, failed: 0 } };
await waitFor('task 13 gone', () => !row(13));
check('a ticked task that leaves the list is no longer ticked', bar().startsWith('2 tasks selected'), true);
await act('queue.historySelectClear');
await tick('queue.selecting', false, { list: 'history' });
await waitFor('no ticks', () => !document.querySelector('#queue_history [data-queue-pick]'));
await tick('queue.selecting', true, { list: 'active' });
await waitFor('Active redrawn', () => rows('active').length);
check('a running task cannot be ticked', document.querySelector('#queue_active [data-queue-pick]'), null);
await tick('queue.selecting', false, { list: 'active' });

bodies.length = 0;
posted.length = 0;
doing = act('queue.clearHistory');
question = await answer('Clear history');
await doing;
check('Clear history asks first, saying how many, that nothing is deleted',
      [question.text.startsWith('Clear 21 tasks from History?'), question.text.includes('hidden, not deleted'), posted],
      [true, true, ['/model-manager/queue/history/clear']]);
check('and says how it went', text('queue_report'), 'Hid 21 tasks from History.');

// ----------------------------------------------------------------- paging
check('History has its page strip', !!document.querySelector('#queue_history .mm-pagination'), true);
await act('queue.historyPage', { page: 2 });
await waitFor('History page 2', () => rows('history').map((r) => r.dataset.task).join() === '1');
check('a page of History is asked for by number', asked.some((a) => a.includes('which=history&page=2')), true);
check('Active stays on its page', rows('active').map((r) => r.dataset.task), ['16']);

// --------------------------------------------------------------- controls
startAnswers = [{ success: true, started: false,
                  missing: [{ task: 16, prompt: 'a <b>bold</b> prompt', missing: ['Some Extension'] }] }];
posted.length = 0;
act('queue.start');
await waitFor('the question', () => document.querySelector('.queue-dialog'));
const dialog = document.querySelector('.queue-dialog');
if (!dialog) done();
check('Start asks before running tasks whose extensions are gone',
      [dialog.querySelector('.queue-missing li b')?.textContent, dialog.querySelector('.queue-missing-names')?.textContent],
      ['#16', 'Some Extension']);
check('their prompt as text', dialog.querySelector('.queue-missing b + b'), null);
[...dialog.querySelectorAll('button')].find((b) => b.textContent === 'Cancel').click();
await new Promise((resolve) => setTimeout(resolve, 100));
check('Cancel starts nothing', posted, ['/model-manager/queue/start']);

startAnswers = [{ success: true, started: false, missing: [{ task: 16, prompt: 'x', missing: ['Some Extension'] }] },
                { success: true, started: true, missing: [] }];
posted.length = 0;
act('queue.start');
await waitFor('the question again', () => document.querySelector('.queue-dialog'));
[...document.querySelectorAll('.queue-dialog button')].find((b) => b.textContent === 'Run anyway').click();
await waitFor('the forced start', () => posted.length === 2);
check('Run anyway forces it', posted, ['/model-manager/queue/start', '/model-manager/queue/start?force=true']);

posted.length = 0;
await act('queue.pause');
await act('queue.resume');
await act('queue.stop');
check('Pause, Resume and Stop ask the queue', posted,
      ['/model-manager/queue/pause', '/model-manager/queue/resume', '/model-manager/queue/stop']);

// ------------------------------------------------------- what it is doing
STATUS = { ...STATUS, progress: { ...STATUS.progress, state: 'paused', notes: ['ControlNet: 0: could not be restored; its default was used'] } };
await waitFor('paused', () => text('queue_state') === 'Paused');
check('paused: Resume is offered, Pause is not', [button('pause').hidden, button('resume').hidden], [true, false]);
check('inputs a task ran at their defaults are said', text('queue_message'),
      'Task #16: ControlNet: 0: could not be restored; its default was used');
STATUS = { success: true, running: false, counts: { pending: 0, running: 0, completed: 4, stopped: 0, failed: 1 },
           progress: { state: 'stopped', task_id: null, job: null, notes: [], error: null } };
await waitFor('stopped', () => text('queue_state') === 'Stopped');
check('stopped with nothing pending: nothing to start or stop',
      [button('start').disabled, button('pause').hidden, button('resume').hidden, button('stop').disabled, text('queue_task')],
      [true, true, true, true, '']);

// A poll that finds nothing changed writes nothing.
const changes = [];
const observer = new window.MutationObserver((records) => changes.push(...records));
observer.observe(document.querySelector('.queue-bar'), { childList: true, subtree: true, attributes: true, characterData: true });
await new Promise((resolve) => setTimeout(resolve, 200));
observer.disconnect();
check('a poll that finds nothing changed writes nothing', changes.length, 0);

// ------------------------------------------------------------- the tab hidden
tabButton.classList.remove('selected');
await new Promise((resolve) => setTimeout(resolve, 100));
asked.length = 0;
await new Promise((resolve) => setTimeout(resolve, 200));
check('nothing is asked while the tab is hidden', asked, []);
LISTS.active = [];
tabButton.classList.add('selected');
await waitFor('the lists read again', () => asked.some((a) => a.includes('which=active')));
await waitFor('Active redrawn', () => !rows('active').length);
check('opened, the lists are read again', text('queue_active'),
      'No task is waiting. Press Queue beside Generate, in txt2img or img2img, to add one.');

done();
