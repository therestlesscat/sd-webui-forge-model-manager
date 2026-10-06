// paidAccessLabel / isPaid / getFilters / syncCheckpointTypeEnabled
const fs = require('fs');
const vm = require('vm');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/tabs/civitai_browser.mjs', 'utf8');

// --- DOM stubs --------------------------------------------------------------
const els = {};
function makeSelect(value, group) {
    return {
        value, disabled: false, title: '',
        _group: group,
        closest: () => group,
        addEventListener() {},
    };
}
function makeGroup() {
    const classes = new Set();
    return {
        classList: {
            toggle: (name, on) => { on ? classes.add(name) : classes.delete(name); },
            has: name => classes.has(name),
        },
        _classes: classes,
    };
}

const sandbox = {
    console: { log() {}, warn() {} },
    document: {
        getElementById: id => els[id] ?? null,
        createElement: () => {
            const el = { _t: '' };
            Object.defineProperty(el, 'textContent', { set(v) { el._t = String(v); }, get: () => el._t });
            Object.defineProperty(el, 'innerHTML', {
                get: () => el._t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
            });
            return el;
        },
    },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(require('./shared_script.cjs')(), sandbox);
sandbox.escapeHtml = sandbox.escapeHtml;
// The browser reads dates as the shared formatDay does.
sandbox.formatDate = sandbox.formatDay;
sandbox.selectedTag = '';

function lift(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    if (!m) throw new Error('not found: ' + name);
    const isAsync = !!m[1];
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i;
    depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(' + (isAsync ? 'async ' : '') + 'function'
        + src.slice(src.indexOf('(', m.index), start) + src.slice(start, i + 1) + ')', sandbox);
}

let failures = 0;
function check(label, cond, extra) {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
}

// Shared with the Model Manager, so they live in javascript/shared/.
const { paidAccessLabel, isPaid } = sandbox;

// --- paidAccessLabel / isPaid -----------------------------------------------
check('free -> no label', paidAccessLabel({}) === '');
check('free -> not paid', isPaid({}) === false);
check('undefined version safe', paidAccessLabel(undefined) === '' && isPaid(undefined) === false);
check('null paid_access', paidAccessLabel({ paid_access: null }) === '');

check('permanent label',
      paidAccessLabel({ paid_access: { permanent: true, ends_at: null } }) === 'Paid');
const ea = paidAccessLabel({ paid_access: { permanent: false, ends_at: '2026-10-02T21:30:26.576Z' } });
check('early access label', /^Early Access until \w+ \d+, 2026$/.test(ea), ea);
check('early access, no date',
      paidAccessLabel({ paid_access: { permanent: false, ends_at: null } }) === 'Early Access');
check('permanent beats date',
      paidAccessLabel({ paid_access: { permanent: true, ends_at: '2026-10-02T00:00:00Z' } }) === 'Paid');
check('isPaid true for both',
      isPaid({ paid_access: { permanent: true } }) && isPaid({ paid_access: { permanent: false, ends_at: 'x' } }));

// --- getFilters: checkpoint_type only for checkpoints ------------------------
// getFilters reads the size boxes through sizeBound, which filters.mjs, loaded above, has.
sandbox.feelingLucky = lift('feelingLucky');       // which asks whether a draw is on
sandbox.sfwOnlyEnabled = lift('sfwOnlyEnabled');   // and the SFW box through this
const getFilters = lift('getFilters');
const group = makeGroup();
els.cb_search = { value: 'anime' };
els.cb_type = makeSelect('Checkpoint', group);
els.cb_checkpoint_type = makeSelect('Merge', group);
els.cb_base_model = { value: 'SDXL 1.0' };
els.cb_sort = { value: 'Most Downloaded' };
els.cb_period = { value: 'AllTime' };
els.cb_nsfw = { checked: false };
els.cb_require_prompt = { checked: false };

let f = getFilters();
check('checkpoint_type sent for Checkpoint', f.checkpoint_type === 'Merge', JSON.stringify(f));
check('types still sent', f.types === 'Checkpoint');

els.cb_type.value = 'LORA';
f = getFilters();
check('checkpoint_type dropped for LORA', f.checkpoint_type === '', JSON.stringify(f));

els.cb_type.value = '';
f = getFilters();
check('checkpoint_type dropped for All types', f.checkpoint_type === '');

els.cb_type.value = 'Checkpoint';
els.cb_checkpoint_type.value = '';
f = getFilters();
check('empty checkpoint_type stays empty', f.checkpoint_type === '');

// Missing element must not throw (Gradio builds the tab lazily).
delete els.cb_checkpoint_type;
f = getFilters();
check('missing control is safe', f.checkpoint_type === '');
els.cb_checkpoint_type = makeSelect('Merge', group);

// --- syncCheckpointTypeEnabled ----------------------------------------------
// Shared with the Model Manager (shared/filters.mjs), loaded above with the rest.
const sync = () => vm.runInContext("syncCheckpointType('cb')", sandbox);
els.cb_type.value = 'Checkpoint';
sync();
check('enabled for Checkpoint', els.cb_checkpoint_type.disabled === false);
check('no dimming class', !group._classes.has('filter-disabled'));
check('helpful title', /trained checkpoints/.test(els.cb_checkpoint_type.title), els.cb_checkpoint_type.title);

els.cb_type.value = 'LORA';
sync();
check('disabled for LORA', els.cb_checkpoint_type.disabled === true);
check('dimming class applied', group._classes.has('filter-disabled'));
check('explains why', /Only applies/.test(els.cb_checkpoint_type.title), els.cb_checkpoint_type.title);

els.cb_type.value = 'Checkpoint';
sync();
check('re-enabled', els.cb_checkpoint_type.disabled === false && !group._classes.has('filter-disabled'));

delete els.cb_checkpoint_type;
sync();  // must not throw
check('sync tolerates missing control', true);

console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
process.exit(failures ? 1 : 0);
