// "Hide paid and Early Access models", the Civitai Browser's fourth
// post-processing box (#385), from the browser's side; the server's is
// browser_api_test.py's, the loop's prompt_filter_test.py's.
//
// Ticked, a search leaves out every model whose card shows a paid or Early
// Access version and fills the page from the rest. Free, like the Hide box,
// and needing several searches as often, so a search with it ticked streams.
// The status line and the running line count what it passed over. A draw
// sets it aside (cb_lucky_test.mjs); a search saved before it leaves it
// unticked (cb_saved_search_test.mjs).
import { checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// The tab showing, so the saved search runs as the tab starts.
document.body.insertAdjacentHTML('afterbegin',
    '<div id="tabs"><button id="tab_civitai_browser_tab-button" class="selected" aria-selected="true">Civitai Browser</button></div>');

const MODEL = (id) => ({ id, name: `M${id}`, type: 'Checkpoint', stats: {}, creator: {},
    modelVersions: [{ id: id * 10, name: 'v1', images: [], files: [] }] });

const SAVED = { query: '', types: '', checkpoint_type: '', base_models: '', sort: 'Most Downloaded',
    period: 'AllTime', nsfw: false, tag: '', require_prompt: false, sfw_only: false, min_size: '',
    max_size: '', hide_owned: false, hide_paid: true };
let streamLines = [];
const asked = [];
const saves = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/saved-search')) {
        if (init.method === 'POST') {
            saves.push(JSON.parse(init.body));
            return reply({ success: true });
        }
        return reply({ success: true, filters: SAVED });
    }
    if (!href.includes('/model-manager/civitai/models')) return reply({ success: true });
    asked.push(new URL(href, 'http://webui'));
    if (!href.includes('/stream')) {
        return reply({ success: true, models: [], nextCursor: null, pageSize: 20,
                       cardWidth: 200, cardHeight: 280, filterStats: null });
    }
    const queue = streamLines.map((l) => new TextEncoder().encode(JSON.stringify(l) + '\n'));
    return { ok: true, body: { getReader: () => ({
        read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true }),
        cancel: async () => {},
    }) } };
};

const $ = (id) => document.getElementById(id);
const status = () => $('cb_status').textContent;
const summary = (stats) => ({ type: 'done', nextCursor: null, filterStats: stats });
const NONE = { checked: 0, dropped: 0, unsafe: 0, failed: 0, rejected: 0, promptFilter: false };

// ------------------------------------------------------- the saved search
streamLines = [summary({ ...NONE, paid: 2, paidFilter: true })];
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the saved search to run', () => asked.length > 0);
check('a saved search brings the box back ticked, and searches with it',
      [$('cb_hide_paid')?.checked, asked[0]?.pathname, asked[0]?.searchParams.get('hide_paid')],
      [true, '/model-manager/civitai/models/stream', 'true']);
await waitFor('the saved search to finish', () => status().startsWith('Showing'));

// ---------------------------------------------------------------- the markup
const group = $('cb_require_prompt').closest('.filter-group');
check('the box sits under Post-processing Options, after the Hide box',
      [group?.querySelector('label')?.textContent, Array.from(group?.querySelectorAll('input[type="checkbox"]') || [])
          .map((box) => box.id)],
      ['Post-processing Options', ['cb_sfw_only', 'cb_require_prompt', 'cb_hide_owned', 'cb_hide_paid']]);
check('saying what it does', $('cb_hide_paid_label')?.textContent.replace(/\s+/g, ' ').trim(),
      'Hide paid and Early Access models');
check('and, held over, which version decides, that a bought one goes too, and what it costs',
      $('cb_hide_paid_label')?.title,
      'Leaves out models whose card shows a version that costs Buzz, for good (Paid) or until a date (Early Access), '
      + 'and fills the page from the rest. A version you bought is left out too: untick the box to see it. '
      + 'Free: no extra requests, though a search of a creator who posts many paid models may need more searches '
      + 'to fill a page.');
// A page without the box has failed the checks above; the rest would only crash on it.
if (!$('cb_hide_paid')) done();

// One search, run to the end.
async function search() {
    asked.length = 0;
    $('cb_status').textContent = '';
    $('cb_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the search to finish', () => status().startsWith('Showing') || status().startsWith('Looked'));
}

// ------------------------------------------------------ unticked: as before
$('cb_hide_paid').checked = false;
await search();
check('unticked, the plain search is used, and nothing is hidden',
      [asked[0]?.pathname, asked[0]?.searchParams.get('hide_paid') === 'true'], ['/model-manager/civitai/models', false]);

// ------------------------------------------------ ticked alone, it streams
$('cb_hide_paid').checked = true;
streamLines = [
    { type: 'meta', pageSize: 20 },
    { type: 'model', model: MODEL(1) },
    { type: 'progress', checked: 0, dropped: 0, rejected: 0, in_library: 0, paid: 6, found: 1 },
];
await search();
check('ticked alone, a search streams, sending it, and no prompt check',
      [asked[0]?.pathname, asked[0]?.searchParams.get('hide_paid'), asked[0]?.searchParams.get('require_prompt')],
      ['/model-manager/civitai/models/stream', 'true', 'false']);
check('its running line counts the paid models among what it looked through',
      status(), 'Looked through 7 models, found 1 of 20 (6 paid or Early Access)');

$('cb_hide_owned').checked = true;
streamLines = [
    { type: 'meta', pageSize: 20 },
    { type: 'model', model: MODEL(1) },
    { type: 'progress', checked: 0, dropped: 0, rejected: 0, in_library: 88, paid: 6, found: 1 },
];
await search();
check('with the Hide box, the library\'s count first, then the paid',
      status(), 'Looked through 95 models, found 1 of 20 (88 in your library, 6 paid or Early Access)');

streamLines = [summary({ ...NONE, inLibrary: 12, libraryFilter: true, paid: 4, paidFilter: true })];
await search();
check('at the end, it says how many paid models it hid, after the library\'s',
      status(), 'Showing 0 models (page 1) - skipped 12 in your library, 4 paid or Early Access');

$('cb_hide_owned').checked = false;
$('cb_max_size').value = '7';
streamLines = [summary({ ...NONE, rejected: 30, paid: 4, paidFilter: true, sizeFilter: true })];
await search();
check('with the size filter too, the paid count comes before it',
      status(), 'Showing 0 models (page 1) - skipped 4 paid or Early Access, 30 outside the size range');
$('cb_max_size').value = '';

// ------------------------------------------------- what it says while it looks
async function firstWords() {
    streamLines = [{ type: 'meta', pageSize: 20 }];
    asked.length = 0;
    $('cb_status').textContent = '';
    let first = '';
    const seen = new window.MutationObserver(() => { if (!first) first = status(); });
    seen.observe($('cb_status'), { childList: true, characterData: true, subtree: true });
    $('cb_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the stream to open', () => asked.length === 1);
    await new Promise((resolve) => setTimeout(resolve, 30));
    seen.disconnect();
    return first;
}
check('while it fills, before the first card', await firstWords(), 'Leaving out paid and Early Access models...');
$('cb_hide_owned').checked = true;
check('with the Hide box too', await firstWords(), 'Leaving out models in your library and paid ones...');
$('cb_hide_owned').checked = false;

// ------------------------------------------------------------- Save Search
$('cb_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps the box with the others', saves[0]?.filters?.hide_paid, true);

done();
