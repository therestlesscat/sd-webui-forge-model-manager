// The Queue tab's view of a task of several checkpoints (#400), against a
// stand-in server.
//
// Its row says "3 checkpoints" where a task of one names its checkpoint and
// VAE, each checkpoint and how its run ended on hover. While it runs, the row
// and the status line say which run it is on - "run 2 of 3" - and a task of
// one says no run. Its details list each checkpoint with how its run ended.
// Its Show images asks the Generations tab for the task grouped by Model; a
// task of one's asks for it ungrouped, as ever.
import { act, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('afterbegin', '<button id="tab_queue_tab-button" class="selected">Queue</button>');
window.mmTiming = { poll: 40, loadTask: 1000 };

const CHECKPOINTS = [
    { checkpoint: 'anime_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'], status: 'completed', error: null },
    { checkpoint: 'flux_dev.safetensors', modules: [], status: 'failed', error: 'The checkpoint is not in this WebUI' },
    { checkpoint: 'photo_v5.safetensors', modules: [], status: null, error: null },
];
const task = (id, status, extra = {}) => ({
    id, mode: 'txt2img', status, prompt: `task ${id}`, script: null,
    checkpoint: 'anime_v12.safetensors', modules: ['F:\\models\\VAE\\sdxl_vae.safetensors'],
    checkpoints: [{ checkpoint: 'anime_v12.safetensors', modules: [], status: null, error: null }],
    width: 832, height: 1216, hires: null, scale_by: null, sampler: 'Euler a', scheduler: 'Karras', steps: 30,
    batch_size: 1, n_iter: 1, created_at: '2026-11-05T12:50:00', started_at: null, finished_at: null,
    error: null, first_seed: null, retry_of: null, retried_as: null, generations: [], image_count: 0, ...extra,
});
const LISTS = {
    active: [task(21, 'running', { checkpoints: CHECKPOINTS.map((c, i) => ({ ...c, status: i ? null : c.status, error: null })) })],
    history: [task(20, 'failed', { checkpoints: CHECKPOINTS, image_count: 2, error: '1 of 3 failed' }),
              task(19, 'completed', { image_count: 1 })],
};
// A running task of one beside it, as a row: no run label, ever.
LISTS.active.push(task(22, 'running'));
const STATUS = { success: true, running: true, counts: { pending: 0, running: 1, completed: 1, failed: 1 },
                 progress: { state: 'running', task_id: 21, job: 'task(mmq-21-11)', run: 2, runs: 3, completed: 0,
                             failed: 0, stopped: 0, notes: [], error: null } };
const FORGE = { active: true, queued: false, progress: 0.45, eta: null, textinfo: null };
const INPUTS = { fixed: [{ name: 'prompt', value: 'task 20' }], script: null, scripts: [], loose: [] };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/internal/progress')) return reply(FORGE);
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
const LINES = 'anime_v12.safetensors (sdxl_vae) - Completed\n'
    + 'flux_dev.safetensors - Failed: The checkpoint is not in this WebUI\nphoto_v5.safetensors - not run';
check('each checkpoint, its VAE, and how its run ended on hover, a line each; one never reached, not run',
      facts(20)[0].title, LINES);

await waitFor('the run it is on', () => row(21).querySelector('.queue-run')?.textContent === 'run 2 of 3');
check('while it runs, its row says which run it is on', row(21).querySelector('.queue-run')?.textContent, 'run 2 of 3');
await waitFor('the status line', () => text('queue_task')?.includes('45%'));
check('and so does the status line', text('queue_task'), 'Task #21 · run 2 of 3 · 45%');
check('a task of one has no run label, running or not, nor a task of several that has ended',
      [row(22)?.querySelector('.queue-run'), row(19).querySelector('.queue-run'), row(20).querySelector('.queue-run')],
      [null, null, null]);

check('Show images on a task of several asks for it grouped by Model; on a task of one, as ever',
      [row(20).querySelector('[data-action="queue.showImages"]')?.dataset.several,
       row(19).querySelector('[data-action="queue.showImages"]')?.dataset.several], ['1', undefined]);

act('queue.details', { task: 20 });
await waitFor('the details', () => document.querySelector('#mm_meta_modal .queue-details'));
const details = document.querySelector('#mm_meta_modal');
const cell = (key) => [...details.querySelectorAll('tr')].find((tr) => tr.querySelector('th')?.textContent === key)
    ?.querySelector('td')?.textContent;
check('its details list each checkpoint with how its run ended, in place of one checkpoint and its VAE',
      [cell('Checkpoints'), cell('Checkpoint'), cell('VAE / Text Encoder')],
      [LINES, undefined, undefined]);

done();
