// "Hide models in my library", the Civitai Browser's third post-processing
// box (#217), from the browser's side; the server's is browser_api_test.py's.
//
// Ticked, a search leaves out every model with the Owned badge and fills the
// page from the rest. Hiding them is free, like the size filter, and needs
// several searches as often, so a search with the box ticked streams. The
// status line counts them among what was passed over. A draw leaves them out
// always, so the box is set aside while I'm feeling lucky is ticked, and Save
// Search keeps it with the other boxes.
import { checker, mountTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// The tab showing, so the saved search runs as the tab starts.
document.body.insertAdjacentHTML('afterbegin',
    '<div id="tabs"><button id="tab_civitai_browser_tab-button" class="selected" aria-selected="true">Civitai Browser</button></div>');

const MODEL = (id) => ({ id, name: `M${id}`, type: 'Checkpoint', stats: {}, creator: {},
    modelVersions: [{ id: id * 10, name: 'v1', images: [], files: [] }] });

const SAVED = { query: '', types: '', checkpoint_type: '', base_models: '', sort: 'Most Downloaded',
    period: 'AllTime', nsfw: false, tag: '', require_prompt: false, sfw_only: false, min_size: '',
    max_size: '', hide_owned: true };
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
streamLines = [summary({ ...NONE, inLibrary: 3, libraryFilter: true })];
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the saved search to run', () => asked.length > 0);
check('a saved search brings the box back ticked, and searches with it',
      [$('cb_hide_owned')?.checked, asked[0]?.pathname, asked[0]?.searchParams.get('hide_owned')],
      [true, '/model-manager/civitai/models/stream', 'true']);
await waitFor('the saved search to finish', () => status().startsWith('Showing'));

// ---------------------------------------------------------------- the markup
const group = $('cb_require_prompt').closest('.filter-group');
check('the box sits under Post-processing Options, after the other two',
      [group?.querySelector('label')?.textContent, Array.from(group?.querySelectorAll('input[type="checkbox"]') || [])
          .map((box) => box.id)],
      ['Post-processing Options', ['cb_sfw_only', 'cb_require_prompt', 'cb_hide_owned']]);
check('saying what it does', $('cb_hide_owned_label')?.textContent.replace(/\s+/g, ' ').trim(),
      'Hide models in my library');
check('and, held over, that owned means the library here', $('cb_hide_owned_label')?.title.includes('not a paid version'),
      true);
// The status line, which the library's count makes longer, sits at the left
// of the row with Search, taking the room the buttons leave and wrapping
// beside them as they grow.
check('the status line is the first thing in the row with Search',
      [$('cb_status')?.parentElement?.classList.contains('filter-buttons-row'),
       $('cb_status')?.parentElement?.firstElementChild?.id,
       $('cb_status')?.parentElement === $('cb_search_btn')?.parentElement], [true, 'cb_status', true]);
// A page without the box has failed the checks above; the rest would only crash on it.
if (!$('cb_hide_owned')) done();

// One search, run to the end.
async function search() {
    asked.length = 0;
    $('cb_status').textContent = '';
    $('cb_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the search to finish', () => status().startsWith('Showing') || status().startsWith('Drew'));
}

// ------------------------------------------------------ unticked: as before
$('cb_hide_owned').checked = false;
await search();
// The plain search sends every filter, an unticked box as false.
check('unticked, the plain search is used, and nothing is hidden',
      [asked[0]?.pathname, asked[0]?.searchParams.get('hide_owned') === 'true'], ['/model-manager/civitai/models', false]);

// ------------------------------------------------ ticked alone, it streams
$('cb_hide_owned').checked = true;
streamLines = [
    { type: 'meta', pageSize: 20 },
    { type: 'progress', checked: 0, dropped: 0, rejected: 0, in_library: 0, found: 0 },
    { type: 'model', model: MODEL(1) },
    { type: 'progress', checked: 0, dropped: 0, rejected: 0, in_library: 88, found: 1 },
];
asked.length = 0;
$('cb_status').textContent = '';
$('cb_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the stream to open', () => asked.length === 1);
check('ticked alone, a search streams, sending it, and no prompt check',
      [asked[0]?.pathname, asked[0]?.searchParams.get('hide_owned'), asked[0]?.searchParams.get('require_prompt')],
      ['/model-manager/civitai/models/stream', 'true', 'false']);
await waitFor('the stream to end', () => status().startsWith('Looked'));
check('its progress counts the library\'s models among what it looked through',
      status(), 'Looked through 89 models, found 1 of 20 (88 in your library)');

streamLines = [summary({ ...NONE, inLibrary: 88, libraryFilter: true })];
await search();
check('at the end, it says how many models in the library it hid',
      status(), 'Showing 0 models (page 1) - skipped 88 in your library');

$('cb_max_size').value = '7';
streamLines = [summary({ ...NONE, rejected: 30, inLibrary: 88, libraryFilter: true, sizeFilter: true })];
await search();
check('with the size filter too, the library\'s count comes first',
      status(), 'Showing 0 models (page 1) - skipped 88 in your library, 30 outside the size range');
$('cb_max_size').value = '';

// ------------------------------------------------- what it says while it looks
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
check('while it fills, before the first card', first, 'Leaving out models in your library...');

// ------------------------------------------------------ I'm feeling lucky
tick('civitaiBrowser.feelingLucky', true);
check('a draw sets the box aside, saying a draw leaves them out always',
      [$('cb_hide_owned').disabled, $('cb_hide_owned_label').classList.contains('filter-disabled'),
       $('cb_hide_owned_label').title.startsWith('A draw always leaves out the models in your library.')],
      [true, true, true]);
tick('civitaiBrowser.feelingLucky', false);
check('unticked again, the box is back as it was, still ticked',
      [$('cb_hide_owned').disabled, $('cb_hide_owned').checked,
       $('cb_hide_owned_label').title.startsWith('A draw')], [false, true, false]);

// ------------------------------------------------------------- Save Search
$('cb_save_search_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the save', () => saves.length > 0);
check('Save Search keeps the box with the others', saves[0]?.filters?.hide_owned, true);

done();
