// The Generations tab's search, against a stand-in server.
//
// The box starts empty, whatever the browser kept in it. Enter asks the
// server for the images that match, from the top level - out of a group
// opened before - and the same search goes with every part after, and with
// a batch's rating. Emptied - by hand, or by the box's × - it shows
// everything again. Nothing found says so.
import { ROOT, act, call, checker, mountTab, startTab, tick, openTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
// The browser kept a search from before.
document.getElementById('gen_search').value = 'kept from before';

const image = (id, generation) => ({ id, generation_id: generation, position: 0, url: `/x/${id}`, exists: true,
                                     mm_level: 1, meta: {}, infotext: '' });
const tile = (generation, kind = 'generation') => ({
    kind, generation: { id: generation, created_at: '2026-10-05T12:00:00', mode: 'txt2img', image_count: 2 },
    images: [image(generation * 10, generation), image(generation * 10 + 1, generation)], matching_count: 2,
    ...(kind === 'group' ? { group: { id: `g${generation}`, value: `group ${generation}`, by: 'prompt', generations: 1 } } : {}),
});
const taskTile = (id) => ({ ...tile(201), kind: 'task', task: { id, checkpoints: 2, generations: [202, 201], images: 4 },
                             images: [image(2021, 202), image(2011, 201)] });
const browsed = [];
const rated = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_hide_nsfw: false, generations_enabled: true });
    }
    if (href.includes('/model-manager/generations/rate')) {
        rated.push(Object.fromEntries(new URLSearchParams(String(init.body))));
        return reply({ success: true, rated: 2 });
    }
    if (href.includes('/model-manager/generations/browse')) {
        const params = Object.fromEntries(new URL(href).searchParams);
        browsed.push(params);
        const search = params.search || '';
        // task:20 is a task of several checkpoints (#401): one tile at its top,
        // its runs when opened - with Expand on, images; task:21's images all hidden.
        const tiles = search === 'nothing here' || search === 'task:21' ? []
            : search === 'task:20' && params.task === '20' ? [tile(201), tile(202)]
            : search === 'task:20' && params.expand === 'true'
                ? [{ ...tile(201), kind: 'image', matching_count: 1, images: [image(2011, 201)] }]
            : search === 'task:20' ? [taskTile(20)]
            : params.in_group ? [tile(3)]
            : search ? [tile(2)] : params.group ? [tile(1, 'group')] : [tile(1), tile(2)];
        return reply({ success: true, tiles, more: false, scope: { count: tiles.length * 2 },
                       state: { total: tiles.length * 2, filtered: tiles.length * 2, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    return reply({ success: true, notes: [] });
};

await startTab('generations');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the first page', () => browsed.length);
const box = document.getElementById('gen_search');
check('the search starts empty, whatever the browser kept', [box.value, browsed[0].search], ['', undefined]);

// Group by a prompt, and open a group: a search starts again from the top.
await call('generations.groupBy', 'prompt');
await waitFor('the groups', () => browsed.at(-1)?.group === 'prompt' && !browsed.at(-1)?.in_group);
await act('generations.open', { tile: 0 });
await waitFor('the group opened', () => browsed.at(-1)?.in_group === 'g1');

box.value = '  lighthouse   at dusk ';
browsed.length = 0;
box.dispatchEvent(new window.Event('change', { bubbles: true }));
await waitFor('the search drawn', () => browsed.length && document.querySelectorAll('#gen_grid .gen-tile').length === 1);
check('a search asks for the matching images, trimmed, from the top level',
      [browsed[0].search, browsed[0].in_group, browsed[0].group], ['lighthouse   at dusk', undefined, 'prompt']);
check('and draws them', [...document.querySelectorAll('#gen_grid .gen-tile')].length, 1);
check('the banner counts what the search found, not all that is stored',
      document.getElementById('gen_banner').textContent.replace(/\s+/g, ' ').includes('2 images found by the search'), true);

browsed.length = 0;
box.dispatchEvent(new window.Event('change', { bubbles: true }));
await new Promise((resolve) => setTimeout(resolve, 150));
check('the same search again asks nothing', browsed.length, 0);

// A batch rated under a search rates only what the search shows.
await call('generations.groupBy', '');
await waitFor('ungrouped', () => browsed.at(-1)?.group === '' || browsed.at(-1)?.group === undefined);
await tick('generations.rating', true);
rated.length = 0;
await act('generations.rate', { tile: 0, level: 4 });
check("a batch's rating carries the search", rated[0]?.search, 'lighthouse   at dusk');

box.value = 'nothing here';
box.dispatchEvent(new window.Event('change', { bubbles: true }));
await waitFor('nothing found', () => document.getElementById('gen_status')?.textContent === 'No image matches the search.');
check('nothing found says so', document.getElementById('gen_status').textContent, 'No image matches the search.');

// The box's ×: emptied, and a search event says so.
browsed.length = 0;
box.value = '';
box.dispatchEvent(new window.Event('search'));
await waitFor('everything again', () => browsed.length && document.querySelectorAll('#gen_grid .gen-tile').length === 2);
check('emptied, it shows everything again', [browsed[0]?.search, document.querySelectorAll('#gen_grid .gen-tile').length],
      [undefined, 2]);

// The Queue's Show images: this tab, searched by the task, ungrouped for now.
await call('generations.groupBy', 'prompt');
await waitFor('grouped again', () => browsed.at(-1)?.group === 'prompt');
browsed.length = 0;
await openTab('generations', 'showTask', 19);
await waitFor('the task asked', () => browsed.length);
check("Show images searches by the task, with Group by at Nothing",
      [box.value, browsed[0].search, browsed[0].group ?? '', document.getElementById('gen_group_by').textContent],
      ['task:19', 'task:19', '', 'Nothing']);
check('the grouping chosen before is still the one remembered',
      window.localStorage.getItem('mm_generations_group_by'), 'prompt');
browsed.length = 0;
await openTab('generations', 'showTask', 19);
await waitFor('asked again', () => browsed.length);
check('asked again for the same task, it is drawn again', browsed[0]?.search, 'task:19');

// A task of several checkpoints (#401): searched by the task, ungrouped, and
// its tile - where the search shows one - opened onto its runs; Back shows it.
browsed.length = 0;
await openTab('generations', 'showTask', 20);
await waitFor('the task opened', () => browsed.some((b) => b.task === '20'));
check('Show images on a task of several: searched by the task, ungrouped, then its tile opened onto its runs',
      [box.value, browsed[0]?.search, browsed[0]?.group ?? '', browsed.at(-1)?.task,
       document.querySelectorAll('#gen_grid .gen-tile').length], ['task:20', 'task:20', '', '20', 2]);
check('the grouping chosen before is still the one remembered, here too',
      window.localStorage.getItem('mm_generations_group_by'), 'prompt');
await call('generations.back');
check('Back: the task\'s one tile', [...document.querySelectorAll('#gen_grid .gen-tile')].map((t) => t.dataset.task),
      ['20']);
// Select on, a click on a task's tile ticks it (#401): Show images turns Select
// off, and opens the task's runs all the same.
tick('generations.selecting', true);
browsed.length = 0;
await openTab('generations', 'showTask', 20);
await waitFor('the task opened, from Select', () => browsed.some((b) => b.task === '20'));
check('Show images with Select on: Select turned off, the task\'s tile opened onto its runs',
      [document.getElementById('gen_select').checked, browsed.at(-1)?.task], [false, '20']);
// No task tile to open: every image hidden, or Expand on - the tab stays on what it found.
browsed.length = 0;
await openTab('generations', 'showTask', 21);
await waitFor('the hidden task asked', () => browsed.length);
check('every image hidden: the search alone, nothing opened', browsed.map((b) => b.task ?? ''), ['']);
tick('generations.expand', true);
browsed.length = 0;
await openTab('generations', 'showTask', 20);
await waitFor('the task asked, expanded', () => browsed.length);
check('Expand on: its images, nothing opened', [browsed.map((b) => b.task ?? ''), browsed[0]?.expand], [[''], 'true']);
tick('generations.expand', false);

done();
