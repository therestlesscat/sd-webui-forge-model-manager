// Previous Position in a tab of tiles finds the tile left (#264), in the
// shared module (shared/previous_position.mjs). The Generations tab lists the
// newest first, so each batch generated after a Send pushed every tile down,
// and a height came back on older images; after a reload a grid starts again
// from its first part. So the place is the tile, by what it shows - the
// image, its batch, the groups opened to reach it - and the button looks for
// it in the grid the tab shows: in the parts loaded, then loading more, up to
// 20 parts, then on only if the person says so. Not found, the page stays.
//
// The grid here is a stand-in, as the tabs hand theirs to the module: tiles
// by id, in parts of 2. The tabs' own ids and what they note are their place
// suites'.
import { checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
const { previousPosition, SEEK_PARTS, TILE_BUTTON } = await sharedModule('previous_position.mjs');
document.body.insertAdjacentHTML('beforeend', '<div id="place_row"></div>');

const scrolls = [];
window.scrollTo = (...args) => { scrolls.push(typeof args[0] === 'object' ? args[0].top : args[1]); };
const asked = [];
let answer = false;
window.confirm = (question) => {
    asked.push({ question, parts: current?.parts() });
    return answer;
};
let current = null;

/** A grid of `order` - tile ids, in the grid's order - in parts of 2, the first loaded. */
function standIn(order) {
    const grid = {
        tiles: order.slice(0, 2), loaded: 1, loads: 0, shown: [], said: [], v: 0, hold: null, fails: false,
        count: () => grid.tiles.length,
        ids: (index) => [grid.tiles[index]],
        parts: () => grid.loaded,
        more: () => grid.loaded * 2 < order.length,
        load: async () => {
            grid.loads += 1;
            if (grid.hold) await grid.hold;
            if (grid.fails) return;
            grid.tiles = grid.tiles.concat(order.slice(grid.loaded * 2, grid.loaded * 2 + 2));
            grid.loaded += 1;
            // As the tabs' own load does, a part come clears the status.
            grid.status('');
        },
        show: (index) => grid.shown.push(index),
        status: (text) => grid.said.push(text),
        view: () => grid.v,
    };
    return grid;
}

let made = 0;
/** A Previous Position over `grid`, with `ids` noted - the tile left, innermost first. */
function place(grid, ids) {
    made += 1;
    current = grid;
    const p = previousPosition({ id: `place_btn_${made}`, action: 'test.place', row: '#place_row',
                                 storageKey: `place_${made}`, grid, ...TILE_BUTTON });
    p.remember(ids);
    return p;
}
const generations = (n) => Array.from({ length: n }, (_, i) => `generation:${n - i}`);
// The button as it stands: disabled, busy, its circle, its words.
const button = () => document.getElementById(`place_btn_${made}`);
const looks = () => [Boolean(button()?.disabled), button()?.getAttribute('aria-busy') ?? null,
                     Boolean(button()?.querySelector('.mm-btn-spinner')), button()?.textContent];

// ------------------------------------------------------------ in the parts loaded
let grid = standIn(generations(6));
await place(grid, ['image:60', 'generation:6']).restore();
check('a tile in the part loaded is brought into view, nothing loaded', [grid.shown, grid.loads], [[0], 0]);
check('found at once, the button never turned busy', looks(), [false, null, false, '↓ Back to image']);
check('and no scroll to a height', scrolls.length, 0);

// ------------------------------------------------------------ pushed down by newer batches
// Generation 3 was the first tile when noted; three generated since.
grid = standIn(generations(6));
await place(grid, ['image:30', 'generation:3']).restore();
check('pushed into the second part, it is loaded and brought into view', [grid.shown, grid.loads], [[3], 1]);
check('the status cleared once found', grid.said.at(-1), '');

// ------------------------------------------------------------ the batch that holds the image
// Noted inside a batch, at its second image; the top level shows batches.
grid = standIn(generations(6));
await place(grid, ['image:21', 'generation:2', 'group:model:v1']).restore();
check('at a level of batches, the batch holding the image', grid.shown, [4]);

// ------------------------------------------------------------ gone
grid = standIn(generations(6));
await place(grid, ['image:990', 'generation:99']).restore();
check('a tile in none of the parts: every part loaded, nothing brought into view',
      [grid.loads, grid.shown, scrolls.length], [2, [], 0]);
check('the status says so', grid.said.at(-1), 'The image you left is not in this view: none of its tiles is it, or holds it.');

// ------------------------------------------------------------ 20 parts, then asked
grid = standIn(generations(60));
const deep = ['generation:11'];   // tile 49: part 25 of 30
answer = false;
await place(grid, deep).restore();
check(`${SEEK_PARTS} parts are looked through, then the person is asked`,
      [SEEK_PARTS, asked.length, asked[0]?.parts], [20, 1, 20]);
check('the question says how many tiles were looked through',
      asked[0]?.question.startsWith('The image you left is not in the 40 tiles loaded here.'), true);
check('told no, it stops there: nothing more loaded, nothing brought into view',
      [grid.loaded, grid.shown, grid.said.at(-1)], [20, [], '']);
answer = true;
const again = place(grid, deep);
await again.restore();
check('pressed again, asked again at once, and told yes it loads on until the tile comes',
      [asked.length, asked[1]?.parts, grid.loaded, grid.shown], [2, 20, 25, [49]]);

// ------------------------------------------------------------ a new grid meanwhile
grid = standIn(generations(6));
let release;
grid.hold = new Promise((resolve) => { release = resolve; });
const held = place(grid, ['generation:1']);
// No layout here: the button measures as a browser drew it.
button().getBoundingClientRect = () => ({ width: 125.8, height: 36 });
const looking = held.restore();
check('while a part is on its way: busy, the circle, Looking..., and a stop square',
      [...looks(), Boolean(button()?.querySelector('.mm-btn-spinner + .mm-btn-stop, .mm-btn-stop'))],
      [false, 'true', true, 'Looking...', true]);
check('its tooltip says what it is doing, and that a press stops it', button()?.title,
      'Looking for the image you left. Press to stop.');
check('held at its width, so what follows in the row stays put', button()?.style.width, '125.8px');
grid.v += 1;   // a reload, or Back, while its part was on its way
release();
await looking;
check('a new grid while it looks ends the search', [grid.loads, grid.shown], [1, []]);
check('and the button is as it was', [...looks(), button()?.title, button()?.style.width],
      [false, 'false', false, '↓ Back to image', TILE_BUTTON.tip, '']);

// ------------------------------------------------------------ a part that does not come
grid = standIn(generations(6));
grid.fails = true;
await place(grid, ['generation:1']).restore();
check('a part that did not come is not asked for again', [grid.loads, grid.shown], [1, []]);

// ------------------------------------------------------------ Stop
// Pressed while it looks, the button stops it: at once on the page, and the
// part already on its way is let come, nothing asked after it.
const STOPPED = 'Stopped looking for the image you left.';
grid = standIn(generations(6));
grid.hold = new Promise((resolve) => { release = resolve; });
const stopped = place(grid, ['generation:1']);
const search = stopped.restore();
stopped.restore();
check('pressed while it looks, the button is itself again at once', looks(), [false, 'false', false, '↓ Back to image']);
check('and the status says it stopped', grid.said.at(-1), STOPPED);
release();
await search;
check('the part on its way comes, and nothing more is asked for, nothing brought into view',
      [grid.loads, grid.shown], [1, []]);
check('the status still says it stopped, after that part came', grid.said.at(-1), STOPPED);

// Pressed once more before that part has come: a new search, once the
// stopped one has ended.
grid = standIn(generations(6));
grid.hold = new Promise((resolve) => { release = resolve; });
const restarted = place(grid, ['generation:1']);
const presses = [restarted.restore(), restarted.restore(), restarted.restore()];
grid.hold = null;
release();
await Promise.all(presses);
check('pressed again after Stop, it looks again once the stopped search ends, on from the part that came',
      [grid.loads, grid.shown], [2, [5]]);

// ------------------------------------------------------------ no tile noted
grid = standIn(generations(6));
window.scrollY = 1200;
const height = place(grid, null);
window.scrollY = 0;
await height.restore();
check('a place that names no tile goes back to its height', [grid.loads, scrolls], [0, [1200]]);

done();
