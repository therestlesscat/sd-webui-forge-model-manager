// A tab stopped mid-session leaves nothing behind (#183). Switched off, a tab
// used to stay as it was, hidden: the Queue went on polling its status every
// second, its listener on Generate went on asking before a large batch, and
// its actions stayed offered. Now what a tab adds outside its own markup goes
// through its scope (shared/loading.mjs), which takes it all back.
//
// The Queue's shared modules are started first, for the suite: what they do
// is theirs, and stops with the last tab that uses them (service_stop_test.mjs). From then on, every listener
// on the document or the window, interval, after-update hook and action is
// the tab's. The switch that stops it, in the page: queue_switch_test.mjs.
import { ROOT, checker, mountTab, sharedModule, startServices, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs"><button id="tab_queue_tab-button" class="selected" aria-selected="true">Queue</button></div>`);

const asked = [];
globalThis.fetch = async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    return { ok: true, status: 200, json: async () => ({ success: true, notes: [], tasks: [], total: 0, page: 1,
                                                          pages: 1, running: false, counts: {} }) };
};

// What the Queue tab uses, started first: importing its script does nothing.
const { STARTS } = await import(`file:///${ROOT}/javascript/tabs/queue.mjs`);
await startServices(...STARTS);

// From here on, everything added is the tab's.
const listening = new Set();
const capture = (options) => Boolean(typeof options === 'object' ? options?.capture : options);
for (const [name, target] of [['document', document], ['window', window]]) {
    const add = target.addEventListener.bind(target);
    const remove = target.removeEventListener.bind(target);
    target.addEventListener = (type, listener, options) => {
        listening.add({ name, type, listener, capture: capture(options) });
        return add(type, listener, options);
    };
    target.removeEventListener = (type, listener, options) => {
        for (const l of listening) {
            if (l.name === name && l.type === type && l.listener === listener && l.capture === capture(options)) {
                listening.delete(l);
            }
        }
        return remove(type, listener, options);
    };
}
const intervals = new Set();
const realSetInterval = setInterval;
const realClearInterval = clearInterval;
globalThis.setInterval = (fn, ms) => {
    const id = realSetInterval(fn, ms);
    intervals.add(id);
    return id;
};
globalThis.clearInterval = (id) => {
    intervals.delete(id);
    realClearInterval(id);
};
const hooks = [];
globalThis.onAfterUiUpdate = (fn) => hooks.push(fn);
const offered = () => [...globalThis.__mmOffered.keys()].filter((name) => name.startsWith('queue.')).length;

await startTab('queue');
await waitFor('the Queue tab to poll', () => intervals.size > 0);
const started = { listeners: [...listening].map((l) => `${l.name} ${l.type}`).sort(), intervals: intervals.size,
                  actions: offered() };
check('started, the tab listens, polls and offers its actions',
      [started.listeners.length > 0, started.intervals, started.actions > 0], [true, 1, true]);

const { stopTab } = await sharedModule('loading.mjs');
stopTab('queue');
check('stopped: every listener it added is gone', [...listening].map((l) => `${l.name} ${l.type}`), []);
check('its poll is cleared', intervals.size, 0);
check('none of its actions is offered', offered(), 0);

// And nothing of it runs after: the WebUI's after-update callbacks run, a
// poll's time passes, Generate is pressed.
asked.length = 0;
hooks.forEach((hook) => hook());
document.dispatchEvent(new window.Event('click', { bubbles: true }));
await new Promise((resolve) => setTimeout(resolve, 1300));
check('nothing of it runs after: it asks the server nothing in a poll\'s time',
      asked.filter((path) => path.startsWith('/model-manager/queue')), []);

done();
