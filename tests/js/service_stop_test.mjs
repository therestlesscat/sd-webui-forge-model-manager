// Every part of the page stops with the last tab that uses it (#186). A tab
// switched off stopped its own work (#183), and the shared services it had
// started ran on: with the Model Manager off, the sync's progress was asked
// whenever the page came back into view, and a sync's poll ran until the sync
// ended; with both download tabs off, the downloads list polled on; with
// every tab off, the page's actions, the notes, the settings window and the
// update notice stayed. Here the four tabs run, then go off one at a time -
// the Model Manager, the Civitai Browser, Generations, the Queue - and after
// each, nothing is left of what only stopped tabs used: no listener on the
// document or the window, no timer, no action, no request. What the tabs
// still running use runs on.
import { bootPage, checker, mountTab, tabMarkup, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
for (const file of ['tab_civitai_browser.py', 'tab_generations.py', 'tab_queue.py']) {
    document.body.insertAdjacentHTML('beforeend', tabMarkup(`model_manager/ui/${file}`));
}
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected" aria-selected="true">txt2img</button>
        <button id="tab_queue_tab-button">Queue</button>
        <button id="tab_generations_tab-button">Generations</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
    </div>`);
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
const { check, waitFor, done } = checker();

// ------------------------------------------------- whose work is whose
// The extension's file that asked, read from the call's stack: past the
// loading module, whose scopes do the adding for the tabs and the services.
const OURS = /\/javascript\/((?:shared|tabs)\/\w+\.mjs)/;
function owner() {
    const files = (new Error().stack || '').split('\n').map((line) => line.match(OURS)?.[1]).filter(Boolean);
    return files.find((file) => file !== 'shared/loading.mjs') || files[0] || null;
}

const listening = new Set();
const capture = (options) => Boolean(typeof options === 'object' ? options?.capture : options);
for (const [name, target] of [['document', document], ['window', window]]) {
    const add = target.addEventListener.bind(target);
    const remove = target.removeEventListener.bind(target);
    target.addEventListener = (type, listener, options) => {
        const by = owner();
        const record = { name, type, listener, capture: capture(options), by };
        if (by) listening.add(record);
        // One that runs once is gone once it has, with no removeEventListener.
        if (by && options?.once) add(type, () => listening.delete(record), { once: true });
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
const timers = new Map();           // id -> who set it, while it can still run
const real = { setInterval, clearInterval, setTimeout, clearTimeout };
globalThis.setInterval = (fn, ms, ...rest) => {
    const id = real.setInterval(fn, ms, ...rest);
    const by = owner();
    if (by) timers.set(id, `${by} every ${ms}`);
    return id;
};
globalThis.clearInterval = (id) => { timers.delete(id); real.clearInterval(id); };
globalThis.setTimeout = (fn, ms, ...rest) => {
    const by = owner();
    const id = real.setTimeout((...args) => { timers.delete(id); fn(...args); }, ms, ...rest);
    if (by) timers.set(id, `${by} after ${ms}`);
    return id;
};
globalThis.clearTimeout = (id) => { timers.delete(id); real.clearTimeout(id); };
const hooks = [];
globalThis.onAfterUiUpdate = (fn) => hooks.push(fn);

// A sync running, and a download: each polls while its tab is there.
const asked = [];
const path = (url) => String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
globalThis.fetch = async (url) => {
    asked.push(path(url));
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    switch (path(url)) {
    case '/model-manager/ui-options':
        return reply({ success: true, samplers: [], schedulers: [],
                       tabs: tabsAnswer({ queue: true, generations: true, model_manager: true, civitai_browser: true }) });
    case '/model-manager/sync/progress':
        return reply({ success: true, log: [], log_next: 0,
                       progress: { is_complete: false, processed: 1, total: 5, synced: 0, current_model: 'a' } });
    case '/model-manager/civitai/download/progress':
        return reply({ success: true, downloads: [{ version_id: 7, model_id: 3, status: 'downloading',
                                                    progress: 10, file_name: 'a.safetensors' }] });
    default:
        return reply({ success: true, notes: [], models: [], tasks: [], total: 0, page: 1, pages: 1, counts: {},
                       tiles: [], more: false, state: {}, running: false });
    }
};

// ------------------------------------------------------------- the steps
const offered = () => [...(globalThis.__mmOffered?.keys() || [])];
const actionsOf = (...prefixes) => offered().filter((name) => prefixes.some((p) => name.startsWith(p))).sort();
const workOf = (...files) => [
    ...[...listening].filter((l) => files.includes(l.by)).map((l) => `${l.by}: ${l.name} ${l.type}`),
    ...[...timers.values()].filter((t) => files.some((file) => t.startsWith(`${file} `))),
].sort();
const off = (setting) => window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: {
    changed: [setting], settings: { [setting]: { value: false } } } }));
const pollTime = () => new Promise((resolve) => real.setTimeout(resolve, 1300));
/** What is asked from now on, while the page comes into view, is clicked and updated. */
async function askedAfter() {
    asked.length = 0;
    document.dispatchEvent(new window.Event('visibilitychange'));
    document.body.dispatchEvent(new window.Event('click', { bubbles: true }));
    hooks.forEach((hook) => hook());
    await pollTime();
    return [...new Set(asked)].sort();
}

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the four tabs to start', () => ['modelManager.', 'civitaiBrowser.', 'generations.', 'queue.']
    .every((prefix) => offered().some((name) => name.startsWith(prefix))));
await waitFor('the sync and the downloads to poll', () => workOf('shared/jobs.mjs').some((w) => w.includes('every'))
    && workOf('shared/downloads.mjs').some((w) => w.includes('every')));
check('running: the sync and the downloads list poll, the services offer their actions',
      [actionsOf('downloads.', 'resources.', 'settings.').length > 0,
       workOf('shared/jobs.mjs').some((w) => w.includes('visibilitychange'))], [true, true]);

// ------------------------------------------------------ the Model Manager
off('model_manager_model_manager_enabled');
check('the Model Manager off: nothing left of it, or of the sync it alone used',
      [actionsOf('modelManager.'), workOf('tabs/model_manager.mjs', 'shared/jobs.mjs')], [[], []]);
check('the page back in view asks nothing of the sync',
      (await askedAfter()).filter((p) => p.startsWith('/model-manager/sync')), []);
check('the downloads list runs on, for the Civitai Browser',
      [actionsOf('downloads.').length, workOf('shared/downloads.mjs').some((w) => w.includes('every'))], [4, true]);

// ----------------------------------------------------- the Civitai Browser
off('model_manager_civitai_browser_enabled');
check('the Civitai Browser off: nothing left of it, or of the downloads list',
      [actionsOf('civitaiBrowser.', 'downloads.'),
       workOf('tabs/civitai_browser.mjs', 'shared/downloads.mjs', 'shared/image_card.mjs')], [[], []]);
check('nothing asked of the downloads', (await askedAfter()).filter((p) => p.includes('/download')), []);
check('Send\'s Resources dialog runs on, for Generations and the Queue', actionsOf('resources.').length, 2);

// ----------------------------------------------------------- Generations
off('model_manager_record_generations');
check('Generations off: nothing left of it, or of the media fallback',
      [actionsOf('generations.'), workOf('tabs/generations.mjs', 'shared/media.mjs')], [[], []]);
check('the settings window runs on, for the Queue', actionsOf('settings.'), ['settings.open']);

// ------------------------------------------------------------- the Queue
off('model_manager_queue_enabled');
check('every tab off: no action offered', offered(), []);
const everyone = [...new Set([...listening].map((l) => l.by)
    .concat([...timers.values()].map((t) => t.split(' ')[0])))].filter((by) => by !== 'shared/loading.mjs');
check('no listener or timer of any tab or service: only the loading module\'s own', workOf(...everyone), []);
check('and nothing asked, in view, clicked or updated', await askedAfter(), []);

done();
