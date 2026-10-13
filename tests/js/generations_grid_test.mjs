// The Generations tab's grid setting (#240): Fast, placed by the tab, or
// Classic, the browser's grid.
//
// Every feature works the same either way: each control asks the server the
// same, and shows the same tiles in the same order. A choice that changes the
// data - Search, Group by, Show NSFW, Expand generations - starts the grid
// again from its first tile; Rate, Select and Preserve order keep the place.
// The setting applies as it is saved, the page where it was.
import { checker, gridLayout, mountTab, sharedModule, startTab, call, act, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
const { newPlacement, placeTiles } = await sharedModule('tiles.mjs');
// A tile's height, as a browser would measure it: its image and buttons, and
// the rating row under them once Rate is on - the one thing that changes it.
Object.defineProperty(Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div'))), 'offsetHeight', {
    configurable: true,
    get() {
        if (this.classList?.contains('gen-tile')) return this.querySelector('.mm-rate') ? 380 : 340;
        return 0;
    },
});

// ------------------------------------------------------------- the server
// 250 generations, in parts of 100; every fourth image 16:9. A search, a
// grouping, the NSFW switch and Expand each answer something else.
const image = (id, generation, wide) => ({
    id, generation_id: generation, position: 0, url: `/x/${id}`, exists: true, mm_level: 1, meta: {}, infotext: '',
    width: wide ? 1600 : 832, height: wide ? 900 : 1216,
});
const tile = (generation, kind = 'generation') => ({
    kind, generation: { id: generation, created_at: '2026-10-05T12:00:00', mode: 'txt2img', image_count: 1 },
    images: [image(generation * 10, generation, generation % 4 === 0)], matching_count: 1,
    ...(kind === 'group' ? { group: { id: `g${generation}`, value: `group ${generation}`, by: 'prompt', generations: 1 } } : {}),
});
function answer(params) {
    const count = params.search ? 30 : params.group ? 40 : params.expand === 'true' ? 260
        : params.hide_nsfw_images === 'false' ? 255 : 250;
    const offset = params.search ? 1000 : params.expand === 'true' ? 2000 : params.hide_nsfw_images === 'false' ? 3000 : 0;
    const page = Number(params.page || 1);
    const all = Array.from({ length: count }, (_, i) => tile(offset + i + 1, params.group ? 'group' : 'generation'));
    const tiles = all.slice((page - 1) * 100, page * 100);
    return { success: true, tiles, more: page * 100 < count, scope: { count },
             state: { total: count, filtered: count, hidden_nsfw: params.hide_nsfw_images === 'false' ? 0 : 5, nsfw_count: 5 } };
}
let grid = 'Fast';
const browsed = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], generations_hide_nsfw: true,
                       generations_enabled: true, generations_grid: grid });
    }
    if (href.includes('/model-manager/generations/browse')) {
        const params = Object.fromEntries(new URL(href, 'http://x').searchParams);
        browsed.push(params);
        return reply(answer(params));
    }
    return reply({ success: true, notes: [] });
};

// The window: 1,000 px tall, scrolled by where the grid's top is.
const view = gridLayout(window, { top: 0, height: 1000 });
window.scrollY = 0;
window.scrollTo = (x, y) => {
    window.scrollY = y;
    view({ top: -y });
};
const gridEl = () => document.getElementById('gen_grid');
const shown = () => [...gridEl().querySelectorAll('.gen-set')].map((set) => Number(set.dataset.tile));
const generations = () => [...gridEl().querySelectorAll('.gen-tile')].map((t) => Number(t.dataset.generation));
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
const loaded = (n) => waitFor(`${n} tiles`, async () => {
    await settle();
    return browsed.length && !browsed.at(-1).pending && document.getElementById('gen_status')?.textContent === '';
});

await startTab('generations');
await waitFor('the first parts', () => browsed.length >= 1);
await settle();
check('Fast by default: the grid is the tab\'s', gridEl().classList.contains('gen-placed'), true);
check('only the rows near the view are on the page', shown().length < 100, true);

// ------------------------------------------------------- switching
async function saved(choice) {
    grid = choice;
    window.dispatchEvent(new window.CustomEvent('mm-settings-saved',
        { detail: { changed: ['model_manager_generations_grid'], settings: {} } }));
    await waitFor(`the grid ${choice}`, () => gridEl().classList.contains('gen-placed') === (choice === 'Fast'));
    await settle();
}
await saved('Classic');
check('Classic saved: the browser\'s grid, every tile loaded on the page', [gridEl().style.height, shown().length],
      ['', 250]);
await saved('Fast');
check('Fast saved: the tab\'s again', [gridEl().style.height !== '', shown().length < 100], [true, true]);
grid = 'Classic';
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied',
    { detail: { changed: ['model_manager_generations_grid'] } }));
await waitFor('Classic from the Settings page', () => !gridEl().classList.contains('gen-placed'));
await saved('Fast');

// ------------------------------------------------- each control, both ways
// The tiles a control leaves, as the tab holds them: every tile drawn in
// Classic, and in Fast with a window tall enough to hold them all.
async function run(choice) {
    await saved(choice);
    view({ top: 0, height: 100000 });
    window.scrollY = 0;
    const seen = [];
    const asked = () => browsed.splice(0).map(({ page, search, group, hide_nsfw_images: nsfw, expand }) =>
        JSON.stringify({ page, search, group, nsfw, expand }));
    const look = async (label, step) => {
        browsed.length = 0;
        await step();
        await settle();
        await settle();
        seen.push([label, asked(), generations()]);
    };
    await look('Search', async () => {
        const box = document.getElementById('gen_search');
        box.value = 'dusk';
        box.dispatchEvent(new window.Event('change', { bubbles: true }));
    });
    await look('Search emptied', async () => {
        const box = document.getElementById('gen_search');
        box.value = '';
        box.dispatchEvent(new window.Event('search'));
    });
    await look('Group by', () => call('generations.groupBy', 'prompt'));
    await look('Group by nothing', () => call('generations.groupBy', ''));
    await look('Show NSFW', () => tick('generations.showNsfw', true));
    await look('Show NSFW off', () => tick('generations.showNsfw', false));
    await look('Expand generations', () => tick('generations.expand', true));
    await look('Expand off', () => tick('generations.expand', false));
    await look('Rate', () => tick('generations.rating', true));
    await look('Rate off', () => tick('generations.rating', false));
    await look('Select', () => tick('generations.selecting', true));
    await look('Select off', () => tick('generations.selecting', false));
    await look('Preserve order', () => tick('generations.preserveOrder', true));
    await look('Preserve order off', () => tick('generations.preserveOrder', false));
    view({ top: 0, height: 1000 });
    return seen;
}
const classic = await run('Classic');
const fast = await run('Fast');
classic.forEach(([label, asked, tiles], i) => {
    check(`${label}: the same asked of the server, both ways`, fast[i][1], asked);
    check(`${label}: the same tiles, in the same order, both ways`, fast[i][2], tiles);
});
check('the controls were tried with tiles to show', classic.every(([, , tiles]) => tiles.length > 0), true);

// --------------------------------------------- reset, or the place kept
// Fast, scrolled 6,000 px down the grid of 250.
const pitch = 340 + 4;
async function scrolledTo(y) {
    window.scrollTo(0, y);
    window.dispatchEvent(new window.Event('scroll'));
    await settle();
}
const topTile = () => shown().find((i) => {
    const t = gridEl().querySelector(`.gen-set[data-tile="${i}"] .gen-tile`);
    return parseFloat(t.style.top) + pitch > window.scrollY;
});
const screenTop = (i) => {
    const tile = gridEl().querySelector(`.gen-set[data-tile="${i}"] .gen-tile`);
    return tile ? parseFloat(tile.style.top) - window.scrollY : null;
};

for (const [label, first, count, step] of [
    ['Search', 1001, 30, async () => {
        const box = document.getElementById('gen_search');
        box.value = 'dusk';
        box.dispatchEvent(new window.Event('change', { bubbles: true }));
    }],
    ['Group by', 1, 40, () => call('generations.groupBy', 'prompt')],
    ['Show NSFW', 3001, 255, () => tick('generations.showNsfw', true)],
    ['Expand generations', 2001, 260, () => tick('generations.expand', true)],
]) {
    // Back to the 250, scrolled down.
    const box = document.getElementById('gen_search');
    box.value = '';
    box.dispatchEvent(new window.Event('search'));
    await call('generations.groupBy', '');
    await tick('generations.showNsfw', false);
    await tick('generations.expand', false);
    await settle();
    await settle();
    await scrolledTo(6000);
    check(`before ${label}: scrolled down, the first tiles off the page`, shown().includes(0), false);
    await step();
    await settle();
    await settle();
    await scrolledTo(0);
    check(`${label} changes the data: the grid starts again from its first tile, the new one's`,
          [shown()[0], generations()[0]], [0, first]);
    check(`${label}: placed afresh - no tile of the old grid left, each tile once`,
          [Math.max(...shown()) < count, new Set(shown()).size === shown().length], [true, true]);
    // As tall as the new grid's rows: 4 columns, a 16:9 tile across 3.
    const rows = placeTiles(newPlacement(4), Array.from({ length: count }, (_, i) => ({ span: (first + i) % 4 ? 1 : 3 })))
        .reduce((last, s) => Math.max(last, s.row), 0) + 1;
    check(`${label}: the grid as tall as the new grid's rows`, gridEl().style.height, `${rows * pitch - 4}px`);
}
// Back to the 250.
{
    const box = document.getElementById('gen_search');
    box.value = '';
    box.dispatchEvent(new window.Event('search'));
    await call('generations.groupBy', '');
    await tick('generations.showNsfw', false);
    await tick('generations.expand', false);
    await settle();
    await settle();
}
for (const [label, on, off] of [
    ['Rate', () => tick('generations.rating', true), () => tick('generations.rating', false)],
    ['Select', () => tick('generations.selecting', true), () => tick('generations.selecting', false)],
    ['Preserve order', () => tick('generations.preserveOrder', true), () => tick('generations.preserveOrder', false)],
]) {
    await scrolledTo(6000);
    const anchor = topTile();
    const before = screenTop(anchor);
    browsed.length = 0;
    await on();
    await settle();
    check(`${label} asks the server nothing`, browsed.length, 0);
    if (label === 'Rate') {
        check('Rate: the tiles grow by their rating row, the rows with them',
              gridEl().querySelector('.gen-tile')?.offsetHeight, 380);
    }
    check(`${label} keeps the place: the tile at the top stays where it was on the screen`,
          [shown().includes(anchor), screenTop(anchor)], [true, before]);
    await off();
    await settle();
}

done();
