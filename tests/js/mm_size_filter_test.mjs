// The Model Manager's File Size filter (#40), in Advanced filters: a range in
// GB, either end open, sent with Load Models as min_size_gb / max_size_gb -
// what is not a size left out - kept with the saved search and restored with
// it, and loosened, with every other filter, when a model is jumped to. The
// server's side: grid_query_test.py, api_test.py.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';
const { call } = await import(`file:///${ROOT}/javascript/shared/calls.mjs`);

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const listed = [];
const saves = [];
let savedOnServer = { min_size: '1.5', max_size: '8' };
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            savedOnServer = saves.at(-1).filters;
        }
        return { ok: true, json: async () => ({ success: true, filters: savedOnServer }) };
    }
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        listed.push(new URL(href, 'http://webui').searchParams);
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0, page: 1, page_size: 20 }) };
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const load = async () => {
    const before = listed.length;
    $('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid request', () => listed.length > before);
    return listed.at(-1);
};

check('in Advanced filters, a range: min and max', [!!$('mm_min_size')?.closest('#mm_advanced'),
      $('mm_min_size')?.closest('.filter-range') === $('mm_max_size')?.closest('.filter-range')], [true, true]);
await waitFor('the saved search', () => $('mm_min_size').value === '1.5');
check('a saved search restores the range', [$('mm_min_size').value, $('mm_max_size').value], ['1.5', '8']);

let asked = await load();
check('Load Models asks for it, in GB', [asked.get('min_size_gb'), asked.get('max_size_gb')], ['1.5', '8']);

$('mm_min_size').value = '';
$('mm_max_size').value = 'abc';
asked = await load();
check('an end left empty, or not a size, is left out', [asked.has('min_size_gb'), asked.has('max_size_gb')],
      [false, false]);

$('mm_min_size').value = '2';
$('mm_max_size').value = '6.5';
$('mm_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps it', [saves.at(-1).filters.min_size, saves.at(-1).filters.max_size], ['2', '6.5']);

// "Only Show Models with SFW images" too: it was left on, and Show model in
// Model Manager, from a generation, found "nothing" for a model with an
// explicit image, though its file was in the library.
$('mm_sfw_only').checked = true;
const before = listed.length;
await call('modelManager.showModel', 'path:C:\\models\\some model.safetensors');
check('jumping to a model loosens it, with every other filter', [$('mm_min_size').value, $('mm_max_size').value],
      ['', '']);
check('SFW only included', $('mm_sfw_only').checked, false);
await waitFor('the lookup', () => listed.length > before);
check('and the lookup asks for no SFW filter', listed.at(-1).has('sfw_only'), false);
await waitFor('the answer', () => /Nothing found/.test($('mm_status')?.textContent || ''));
check('found nowhere, it names the file, not the query it was looked up by',
      $('mm_status').textContent.includes('"some model.safetensors"'), true);

done();
