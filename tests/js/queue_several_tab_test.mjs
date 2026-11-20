// The Queue tab's view of a task of several checkpoints (#400), against a
// stand-in server.
//
// Its row says "3 checkpoints" where a task of one names its checkpoint and
// VAE, each checkpoint, what its run ran with and how it ended on hover, and
// states no sampler, schedule type, steps or CFG of its own: each run had its
// own (#403). Once it has ended, how its runs ended (#432). While it runs, the row
// and the status line say which run it is on - "run 2 of 3" - and a task of
// one says no run. Its bar and the status line's % are the whole task's,
// each run an equal share, never falling back between runs (#337). Its
// details list each checkpoint with how its run ended.
// Its Show images asks the Generations tab for the task grouped by Model; a
// task of one's asks for it ungrouped, as ever.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('afterbegin', '<button id="tab_queue_tab-button" class="selected">Queue</button>');
window.mmTiming = { poll: 40, loadTask: 1000 };

// What each run ran with, as the server works it out (#403): anime_v12's
// usual steps alone, the press's sampler, schedule type and CFG with them;
// photo_v5 its own of each - said while it is to run, not once an ended task
// never reached it; flux_dev none, as a server from before 0.82.0 sends.
const CHECKPOINTS = [
    { checkpoint: 'anime_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'], status: 'completed', error: null,
      ran_with: { sampler: 'Euler a', schedule_type: 'Karras', steps: 24, cfg: 7 } },
    { checkpoint: 'flux_dev.safetensors', modules: [], status: 'failed', error: 'The checkpoint is not in this WebUI' },
    { checkpoint: 'photo_v5.safetensors', modules: [], status: null, error: null,
      ran_with: { sampler: 'DPM++ 2M', schedule_type: 'Automatic', steps: 20, cfg: 4.5 } },
];
const task = (id, status, extra = {}) => ({
    id, mode: 'txt2img', status, prompt: `task ${id}`, script: null,
    checkpoint: 'anime_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'],
    checkpoints: [{ checkpoint: 'anime_v12.safetensors', modules: [], status: null, error: null }],
    width: 832, height: 1216, hires: null, scale_by: null, sampler: 'Euler a', scheduler: 'Karras', steps: 30,
    cfg: 7, batch_size: 1, n_iter: 1, created_at: '2026-11-05T12:50:00', started_at: null, finished_at: null,
    error: null, first_seed: null, retry_of: null, retried_as: null, generations: [], image_count: 0, ...extra,
});
const LISTS = {
    active: [task(21, 'running', { checkpoints: CHECKPOINTS.map((c, i) => ({ ...c, status: i ? null : c.status, error: null })) })],
    history: [task(20, 'failed', { checkpoints: CHECKPOINTS, image_count: 2, error: '1 of 3 failed' }),
              task(19, 'completed', { image_count: 1 }),
              task(23, 'stopped', { checkpoints: [CHECKPOINTS[0], { ...CHECKPOINTS[1], status: 'stopped', error: null },
                                                  CHECKPOINTS[2]] })],
};
// A running task of one beside it, as a row: no run label, ever.
LISTS.active.push(task(22, 'running'));
let STATUS = { success: true, running: true, counts: { pending: 0, running: 1, completed: 1, failed: 1 },
                 progress: { state: 'running', task_id: 21, job: 'task(mmq-21-11)', run: 2, runs: 3, completed: 0,
                             failed: 0, stopped: 0, notes: [], error: null } };
// What Forge says of the running run's job: at first, that it does not know it yet.
let FORGE = { active: false, queued: false, completed: false, textinfo: 'Waiting...' };
// Each time the page asks Forge.
const reads = [];
const INPUTS = { fixed: [{ name: 'prompt', value: 'task 20' }], script: null, scripts: [], loose: [] };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/internal/progress')) {
        reads.push(href);
        return reply(FORGE);
    }
    if (href.includes('/model-manager/queue/status')) return reply(STATUS);
    const detail = new URL(href, 'http://webui').pathname.match(/\/model-manager\/queue\/tasks\/(\d+)$/);
    if (detail) {
        const found = [...LISTS.active, ...LISTS.history].find((t) => t.id === Number(detail[1]));
        return reply({ success: true, task: found, inputs: INPUTS });
    }
    if (href.includes('/model-manager/queue/tasks')) {
        const which = new URL(href).searchParams.get('which');
        return reply({ success: true, which, page: 1, pages: 1, page_size: 20, total: LISTS[which].length,
                       tasks: LISTS[which] });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [] });
};

await startTab('queue');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const text = (id) => document.getElementById(id)?.textContent.trim();
const row = (id) => document.querySelector(`.queue-task[data-task="${id}"]`);
const facts = (id) => [...row(id).querySelectorAll('.queue-fact')];

await waitFor('the rows', () => row(21) && row(20) && row(19));
if (!row(21) || !row(20) || !row(19)) done();
check('a task of several says how many checkpoints, where one names its checkpoint and VAE',
      [facts(20)[0].textContent.trim(), facts(19).slice(0, 2).map((f) => f.textContent.trim())],
      ['3 checkpoints', ['anime_v12', 'sdxl_vae']]);
const LINES = 'anime_v12.safetensors (sdxl_vae) - Euler a, Karras, 24 steps, CFG 7 - Completed\n'
    + 'flux_dev.safetensors - Failed: The checkpoint is not in this WebUI\n'
    + 'photo_v5.safetensors - not run';
check('each checkpoint, its VAE, what its run ran with and how it ended on hover, a line each; one never '
      + 'reached, not run, and no settings; one the server says nothing of, no settings', facts(20)[0].title, LINES);
check('a run still to come says what it will run with', facts(21)[0].title.split('\n')[2],
      'photo_v5.safetensors - DPM++ 2M, Automatic, 20 steps, CFG 4.5');
// #403: none of the press's settings on the row of a task of several - each
// run had its own, in the tip - where a task of one keeps them.
const said = (id) => facts(id).map((f) => f.textContent.trim());
check('a task of several states no sampler, schedule type, steps or CFG; its size and batch stay',
      [said(20).filter((f) => f.includes('Euler') || f.includes('Karras') || f.endsWith(' steps') || f.startsWith('CFG')),
       said(20).includes('832×1216'), said(20).includes('batch 1 × 1')], [[], true, true]);
check('a task of one keeps them', said(19).filter((f) => f.includes('Euler') || f.endsWith(' steps') || f.startsWith('CFG')),
      ['Euler a · Karras', '30 steps', 'CFG 7']);
// #432: how its runs ended, once it has, beside how many there were.
check('an ended task of several says how its runs ended, after how many there were',
      [said(20)[1], facts(20)[1].title], ['1 completed, 1 failed, 1 not run', LINES]);
check('a running one does not yet', said(21).some((f) => f.includes('completed') || f.includes('not run')), false);
check('a run stopped is counted as stopped', said(23)[1], '1 completed, 1 stopped, 1 not run');

await waitFor('the run it is on', () => row(21).querySelector('.queue-run')?.textContent === 'run 2 of 3');
check('while it runs, its row says which run it is on', row(21).querySelector('.queue-run')?.textContent, 'run 2 of 3');
// The bar and the status line follow the whole task (#337), each run an
// equal share. The page first finds run 2 begun and Forge not yet on it:
// run 1 shows as done.
const bar = () => {
    const shown = row(21)?.querySelector('.queue-progress');
    return [shown?.getAttribute('aria-valuenow'), shown?.firstElementChild.style.width];
};
const settle = async (what) => {
    reads.length = 0;
    await waitFor(what, () => reads.length >= 2);
};
await waitFor('the status line', () => text('queue_task')?.includes('%'));
check("a run begun that Forge has not taken up yet: the runs before it show as done, on the bar and the line",
      [text('queue_task'), ...bar()], ['Task #21 · run 2 of 3 · 33%', '33', '33%']);
// Run 2 at Forge's 45% is (1 + 0.45) / 3 of the task; Forge's time left is the run's own.
FORGE = { active: true, queued: false, progress: 0.45, eta: 40.2, textinfo: null };
await waitFor('run 2 at 45%', () => bar()[0] === '48');
check("and so does the status line, with the whole task's figure and the run's time left",
      [text('queue_task'), ...bar()], ['Task #21 · run 2 of 3 · 48% · 40 s left in this run', '48', '48%']);
FORGE = { ...FORGE, progress: 0.9 };
await waitFor('run 2 at 90%', () => bar()[0] === '63');
// Forge finishes run 2 before the poll that would have read 100%.
FORGE = { active: false, queued: false, completed: true, textinfo: 'Waiting...' };
await settle('Forge read as done with run 2');
check('a run Forge has finished counts whole, wherever its last read left the bar', bar(), ['67', '67%']);
// Between runs the queue waits for the person's own Generate (#170).
STATUS = { ...STATUS, progress: { ...STATUS.progress, holding: true } };
await settle('the queue holding');
check('holding between runs, the line still says the task, its run and how far along it is; the bar is kept',
      [text('queue_task'), ...bar()],
      ['Task #21 · run 2 of 3 · 67% · waiting for your own generation to end', '67', '67%']);
// Run 3 waits for Forge's lock.
STATUS = { ...STATUS, progress: { ...STATUS.progress, holding: false, run: 3, job: 'task(mmq-21-12)' } };
FORGE = { active: false, queued: true, completed: false, textinfo: 'In queue: 2/2' };
await settle('run 3 waiting for Forge');
check("run 3 waiting for Forge's lock: the bar keeps the runs before it, and so does the line",
      [text('queue_task'), ...bar()], ['Task #21 · run 3 of 3 · 67% · waiting for Forge', '67', '67%']);
check('a task of one has no run label, running or not, nor a task of several that has ended',
      [row(22)?.querySelector('.queue-run'), row(19).querySelector('.queue-run'), row(20).querySelector('.queue-run')],
      [null, null, null]);

// Show images asks for no grouping (#401): the Generations tab opens a task's
// tile where its search shows one.
check('Show images on a task of several names its task alone, as on a task of one',
      [row(20).querySelector('[data-action="queue.showImages"]')?.dataset,
       row(19).querySelector('[data-action="queue.showImages"]')?.dataset]
          .map((d) => d && [d.task, 'several' in d]), [['20', false], ['19', false]]);

act('queue.details', { task: 20 });
await waitFor('the details', () => document.querySelector('#mm_meta_modal .queue-details'));
const details = document.querySelector('#mm_meta_modal');
const cell = (key) => [...details.querySelectorAll('tr')].find((tr) => tr.querySelector('th')?.textContent === key)
    ?.querySelector('td')?.textContent;
check('its details list each checkpoint with what its run ran with and how it ended, in place of one checkpoint '
      + 'and its VAE',
      [cell('Checkpoints'), cell('Checkpoint'), cell('VAE / Text Encoder')],
      [LINES, undefined, undefined]);

done();
