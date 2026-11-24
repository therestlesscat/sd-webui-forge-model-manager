// The Queue tab opened (#435): its status and lists are asked as the WebUI
// says a tab changed, not at the tab's next look, a second away at most. The
// look is a minute here, so only the signal can ask. The WebUI's own callback
// (onUiTabChange) is stood in for; that a press on the real tab reaches it is
// seen in a browser.
import { ROOT, checker, mountTab, sharedModule, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('afterbegin', '<button id="tab_queue_tab-button">Queue</button>');
const tabButton = document.getElementById('tab_queue_tab-button');
window.mmTiming = { poll: 60000 };
const callbacks = [];
globalThis.onUiTabChange = (callback) => callbacks.push(callback);

// Another of the WebUI's tabs selected - this one, or one that is not ours.
const select = (shows) => {
    tabButton.classList.toggle('selected', shows);
    for (const callback of callbacks) callback();
};

let asked = [];
let answered = 0;
let hold = null;
globalThis.fetch = async (url) => {
    const { pathname, searchParams } = new URL(String(url), 'http://webui');
    const queue = pathname.includes('/model-manager/queue/');
    if (queue) asked.push(searchParams.get('which') || pathname.split('/').pop());
    if (queue && hold) await hold;
    const which = searchParams.get('which');
    const body = pathname.includes('/asset-version') ? { success: true, version: '1' }
        : which ? { success: true, which, page: 1, pages: 1, page_size: 20, total: 0, tasks: [] }
            : { success: true, running: false, progress: null, counts: {}, notes: [] };
    if (queue) answered += 1;
    return { ok: true, status: 200, json: async () => body };
};
// Every answer here is a promise already settled: one turn drains them.
const settle = () => new Promise((resolve) => setImmediate(resolve));

await startTab('queue');
await settle();
check('hidden at the start, nothing is asked', asked, []);

const ALL = ['active', 'history', 'status'];
asked = [];
select(true);
check('opened, the status and both lists are asked at once, each once', [...asked].sort(), ALL);
await settle();

asked = [];
select(false);
await settle();
check('another tab selected, nothing is asked', asked, []);
select(false);
await settle();
check('nor as the other tabs change', asked, []);

asked = [];
select(true);
await settle();
asked = [];
select(false);
select(true);
await settle();
check('left and opened again at once, the status and both lists are asked again, each once', [...asked].sort(), ALL);

// Left while the opening's answers are still out, and opened again: once
// they are in, and while they are out - read then at the tab's next look.
let release = null;
const holding = () => { hold = new Promise((resolve) => { release = resolve; }); };
const answer = async () => { release(); hold = null; await settle(); };
const heldOpening = async () => {
    select(false);
    await settle();
    holding();
    select(true);
    await settle();
};
await heldOpening();
select(false);
await answer();
asked = [];
select(true);
await settle();
check('left while its answers were out and opened again after, the status and both lists are asked again',
      [...asked].sort(), ALL);
await heldOpening();
select(false);
select(true);
await answer();
asked = [];
for (const callback of callbacks) callback();
await settle();
check('opened again while they were out, the next look asks both lists', [...asked].sort(), ALL);

await heldOpening();
for (const callback of callbacks) callback();
await answer();
asked = [];
for (const callback of callbacks) callback();
await settle();
check('a look while one is out, the tab still showing: the next look asks the status alone', asked, ['status']);

// A WebUI without the callback: the helper is nothing, and the tab keeps its look.
const { createScope, stopTab } = await sharedModule('loading.mjs');
const given = globalThis.onUiTabChange;
delete globalThis.onUiTabChange;
let threw = null;
try { createScope('queue').tabChange(() => {}); } catch (error) { threw = String(error); }
globalThis.onUiTabChange = given;
check('a WebUI without the callback: registering does nothing, and raises nothing', threw, null);

// Switched off, in a page that goes on: the WebUI keeps the callback.
stopTab('queue');
select(false);
asked = [];
select(true);
await settle();
check('switched off, its callback asks nothing', asked, []);

// Switched off while its first answer is out: the callback comes after the stop.
const version = (await window.mmSharedVersion) || '';
const queue = await import(`file:///${ROOT}/javascript/tabs/queue.mjs${version}`);
holding();
const scope = createScope('queue');
asked = [];
const starting = queue.start(scope);
await waitFor('the first question', () => asked.length > 0, 20);
answered = 0;
scope.stop();
release();
hold = null;
await starting;
await waitFor('the answers held', () => answered > 0, 20);
select(false);
asked = [];
select(true);
await settle();
check('switched off while the first answer was out, it asks nothing after', asked, []);

done();
