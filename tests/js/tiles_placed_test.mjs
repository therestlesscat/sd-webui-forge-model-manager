// Fast, a grid placed by the tab (#240): javascript/shared/tiles.mjs.
//
// The browser's grid placed every tile again as each part arrived, and froze
// for up to 42 s at 75,684 tiles. Fast places them itself, by the same rule -
// a tile in the first free spot it fits, so a narrow one fills the hole a
// wide one left - and keeps on the page only the rows within 3,000 px of
// the view. These hold the placing to the browser's rule, a part at a time
// to the whole grid at once, and the page to the rows near the view.
import { GRID_LAYOUT, checker, gridLayout, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, done } = checker();
const { newPlacement, placeTiles, placedGrid, DRAW_AHEAD_PX } = await sharedModule('tiles.mjs');

const place = (columns, items, dense = true) => placeTiles(newPlacement(columns, { dense }), items);
const at = (placed) => placed.map(({ row, col }) => [row, col]);
const narrowOrWide = (spans) => spans.map((span) => ({ span }));

// ------------------------------------------------------------- the rule
// Worked by hand, as `grid-auto-flow: row dense` and `row` place them.
check('dense: a narrow tile fills the hole a wide one left at a row\'s end',
      at(place(3, narrowOrWide([2, 2, 1]))), [[0, 0], [1, 0], [0, 2]]);
check('in order (Preserve order, sections), it goes on after the last instead',
      at(place(3, narrowOrWide([2, 2, 1]), false)), [[0, 0], [1, 0], [1, 2]]);
check('dense: a tile as wide as the row goes below, and the narrow ones after it fill the first row',
      at(place(3, narrowOrWide([1, 3, 1, 1]))), [[0, 0], [1, 0], [0, 1], [0, 2]]);
check('in order, they go on below it', at(place(3, narrowOrWide([1, 3, 1, 1]), false)),
      [[0, 0], [1, 0], [2, 0], [2, 1]]);
check('a tile wider than the grid takes the grid\'s width', place(2, [{ span: 4 }])[0].span, 2);
check('Preserve order, every tile one column: strictly in reading order',
      at(place(3, narrowOrWide([1, 1, 1, 1, 1]), false)), [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1]]);

// A library's mix: most images tall, some wide - 2 to 4 columns.
let seed = 7;
const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const spanOfMix = () => {
    const r = random();
    return r < 0.7 ? 1 : r < 0.85 ? 2 : r < 0.95 ? 3 : 4;
};
const mix = Array.from({ length: 300 }, spanOfMix);
const COLUMNS = 7;
const whole = place(COLUMNS, narrowOrWide(mix));
const byParts = newPlacement(COLUMNS);
const inParts = [0, 100, 200].flatMap((from) => placeTiles(byParts, narrowOrWide(mix.slice(from, from + 100))));
check('three parts of 100, one by one: the same spots as the 300 placed at once',
      JSON.stringify(inParts), JSON.stringify(whole));

// The rows that end short, but the grid's last two: a row is full when its
// tiles' widths add up to the columns.
function shortRows(placed) {
    const widths = [];
    placed.forEach(({ row, span }) => { widths[row] = (widths[row] || 0) + span; });
    return widths.map((width, row) => (width < COLUMNS && row < widths.length - 2 ? row : -1)).filter((row) => row >= 0);
}
check('no row ends short before the grid\'s end - at a part\'s end neither', shortRows(inParts), []);
// What a grid per part did (run 4): each part packed alone, below the last.
let below = 0;
const perPart = [0, 100, 200].flatMap((from) => {
    const own = place(COLUMNS, narrowOrWide(mix.slice(from, from + 100))).map((s) => ({ ...s, row: s.row + below }));
    below = Math.max(...own.map((s) => s.row)) + 1;
    return own;
});
check('which a grid per part fails: its parts end on short rows', shortRows(perPart).length > 0, true);

// Sections, grouped twice: a header takes a row across the grid, and no
// tile goes above its own header. Worked by hand, as `row` places them.
const sectioned = newPlacement(4, { dense: false });
const inSections = placeTiles(sectioned, [
    { span: 1, head: true }, { span: 2 }, { span: 2 }, { span: 1 },
    { span: 1, head: true }, { span: 3 }, { span: 1 },
]);
check('each section\'s header has a row of its own, taken whole',
      [inSections[0].head, inSections[4].head, sectioned.rows[0].every(Boolean), sectioned.rows[3].every(Boolean)],
      [0, 3, true, true]);
check('each tile below its own section\'s header, in order',
      at(inSections), [[1, 0], [1, 1], [2, 0], [2, 2], [4, 0], [4, 1], [5, 0]]);

// ------------------------------------------------------------- the page
// 1,000 tiles, every fifth 16:9 - three columns at 200 px and a 300 px image.
const grid = document.getElementById('gen_grid');
let tiles = Array.from({ length: 1000 }, (_, i) => ({ n: i, wide: i % 5 === 4 }));
const imageOf = (i) => (tiles[i]?.wide ? { width: 1600, height: 900 } : { width: 832, height: 1216 });
let mark = '';
const html = (i) => `<div class="gen-set" data-tile="${i}"><div class="gen-tile">${tiles[i].n}${i === 3 ? mark : ''}</div></div>`;
const listeners = [];
const scope = { listen: (target, type, fn) => listeners.push([type, fn]) };
let drawnCalls = 0;
// The window: scrolled by the grid's top, 1,000 px tall; scrollTo moves it.
const view = gridLayout(window, { top: 0, height: 1000 });
let scrolled = 0;
window.scrollY = 0;
window.scrollTo = (x, y) => {
    scrolled = y;
    window.scrollY = y;
    view({ top: -y });
};
const placed = placedGrid({
    scope, grid: () => grid, app: () => document.getElementById('generations_app'),
    count: () => tiles.length, html, imageOf, drawn: () => { drawnCalls += 1; },
});
const frame = () => new Promise((resolve) => setTimeout(resolve, 20));
const scrollTo = async (y) => {
    window.scrollTo(0, y);
    listeners.filter(([type]) => type === 'scroll').forEach(([, fn]) => fn());
    await frame();
};
const onPage = () => [...grid.querySelectorAll('.gen-set')].map((set) => Number(set.dataset.tile));

placed.add();
// As the page places them: 4 columns in 1,000 px; a row the image and its
// buttons tall until a tile is measured - this DOM measures none.
const columns = Math.floor((GRID_LAYOUT.width + GRID_LAYOUT.gap) / (GRID_LAYOUT.column + GRID_LAYOUT.gap));
const expected = place(columns, tiles.map((_, i) => ({ span: tiles[i].wide ? 3 : 1 })));
const pitch = GRID_LAYOUT.image + 40 + GRID_LAYOUT.gap;
const near = (scroll) => expected.map((s, i) => [s, i])
    .filter(([s]) => s.row * pitch < scroll + 1000 + DRAW_AHEAD_PX && s.row * pitch + pitch - GRID_LAYOUT.gap > scroll - DRAW_AHEAD_PX)
    .map(([, i]) => i);
check('the tiles are placed as the rule places them, 4 columns', columns, 4);
check('only the rows within 3,000 px of the view are on the page', onPage(), near(0));
check('far fewer than the tab holds', onPage().length < 100, true);
check('the grid is as tall as all its rows, so the scrollbar is true',
      grid.style.height, `${(Math.max(...expected.map((s) => s.row)) + 1) * pitch - GRID_LAYOUT.gap}px`);
check('the grid is the placed one', grid.classList.contains('gen-placed'), true);
const tileAt = (i) => grid.querySelector(`.gen-set[data-tile="${i}"] .gen-tile`);
const spotOf = (i) => [tileAt(i)?.style.left, tileAt(i)?.style.top, tileAt(i)?.style.width];
const wideOne = near(0).find((i) => tiles[i].wide);
check('a tile at its spot, as wide as its columns',
      spotOf(wideOne), [`${expected[wideOne].col * 204}px`, `${expected[wideOne].row * pitch}px`, `${3 * 200 + 2 * 4}px`]);
check('its images are asked to load as it comes onto the page', drawnCalls > 0, true);

await scrollTo(20000);
check('scrolled 20,000 px: the rows near the view now, and none of the first', onPage(), near(20000));
check('in order on the page, as they read', onPage().join(), [...onPage()].sort((a, b) => a - b).join());

// The viewer closes on a tile far below: the page brings its row into view, and draws it.
const far = 600;
check('a far tile is not on the page', placed.isDrawn(far), false);
placed.scrollTo(far);
check('closing the viewer on it scrolls its row to the view\'s bottom',
      scrolled, expected[far].row * pitch + pitch - GRID_LAYOUT.gap - 1000);
check('and draws it', placed.isDrawn(far), true);

// Back to image finds a tile far below: its row in the middle of the window (#264).
const found = 800;
placed.scrollTo(found, { center: true });
check('centred: the middle of its row at the middle of the 1,000 px window',
      scrolled, expected[found].row * pitch + (pitch - GRID_LAYOUT.gap) / 2 - 500);
check('and drawn', placed.isDrawn(found), true);

// A tile rated: drawn again where it was. Then the one before it deleted:
// the grid is placed again, and it moves up into that one's spot.
await scrollTo(0);
const spotBefore = spotOf(3);
mark = ' rated';
placed.redraw(3);
check('a tile drawn again shows its new markup, at its spot', [tileAt(3)?.textContent, spotOf(3)], ['3 rated', spotBefore]);
const spotOf2 = spotOf(2);
tiles = tiles.filter((_, i) => i !== 2);
grid.innerHTML = '';
placed.reset();
placed.add();
check('a tile deleted: the next moves up into its spot', [tileAt(2)?.textContent, spotOf(2)], ['3', spotOf2]);

// Hidden while placed - another tab shown - a scroll there leaves the grid as it is.
await scrollTo(20000);
const before = onPage();
grid.getBoundingClientRect = () => ({ width: 0, top: 0, height: 0, bottom: 0 });
await scrollTo(30000);
delete grid.getBoundingClientRect;
check('hidden, a scroll in another tab leaves the rows on the page as they were', onPage(), before);
await scrollTo(0);

// Hidden, the tab measures nothing: nothing is placed until it shows.
grid.innerHTML = '';
placed.reset();
grid.getBoundingClientRect = () => ({ width: 0, top: 0, height: 0, bottom: 0 });
placed.add();
check('a hidden tab places nothing', onPage(), []);
delete grid.getBoundingClientRect;
placed.relayout();
check('shown again, it places them: the first rows are on the page', onPage().slice(0, 4), [0, 1, 2, 3]);

// A wider window has more columns: every tile placed again.
GRID_LAYOUT.width = 1400;
placed.relayout();
const lefts = [...grid.querySelectorAll('.gen-tile')].map((tile) => parseFloat(tile.style.left));
check('a wider window: 6 columns, the tiles placed again over them', Math.max(...lefts), 5 * 204);
GRID_LAYOUT.width = 1000;

// Grouped twice, on the page: a section's header across the grid, above its
// tiles, the section gap above it but the first. Worked by hand: 4 columns,
// a header 30 px tall until one is measured - this DOM measures none.
const sectionGrid = document.createElement('div');
sectionGrid.className = 'gen-grid';
document.body.appendChild(sectionGrid);
const starts = (i) => i === 0 || i === 5;
const sections = placedGrid({
    grid: () => sectionGrid, app: () => document.getElementById('generations_app'), count: () => 10,
    html: (i) => `<div class="gen-set" data-tile="${i}">${starts(i) ? `<div class="gen-section-head">S${i}</div>` : ''}`
        + `<div class="gen-tile">${i}</div></div>`,
    imageOf: () => ({ width: 832, height: 1216 }), head: starts, dense: () => false,
});
sections.add();
const headAt = (i) => sectionGrid.querySelector(`.gen-set[data-tile="${i}"] .gen-section-head`)?.style;
const tileTop = (i) => sectionGrid.querySelector(`.gen-set[data-tile="${i}"] .gen-tile`)?.style.top;
check('the first header at the top, across the grid', [headAt(0)?.top, headAt(0)?.left, headAt(0)?.width],
      ['0px', '0px', `${4 * 200 + 3 * 4}px`]);
check('its tiles on the row below it', [tileTop(0), tileTop(3), tileTop(4)], ['34px', '34px', '378px']);
check('the next header on a row of its own after them, the section gap above it', headAt(5)?.top, `${722 + 6}px`);
check('and its first tile below it', tileTop(5), `${722 + 6 + 30 + 4}px`);
sectionGrid.remove();

// ------------------------------------------------------------- the time
// What a part costs at the end of the grid, and the whole grid at once -
// a resize, a tile deleted - at the size the measurement reached.
const big = Array.from({ length: 75684 }, spanOfMix);
let started = performance.now();
place(7, narrowOrWide(big));
const all = performance.now() - started;
const growing = newPlacement(7);
placeTiles(growing, narrowOrWide(big.slice(0, 75584)));
started = performance.now();
placeTiles(growing, narrowOrWide(big.slice(75584)));
const lastPart = performance.now() - started;
console.log(`placing 75,684 tiles: ${all.toFixed(1)} ms; the last part of 100: ${lastPart.toFixed(2)} ms`);
// Measured at 12.6 ms on the machine the plan was measured on: room for a slower one.
check('75,684 tiles placed at once in under 250 ms', all < 250, true);
check('the last part of 100 placed in under 5 ms', lastPart < 5, true);

done();
