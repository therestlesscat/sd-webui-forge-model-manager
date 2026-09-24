// The Civitai Browser grid keeps its rows even as the window is resized.
//
// A page of cards used to wrap wherever the width ran out: ten cards with
// room for nine was 9 + 1. Now it takes the fewest rows the width allows and
// spreads the cards across them, so that is 5 + 5 - and stays 5 + 5 down to
// room for five. Only when another row is unavoidable does it change: room
// for four is 4 + 4 + 2, as even as equal columns get.
//
// linkedom does no layout, so the widths are stubbed: every card is 200px,
// the gap 15px, and the grid as wide as each check says. The layout is read
// back from the cap put on the card list, which is what makes it wrap.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const CARD = 200;
const GAP = 15;
let gridWidth = 0;
let pageSize = 10;

// Width, as far as the module can see it.
const elementProto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
elementProto.getBoundingClientRect = function () {
    return { width: this.classList?.contains('model-card') ? CARD : 0, height: 0 };
};
Object.defineProperty(elementProto, 'clientWidth', {
    configurable: true,
    get() { return this.id === 'cb_grid' ? gridWidth : 0; },
});
window.getComputedStyle = () => ({ columnGap: `${GAP}px`, getPropertyValue: () => '' });

// Resizing is the observer firing; keep hold of it to fire it.
const observers = [];
globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {} unobserve() {} disconnect() {}
};
function resize(width) {
    gridWidth = width;
    observers.forEach((o) => o.callback([]));
}

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/civitai/models')) {
        const models = Array.from({ length: pageSize }, (_, i) => ({
            id: i + 1, name: `Model ${i + 1}`, type: 'LORA', nsfw: false, nsfwLevel: 1,
            stats: {}, creator: { username: 'someone' }, owned_locally: false,
            modelVersions: [{ id: 100 + i, name: 'v1', baseModel: 'SDXL 1.0', images: [], files: [] }],
        }));
        return { ok: true, json: async () => ({ success: true, models, nextCursor: null,
            pageSize, cardWidth: CARD, cardHeight: 280 }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

// Room for n cards across, and the rows that come out of it.
const roomFor = (n) => n * CARD + (n - 1) * GAP;
function rows() {
    const inner = document.querySelector('#cb_grid .model-grid-inner');
    const cap = parseFloat(inner?.style.maxWidth);
    const cards = inner?.querySelectorAll('.model-card').length || 0;
    if (!cap) return 'no cap';
    const cols = Math.floor((cap + GAP) / (CARD + GAP));
    const out = [];
    for (let left = cards; left > 0; left -= cols) out.push(Math.min(cols, left));
    return out.join(' + ');
}

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

gridWidth = roomFor(10) + 50;
window.cbSearch();
await waitFor('a page of cards', () => document.querySelectorAll('#cb_grid .model-card').length === 10);

check('ten cards with room for ten sit in one row', rows(), '10');
for (const [room, want] of [[9, '5 + 5'], [7, '5 + 5'], [6, '5 + 5'], [5, '5 + 5'],
                            [4, '4 + 4 + 2'], [3, '3 + 3 + 3 + 1'], [2, '2 + 2 + 2 + 2 + 2'],
                            [1, '1 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1 + 1']]) {
    resize(roomFor(room) + 10);
    check(`room for ${room} lays them out ${want}`, rows(), want);
}
resize(roomFor(10));
check('an exact fit counts as a fit', rows(), '10');

// Another page size, and a width the page has never been rendered at.
pageSize = 20;
resize(roomFor(8) + 10);
window.cbSearch();
await waitFor('a page of twenty', () => document.querySelectorAll('#cb_grid .model-card').length === 20);
check('twenty with room for eight is 7 + 7 + 6, not 8 + 8 + 4', rows(), '7 + 7 + 6');

// A hidden tab has no width. Leave the grid be until it is shown.
resize(0);
check('a hidden grid keeps the layout it had', rows(), '7 + 7 + 6');

done();
