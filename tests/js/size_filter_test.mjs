// The Civitai Browser's file size filter, from the browser's side.
//
// Two boxes in GB between Search and Tag. They reach the server as
// min_size_gb / max_size_gb, and an empty box is not sent at all. A size
// range can take several searches to fill a page, so a sized search streams,
// as the prompt filter does: models appear as they are found, with a running
// count, instead of the whole page after a wait of up to ten seconds - which
// is how it first shipped. The stream is told whether to check prompts too.
//
// A range whose minimum is above its maximum is refused before any search,
// since it would spend every search it is allowed on finding nothing.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const MODEL = (id) => ({ id, name: `M${id}`, type: 'Checkpoint', stats: {}, creator: {},
    modelVersions: [{ id: id * 10, name: 'v1', images: [], files: [] }] });

// What the stream says, and a hold on it: the test lets it go line by line,
// to see what is on screen between one line and the next.
let streamLines = [];
let release = null;
const asked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    if (!href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    asked.push(new URL(href, 'http://webui'));
    if (!href.includes('/stream')) {
        return { ok: true, json: async () => ({ success: true, models: [], nextCursor: null,
            pageSize: 20, cardWidth: 200, cardHeight: 280, filterStats: null }) };
    }
    const queue = streamLines.map((l) => new TextEncoder().encode(JSON.stringify(l) + '\n'));
    return { ok: true, body: { getReader: () => ({
        read: async () => {
            if (!queue.length) return { done: true };
            if (release) await new Promise((r) => { release.next = r; });
            return { done: false, value: queue.shift() };
        },
        cancel: async () => {},
    }) } };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const status = () => $('cb_status').textContent;
const cards = () => $('cb_grid').querySelectorAll('.model-card').length;
const summary = (stats) => ({ type: 'done', nextCursor: null, filterStats: stats });

// One search, run to the end: a second one while the first is loading is
// ignored, as it is for anyone pressing the button twice.
async function search() {
    asked.length = 0;
    $('cb_status').textContent = '';
    window.cbSearch();
    await waitFor('the search to finish', () => status().startsWith('Showing')
        || status().startsWith('File size'));
}

// ---------------------------------------------------------------- the markup
const row = $('cb_search').closest('.filter-row');
const groups = Array.from(row.querySelectorAll(':scope > .filter-group'));
const at = (id) => groups.findIndex((g) => g.querySelector(`#${id}`));
check('the size boxes sit between Search and Tag',
      [at('cb_search') < at('cb_min_size'), at('cb_min_size') < at('cb_tag_input')], [true, true]);
check('a group that keeps to its content rather than sharing the row',
      groups[at('cb_min_size')]?.classList.contains('filter-group-compact'), true);
check('both in one group, under one caption',
      [at('cb_min_size') === at('cb_max_size'),
       groups[at('cb_min_size')]?.querySelector('label')?.textContent], [true, 'File Size (GB)']);

// ------------------------------------------------------ no size, no stream
streamLines = [];
await search();
check('with no filter the plain search is used',
      asked[0]?.pathname, '/model-manager/civitai/models');

// ------------------------------------------------ a size range streams
$('cb_min_size').value = '2';
$('cb_max_size').value = '7.5';
streamLines = [
    { type: 'meta', pageSize: 20 },
    { type: 'progress', checked: 0, dropped: 0, rejected: 0, found: 0 },
    { type: 'model', model: MODEL(1) },
    { type: 'progress', checked: 0, dropped: 0, rejected: 41, found: 1 },
    { type: 'model', model: MODEL(2) },
    summary({ checked: 0, dropped: 0, rejected: 60, promptFilter: false,
              sizeFilter: true, budgetReached: true }),
];
release = {};
asked.length = 0;
$('cb_status').textContent = '';
window.cbSearch();
// Let the stream say one more line, then give the page a moment to show it.
async function step() {
    await waitFor('the next line', () => release.next, 20);
    const next = release.next;
    if (!next) return;                  // no stream to step: the waitFor has failed already
    release.next = null;
    next();
    await new Promise((r) => setTimeout(r, 20));
}

await waitFor('the stream to open', () => asked.length === 1);
check('a size range is searched through the stream',
      asked[0].pathname, '/model-manager/civitai/models/stream');
check('with both bounds',
      [asked[0].searchParams.get('min_size_gb'), asked[0].searchParams.get('max_size_gb')],
      ['2', '7.5']);
check('telling it not to check prompts, which it would otherwise assume',
      asked[0].searchParams.get('require_prompt'), 'false');
check('saying what it is doing before anything is found', status(),
      'Looking for models in the size range...');

await step(); await step(); await step();
check('the first model is on screen before the rest are found', cards(), 1);
await step();
check('with a running count of what it has looked through', status(),
      'Looked through 42 models, found 1 of 20 (41 outside the size range)');
await step(); await step();
release = null;
await waitFor('the summary', () => status().startsWith('Showing'));
check('both models are there at the end', cards(), 2);
check('and the summary says what the size passed over, and nothing about prompts', status(),
      'Showing 2 models (page 1) - skipped 60 outside the size range. '
      + 'Stopped early to avoid a long wait; press Next to keep looking.');

// ------------------------------------------------ an empty box is left out
$('cb_min_size').value = '';
streamLines = [summary({ checked: 0, dropped: 0, rejected: 0, promptFilter: false, sizeFilter: true })];
await search();
check('an empty box is left out, not sent as nothing',
      [asked[0].searchParams.has('min_size_gb'), asked[0].searchParams.get('max_size_gb')],
      [false, '7.5']);

// ---------------------------------------------------------- an impossible range
$('cb_min_size').value = '8';
$('cb_max_size').value = '2';
await search();
check('a minimum above the maximum is not searched for', asked.length, 0);
check('and says why', status(), 'File size: Min is larger than Max.');

// ------------------------------------------------------------ with prompts too
$('cb_min_size').value = '1';
$('cb_max_size').value = '';
$('cb_require_prompt').checked = true;
streamLines = [summary({ checked: 4, dropped: 1, rejected: 3, promptFilter: true,
                         sizeFilter: true, budgetReached: false })];
await search();
check('with the prompt filter as well, the stream is told to check prompts',
      [asked[0]?.searchParams.get('require_prompt'), asked[0]?.searchParams.get('min_size_gb')],
      ['true', '1']);
check('and its summary names both filters', status(),
      'Showing 0 models (page 1) - checked 4, skipped 1 without usable prompts, '
      + '3 outside the size range');

done();
