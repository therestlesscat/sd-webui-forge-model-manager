// "Only Show Models with SFW images" in the Model Manager, from the browser's side.
//
// The server does the judging (tests/py/mm_sfw_filter_test.py); what the tab
// owes it is the question. The box sits with the other options, is sent as
// sfw_only only when ticked, and is kept by a saved search like every other
// filter - a filter a saved search forgets is one that silently turns off.
import { ROOT, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const listed = [];
const saved = [];            // what Save Search sent: it is kept in the database
globalThis.fetch = async (url, init = {}) => {
    if (String(url).includes('/model-manager/saved-search') && init.method === 'POST') {
        saved.push(JSON.parse(init.body));
        return { ok: true, json: async () => ({ success: true }) };
    }
    const href = String(url);
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        listed.push(new URL(href, 'http://webui').searchParams);
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0, page: 1,
        page_size: 20 }) };
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const load = async () => {
    const before = listed.length;
    $('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid request', () => listed.length > before);
    return listed[listed.length - 1];
};

check('the box is with the other options',
      $('mm_sfw_only')?.closest('.filter-group')?.querySelector('label')?.textContent, 'Options');
check('beside the preview box',
      $('mm_sfw_only')?.closest('.filter-group')?.contains($('mm_preview_show_nsfw')), true);
check('named as in the Civitai Browser',
      $('mm_sfw_only')?.closest('label')?.textContent.trim(), 'Only Show Models with SFW images');
check('with a tooltip saying what it looks at',
      [$('mm_sfw_only')?.closest('label')?.title.includes('first 20'),
       $('mm_sfw_only')?.closest('label')?.title.includes('the version the card shows'),
       $('mm_sfw_only')?.closest('label')?.title.includes('A model with none is left out')],
      [true, true, true]);

check('unticked, it is not sent', (await load()).has('sfw_only'), false);
$('mm_sfw_only').checked = true;
check('ticked, it is', (await load()).get('sfw_only'), 'true');

$('mm_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saved.length > 0);
check('a saved search keeps it', [saved[0].tab, saved[0].filters.sfw_only], ['model_manager', true]);

done();
