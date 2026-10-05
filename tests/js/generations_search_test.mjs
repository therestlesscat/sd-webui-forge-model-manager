// The Generations tab's search, against a stand-in server.
//
// The box starts empty, whatever the browser kept in it. Enter asks the
// server for the images that match, from the top level - out of a group
// opened before - and the same search goes with every part after, and with
// a batch's rating. Emptied - by hand, or by the box's × - it shows
// everything again. Nothing found says so.
import { ROOT, act, call, checker, mountTab, tick } from './harness.mjs';

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
        const tiles = search === 'nothing here' ? [] : params.in_group ? [tile(3)]
            : search ? [tile(2)] : params.group ? [tile(1, 'group')] : [tile(1), tile(2)];
        return reply({ success: true, tiles, more: false, scope: { count: tiles.length * 2 },
                       state: { total: tiles.length * 2, filtered: tiles.length * 2, hidden_nsfw: 0, nsfw_count: 0 } });
    }
    return reply({ success: true, notes: [] });
};

await import(`file:///${ROOT}/javascript/generations.mjs`);
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

done();
