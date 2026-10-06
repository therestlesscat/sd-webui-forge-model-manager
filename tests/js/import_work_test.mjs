// The shared modules start nothing when they are imported (#182). Each that
// has work - a listener, a hook, a request, a timer, an action offered -
// does it in its start(), which a tab calls for what it uses: a tab that does
// not use a module's work never starts it. They used to start it at import,
// so one tab's work ran wherever any tab did: the Queue alone asked for the
// sync's progress, through the notes, and for the downloads list, through Send.
//
// Each module is imported with every kind of work recorded, then started, then
// started again. The Queue alone, through its tab: queue_alone_test.mjs.
import { readdirSync } from 'fs';
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// ------------------------------------------------------- every kind of work
const work = [];
let current = '';
const tag = (what) => work.push([current, what]);
const path = (url) => String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
for (const [name, target] of [['document', document], ['window', window]]) {
    const real = target.addEventListener.bind(target);
    target.addEventListener = (type, fn, options) => {
        tag(`${name} listener: ${type}`);
        return real(type, fn, options);
    };
}
globalThis.onAfterUiUpdate = () => tag('onAfterUiUpdate');
globalThis.setInterval = (fn, ms) => { tag(`setInterval ${ms}`); return 0; };
const realTimeout = setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => { tag(`setTimeout ${ms}`); return realTimeout(fn, ms, ...rest); };
globalThis.MutationObserver = class { constructor() { tag('MutationObserver'); } observe() {} disconnect() {} };
globalThis.__mmOffered = new (class extends Map {
    set(key, value) { tag(`provide ${key}`); return super.set(key, value); }
})();
globalThis.fetch = async (url) => {
    tag(`fetch ${path(url)}`);
    const body = path(url) === '/model-manager/ui-options'
        ? { success: true, samplers: ['Euler a', 'DPM++ 2M'], schedulers: ['Automatic', 'Karras'] }
        : { success: true, downloads: [], notes: [] };
    return { ok: true, status: 200, json: async () => body };
};
const settle = () => new Promise((resolve) => realTimeout(resolve, 20));

// ------------------------------------------------------ nothing at import
const names = readdirSync(`${ROOT}/javascript/shared`).filter((f) => f.endsWith('.mjs')).sort();
const modules = {};
const atImport = {};
for (const name of names) {
    current = name;
    modules[name] = await sharedModule(name);
    await settle();
    atImport[name] = work.filter(([module]) => module === name).map(([, what]) => what);
}
check('no shared module does anything as it is imported',
      Object.fromEntries(Object.entries(atImport).filter(([, done]) => done.length)), {});

// ------------------------------------------------- start() does the work
// In this order: image_card and send start what they rely on running - the
// Resources dialog's actions, the chips, the samplers - before those are
// started on their own.
const STARTED = {
    'core.mjs': ['document listener: click'],
    'calls.mjs': ['document listener: change', 'document listener: click'],
    'media.mjs': ['document listener: error'],
    'ui_options.mjs': ['fetch /model-manager/ui-options', 'onAfterUiUpdate', 'onAfterUiUpdate',
                       'window listener: mm-settings-page-applied', 'window listener: mm-settings-saved'],
    'jobs.mjs': ['document listener: visibilitychange', 'provide sync.showDialog'],
    'notes.mjs': ['document listener: click', 'onAfterUiUpdate'],
    'settings.mjs': ['document listener: click', 'fetch /model-manager/settings/nsfw-levels',
                     'provide settings.open'],
    'update_notice.mjs': ['fetch /model-manager/update', 'onAfterUiUpdate', 'setInterval 3600000',
                          'window listener: mm-settings-page-applied', 'window listener: mm-settings-saved'],
    'image_card.mjs': ['provide resources.download', 'provide resources.sendAgain'],
    'send.mjs': ['onAfterUiUpdate', 'window listener: mm-resource-downloads'],
    'downloads.mjs': ['fetch /model-manager/civitai/download/progress', 'onAfterUiUpdate',
                      'provide downloads.cancel', 'provide downloads.control', 'provide downloads.dismiss',
                      'provide downloads.dismissFinished'],
    'chips.mjs': [],
    'resources.mjs': [],
    'samplers.mjs': [],
};
const started = {};
const again = {};
for (const name of Object.keys(STARTED)) {
    current = `${name} started`;
    modules[name].start?.();
    await settle();
    started[name] = work.filter(([module]) => module === current).map(([, what]) => what).sort();
    current = `${name} again`;
    modules[name].start?.();
    await settle();
    again[name] = work.filter(([module]) => module === current).map(([, what]) => what);
}
check('each start() does its own work - and image_card and send start what they rely on', started, STARTED);
check('started again, nothing more', Object.fromEntries(Object.entries(again).filter(([, done]) => done.length)), {});
check('every module with work has a start()',
      names.filter((name) => STARTED[name] && typeof modules[name].start !== 'function'), []);
check('and no other module has one',
      names.filter((name) => !STARTED[name] && typeof modules[name].start === 'function'), []);

// What the samplers do once started is read the ui-options answer: the
// scheduler at the end of an image's sampler text is told apart.
current = '';
const { splitSamplerScheduler } = modules['samplers.mjs'];
await waitFor('the samplers', () => splitSamplerScheduler('Euler a Karras').scheduler);
check('the samplers, read from ui-options once started', splitSamplerScheduler('Euler a Karras'),
      { sampler: 'Euler a', scheduler: 'Karras' });

done();
