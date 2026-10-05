// The Queue tab (#156-#158), against a stand-in server.
//
// While the tab shows, its status line says what the queue is doing - the
// task it is on and how far Forge is with it, the counts - and offers what
// can be done now: Start, Pause or Resume, Stop. Nothing is asked while it is
// hidden; opened, both lists are read again. A row says what its task asks
// for, and shows the first images its run made. Start that finds tasks
// whose extensions are gone asks first: Cancel starts nothing, Run anyway
// forces it.
import { ROOT, act, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
// Gradio's button for the tab, selected while the tab shows.
document.body.insertAdjacentHTML('afterbegin', '<button id="tab_queue_tab-button" class="selected">Queue</button>');
const tabButton = document.getElementById('tab_queue_tab-button');
window.mmTiming = { poll: 40 };

const image = (id) => ({ id, generation_id: 1, position: 0, url: `/model-manager/generations/images/${id}/file`,
                         exists: true, mm_level: 1, mm_level_from_prompt: false });
const task = (id, status, extra = {}) => ({
    id, mode: 'txt2img', status, prompt: `task ${id}, a lighthouse`, script: null,
    checkpoint: '_SDXL\\Asgard\\asgard_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'],
    width: 832, height: 1216, hires: null, scale_by: null, sampler: 'Euler a', scheduler: 'Karras', steps: 30,
    batch_size: 1, n_iter: 2, created_at: '2026-10-05T12:50:00', started_at: null, finished_at: null,
    error: null, first_seed: null, retry_of: null, retried_as: null, generations: [], images: [],
    image_count: 0, hidden_nsfw: 0, ...extra,
});
const LISTS = {
    active: [task(15, 'running', { hires: { scale: 2 } }), task(16, 'pending', { retry_of: 4, prompt: 'a <b>bold</b> prompt' })],
    history: [
        task(14, 'completed', { finished_at: '2026-10-05T13:05:00', retried_as: 17, script: 'X/Y/Z plot',
                                images: [image(1), image(2), image(3), image(4)], image_count: 7, hidden_nsfw: 1 }),
        task(13, 'failed', { error: 'RuntimeError: boom', hires: { resize: [2048, 0] } }),
    ],
};
let STATUS = { success: true, running: true, counts: { pending: 2, running: 1, completed: 3, stopped: 0, failed: 1 },
               progress: { state: 'running', task_id: 15, job: 'task(mmq-15-1)', completed: 0, failed: 0,
                           stopped: 0, notes: [], error: null } };
const asked = [];
const posted = [];
let startAnswers = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (init.method === 'POST' && href.includes('/model-manager/queue/')) {
        posted.push(href.replace(/^https?:\/\/[^/]+/, ''));
        if (href.includes('/queue/start')) return reply(startAnswers.shift() || { success: true, started: true, missing: [] });
        return reply({ success: true, acted: true });
    }
    if (href.includes('/internal/progress')) {
        return reply({ active: true, queued: false, progress: 0.45, eta: 12.4, textinfo: null });
    }
    if (href.includes('/model-manager/queue/status')) return reply(STATUS);
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
check("a finished task shows its run's first images, and how many more there are",
      [row(14).querySelectorAll('.mm-generation-tile').length,
       [...row(14).querySelectorAll('.queue-more')].map((m) => m.textContent.trim())],
      [4, ['+2', '1 hidden']]);
check('as the Generations tab draws them, by their record',
      row(14).querySelector('.mm-generation-tile img').getAttribute('data-src'),
      'http://localhost:7860/model-manager/generations/images/1/file');

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
STATUS = { ...STATUS, progress: { ...STATUS.progress, state: 'paused', notes: ['ControlNet: 0: could not be restored; its default ran'] } };
await waitFor('paused', () => text('queue_state') === 'Paused');
check('paused: Resume is offered, Pause is not', [button('pause').hidden, button('resume').hidden], [true, false]);
check('inputs a task ran at their defaults are said', text('queue_message'),
      'Task #16: ControlNet: 0: could not be restored; its default ran');
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
