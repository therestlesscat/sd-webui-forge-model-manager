// Select in the Civitai Browser (#223): tick models on any page of a search,
// then Download selected.
//
// Ticks are kept by model, so paging away and back draws them again, and a
// new search clears them. A click on a card ticks it rather than opening it.
// Download selected presses the Download a card's details use for each tick,
// in page order, one after another, and the server says what became of each
// - queued, already in the library (#276), paid and not bought, no file - or
// fails, which leaves the tick to press again. The page decides nothing
// about what may be downloaded.
import { act, checker, mountTab, openTab, startTab, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// Three pages of three models; each version's primary file is its second.
const model = (id, extra = {}) => ({
    id, name: `Model ${id}`, type: 'LORA', stats: {}, creator: {}, owned_locally: false, ...extra,
    modelVersions: [{ id: id * 10, name: 'v2', images: [], paid_access: null,
                      files: [{ id: id * 10 + 1, name: `m${id}_fp32.safetensors` },
                              { id: id * 10 + 2, name: `m${id}.safetensors`, primary: true }] }],
});
// Model 1: Owned - the library holds an older version - its newest not held.
const PAGES = [[model(1, { owned_locally: true }), model(2), model(3)], [model(4), model(5), model(6)],
               [model(7), model(8), model(9)]];

const posted = [];          // each download asked for: model, version, file
let answers = {};           // version id -> the server's answer, when not "queued"
let hold = 0;               // ms each download answer is held
let inFlight = 0, mostInFlight = 0;
let draws = [];             // what each I'm feeling lucky draw answers, in turn
let progress = [{ version_id: 60, file_name: 'm6.safetensors', status: 'downloading', percent: 5, synced: false }];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: structuredClone(progress) });
    if (href.includes('/civitai/download')) {
        const asked = { model: Number(init.body.get('model_id')), version: Number(init.body.get('version_id')),
                        file: Number(init.body.get('file_id')) };
        posted.push(asked);
        inFlight++;
        mostInFlight = Math.max(mostInFlight, inFlight);
        if (hold) await new Promise((r) => setTimeout(r, hold));
        inFlight--;
        const answer = answers[asked.version];
        if (answer) return reply(answer.body, answer.status);
        const queued = { version_id: asked.version, file_name: `m${asked.model}.safetensors`, status: 'pending', synced: false };
        progress.push(queued);
        return reply({ success: true, progress: queued });
    }
    if (href.includes('/civitai/owned')) return reply({ success: true, models: {}, versions: {} });
    if (href.includes('/civitai/models/random')) {
        const lines = [{ type: 'meta', pageSize: 3 }, { type: 'done', models: structuredClone(draws.shift() || []), draw: {} }]
            .map((line) => new TextEncoder().encode(JSON.stringify(line) + '\n'));
        return { ok: true, status: 200, body: { getReader: () => ({
            read: async () => (lines.length ? { done: false, value: lines.shift() } : { done: true }),
            cancel: async () => {},
        }) } };
    }
    const single = href.match(/\/civitai\/models\/(\d+)/);
    if (single) return reply({ success: true, model: structuredClone(PAGES.flat().find((m) => m.id === Number(single[1]))) });
    if (href.includes('/model-manager/civitai/models')) {
        const cursor = new URL(href, 'http://webui').searchParams.get('cursor') || 'c0';
        const n = Number(cursor.slice(1));
        return reply({ success: true, pageSize: 3, nextCursor: n < 2 ? `c${n + 1}` : null,
                       models: structuredClone(PAGES[n]) });
    }
    return reply({ success: true });
};

window.mmTiming = { poll: 60 };
await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const cards = () => Array.from(document.querySelectorAll('#cb_grid .model-card'));
const boxes = () => Array.from(document.querySelectorAll('#cb_grid [data-card-pick]'));
const ticked = () => boxes().map((b) => b.checked);
const count = () => $('cb_select_bar')?.querySelector('.mm-select-count')?.textContent.trim();
const status = () => $('cb_status').textContent.trim();
const click = (i, shift = false) => cards()[i].dispatchEvent(
    Object.assign(new window.Event('click', { bubbles: true, cancelable: true }), { shiftKey: shift }));
const onPage = (n) => waitFor(`page ${n}`, () => status().includes(`(page ${n})`) && cards().length === 3);
const pressed = () => posted.map((p) => p.model);

$('cb_search').value = 'loras';
act('civitaiBrowser.search');
await onPage(1);

// ------------------------------------------------------------ ticking
check('a Select switch in the row under the filters', Boolean($('cb_select')), true);
if (!$('cb_select')) done();
check('no boxes until Select is on', boxes().length, 0);
tick('civitaiBrowser.selecting', true);
check('Select on: a box on every card, and the bar', [boxes().length, $('cb_select_bar').hidden, count()],
      [3, false, '0 models selected']);
check('Download selected waits for a tick', $('cb_select_bar').querySelector(
    '[data-action="civitaiBrowser.downloadSelected"]')?.disabled, true);

click(0);
check('a click on a card ticks it, and opens nothing', [ticked(), $('cb_details').style.display, count()],
      [[true, false, false], 'none', '1 model selected']);
click(2, true);
check('shift-click ticks every card from the last one ticked', ticked(), [true, true, true]);
click(1);
check('a click on a ticked card unticks it', ticked(), [true, false, true]);
const box = boxes()[1];
box.checked = true;
box.dispatchEvent(new window.Event('click', { bubbles: true, cancelable: true }));
check('a click on the box itself ticks it', [ticked(), $('cb_details').style.display], [[true, true, true], 'none']);

// ------------------------------------------------------------- paging
act('civitaiBrowser.nextPage');
await onPage(2);
check('another page: its cards unticked, the count all of them', [ticked(), count()],
      [[false, false, false], '3 models selected']);
click(0);
act('civitaiBrowser.prevPage');
await onPage(1);
check('back on page 1: its ticks drawn again, the count both pages\'', [ticked(), count()],
      [[true, true, true], '4 models selected']);

tick('civitaiBrowser.selecting', false);
check('Select off: no boxes, no bar', [boxes().length, $('cb_select_bar').hidden], [0, true]);
tick('civitaiBrowser.selecting', true);
check('Select on again: the same ticks', [ticked(), count()], [[true, true, true], '4 models selected']);

// ---------------------------------------------------- Download selected
// Ticked page 2's first, then page 1's last to first: pressed in page order.
act('civitaiBrowser.selectClear');
check('Clear clears every page\'s ticks', [ticked(), count()], [[false, false, false], '0 models selected']);
act('civitaiBrowser.nextPage');
await onPage(2);
click(0);
click(1);
click(2);
act('civitaiBrowser.prevPage');
await onPage(1);
click(2);
click(1);
click(0);
answers = {
    20: { body: { success: true, already_installed: true, version_id: 20, file_path: 'models\\Lora\\m2.safetensors' } },
    30: { status: 403, body: { success: false, paid: true, error: 'This version is paid on Civitai.' } },
    40: { status: 409, body: { success: false, no_file: true, error: 'No files available for download' } },
    50: { status: 500, body: { success: false, error: 'Civitai is limiting requests' } },
};
act('civitaiBrowser.downloadSelected');
await waitFor('the batch to end', () => status().length > 0);
check('pressed in page order, page 1 top to bottom, then page 2 - model 6, already on its way, not asked for',
      pressed(), [1, 2, 3, 4, 5]);
check('the Owned card\'s newest version, by its primary file - not the first',
      posted[0], { model: 1, version: 10, file: 12 });
check('one line, only for what did not join the queue',
      status(), 'Not queued: 1 already in your library, 1 paid on Civitai, not bought, 1 already downloading, '
                + '1 model with no file to download. 1 failed: Civitai is limiting requests - still ticked, '
                + 'press Download selected again.');
check('the failed one stays ticked; every other is cleared', [ticked(), count()], [[false, false, false], '1 model selected']);

// Every tick queued: nothing to say.
answers = {};
posted.length = 0;
act('civitaiBrowser.nextPage');
await onPage(2);
check('the failed one, still ticked on its page', ticked(), [false, true, false]);
act('civitaiBrowser.nextPage');
await onPage(3);
click(0);
await act('civitaiBrowser.downloadSelected');
check('every tick queued: the status line cleared, no ticks left', [pressed(), status(), count()],
      [[5, 7], '', '0 models selected']);

// ------------------------------------------------------- Stop, one at a time
// The server forgets what it queued: none of page 3 is on its way now.
progress = [];
await waitFor('the downloads list to empty', () => !document.getElementById('cb_download_list')?.children.length);
posted.length = 0;
act('civitaiBrowser.selectAll');
hold = 120;
act('civitaiBrowser.downloadSelected');
await waitFor('the second press', () => posted.length >= 2);
const stop = $('cb_select_bar').querySelector('[data-action="civitaiBrowser.stopSelected"]');
check('while it runs, Download selected is Stop', stop?.textContent.trim(), 'Stop');
act('civitaiBrowser.stopSelected');
await waitFor('the batch to stop', () => status().startsWith('Stopped'));
check('Stop: no third press; the rest stay ticked', [pressed(), count(), status()],
      [[7, 8], '1 model selected', 'Stopped: 1 model not asked for, still ticked.']);
check('never two presses at once', mostInFlight, 1);
hold = 0;

// ---------------------------------------------------- I'm feeling lucky
// A draw is lucky mode's next page: ticks stay from draw to draw under the
// same filters, and go when the filters change - or the mode, from a Search's
// pages to a draw. Each Draw ran through Search's start, which cleared them:
// only the last draw's ticks were ever downloaded.
const drawn = (n) => waitFor(`draw ${n}`, () => cards().length === 3 && cards()[0].textContent.includes(`Model ${n}1`));
draws = [[model(11), model(12), model(13)], [model(21), model(22), model(23)], [model(31), model(32), model(33)]];
tick('civitaiBrowser.feelingLucky', true);
act('civitaiBrowser.search');
await drawn(1);
check('the first draw after a Search starts with no ticks: none carries over', count(), '0 models selected');
click(2);
click(0);
act('civitaiBrowser.search');
await drawn(2);
check('the next draw, same filters: the ticks stay', count(), '2 models selected');
click(2, true);
check('a shift-click starts on this draw: only its card, not a run from the last draw\'s tick', ticked(), [false, false, true]);
click(0);
posted.length = 0;
await act('civitaiBrowser.downloadSelected');
check('pressed draw by draw, each in its order', pressed(), [11, 13, 21, 23]);

click(1);
$('cb_period').value = 'Month';
act('civitaiBrowser.search');
await drawn(3);
check('a draw under other filters starts with no ticks', count(), '0 models selected');
click(0);
tick('civitaiBrowser.feelingLucky', false);

// --------------------------------------------------------- a new search
act('civitaiBrowser.search');
await onPage(1);
check('a new search clears the ticks', count(), '0 models selected');
click(0);
await openTab('civitaiBrowser', 'showModel', 'model:4');
await waitFor('model 4 shown', () => cards().length === 1);
check('so does a model shown from another tab', count(), '0 models selected');

done();
