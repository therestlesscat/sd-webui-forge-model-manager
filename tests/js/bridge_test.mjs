// Jumping from one tab to the other, through the real modules.
//
// The Civitai Browser could only ever be asked to *search*, so "show me this
// exact model" had nowhere to go. It now reads model:<id>, the same shape the
// Model Manager's search takes, and answers it from the model endpoint rather
// than from a text search - Civitai has no way to search for a known id.
//
// The risk here is the routing: a targeted query that quietly falls through to
// the ordinary search looks like it works and returns the wrong models. So
// this checks which endpoint was asked, not just what came back.
import { readFileSync } from 'fs';
import { parseHTML } from 'linkedom';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..').replace(/\\/g, '/');

// The shipped markup, not a replica of it.
const tabSource = readFileSync(`${ROOT}/model_manager/ui/tab_civitai_browser.py`, 'utf8');
const htmlMatch = tabSource.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/);
if (!htmlMatch) throw new Error('could not find the tab markup in tab_civitai_browser.py');
const { window } = parseHTML(`<!doctype html><html><body>${htmlMatch[2]}</body></html>`);

globalThis.window = window;
globalThis.document = window.document;
globalThis.location = { origin: 'http://localhost:7860' };
window.location = globalThis.location;
globalThis.URL = URL;
globalThis.Event = window.Event;
globalThis.MouseEvent = window.MouseEvent ?? window.Event;
globalThis.CustomEvent = window.CustomEvent;
globalThis.DOMParser = window.DOMParser;   // descriptions are sanitized with it
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.gradioApp = () => window.document;
globalThis.onUiLoaded = (cb) => cb();
globalThis.onAfterUiUpdate = () => {};
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

// linkedom leaves these as plain properties, so the module's reads of
// select.value and input.checked never see what it set.
const selectProto = Object.getPrototypeOf(window.document.createElement('select'));
Object.defineProperty(selectProto, 'value', {
    configurable: true,
    get() {
        const chosen = Array.from(this.options).find((o) => o.hasAttribute('selected'));
        return chosen ? chosen.value : (this.options[0] ? this.options[0].value : '');
    },
    set(v) {
        Array.from(this.options).forEach((o) => {
            if (o.value === String(v)) o.setAttribute('selected', '');
            else o.removeAttribute('selected');
        });
    },
});
const inputProto = Object.getPrototypeOf(window.document.createElement('input'));
Object.defineProperty(inputProto, 'checked', {
    configurable: true,
    get() { return this.hasAttribute('checked'); },
    set(on) { if (on) this.setAttribute('checked', ''); else this.removeAttribute('checked'); },
});

// --- Civitai, as far as the browser is concerned ----------------------------
const asked = [];

function remoteModel(id) {
    return {
        id, name: `Remote ${id}`, type: 'LORA', description: '<p>d</p>',
        tags: ['t'], nsfw: false, nsfwLevel: 1, stats: { downloadCount: 5 },
        creator: { username: 'someone' },
        owned_locally: false, owned_versions: [],
        modelVersions: [{
            id: id * 2, name: 'v1', baseModel: 'SDXL 1.0', images: [],
            paid_access: null, owned_locally: false,
            files: [{ id: 1, name: 'm.safetensors', primary: true, sizeKB: 1024 }],
        }],
    };
}

// The images a version's gallery answers with. Empty until the last check,
// which needs something for the prompt filter to act on.
let galleryImages = [];

globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    if (href.includes('/model-manager/civitai/models/404404')) {
        return { ok: true, json: async () => ({ success: false, error: 'Model not found' }) };
    }
    const single = href.match(/\/model-manager\/civitai\/models\/(\d+)/);
    if (single) {
        return { ok: true, json: async () => ({ success: true, model: remoteModel(Number(single[1])) }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({
            success: true, models: [remoteModel(1), remoteModel(2)],
            nextCursor: null, pageSize: 10, cardWidth: 200, cardHeight: 280,
        }) };
    }
    if (href.includes('/versions/') || href.includes('/images')) {
        return { ok: true, json: async () => ({ success: true, images: galleryImages, next_cursor: null }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

// --- run --------------------------------------------------------------------
const fails = [];
const check = (label, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) {
        fails.push(`${label}\n     got  ${JSON.stringify(got)}\n     want ${JSON.stringify(want)}`);
    }
};
const settle = () => new Promise((r) => setTimeout(r, 300));
const $ = (id) => window.document.getElementById(id);
const singleLookups = () => asked.filter((u) => /\/civitai\/models\/\d+/.test(u));
const searches = () => asked.filter((u) => /\/civitai\/models\?/.test(u));

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
await settle();

check('the tab exposes the hop the other tab calls',
      typeof window.cbShowModel, 'function');

// ------------------------------------------------------- a targeted lookup
asked.length = 0;
await window.cbShowModel('model:12345');
await settle();

check('the query lands in the search box', $('cb_search').value, 'model:12345');
check('it goes to the model endpoint', singleLookups().length, 1);
check('naming the model asked for',
      (singleLookups()[0] || '').includes('/civitai/models/12345'), true);
check('and never to the search endpoint', searches().length, 0);
check('one card is shown',
      $('cb_grid').querySelectorAll('.model-card').length, 1);

// ----------------------------------------------------- an ordinary search
asked.length = 0;
$('cb_search').value = 'anime';
await window.cbSearch();
await settle();

check('a plain query searches', searches().length >= 1, true);
check('and asks for no model by id', singleLookups().length, 0);
check('returning what Civitai listed',
      $('cb_grid').querySelectorAll('.model-card').length, 2);

// ------------------------------------------------ what is not a lookup
for (const query of ['model:', 'model:abc', 'a model:12', 'version:99', '12345']) {
    asked.length = 0;
    $('cb_search').value = query;
    await window.cbSearch();
    await settle();
    check(`"${query}" is a search, not a lookup`, singleLookups().length, 0);
}

// Whitespace and case are the shapes a person types.
for (const query of ['model: 77', ' MODEL:77 ']) {
    asked.length = 0;
    await window.cbShowModel(query);
    await settle();
    check(`"${query}" is still a lookup`, singleLookups().length, 1);
}

// ------------------------------------------------------- a model that is gone
asked.length = 0;
await window.cbShowModel('model:404404');
await settle();
check('a model Civitai no longer has shows nothing',
      $('cb_grid').querySelectorAll('.model-card').length, 0);
check('and says so rather than failing silently',
      $('cb_status').textContent.includes('404404'), true);

// ------------------------------------------ the prompt filter, in a gallery
// hasUsablePrompt() moved into the shared module and this tab's import of it
// was never added, so with "Only with usable prompts" ticked every gallery
// render threw ReferenceError. The module checker looks at calls, and this is
// a function passed by name to filter(), which is why it got through.
galleryImages = [
    { id: 11, url: 'https://example.invalid/11.jpeg', browsingLevel: 1,
      meta: { prompt: 'a prompt long enough', steps: 20, sampler: 'Euler', cfgScale: 7 } },
    { id: 12, url: 'https://example.invalid/12.jpeg', browsingLevel: 1, meta: null },
];
await window.cbShowModel('model:12345');
await settle();
$('cb_require_prompt').checked = true;
let renderError = null;
try {
    window.cbToggleShowAllImages(true);
} catch (e) {
    renderError = e.message;
}
check('the prompt filter can render a gallery', renderError, null);
check('keeping only the image with a prompt to reuse',
      $('cb_images').querySelectorAll('.mm-image-card').length, 1);

// One banner, one sentence, a switch per filter on its right. The prompt
// switch is a per-model override that leaves the search's own filter alone.
const banners = () => document.querySelectorAll('#cb_images .cb-nsfw-warning');
const sentence = () => (banners()[0]?.querySelector('span')?.textContent || '').trim();
const switchLabel = (id) => (document.querySelector(`#cb_images .cb-nsfw-warning #${id}`)
    ?.closest('label')?.textContent || '').replace(/\s+/g, ' ').trim() || null;
const PROMPT = 'cb_show_promptless_images';
const NSFW = 'cb_show_all_images';

check('the banner carries the prompt switch', switchLabel(PROMPT), 'Show unusable prompts (1)');
check('and its sentence says what the prompt filter hides', sentence(),
      'Showing 1 of 2 images (1 hidden due to unusable prompt)');

window.cbToggleShowPromptless?.(true);
check('ticking it shows the images without a prompt',
      $('cb_images').querySelectorAll('.mm-image-card').length, 2);
check('and the switch is still there to turn back, saying how many it shows',
      switchLabel(PROMPT), 'Show unusable prompts (1)');
check('with nothing hidden the sentence says so', sentence(), 'Showing all 2 images');
check("without touching the search's own filter", $('cb_require_prompt').checked, true);

window.cbToggleShowPromptless?.(false);
check('unticking hides them again',
      $('cb_images').querySelectorAll('.mm-image-card').length, 1);

// --------------------------------------------- the NSFW switch, in the banner
// It sits on the right of the banner, as in the Model Manager, rather than in
// the list's header. The banner is up whenever something is hidden and stays
// up while everything is shown, so the switch can always be turned back.
galleryImages = [
    { id: 21, url: 'https://example.invalid/21.jpeg', browsingLevel: 1,
      meta: { prompt: 'a prompt long enough', steps: 20, sampler: 'Euler', cfgScale: 7 } },
    { id: 22, url: 'https://example.invalid/22.jpeg', browsingLevel: 8,
      meta: { prompt: 'a prompt long enough', steps: 20, sampler: 'Euler', cfgScale: 7 } },
];
await window.cbShowModel('model:12345');
await settle();
const switchIn = (where) => document.querySelectorAll(`${where} #cb_show_all_images`).length;

window.cbToggleShowAllImages(false);
check('the NSFW switch sits in the banner', switchIn('.cb-nsfw-warning'), 1);
check('not in the list header', switchIn('.mm-images-header'), 0);
check('and there is one of it, though the sentence repeats below the list',
      document.querySelectorAll('#cb_show_all_images').length, 1);
check('beside a count of what it is holding back', switchLabel(NSFW), 'Show NSFW (1)');
check('which the sentence states too', sentence(),
      'Showing 1 of 2 images (1 hidden due to NSFW filter)');

window.cbToggleShowAllImages(true);
check('with everything shown the switch is still there to turn back',
      switchIn('.cb-nsfw-warning'), 1);
check('saying how many NSFW it shows', switchLabel(NSFW), 'Show NSFW (1)');
check('and the sentence says nothing is hidden', sentence(), 'Showing all 2 images');

// ------------------------------------------- what the numbers count
// One banner for both filters. The hidden figures and what is shown add up
// to the total, so an image both would hide is counted once, by the NSFW
// filter, which applies first. An unticked switch states its clause's number;
// a ticked one, how many of its kind it now shows.
galleryImages = [
    { id: 31, url: 'https://example.invalid/31.jpeg', browsingLevel: 1,
      meta: { prompt: 'a prompt long enough', steps: 20, sampler: 'Euler', cfgScale: 7 } },
    { id: 32, url: 'https://example.invalid/32.jpeg', browsingLevel: 1, meta: null },
    { id: 33, url: 'https://example.invalid/33.jpeg', browsingLevel: 8, meta: null },
];
await window.cbShowModel('model:12345');
await settle();
$('cb_require_prompt').checked = true;
window.cbToggleShowAllImages(false);

check('there is one banner at the top, not one per filter', banners().length >= 1
      && banners()[0].querySelectorAll(`#${NSFW}, #${PROMPT}`).length, 2);
check('whose sentence adds up to the total', sentence(),
      'Showing 1 of 3 images (1 hidden due to NSFW filter, 1 hidden due to unusable prompt)');
check('each switch stating its clause\'s number',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (1)', 'Show unusable prompts (1)']);

window.cbToggleShowAllImages(true);
check('showing NSFW moves the NSFW image without a prompt to the prompt clause', sentence(),
      'Showing 1 of 3 images (2 hidden due to unusable prompt)');
check('and the switches follow',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (0)', 'Show unusable prompts (2)']);

window.cbToggleShowAllImages(false);
window.cbToggleShowPromptless(true);
check('showing prompts leaves only the NSFW clause', sentence(),
      'Showing 2 of 3 images (1 hidden due to NSFW filter)');
check('and the switches follow',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (1)', 'Show unusable prompts (1)']);
window.cbToggleShowPromptless(false);

console.log(fails.length
    ? fails.map((f) => 'FAIL ' + f).join('\n')
    : 'All checks passed.');
process.exit(fails.length ? 1 : 0);
