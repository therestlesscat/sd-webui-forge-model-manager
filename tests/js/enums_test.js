// Drive fillSelect / typeRows / sortBaseModels / TYPE_LABELS out of civitai_browser.js
// against the real /enums payload, using a stub that mimics <select> semantics.
const fs = require('fs');
const vm = require('vm');
const { execSync } = require('child_process');

const path = require('path');

// The extension, found from this file rather than from a drive letter, so the
// suite runs wherever the repository happens to be checked out.
const REPO = path.resolve(__dirname, '..', '..').replace(/\\/g, '/');
const src = fs.readFileSync(REPO + '/javascript/tabs/civitai_browser.mjs', 'utf8');

// --- a <select> that behaves like the real thing -----------------------------
class Option {
    constructor(value = '', label = '') { this.value = value; this._text = label; }
    set textContent(v) { this._text = String(v); }
    get textContent() { return this._text; }
}

class Select {
    constructor(html) {
        // Parse the static markup the page ships with.
        this._options = [...html.matchAll(/<option value="([^"]*)"[^>]*>([\s\S]*?)<\/option>/g)]
            .map(m => new Option(m[1], m[2]));
        this._value = this._options[0]?.value ?? '';
    }
    set innerHTML(html) {
        if (html !== '') throw new Error('stub only supports clearing via innerHTML');
        this._options = [];
    }
    appendChild(option) { this._options.push(option); return option; }
    querySelector(sel) {
        const m = /^option\[value="(.*)"\]$/.exec(sel);
        return this._options.find(o => o.value === m[1]) ?? null;
    }
    // Real selects drop an assignment that matches no option: value -> '',
    // selectedIndex -> -1.
    set value(v) { this._value = this._options.some(o => o.value === v) ? v : ''; }
    get value() { return this._value; }
    get selectedIndex() { return this._options.findIndex(o => o.value === this._value); }
    get labels() { return this._options.map(o => o.textContent); }
    get values() { return this._options.map(o => o.value); }
}

// --- sandbox ----------------------------------------------------------------
const selects = {};
const sandbox = {
    console: { log() {}, warn() {} },
    document: {
        getElementById: id => selects[id] ?? null,
        createElement: tag => {
            if (tag === 'option') return new Option();
            const el = { _t: '' };
            Object.defineProperty(el, 'textContent', { set(v) { el._t = String(v); }, get() { return el._t; } });
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

function lift(name) {
    const m = src.match(new RegExp('^[ \\t]*(async )?function ' + name + '\\s*\\(', 'm'));
    const isAsync = !!m[1];
    let i = src.indexOf('(', m.index + m[0].length - 1), depth = 0;
    for (;; i++) { if (src[i] === '(') depth++; else if (src[i] === ')' && --depth === 0) break; }
    i = src.indexOf('{', i);
    const start = i;
    depth = 0;
    for (;; i++) { if (src[i] === '{') depth++; else if (src[i] === '}' && --depth === 0) break; }
    return vm.runInContext('(' + (isAsync ? 'async ' : '') + 'function' + src.slice(src.indexOf('(', m.index), start) + src.slice(start, i + 1) + ')', sandbox);
}

// TYPE_LABELS is a const in the IIFE; lift it by evaluating its literal.
const labelsLiteral = /const TYPE_LABELS = (\{[\s\S]*?\});/.exec(src)[1];
const TYPE_LABELS = vm.runInContext('(' + labelsLiteral + ')', sandbox);
sandbox.makeOption = lift('makeOption');  // fillSelect calls it as a free variable
const fillSelect = lift('fillSelect');
// Type is a list of checkboxes since #341: its rows are worked out apart from drawing them.
sandbox.TYPE_LABELS = TYPE_LABELS;
sandbox.CIVITAI_LORA_KINDS = vm.runInContext('(' + /const CIVITAI_LORA_KINDS = (\[[^\]]*\]);/.exec(src)[1] + ')', sandbox);
const typeRows = lift('typeRows');
const sortBaseModels = lift('sortBaseModels');

// --- real payload -----------------------------------------------------------
const raw = execSync('curl -s --max-time 30 https://civitai.com/api/v1/enums', { encoding: 'buffer' });
const enums = JSON.parse(raw.toString('utf8'));
const modelTypes = enums.ModelType;
const baseModels = enums.ActiveBaseModel;

let failures = 0;
function check(label, cond, extra) {
    if (!cond) { failures++; console.log('FAIL ' + label + (extra ? '\n  ' + extra : '')); }
}

// The static markup that ships in the page today.
const STATIC_BASE = '<option value="">All</option><option value="SD 1.5">SD 1.5</option>'
    + '<option value="SDXL 1.0 LCM">SDXL 1.0 LCM</option><option value="Other">Other</option>';

// 1. Type's rows: one per type Civitai lists, in its order, relabelled, its kinds of LoRA marked.
const rows = typeRows(modelTypes);
const rowValues = rows.map(r => r.value);
check('a row for every type Civitai lists', JSON.stringify(rowValues) === JSON.stringify(modelTypes),
      'got ' + rowValues.length + ' of ' + modelTypes.length);
check('TextualInversion relabelled', rows.find(r => r.value === 'TextualInversion')?.label === 'Embedding');
check('LORA relabelled', rows.find(r => r.value === 'LORA')?.label === 'LoRA');
check('DoRA among them', rowValues.includes('DoRA'));
check('Civitai still lists every kind of LoRA the setting combines',
      sandbox.CIVITAI_LORA_KINDS.every(kind => rowValues.includes(kind)), sandbox.CIVITAI_LORA_KINDS.join());
check('and those alone are marked as kinds of LoRA',
      JSON.stringify(rows.filter(r => r.lora).map(r => r.value)) === JSON.stringify(sandbox.CIVITAI_LORA_KINDS));

// 2. Base model dropdown: sorted, Other last, retired value dropped -> "All".
selects.cb_base_model = new Select(STATIC_BASE);
selects.cb_base_model.value = 'SDXL 1.0 LCM';  // in BaseModel but NOT in ActiveBaseModel
check('cb_base fills', fillSelect('cb_base_model', sortBaseModels(baseModels)));
const bvals = selects.cb_base_model.values;
check('cb_base keeps All first', bvals[0] === '');
check('cb_base Other last', bvals[bvals.length - 1] === 'Other', bvals.slice(-3).join(' | '));
const middle = bvals.slice(1, -1);
const sorted = [...middle].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
check('cb_base alphabetical', JSON.stringify(middle) === JSON.stringify(sorted));
check('cb_base drops retired selection', selects.cb_base_model.value === '',
      'value=' + JSON.stringify(selects.cb_base_model.value));
check('cb_base has Flux.2 D', bvals.includes('Flux.2 D'));
check('cb_base has Pony V7', bvals.includes('Pony V7'));

// 3. A selection Civitai still offers must survive.
selects.cb_base_model = new Select(STATIC_BASE);
selects.cb_base_model.value = 'SD 1.5';
fillSelect('cb_base_model', sortBaseModels(baseModels));
check('cb_base keeps live selection', selects.cb_base_model.value === 'SD 1.5', selects.cb_base_model.value);

// 4. Empty payload and a missing element must leave things untouched.
selects.cb_base_model = new Select(STATIC_BASE);
selects.cb_base_model.value = 'SD 1.5';
check('empty payload is a no-op', fillSelect('cb_base_model', []) === false);
check('empty payload keeps markup', selects.cb_base_model.values.includes('SDXL 1.0 LCM'));
check('missing element is a no-op', fillSelect('cb_nonexistent', modelTypes) === false);

// 5. A name with quotes/ampersands is carried verbatim, with no markup to break.
selects.cb_base_model = new Select(STATIC_BASE);
const nasty = 'A "quoted" <name> & more';
fillSelect('cb_base_model', [nasty], v => v);
check('exotic value kept verbatim', selects.cb_base_model.values[1] === nasty, selects.cb_base_model.values[1]);
check('exotic label kept verbatim', selects.cb_base_model.labels[1] === nasty, selects.cb_base_model.labels[1]);
selects.cb_base_model.value = nasty;
check('exotic value selectable', selects.cb_base_model.value === nasty);
check('and as a type row, its value and label as they are', JSON.stringify(typeRows([nasty])[0])
      === JSON.stringify({ value: nasty, label: nasty, lora: false }));

// 6. sortBaseModels leaves a list without "Other" alone in length.
check('sortBaseModels without Other', sortBaseModels(['b', 'a']).join(',') === 'a,b');
check('sortBaseModels keeps every value',
      sortBaseModels(baseModels).length === baseModels.length);

// --- 7. loadEnums: one request per page load, retries only re-fill ----------
(async () => {
    let calls = 0;
    sandbox.apiCall = () => { calls++; return Promise.resolve({
        success: true, model_types: modelTypes, base_models: baseModels }); };
    sandbox.enumsLoaded = false;
    sandbox.enumsRequest = null;
    sandbox.fillSelect = fillSelect;
    // Type's rows are drawn only once its list is there, as the select was filled.
    let typeRowsFilled = null;
    sandbox.fillTypeRows = (values) => {
        if (!selects.cb_type || !values.length) return false;
        typeRowsFilled = values;
        return true;
    };
    sandbox.sortBaseModels = sortBaseModels;
    sandbox.fetchEnums = lift('fetchEnums');
    sandbox.syncCheckpointTypeEnabled = () => {};  // exercised by three_js_test.js
    const loadEnums = lift('loadEnums');

    // Tab not built yet: the selects are missing, so filling must fail...
    delete selects.cb_type; delete selects.cb_base_model;
    check('loadEnums fails while tab is unbuilt', (await loadEnums()) === false);
    check('...but the request was already made', calls === 1, 'calls=' + calls);

    // ...and the retry must succeed without asking Civitai again.
    selects.cb_type = {};
    selects.cb_base_model = new Select(STATIC_BASE);
    check('loadEnums succeeds once the tab exists', (await loadEnums()) === true);
    check('no second request', calls === 1, 'calls=' + calls);
    check('type rows filled with every type', typeRowsFilled?.length === modelTypes.length);

    // Already loaded: short-circuits.
    check('loadEnums is idempotent', (await loadEnums()) === true);
    check('still one request', calls === 1, 'calls=' + calls);

    // A failing endpoint leaves the static options alone and is not retried.
    sandbox.enumsLoaded = false; sandbox.enumsRequest = null;
    let failCalls = 0;
    sandbox.apiCall = () => { failCalls++; return Promise.reject(new Error('offline')); };
    selects.cb_base_model = new Select(STATIC_BASE);
    check('loadEnums reports failure', (await loadEnums()) === false);
    check('retry does not re-request', (await loadEnums()) === false && failCalls === 1,
          'failCalls=' + failCalls);
    check('static options survive failure', selects.cb_base_model.values.includes('SDXL 1.0 LCM'));

    console.log(failures === 0 ? 'All checks passed.' : failures + ' check(s) failed.');
    process.exit(failures ? 1 : 0);
})();
