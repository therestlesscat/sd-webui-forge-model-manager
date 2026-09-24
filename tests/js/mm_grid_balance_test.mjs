// The Model Manager grid: a page size from its setting, rows kept even.
//
// It used to size pages from the window - cards that fit across times two
// rows - behind a calibration overlay, and re-page on every resize. Now the
// page holds what the Models per page setting says, the server applies it,
// and a resize only rearranges the cards, with the same rule as the Civitai
// Browser: the fewest rows the width allows, the cards spread across them.
//
// linkedom does no layout, so widths are stubbed as in grid_balance_test.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const CARD = 200;
const GAP = 15;
let gridWidth = 0;
const SETTING = 10;             // what the server's Models per page says

const elementProto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
elementProto.getBoundingClientRect = function () {
    return { width: this.classList?.contains('model-card') ? CARD : 0, height: 0 };
};
Object.defineProperty(elementProto, 'clientWidth', {
    configurable: true,
    get() { return this.id === 'mm_grid' ? gridWidth : 0; },
});
window.getComputedStyle = () => ({ columnGap: `${GAP}px`, getPropertyValue: () => '' });

const observers = [];
globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {} unobserve() {} disconnect() {}
};
function resize(width) {
    gridWidth = width;
    observers.forEach((o) => o.callback([]));
    window.dispatchEvent(new window.Event('resize'));
}

const listed = [];              // every grid request's query string
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/models?') || href.endsWith('/model-manager/models')) {
        const params = new URL(href, 'http://webui').searchParams;
        listed.push(params);
        const size = Number(params.get('page_size')) || SETTING;
        const page = Number(params.get('page')) || 1;
        const models = Array.from({ length: size }, (_, i) => ({
            id: 5000 + i, model_id: 4000 + i, name: `Model ${i}`, display_name: `Model ${i}`,
            version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
            file_path: `C:/models/${i}.safetensors`, file_name: `${i}.safetensors`,
            file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
            trained_words: [], tags: [],
        }));
        return { ok: true, json: async () => ({ success: true, total: 47, page,
            page_size: size, models, card_width: CARD, card_height: 280 }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

const roomFor = (n) => n * CARD + (n - 1) * GAP;
function rows() {
    const inner = document.querySelector('#mm_grid .model-grid-inner');
    const cap = parseFloat(inner?.style.maxWidth);
    const cards = inner?.querySelectorAll('.model-card').length || 0;
    if (!cap) return 'no cap';
    const cols = Math.floor((cap + GAP) / (CARD + GAP));
    const out = [];
    for (let left = cards; left > 0; left -= cols) out.push(Math.min(cols, left));
    return out.join(' + ');
}

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

gridWidth = roomFor(13);
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);

check('the request leaves the page size to the setting', listed[0]?.has('page_size'), false);
check('so a page holds what the setting says',
      document.querySelectorAll('#mm_grid .model-card').length, SETTING);
check('and nothing is laid over the tab while it loads',
      document.getElementById('mm_layout_overlay'), null);
check('the status counts pages of that size',
      document.getElementById('mm_status')?.textContent.includes('Showing 1-10 of 47 models (Page 1/5)'), true);

check('room for more than a page is one row', rows(), '10');
for (const [room, want] of [[9, '5 + 5'], [5, '5 + 5'], [4, '4 + 4 + 2'], [3, '3 + 3 + 3 + 1']]) {
    resize(roomFor(room) + 10);
    check(`room for ${room} lays them out ${want}`, rows(), want);
}

// Resizing rearranges; it does not re-page or reload.
await new Promise((r) => setTimeout(r, 400));
check('resizing asks the server for nothing', listed.length, 1);
check('and the page is still the setting\'s size',
      document.getElementById('mm_status')?.textContent.includes('(Page 1/5)'), true);

// The next page is the same size and is balanced at the width it lands in.
await window.mmNextPage();
await waitFor('page two', () => listed.length === 2);
check('the next page asks for page 2 with no size of its own',
      [listed[1].get('page'), listed[1].has('page_size')], ['2', false]);
check('and comes out balanced for the current width', rows(), '3 + 3 + 3 + 1');

done();
