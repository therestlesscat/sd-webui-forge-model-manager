// Moving through a model's example images, both ways.
//
// A large model can hold hundreds of images. Paged, adding a page jumps the
// list back to the top, which loses your place; continuous grows one list
// downwards and leaves you where you were. Which one you get is a setting,
// served on /model-manager/ui-options and read once at load.
//
// The thing worth checking is that the two modes do not leak into each other:
// page controls in a continuous list would look like the feature working.
//
// Either way the server sends a page at a time. The whole gallery used to be
// sent and sliced here - 200 images, 900 KB, for one version of a real
// library - and a download from Civitai was added to the list as it arrived,
// explicit images and all, whatever the NSFW switch said.
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
// It filters and pages, as /model-manager/models/details and
// /model-manager/images/page do: the page is sent one page at a time.
const PAGE = 100;              // IMAGE_PAGE_SIZE in the shared module
const DOWNLOADED = 250;        // two full pages and a remainder
const fetched = [];
let civitaiDown = false;       // Civitai answering 503, as it does in an outage

const image = (id, level = 1) => ({
    id, url: `https://example.invalid/${id}.jpeg`, width: 512, height: 768,
    nsfw_level: level, mm_level: level, meta: { prompt: `prompt ${id}`, steps: 20 },
});
// What the server holds. A download from Civitai adds to it.
const library = Array.from({ length: DOWNLOADED }, (_, i) => image(i + 1));

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};

// A page of the library through the NSFW switch, with the state it is drawn
// with. The settings hide NSFW images until the page says otherwise.
function galleryPage(params, offset, limit) {
    const hideNsfw = params.get('hide_nsfw_images') !== 'false';
    const shown = library.filter((img) => !hideNsfw || img.mm_level <= 3);
    return {
        images: shown.slice(offset, offset + limit),
        images_state: {
            version_id: MODEL.id, next_cursor: 'more', sync_date: '2026-01-01T00:00:00Z',
            offset, total_count: library.length, filtered_count: shown.length,
            hidden_nsfw: library.length - shown.length, hidden_promptless: 0,
            nsfw_count: library.length - shown.length, promptless_count: 0,
            hide_nsfw_images: hideNsfw, hide_promptless_images: false,
        },
    };
}

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    fetched.push(href);
    const params = new URL(href, 'http://webui').searchParams;
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({
            success: true, samplers: ['Euler'], schedulers: ['Simple'],
            has_api_key: true, image_browsing: MODE }) };
    }
    if ((href.includes('/images/load-more') || init.method === 'POST') && civitaiDown) {
        return { ok: false, status: 500, json: async () => ({
            success: false, error: 'Request failed: Server error: 503' }) };
    }
    if (href.includes('/images/load-more') || init.method === 'POST') {
        // Five more from Civitai: three of them explicit. The answer holds
        // them all, as the real one does, whatever the switches say.
        const more = [1, 8, 1, 16, 8].map((level, i) => image(DOWNLOADED + i + 1, level));
        library.push(...more);
        return { ok: true, json: async () => ({ success: true, next_cursor: null, images: more }) };
    }
    if (href.includes('/model-manager/images/page')) {
        const page = galleryPage(params, Number(params.get('offset')), Number(params.get('limit')));
        return { ok: true, json: async () => ({ success: true, ...page }) };
    }
    if (href.includes('/model-manager/models/details')) {
        const page = galleryPage(params, 0, Number(params.get('image_limit')));
        return { ok: true, json: async () => ({ success: true, model: { ...MODEL, ...page } }) };
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

check('the details ask for one page of images',
      new URL(fetched.find((u) => u.includes('/models/details')), 'http://webui')
          .searchParams.get('image_limit'), String(PAGE));
check('and a page of images is shown to begin with', cards(), PAGE);

// Where a gallery request asked to start, for the requests made since `from`.
const pageOffsets = (from) => fetched.slice(from)
    .filter((u) => u.includes('/model-manager/images/page'))
    .map((u) => new URL(u, 'http://webui').searchParams.get('offset'));
const downloadNote = () => (window.document.querySelector('#mm_images .mm-load-more-info')
    ?.textContent || '').trim();
const shownIds = () => Array.from(window.document.querySelectorAll('#mm_images .mm-image-card img'))
    .map((img) => Number((img.getAttribute('data-src') || img.getAttribute('src') || '')
        .match(/(\d+)\.jpeg/)?.[1]));

if (MODE === 'pages') {
    check('page controls are offered', pagers() > 0, true);
    check('and no show-more button', has('mm_show_more_btn'), false);

    let askedBefore = fetched.length;
    await window.mmNextImagePage();
    await settle();
    check('a page turn asks the server for that page', pageOffsets(askedBefore), [String(PAGE)]);
    check('and replaces the list with it', cards(), PAGE);
    check('beginning where the first page ended', shownIds()[0], PAGE + 1);

    await window.mmLastImagePage();
    await settle();
    check('the last page holds the remainder', cards(), DOWNLOADED - 2 * PAGE);

    // Civitai down first: the click used to look like one that found nothing.
    let before = cards();
    civitaiDown = true;
    await window.mmLoadMoreImages();
    await settle();
    civitaiDown = false;
    check('a download that fails says so beside the button', downloadNote(),
          'Nothing was downloaded: Request failed: Server error: 503');
    check('changing nothing else', cards(), before);
    check('and the button is offered again', has('mm_load_more_btn'), true);

    askedBefore = fetched.length;
    await window.mmLoadMoreImages();
    await settle();
    check('a download reads the page again from the server', pageOffsets(askedBefore).length > 0, true);
    check('which leaves out the explicit ones it brought, as the switch says',
          shownIds().filter((id) => id > DOWNLOADED), [DOWNLOADED + 1, DOWNLOADED + 3]);
    check('and says so beside the button', downloadNote(),
          '5 more images: 2 shown, 3 hidden by the NSFW filter');
} else {
    check('no page controls', pagers(), 0);
    check('a show-more button is offered instead', has('mm_show_more_btn'), true);

    let askedBefore = fetched.length;
    await window.mmShowMoreImages();
    await settle();
    check('showing more asks the server for the next page', pageOffsets(askedBefore), [String(PAGE)]);
    check('and adds it to the list rather than replacing it', cards(), PAGE * 2);

    await window.mmShowMoreImages();
    await settle();
    check('and again, up to what is downloaded', cards(), DOWNLOADED);
    check('at which point there is nothing more to show', has('mm_show_more_btn'), false);
    check('and the offer becomes one to download more', has('mm_load_more_btn'), true);

    // Civitai down first: the click used to look like one that found nothing.
    let before = cards();
    civitaiDown = true;
    await window.mmLoadMoreImages();
    await settle();
    civitaiDown = false;
    check('a download that fails says so beside the button', downloadNote(),
          'Nothing was downloaded: Request failed: Server error: 503');
    check('changing nothing else', cards(), before);
    check('and the button is offered again', has('mm_load_more_btn'), true);

    askedBefore = fetched.length;
    await window.mmLoadMoreImages();
    await settle();
    check('a download asks the server for what follows the list', pageOffsets(askedBefore),
          [String(DOWNLOADED)]);
    check('which leaves out the explicit ones it brought, as the switch says',
          shownIds().filter((id) => id > DOWNLOADED), [DOWNLOADED + 1, DOWNLOADED + 3]);
    check('keeping what was already shown', cards(), DOWNLOADED + 2);
    check('and it says so beside the button: a batch of explicit images used to look like '
          + 'a click that did nothing', downloadNote(),
          '5 more images: 2 shown, 3 hidden by the NSFW filter');
}

console.log(fails.length
    ? fails.map((f) => 'FAIL ' + f).join('\n')
    : `All checks passed (${MODE}).`);
process.exit(fails.length ? 1 : 0);
