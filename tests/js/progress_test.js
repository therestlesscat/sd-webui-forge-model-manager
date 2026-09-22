// The metadata sync must drive the shared progress bar the same way the full
// sync does: a repeating poll that stops itself on completion and releases the
// buttons. A single poll would freeze the bar and leave the UI disabled.
const fs = require('fs');
const vm = require('vm');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/model_manager.mjs', 'utf8');

let failures = 0;
const check = (label, cond, extra) => {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
};

// --- static: both start paths must arm an interval, not poll once -----------
function body(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    let i = src.indexOf('{', src.indexOf(')', m.index));
    const start = i;
    let depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return src.slice(start, i + 1);
}

for (const fn of ['startSync', 'startMetadataSync']) {
    const b = body(fn);
    check(fn + ' arms a repeating poll',
          /syncPollInterval = setInterval\(pollSyncProgress, \d+\)/.test(b), b.slice(0, 200));
    check(fn + ' does not poll just once',
          !/^\s*pollSyncProgress\(\);\s*$/m.test(b), 'bare pollSyncProgress() found');
    check(fn + ' releases the UI when the request fails',
          /isSyncing = false;[\s\S]{0,60}updateSyncUI\(false\)/.test(b));
}

// --- dynamic: run the real poll loop against a scripted progress feed -------
const samples = [
    { total: 745, processed: 0, synced: 0, skipped: 0, errors: 0, not_found: 0,
      current_model: 'Fetching 631 models from Civitai...', is_complete: false, error_messages: [] },
    { total: 745, processed: 300, synced: 298, skipped: 0, errors: 0, not_found: 2,
      current_model: 'foo.safetensors', is_complete: false, error_messages: [] },
    { total: 745, processed: 745, synced: 740, skipped: 0, errors: 1, not_found: 4,
      current_model: '', is_complete: true, error_messages: ['bar.safetensors: boom'] },
];

let polls = 0;
const els = {
    mm_sync_fill: { style: {} },
    mm_sync_text: { textContent: '' },
};
const timers = new Map();
let nextTimer = 1;

const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    document: { getElementById: (id) => els[id] ?? null, querySelectorAll: () => [] },
    setInterval: (fn, ms) => { const id = nextTimer++; timers.set(id, fn); return id; },
    clearInterval: (id) => { timers.delete(id); },
    apiCall: async () => ({ success: true, progress: samples[Math.min(polls++, samples.length - 1)] }),
    setStatus: (msg) => { sandbox._status = msg; },
    updateSyncUI: (on) => { sandbox._uiSyncing = on; },
    loadModels: () => { sandbox._reloaded = true; },
    setTimeout: (fn) => { fn(); return 0; },
    syncPollInterval: null,
    isSyncing: true,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext('(' + body('pollSyncProgress').replace(/^\{/, 'async function poll() {') + ')', sandbox);
const poll = vm.runInContext(
    '(async function poll() ' + body('pollSyncProgress') + ')', sandbox);

(async () => {
    // Arm the interval exactly as startMetadataSync now does.
    sandbox.syncPollInterval = sandbox.setInterval(poll, 1000);
    check('an interval is registered', timers.size === 1);

    await poll();
    check('first sample shows the fetch phase',
          els.mm_sync_text.textContent.includes('0/745')
          && els.mm_sync_text.textContent.includes('Fetching'), els.mm_sync_text.textContent);
    check('bar starts at 0%', els.mm_sync_fill.style.width === '0%', els.mm_sync_fill.style.width);
    check('still polling', timers.size === 1);
    check('UI still marked busy', sandbox._uiSyncing !== false);

    await poll();
    check('mid-run percentage', els.mm_sync_fill.style.width.startsWith('40.2'),
          els.mm_sync_fill.style.width);
    check('mid-run counts', sandbox._status.includes('298 synced'), sandbox._status);
    check('still polling mid-run', timers.size === 1);

    await poll();
    check('bar reaches 100%', els.mm_sync_fill.style.width === '100%', els.mm_sync_fill.style.width);
    check('interval is cleared on completion', timers.size === 0);
    check('isSyncing released', sandbox.isSyncing === false);
    check('buttons re-enabled', sandbox._uiSyncing === false);
    check('final status reports the error', sandbox._status.includes('boom'), sandbox._status);
    check('grid reloaded after a successful run', sandbox._reloaded === true);

    // An empty run (nothing linked) must still finish cleanly, not divide by zero.
    polls = 0;
    samples.length = 0;
    samples.push({ total: 0, processed: 0, synced: 0, skipped: 0, errors: 0, not_found: 0,
                   current_model: '', is_complete: true, error_messages: [] });
    sandbox.isSyncing = true;
    sandbox.syncPollInterval = sandbox.setInterval(poll, 1000);
    await poll();
    check('zero-total run does not produce NaN', !els.mm_sync_fill.style.width.includes('NaN'),
          els.mm_sync_fill.style.width);
    check('zero-total run still completes', sandbox.isSyncing === false);

    console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
    process.exit(failures ? 1 : 0);
})();
