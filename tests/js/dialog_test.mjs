// Drive the real sync dialog, through the real handlers, against the real
// markup the tab serves.
//
// The previous round of UI tests used a hand-written replica of the control
// being driven, and the replica accepted a .click() that Gradio ignores - so
// the test passed while the feature did nothing. This loads the shipped module
// and dispatches events at the shipped HTML instead.
import { mkdirSync, readFileSync } from 'fs';
import { parseHTML } from 'linkedom';

import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

// The extension, found from this file rather than from a drive letter.
const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..').replace(/\\/g, '/');
const SCRATCH = process.env.MM_SCRATCH
    || resolve(dirname(fileURLToPath(import.meta.url)), 'work');

// Taken from the tab module itself rather than from a copy: a copy goes stale
// the moment the markup changes, and then the test passes against a page that
// no longer exists.
const tabSource = readFileSync(`${ROOT}/model_manager/ui/tab_model_manager.py`, 'utf8');
const htmlMatch = tabSource.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/);
if (!htmlMatch) throw new Error('could not find the tab markup in tab_model_manager.py');
const tabHtml = htmlMatch[2];
mkdirSync(SCRATCH, { recursive: true });
const { window } = parseHTML(`<!doctype html><html><body>${tabHtml}</body></html>`);

// --- the globals the module expects the WebUI to provide ---------------------
globalThis.window = window;
globalThis.document = window.document;
globalThis.location = { origin: 'http://localhost:7860' };
window.location = globalThis.location;
globalThis.URL = URL;
globalThis.Event = window.Event;
globalThis.MouseEvent = window.MouseEvent ?? window.Event;
globalThis.CustomEvent = window.CustomEvent;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.gradioApp = () => window.document;
globalThis.onUiLoaded = (cb) => cb();
const uiUpdateHooks = [];
globalThis.onAfterUiUpdate = (cb) => uiUpdateHooks.push(cb);
globalThis.onUiUpdate = () => {};
globalThis.opts = {};
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
window.scrollTo = () => {};
window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.requestAnimationFrame = window.requestAnimationFrame;
window.localStorage = {
    _d: {}, getItem(k) { return this._d[k] ?? null; },
    setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
globalThis.localStorage = window.localStorage;

// linkedom gives <select> a `value` getter with no setter; browsers have both,
// and the dialog assigns to it to keep the chosen window selected across a
// re-render. Supply the setter the DOM spec has.
const selectProto = Object.getPrototypeOf(window.document.createElement('select'));
Object.defineProperty(selectProto, 'value', {
    configurable: true,
    get() {
        const chosen = Array.from(this.options).find((o) => o.selected);
        return chosen ? chosen.value : (this.options[0] ? this.options[0].value : '');
    },
    set(v) {
        Array.from(this.options).forEach((o) => {
            if (o.value === String(v)) o.setAttribute('selected', '');
            else o.removeAttribute('selected');
        });
    },
});

// ... and `selected` on the options themselves, for the same reason.
const optionProto = Object.getPrototypeOf(window.document.createElement('option'));
Object.defineProperty(optionProto, 'selected', {
    configurable: true,
    get() { return this.hasAttribute('selected'); },
    set(on) {
        if (on) this.setAttribute('selected', '');
        else this.removeAttribute('selected');
    },
});

// linkedom's `checked` is a plain property, so `:checked` - which the dialog
// uses to read the chosen scope - never matches, and setting one radio does
// not clear its group. Back the property with the attribute and enforce the
// group, which is what a browser does.
const inputProto = Object.getPrototypeOf(window.document.createElement('input'));
Object.defineProperty(inputProto, 'checked', {
    configurable: true,
    get() { return this.hasAttribute('checked'); },
    set(on) {
        if (on) {
            if (this.type === 'radio' && this.name) {
                this.ownerDocument
                    .querySelectorAll(`input[type="radio"][name="${this.name}"]`)
                    .forEach((other) => { if (other !== this) other.removeAttribute('checked'); });
            }
            this.setAttribute('checked', '');
        } else {
            this.removeAttribute('checked');
        }
    },
});

// --- the server, as far as the dialog is concerned --------------------------
const posts = [];
let lastEstimateQuery = null;

const ESTIMATE = {
    success: true,
    estimate: {
        versions: 747, all_versions: 747, models: 633, images: 67230,
        // As the server sends it: the checkpoint trained/merged check is its
        // own figure, counted in the total.
        requests: { metadata: 7, checkpoints: 10, images: 745, prompts: 2245, total: 3007 },
    },
    windows: [
        { label: '1 day', days: 1, versions: 0 },
        { label: '2 days', days: 2, versions: 0 },
        { label: '7 days', days: 7, versions: 412 },
        { label: '1 month', days: 30, versions: 633 },
        { label: '3 months', days: 90, versions: 633 },
        { label: '6 months', days: 180, versions: 633 },
    ],
    // The other direction: what arrived recently, rather than what is stale.
    download_windows: [
        { label: '1 day', days: 1, versions: 5 },
        { label: '2 days', days: 2, versions: 8 },
        { label: '7 days', days: 7, versions: 8 },
        { label: '1 month', days: 30, versions: 9 },
        { label: '3 months', days: 90, versions: 9 },
        { label: '6 months', days: 180, versions: 12 },
    ],
    unidentified: {
        total: 1193, identified: 747, unidentified: 446,
        asked_not_found: 5, never_asked: 441,
    },
};

// loadUIOptionsFromAPI() runs at module top level, so whether a key exists is
// fixed at import and cannot be toggled mid-run. The suite is run twice
// instead, once each way.
const hasApiKey = process.env.MM_HAS_KEY === '1';

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({
            success: true, samplers: ['Euler'], schedulers: ['Simple'],
            has_api_key: hasApiKey }) };
    }
    if (init.method === 'POST') {
        posts.push({ url: href, body: init.body });
        return { ok: true, json: async () => ({ success: true }) };
    }
    if (href.includes('/sync/progress')) {
        // Completed, so isSyncing clears and the dialog can be driven again.
        return { ok: true, json: async () => ({ success: true, progress: {
            total: 1, processed: 1, synced: 1, skipped: 0, errors: 0,
            not_found: 0, current_model: '', error_messages: [], is_complete: true,
        } }) };
    }
    if (href.includes('/sync/estimate')) {
        lastEstimateQuery = new URL(href).searchParams;
        return { ok: true, json: async () => ESTIMATE };
    }
    if (href.includes('/model-manager/models')) {
        const params = new URL(href).searchParams;
        if (params.get('paths_only')) {
            return { ok: true, json: async () => ({ success: true, models: 47,
                paths: Array.from({ length: 47 }, (_, i) => `C:/models/m${i}.safetensors`) }) };
        }
        return { ok: true, json: async () => ({
            success: true, total: 47, page: 1, page_size: 10,
            models: Array.from({ length: 10 }, (_, i) => ({
                id: i + 1, model_id: 900 + i, version_name: 'v1', base_model: 'SDXL',
                name: `model ${i}`, file_path: `C:/models/m${i}.safetensors`,
                file_name: `m${i}.safetensors`, file_size: 1e9, nsfw_level: 1,
                has_civitai_data: true, local_version_count: 1, trained_words: [],
            })),
        }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

// --- run --------------------------------------------------------------------
const fails = [];
const check = (label, got, want) => {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) fails.push(`${label}\n     got  ${JSON.stringify(got)}\n     want ${JSON.stringify(want)}`);
};
const settle = () => new Promise((r) => setTimeout(r, 300));
const closeSyncDialogFromTest = () => { $('mm_sync_dialog').style.display = 'none'; };
const $ = (id) => window.document.getElementById(id);
const click = (id) => $(id).dispatchEvent(new window.Event('click', { bubbles: true }));
const change = (el) => el.dispatchEvent(new window.Event('change', { bubbles: true }));

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
// linkedom has no readyState, so onReady() is waiting on the event rather
// than its 100ms timer. Fire it, as a browser would.
window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
await settle();

// --- the API key banner -------------------------------------------------
// Without a key most of what this extension does either crawls or fails, so
// it says so rather than looking merely slow.
// In a browser this module is a <script type="module"> in the head, so the
// answer about the key arrives before Gradio has rendered the tab. Reproduce
// that here: throw the banner away, then let init() run again. If the answer
// is only applied at fetch time it is lost, which is exactly what happened.
const bannerHome = $('mm_api_key_warning').parentNode;
const bannerNode = $('mm_api_key_warning');
bannerNode.remove();
window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
await settle();

// The markup now arrives with nothing left to trigger on: no init, no fetch,
// no event. This is the ordering that broke it in the browser - both fixed
// call sites had already run and found the other half missing.
bannerHome.insertBefore(bannerNode, bannerHome.firstChild);
bannerNode.style.display = 'none';
await new Promise((r) => setTimeout(r, 700));

if (hasApiKey) {
    check('the banner stays hidden when a key is set',
        $('mm_api_key_warning').style.display, 'none');
} else {
    check('the banner is shown when there is no key',
        $('mm_api_key_warning').style.display, 'flex');

    // Gradio redraws a gr.HTML block wholesale and the inline style goes with
    // it. The banner has to come back when the UI is rebuilt, not just once.
    check('the module asked to be told about redraws', uiUpdateHooks.length > 0, true);
    $('mm_api_key_warning').style.display = 'none';        // as a redraw leaves it
    uiUpdateHooks.forEach((cb) => cb());
    check('and puts itself back afterwards',
        $('mm_api_key_warning').style.display, 'flex');
    const bannerText = $('mm_api_key_warning').textContent;
    check('it says what is missing', bannerText.includes('No Civitai API key'), true);
    check('and exactly where to set it',
        bannerText.includes('Settings') && bannerText.includes('Model Manager')
        && bannerText.includes('Civitai API Key'), true);
    check('and what it costs', /0\.5 per second|image prompts/.test(bannerText), true);
}

// the three long buttons are gone, replaced by one
check('old metadata buttons are gone',
    [!!$('mm_sync_meta_btn'), !!$('mm_sync_meta_images_btn')], [false, false]);
check('dialog starts hidden', $('mm_sync_dialog').style.display, 'none');

click('mm_sync_btn');
await settle();
check('the button opens the dialog', $('mm_sync_dialog').style.display, 'flex');

// The metadata checkbox is the only one with no id: it is never read, only
// shown ticked and unticked-able.
check('metadata is compulsory', $('mm_sync_dialog')
    .querySelector('input[type="checkbox"][disabled]:not([id])').checked, true);
check('prompts wait on images', $('mm_sync_prompts').disabled, true);
// A locked box must not sit there ticked, or it claims something will happen
// that cannot.
check('and are unticked while they cannot happen', $('mm_sync_prompts').checked, false);
check('and are visibly muted', $('mm_sync_prompts_row').className.includes('mm-dialog-muted'), true);
check('force sync is a scope, not a depth option',
    [$('mm_sync_rehash'), $('mm_sync_force_row')], [null, null]);

// Requests, not minutes - the count is the same on every machine, the
// duration is not.
check('the estimate counts requests, approximately while it includes prompts',
    $('mm_sync_estimate').textContent, '747 models - ~3,007 requests to Civitai');
check('and says nothing about time',
    /\bmin\b|\bhours?\b|\bs\b|req\/s/.test($('mm_sync_estimate').textContent), false);
check('each line carries its own count, metadata with the checkpoint check in it, '
      + 'and the prompt estimate marked as one',
    [$('mm_cost_metadata').textContent, $('mm_cost_images').textContent,
     $('mm_cost_prompts').textContent],
    ['17 req', '745 req', '~2,245 req']);
// What was wrong: the total counted the checkpoint check and no line did, so
// the lines on screen came to 10 less than the total beneath them.
const shown = (text) => Number((text.match(/[\d,]+/) || ['0'])[0].replace(/,/g, ''));
check('so the lines on screen add up to the total on screen',
    ['mm_cost_metadata', 'mm_cost_images', 'mm_cost_prompts']
        .reduce((sum, id) => sum + shown($(id).textContent), 0),
    shown($('mm_sync_estimate').textContent.split(' - ')[1]));
check('windows carry their counts',
    Array.from($('mm_sync_stale_days').options).map((o) => o.textContent),
    ['1 day (0)', '2 days (0)', '7 days (412)', '1 month (633)', '3 months (633)', '6 months (633)']);
check('the download windows carry their own, different counts',
    Array.from($('mm_sync_downloaded_days').options).map((o) => o.textContent),
    ['1 day (5)', '2 days (8)', '7 days (8)', '1 month (9)', '3 months (9)', '6 months (12)']);
check('all-models count is shown', $('mm_scope_all').textContent, '(747)');

// Nothing has been searched yet, so there are no results to scope to.
const resultsRadioEarly = window.document.querySelector('input[name="mm_sync_scope"][value="results"]');
check('the results scope is disabled before a search', resultsRadioEarly.disabled, true);
check('and is visibly muted',
    resultsRadioEarly.closest('.mm-dialog-option').className.includes('mm-dialog-muted'), true);
check('and carries no count', $('mm_scope_results').textContent, '');

// asking for images unlocks the prompts beneath them
$('mm_sync_images').checked = true;
change($('mm_sync_images'));
await settle();
check('images unlock prompts', $('mm_sync_prompts').disabled, false);
check('and tick them, since that is the useful default', $('mm_sync_prompts').checked, true);

// Unticking prompts must stick - the dependency rule runs on every change and
// must not keep re-ticking it.
$('mm_sync_prompts').checked = false;
change($('mm_sync_prompts'));
await settle();
check('unticking prompts sticks', $('mm_sync_prompts').checked, false);
check('and is sent as such', lastEstimateQuery.get('include_prompts'), 'false');

// Images off again: prompts go with them, unticked as well as locked.
$('mm_sync_images').checked = false;
change($('mm_sync_images'));
await settle();
check('prompts lock again with images', $('mm_sync_prompts').disabled, true);
check('and untick', $('mm_sync_prompts').checked, false);

$('mm_sync_images').checked = true;
change($('mm_sync_images'));
await settle();
check('turning images back on offers prompts again', $('mm_sync_prompts').checked, true);
check('and the request says so',
    [lastEstimateQuery.get('include_images'), lastEstimateQuery.get('include_prompts')],
    ['true', 'true']);

// Force sync is a scope, not a depth: it names which files to read.
const imagesBefore = $('mm_sync_images').checked;
const forceRadio = window.document.querySelector('input[name="mm_sync_scope"][value="force"]');
check('the modes carry their counts',
    Array.from($('mm_sync_force_mode').options).map((o) => o.textContent),
    ['All (1,193*)', 'All identified (747*)', 'All unidentified (446*)']);

forceRadio.checked = true;
change(forceRadio);
await settle();
check('it is costed in files, not requests',
    $('mm_sync_estimate').textContent.startsWith('446 files* to read in full'), true);
check('and says why they are unmatched',
    $('mm_sync_estimate').textContent.includes('441 never asked about')
    && $('mm_sync_estimate').textContent.includes('5 asked before and not on Civitai'), true);
check('and warns it scans the folders too',
    $('mm_sync_estimate').textContent.includes('not in the database yet'), true);
check('and claims no duration',
    /hours|minutes/.test($('mm_sync_estimate').textContent), false);

// identifying fetches everything, so the depth is not a choice meanwhile
check('every depth option is on', [$('mm_sync_images').checked, $('mm_sync_prompts').checked],
    [true, true]);
check('and locked', [$('mm_sync_images').disabled, $('mm_sync_prompts').disabled], [true, true]);

$('mm_sync_force_mode').value = 'all';
change($('mm_sync_force_mode'));
await settle();
check('All re-costs it as every file',
    $('mm_sync_estimate').textContent.startsWith('1,193 files* to read in full'), true);

$('mm_sync_force_mode').value = 'identified';
change($('mm_sync_force_mode'));
await settle();
check('All identified costs the matched ones',
    $('mm_sync_estimate').textContent.startsWith('747 files* to read in full'), true);
check('choosing a mode picks the scope',
    window.document.querySelector('input[name="mm_sync_scope"]:checked').value, 'force');

// Start sends the mode to the hashing endpoint, not the metadata one
click('mm_sync_dialog_start');
await settle();
check('a force sync posts to the identifying endpoint',
    posts[posts.length - 1].url, '/model-manager/sync');
const forceBody = new URLSearchParams(posts[posts.length - 1].body);
check('with the chosen mode', forceBody.get('targets'), 'identified');
check('and forces', forceBody.get('force'), 'true');
posts.length = 0;

// wait out the progress poll, so the run is finished and the dialog usable
await new Promise((r) => setTimeout(r, 1300));
check('the sync releases when it completes', $('mm_sync_btn').disabled, false);

click('mm_sync_btn');
await settle();
const allRadio = window.document.querySelector('input[name="mm_sync_scope"][value="all"]');
allRadio.checked = true;
change(allRadio);
await settle();
// Images is usable again; prompts follow images, as they always do.
check('leaving the scope unlocks the depth',
    [$('mm_sync_images').disabled, $('mm_sync_prompts').disabled],
    [false, !imagesBefore]);
check('and restores what was chosen before', $('mm_sync_images').checked, imagesBefore);

// the download scope runs the other way, and the two never both apply
$('mm_sync_downloaded_days').value = '2';
change($('mm_sync_downloaded_days'));
await settle();
check('choosing a download window picks that scope',
    window.document.querySelector('input[name="mm_sync_scope"]:checked').value, 'downloaded');
check('the download window is sent', lastEstimateQuery.get('downloaded_days'), '2');
check('and the staleness window is not', lastEstimateQuery.get('stale_days'), '0');

$('mm_sync_stale_days').value = '30';
change($('mm_sync_stale_days'));
await settle();
check('switching back sends staleness again', lastEstimateQuery.get('stale_days'), '30');
check('and drops the download window', lastEstimateQuery.get('downloaded_days'), '0');

// run a search, then reopen: the scope is offered, and already counted
closeSyncDialogFromTest();
click('mm_load_btn');
await settle();
click('mm_sync_btn');
await settle();

const resultsRadio = window.document.querySelector('input[name="mm_sync_scope"][value="results"]');
check('a search enables the results scope', resultsRadio.disabled, false);
check('and unmutes it',
    resultsRadio.closest('.mm-dialog-option').className.includes('mm-dialog-muted'), false);
check('and counts it without being picked', $('mm_scope_results').textContent, '(47)');

resultsRadio.checked = true;
change(resultsRadio);
await settle();
check('and passes them to the estimate',
    lastEstimateQuery.get('paths').split(',').length, 47);

// Start sends exactly what was chosen
click('mm_sync_dialog_start');
await settle();
check('dialog closes on start', $('mm_sync_dialog').style.display, 'none');
check('one request was posted', posts.length, 1);
const body = new URLSearchParams(posts[0].body);
check('posted to the metadata sync', posts[0].url, '/model-manager/sync/metadata');
check('with images', body.get('include_images'), 'true');
check('with prompts', body.get('include_prompts'), 'true');
check('with the 47 paths', body.get('paths').split(',').length, 47);
check('and no window, since the scope is results', body.get('stale_days'), '0');
check('nor a download window', body.get('downloaded_days'), '0');

// --- Scan Disk asks first ---------------------------------------------------
// It adds and removes rows to match the disk, which is not something to find
// out afterwards.
// The metadata sync above is still running as far as the page is concerned,
// and Scan Disk is disabled while one is. Let its progress poll finish.
await new Promise((r) => setTimeout(r, 1300));
check('the scan button is available again', $('mm_refresh_btn').disabled, false);

posts.length = 0;
check('the scan dialog starts hidden', $('mm_scan_dialog').style.display, 'none');

click('mm_refresh_btn');
await settle();
check('the button opens it rather than scanning', $('mm_scan_dialog').style.display, 'flex');
check('and nothing has been posted yet', posts.length, 0);

const scanText = $('mm_scan_dialog').textContent;
for (const said of ['Adds models you have added', 'Removes models you have deleted',
                    'Does not contact Civitai']) {
    check('it says: ' + said, scanText.includes(said), true);
}

click('mm_scan_dialog_cancel');
await settle();
check('Cancel closes it', $('mm_scan_dialog').style.display, 'none');
check('and still nothing was posted', posts.length, 0);

click('mm_refresh_btn');
await settle();
click('mm_scan_dialog_start');
await settle();
check('Scan closes it', $('mm_scan_dialog').style.display, 'none');
check('and starts the scan', posts.length, 1);
check('against the scan endpoint', posts[0].url, '/model-manager/scan');

console.log(fails.length ? fails.map((f) => 'FAIL ' + f).join('\n') : 'All dialog checks passed.');
process.exit(fails.length ? 1 : 0);
