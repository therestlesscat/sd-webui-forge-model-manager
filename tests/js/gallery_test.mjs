// Moving through a model's example images, both ways.
//
// A large model can hold hundreds of images. Paged, adding a page jumps the
// list back to the top, which loses your place; continuous grows one list
// downwards and leaves you where you were. Which one you get is a setting,
// served on /model-manager/ui-options and read once at load.
//
// The thing worth checking is that the two modes do not leak into each other:
// page controls in a continuous list, or a "show more" button that fetches
// when it should only reveal, would both look like the feature working.
import { readFileSync } from 'fs';
import { parseHTML } from 'linkedom';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const ROOT = process.env.MM_ROOT
    ? process.env.MM_ROOT.replace(/\\/g, '/')
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..').replace(/\\/g, '/');

// The mode is fixed at module load, so the suite runs twice - once each way.
const MODE = process.env.MM_IMAGE_BROWSING === 'pages' ? 'pages' : 'continuous';

const tabSource = readFileSync(`${ROOT}/model_manager/ui/tab_model_manager.py`, 'utf8');
const htmlMatch = tabSource.match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/);
if (!htmlMatch) throw new Error('could not find the tab markup in tab_model_manager.py');
const { window } = parseHTML(`<!doctype html><html><body>${htmlMatch[2]}</body></html>`);

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

const inputProto = Object.getPrototypeOf(window.document.createElement('input'));
Object.defineProperty(inputProto, 'checked', {
    configurable: true,
    get() { return this.hasAttribute('checked'); },
    set(on) { if (on) this.setAttribute('checked', ''); else this.removeAttribute('checked'); },
});

// --- the server ------------------------------------------------------------
const PAGE = 100;              // IMAGE_PAGE_SIZE in the shared module
const DOWNLOADED = 250;        // two full steps and a remainder
let scrolledToTop = 0;
const fetched = [];

const image = (id) => ({
    id, url: `https://example.invalid/${id}.jpeg`, width: 512, height: 768,
    nsfw_level: 1, meta: { prompt: `prompt ${id}`, steps: 20 },
});

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    fetched.push(href);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({
            success: true, samplers: ['Euler'], schedulers: ['Simple'],
            has_api_key: true, image_browsing: MODE }) };
    }
    if (href.includes('/images/load-more') || init.method === 'POST') {
        // Five more, as a fetch from Civitai would bring.
        return { ok: true, json: async () => ({
            success: true, next_cursor: null,
            images: Array.from({ length: 5 }, (_, i) => image(DOWNLOADED + i + 1)) }) };
    }
    if (href.includes('/model-manager/models/details')) {
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL,
            images: Array.from({ length: DOWNLOADED }, (_, i) => image(i + 1)),
            images_state: {
                version_id: MODEL.id, next_cursor: 'more',
                sync_date: '2026-01-01T00:00:00Z',
                total_count: DOWNLOADED, hidden_count: 0, hide_nsfw_images: false,
            },
        } }) };
    }
    if (href.includes('/model-manager/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [MODEL] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({
            success: true, total: 1, page: 1, page_size: 10, models: [MODEL] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

// --- run --------------------------------------------------------------------
const fails = [];
const check = (label, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) {
        fails.push(`[${MODE}] ${label}\n     got  ${JSON.stringify(got)}\n     want ${JSON.stringify(want)}`);
    }
};
const settle = () => new Promise((r) => setTimeout(r, 300));
// The details load is a fetch chain, so waiting a fixed 300ms is a race that
// passes most of the time - which is worse than failing.
const waitFor = async (what, predicate) => {
    for (let tries = 0; tries < 60; tries++) {
        if (predicate()) return;
        await new Promise((r) => setTimeout(r, 50));
    }
    fails.push(`[${MODE}] timed out waiting for ${what}`);
};
const cards = () => window.document.querySelectorAll('#mm_images .mm-image-card').length;
const $ = (id) => window.document.getElementById(id);
const pagers = () => window.document.querySelectorAll('#mm_images .mm-image-pagination').length;
const has = (id) => !!window.document.querySelector(`#${id}`);

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));
await settle();

check('the tab read the setting',
      fetched.some((u) => u.includes('/ui-options')), true);

$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => window.document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => cards() > 0);

check('a page of images is shown to begin with', cards(), PAGE);

if (MODE === 'pages') {
    check('page controls are offered', pagers() > 0, true);
    check('and no show-more button', has('mm_show_more_btn'), false);

    window.mmNextImagePage();
    await settle();
    check('a page turn replaces the list', cards(), PAGE);
} else {
    check('no page controls', pagers(), 0);
    check('a show-more button is offered instead', has('mm_show_more_btn'), true);

    const askedBefore = fetched.length;
    window.mmShowMoreImages();
    await settle();
    check('showing more adds to the list rather than replacing it', cards(), PAGE * 2);
    check('without asking the server for anything', fetched.length - askedBefore, 0);

    window.mmShowMoreImages();
    await settle();
    check('and again, up to what is downloaded', cards(), DOWNLOADED);
    check('at which point there is nothing more to show', has('mm_show_more_btn'), false);
    check('and the offer becomes one to download more', has('mm_load_more_btn'), true);
}

console.log(fails.length
    ? fails.map((f) => 'FAIL ' + f).join('\n')
    : `All checks passed (${MODE}).`);
process.exit(fails.length ? 1 : 0);
