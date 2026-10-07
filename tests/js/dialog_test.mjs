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
import { startTab, tabMarkup } from './harness.mjs';

// The extension, found from this file rather than from a drive letter.
const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..').replace(/\\/g, '/');
const SCRATCH = process.env.MM_SCRATCH
    || resolve(dirname(fileURLToPath(import.meta.url)), 'work');

// Taken from the tab module itself rather than from a copy: a copy goes stale
// the moment the markup changes, and then the test passes against a page that
// no longer exists.
const tabHtml = tabMarkup('model_manager/ui/tab_model_manager.py');
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
        // Both ways of refetching the images (#103): the first page each, or
        // as many as each has - and what the first would delete.
        image_options: { page: 100, first: { requests: 745, prompts: 2245, images: 67230 },
                         kept: { requests: 1187, prompts: 2539, images: 76050 },
                         deletes: { images: 8820, models: 40 } },
    },
    // A force sync's, over the files it would read.
    force_images: { page: 100, first: { requests: 1193, prompts: 0, images: 0 },
                    kept: { requests: 1635, prompts: 0, images: 0 },
                    deletes: { images: 8820, models: 40 } },
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

// Two files in another type's folder, one of whose names is taken in its own.
const MISPLACED = [
    { path: 'C:/models/Stable-diffusion/ae.safetensors', to: 'C:/models/VAE/ae.safetensors',
      file_type: 'VAE', identified_by: 'Flux VAE', clash: null },
    { path: 'C:/models/Lora/neg.pt', to: 'C:/models/embeddings/neg.pt',
      file_type: 'TextualInversion', identified_by: '', clash: 'same' },
];

// What every sync will read in full, as /sync/new-files counts it: none, until
// the Files section is looked at.
const NEW_FILES = { success: true, files: 0, bytes: 0 };
// What the walk every sync starts with did, added to the progress at its end.
const WALKED = {};
// Polls answered before the finished one: a sync still walking, with no total.
const POLLS = [];
// The console's lines the next poll hands the log panel, and how it was asked.
const LOG = [];
const logAsked = [];

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
        const since = new URL(href, 'http://x').searchParams.get('since');
        if (since !== null) logAsked.push(since);
        const log = since !== null ? { log: LOG.splice(0), log_next: 99 } : {};
        if (POLLS.length) {
            return { ok: true, json: async () => ({ success: true, progress: POLLS.shift(), ...log }) };
        }
        // Completed, so isSyncing clears and the dialog can be driven again.
        return { ok: true, json: async () => ({ success: true, progress: {
            total: 1, processed: 1, synced: 1, skipped: 0, errors: 0,
            not_found: 0, current_model: '', error_messages: [], is_complete: true, ...WALKED,
        }, ...log }) };
    }
    if (href.includes('/sync/new-files')) {
        return { ok: true, json: async () => ({ ...NEW_FILES }) };
    }
    if (href.includes('/sync/misplaced')) {
        return { ok: true, json: async () => ({ success: true, files: MISPLACED }) };
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
const settle = () => new Promise((r) => setTimeout(r, 50));
/** Wait for what a step is waiting on, rather than for a fixed time. */
async function until(what, predicate, ms = 3000) {
    for (const start = Date.now(); Date.now() - start < ms;) {
        if (predicate()) return;
        await new Promise((r) => setTimeout(r, 20));
    }
    fails.push(`timed out waiting for ${what}`);
}
const closeSyncDialogFromTest = () => { $('mm_sync_dialog').style.display = 'none'; };
const $ = (id) => window.document.getElementById(id);
const click = (id) => $(id).dispatchEvent(new window.Event('click', { bubbles: true }));
const change = (el) => el.dispatchEvent(new window.Event('change', { bubbles: true }));

// Every status the page shows, in order. The grid reloads half a second after
// a sync ends and says so in the same line, and a check that read the line
// after a busy moment read that instead.
const statusSeen = [];
{
    const status = $('mm_status');
    let proto = Object.getPrototypeOf(status);
    while (proto && !Object.prototype.hasOwnProperty.call(proto, 'textContent')) proto = Object.getPrototypeOf(proto);
    const own = Object.getOwnPropertyDescriptor(proto, 'textContent');
    Object.defineProperty(status, 'textContent', {
        configurable: true,
        get() { return own.get.call(this); },
        set(value) { statusSeen.push(String(value)); own.set.call(this, value); },
    });
}
/** The last status a sync's end set: "Sync complete: ..." or "Sync cancelled: ...". */
const syncEnd = () => [...statusSeen].reverse().find((text) => /^Sync (complete|cancelled): /.test(text)) || '';

// The page's waits and polls, shortened: the fake server answers at once,
// and the same order of events happens ten times faster. See TIMING.
window.mmTiming = { poll: 100, presetSettle: 60, presetQuiet: 40, presetMax: 3000, estimate: 10 };
// Forge's refresh buttons (#193): the checkpoint and VAE / text encoder
// lists', and the extra networks' hidden one - LoRAs, embeddings.
const refreshed = [];
for (const [id, name] of [['forge_refresh_checkpoint', 'checkpoints'], ['txt2img_lora_extra_refresh_internal', 'extra networks']]) {
    const button = document.createElement('button');
    button.id = id;
    button.addEventListener('click', () => refreshed.push(name));
    document.body.appendChild(button);
}

await startTab('modelManager');
const { showSyncDialog } = await import(`file:///${ROOT}/javascript/shared/jobs.mjs`);
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
await new Promise((r) => setTimeout(r, 150));

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
    const link = $('mm_api_key_warning').querySelector('.mm-banner-link');
    check('and exactly where to set it: a link opening the settings window there',
        [bannerText.includes('Set one in the settings, under Civitai connection'), link?.dataset.action,
         link?.dataset.section],
        [true, 'settings.open', 'connection']);
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
// duration is not. Waited for, not settled: the estimate is asked again once
// the count of new files has come, and a fixed wait read "Estimating..." once.
await until('the estimate', () => $('mm_sync_estimate').textContent.includes(' - '));
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

// How many images come back (#103): as many as each model has, by default -
// nothing deleted - or the first page, which deletes what was stored past it.
const countChoice = (value) => window.document.querySelector(`input[name="mm_sync_images_count"][value="${value}"]`);
const notice = () => $('mm_sync_images_notice');
check('images offer two ways, each with its cost, as many as each has chosen',
    [$('mm_sync_images_count').hidden, countChoice('kept').checked,
     $('mm_cost_images_kept').textContent, $('mm_sync_images_first_label').textContent,
     $('mm_cost_images_first').textContent],
    [false, true, '1,187 req', 'First 100 images per model', '745 req']);
check('and the estimate is asked for that way', lastEstimateQuery.get('keep_image_count'), 'true');
check('the notice above the buttons says the images may not be these',
    [notice().hidden, notice().textContent.includes('won\'t necessarily be the ones you have now'),
     notice().textContent.includes('deletes')], [false, true, false]);
countChoice('first').checked = true;
change(countChoice('first'));
await settle();
check('the first page says what it deletes, and that they can still be seen',
    [notice().textContent.includes('This deletes 8,820 stored images from your library'),
     notice().textContent.includes('40 models hold more than 100'),
     notice().textContent.includes('Load More fetches them from Civitai again'),
     notice().textContent.includes('won\'t necessarily be the ones you have now')],
    [true, true, true, true]);
check('and is asked for so', lastEstimateQuery.get('keep_image_count'), 'false');
countChoice('kept').checked = true;
change(countChoice('kept'));
await settle();

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
check('but how many images come back is still a choice, costed over the files',
    [$('mm_sync_images_count').hidden, countChoice('kept').disabled, countChoice('first').disabled,
     $('mm_cost_images_kept').textContent, $('mm_cost_images_first').textContent, notice().hidden],
    [false, false, false, '1,635 req', '1,193 req', false]);
check('asked for with the mode', lastEstimateQuery.get('force_mode'), 'unidentified');

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
check('and how many images come back', forceBody.get('keep_image_count'), 'true');
check('and forces', forceBody.get('force'), 'true');
posts.length = 0;

// wait out the progress poll, so the run is finished and the dialog usable
await until('the sync to finish', () => $('mm_sync_btn').disabled === false);
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
check('as many images as each has', body.get('keep_image_count'), 'true');
check('with the 47 paths', body.get('paths').split(',').length, 47);
check('and no window, since the scope is results', body.get('stale_days'), '0');
check('nor a download window', body.get('downloaded_days'), '0');
check('nor anything the walk does besides', [body.get('reread_headers'), body.get('move_misplaced')],
      ['false', 'false']);

// --- the Files section: what the walk every sync starts with does besides -----
await until('the metadata sync to finish', () => $('mm_sync_btn').disabled === false);
posts.length = 0;
NEW_FILES.files = 12;
NEW_FILES.bytes = 3 * 1073741824;
click('mm_sync_btn');
await settle();
await settle();
check('both boxes start unticked, the move one usable once its list has come',
      [$('mm_sync_reread').checked, $('mm_sync_move').checked, $('mm_sync_move').disabled], [false, false, false]);
check('the box counts the files it can move',
      $('mm_sync_move_label').textContent, 'Move files into their type\'s folder (1)');
check('the estimate says what every sync will read in full, whatever its scope',
      $('mm_sync_estimate').textContent.endsWith('Also 12 new files to read in full (3.00 GB) and look up on Civitai.'),
      true);
$('mm_sync_reread').checked = true;
$('mm_sync_move').checked = true;
change($('mm_sync_move'));
click('mm_sync_dialog_start');
await settle();
const walkBody = new URLSearchParams(posts[0]?.body || '');
check('Start sends both boxes', [walkBody.get('reread_headers'), walkBody.get('move_misplaced')], ['true', 'true']);
check('every sync so far changed no file, whatever was ticked: Forge\'s lists not refreshed', refreshed, []);
WALKED.added = 2;
WALKED.removed = 1;
WALKED.moved = 1;
await until('that sync to finish', () => $('mm_sync_btn').disabled === false);
check('one that added, forgot or moved files refreshes Forge\'s lists, once', refreshed, ['checkpoints', 'extra networks']);
refreshed.length = 0;
check('the status says what the walk did to the library',
      syncEnd().includes(", 2 new on disk, 1 gone from disk, 1 moved into their type's folder, 0 errors"),
      true);
for (const key of Object.keys(WALKED)) delete WALKED[key];

posts.length = 0;
click('mm_sync_btn');
await settle();
check('the next time the dialog opens, both are unticked again',
      [$('mm_sync_reread').checked, $('mm_sync_move').checked], [false, false]);
forceRadio.checked = true;
change(forceRadio);
await settle();
$('mm_sync_reread').checked = true;
click('mm_sync_dialog_start');
await settle();
const forceWalk = new URLSearchParams(posts[0]?.body || '');
check('a force sync sends them too',
      [posts[0]?.url, forceWalk.get('reread_headers'), forceWalk.get('move_misplaced')],
      ['/model-manager/sync', 'true', 'false']);
await until('the force sync to finish', () => $('mm_sync_btn').disabled === false);
NEW_FILES.files = 0;
NEW_FILES.bytes = 0;

// --- while the walk runs ----------------------------------------------------
// Every sync walks the library before it has a total: the bar said "0/0".
POLLS.push({ total: 0, processed: 0, synced: 0, skipped: 0, errors: 0, not_found: 0,
             current_model: 'Reading your model folders: 120/1576', error_messages: [], is_complete: false });
click('mm_sync_btn');
await settle();
click('mm_sync_dialog_start');
await until('the walk to be shown', () => $('mm_sync_text').textContent.startsWith('Reading'));
check('while the sync has no total, the bar says what the walk is doing, and no "0/0"',
      $('mm_sync_text').textContent, 'Reading your model folders: 120/1576');
await until('that sync to finish too', () => $('mm_sync_btn').disabled === false);
posts.length = 0;

// --- the log, in place of the grid -----------------------------------------
// Every line the extension writes to the console while the sync runs.
LOG.push({ n: 1, time: '20:01:02', text: 'Reading your model folders: 1576/1576' },
         { n: 2, time: '20:01:09', text: 'Found Crystal ball via SHA256: 05194B21F56532AC...' },
         { n: 3, time: '20:01:12', text: 'Error calculating hashes for broken.safetensors: no such file' },
         { n: 4, time: '20:01:13', text: 'Warning: the full model was not fetched' });
const RUNNING = { total: 10, processed: 3, synced: 2, skipped: 0, errors: 0, not_found: 1,
                  current_model: 'next.safetensors', error_messages: [], is_complete: false };
POLLS.push({ ...RUNNING }, { ...RUNNING, cancelling: true, processed: 4 },
           { ...RUNNING, cancelling: true, processed: 4 });
// How the sync will end, set before it starts: the closing poll can come as
// soon as the queue above runs out.
WALKED.cancelled = true;
logAsked.length = 0;
click('mm_sync_btn');
await settle();
click('mm_sync_dialog_start');
await until('the log\'s lines', () => $('mm_sync_log_lines').childElementCount === 4);
check('a sync opens its log in place of the grid and its tabs',
      [$('mm_sync_log').hidden, $('model_manager_app').classList.contains('mm-log-open')], [false, true]);
const logRows = () => Array.from($('mm_sync_log_lines').children);
check('each line with its time, the prefix gone',
      logRows().map((row) => [row.querySelector('.mm-sync-log-time').textContent, row.querySelector('.mm-sync-log-text').textContent]),
      [['20:01:02', 'Reading your model folders: 1576/1576'],
       ['20:01:09', 'Found Crystal ball via SHA256: 05194B21F56532AC...'],
       ['20:01:12', 'Error calculating hashes for broken.safetensors: no such file'],
       ['20:01:13', 'Warning: the full model was not fetched']]);
check('an error in red, a warning in amber, the rest as they are',
      logRows().map((row) => row.className),
      ['mm-sync-log-line', 'mm-sync-log-line', 'mm-sync-log-line mm-sync-log-error', 'mm-sync-log-line mm-sync-log-warn']);

// Cancel: said on the button, the status line and the bar, until it is done.
click('mm_sync_cancel_btn');
await settle();
check('Cancel, once pressed, says it is cancelling and cannot be pressed again',
      [$('mm_sync_cancel_btn').textContent, $('mm_sync_cancel_btn').disabled], ['Cancelling...', true]);
check('and asks the server', posts.some((post) => post.url === '/model-manager/sync/cancel'), true);
await until('the poll to say it is cancelling', () => $('mm_sync_text').textContent.startsWith('Cancelling'));
check('the log was asked from where the sync began, then from where each poll ended',
      logAsked.slice(0, 2), ['-1', '99']);
check('the bar says what it is waiting for', $('mm_sync_text').textContent,
      'Cancelling: 4/10 done - finishing what is in progress');
check('and so does the status line', $('mm_status').textContent,
      'Cancelling the sync: no new file starts, the ones in progress finish first - 2 synced so far');
await until('that sync to stop', () => $('mm_sync_btn').disabled === false);
check('it ends as cancelled, not complete', syncEnd().slice(0, 16), 'Sync cancelled: ');
delete WALKED.cancelled;
check('the log stays once the sync has ended', $('mm_sync_log').hidden, false);

click('mm_sync_log_hide');
check('Hide brings the grid back, and a Log button to return to it',
      [$('mm_sync_log').hidden, $('model_manager_app').classList.contains('mm-log-open'), $('mm_sync_log_btn').style.display],
      [true, false, '']);
click('mm_sync_log_btn');
check('Log shows it again', [$('mm_sync_log').hidden, $('mm_sync_log_btn').style.display], [false, 'none']);

posts.length = 0;
click('mm_sync_btn');
await settle();
click('mm_sync_dialog_start');
await settle();
check('a new sync starts a log of its own', $('mm_sync_log_lines').childElementCount, 0);
check('and a Cancel that can be pressed', [$('mm_sync_cancel_btn').textContent, $('mm_sync_cancel_btn').disabled],
      ['Cancel', false]);
await until('the new sync to finish', () => $('mm_sync_btn').disabled === false);
click('mm_sync_log_hide');
posts.length = 0;

// --- Moving files into their type's folder (#54) ------------------------------
// Said before it is ticked, never ticked for anyone. Scan Disk's dialog did
// this until every sync came to walk the library (0.48).
check('there is no Scan Disk: no button, no dialog', [$('mm_refresh_btn'), $('mm_scan_dialog')], [null, null]);
posts.length = 0;
click('mm_sync_btn');
await settle();
await settle();
check('the box says how many files it can move - not the one whose name is taken in its folder',
      $('mm_sync_move_label').textContent, 'Move files into their type\'s folder (1)');
check('its box can be ticked, and is not', [$('mm_sync_move').disabled, $('mm_sync_move').checked], [false, false]);
check('unticked, it says nothing more: no paragraph, no list',
      [$('mm_sync_move_note').hidden, $('mm_sync_misplaced').hidden], [true, true]);
$('mm_sync_move').checked = true;
change($('mm_sync_move'));
check('ticked, it says what moving does, and that one will stay',
      [$('mm_sync_move_note').hidden, $('mm_sync_move_note').textContent.startsWith('2 files are in a folder for another type'),
       $('mm_sync_move_note').textContent.includes('1 will stay where it is')], [false, true, true]);
check('and lists them, each with where it goes and why',
      [$('mm_sync_misplaced').hidden,
       Array.from($('mm_sync_misplaced_list').querySelectorAll('li')).map((li) => li.textContent.replace(/\s+/g, ' ').trim())],
      [false, ['C:/models/Stable-diffusion/ae.safetensors → C:/models/VAE/ae.safetensors (VAE: Flux VAE)',
               'C:/models/Lora/neg.pt → C:/models/embeddings/neg.pt (TextualInversion) - stays: the same file is already there']]);
$('mm_sync_move').checked = false;
change($('mm_sync_move'));
check('unticked again, both go', [$('mm_sync_move_note').hidden, $('mm_sync_misplaced').hidden], [true, true]);
click('mm_sync_dialog_cancel');
await settle();
showSyncDialog({ rereadHeaders: true });
await settle();
check('a note\'s button ticks "Read every file\'s header again", never the move',
      [$('mm_sync_dialog').style.display, $('mm_sync_reread').checked, $('mm_sync_move').checked], ['flex', true, false]);
click('mm_sync_dialog_cancel');
MISPLACED.length = 0;
click('mm_sync_btn');
await settle();
await settle();
check('with nothing to move, the box says none, cannot be ticked, and says nothing more',
      [$('mm_sync_move_label').textContent, $('mm_sync_move').disabled, $('mm_sync_move_note').hidden,
       $('mm_sync_misplaced').hidden],
      ['Move files into their type\'s folder (0)', true, true, true]);
click('mm_sync_dialog_cancel');
MISPLACED.push({ path: 'C:/models/Lora/taken.pt', to: 'C:/models/embeddings/taken.pt',
                 file_type: 'TextualInversion', identified_by: '', clash: 'different' });
click('mm_sync_btn');
await settle();
await settle();
check('nor when every file\'s name is taken in its folder',
      [$('mm_sync_move_label').textContent, $('mm_sync_move').disabled], ['Move files into their type\'s folder (0)', true]);
MISPLACED.length = 0;
click('mm_sync_dialog_cancel');
check('and nothing was posted', posts.length, 0);

console.log(fails.length ? fails.map((f) => 'FAIL ' + f).join('\n') : 'All dialog checks passed.');
process.exit(fails.length ? 1 : 0);
