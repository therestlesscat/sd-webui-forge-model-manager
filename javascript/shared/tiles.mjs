/**
 * The tile grid both the Generations tab and the Civitai Images tab draw (#209): tiles
 * in columns, a wide image's tile across as many as fit it, the header of a
 * level opened inside another - Back, the way there, what it is - and the next
 * part asked for as the grid's end comes near. Each tab keeps its own tiles,
 * levels and parts, and draws its own tiles' insides; what they draw alike is
 * here, once, so a fix lands in both.
 *
 * Two ways to place the tiles, a setting each tab has (#240): Classic, the
 * browser's grid, every tile on the page; and Fast, the default, placed here
 * by the same rule, with only the rows near the view on the page.
 *
 * Nothing here runs as it is imported: a tab calls what it needs.
 */

const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');

// How near the end of the grid the next part is asked for.
export const LOAD_AHEAD_PX = 800;
// The most columns a wide image's tile takes.
export const MAX_SPAN = 4;

/**
 * Whether an image gets a horizontal card - two columns or more, as tall as
 * the rest - rather than a vertical one: wider than it is tall. A folded
 * batch or a group goes by its first image.
 */
export function wide(image) {
    return Number(image?.width) > Number(image?.height);
}

/** An image's width over its height, or 1 when it is not known. */
export function aspect(image) {
    const ratio = Number(image?.width) / Number(image?.height);
    return Number.isFinite(ratio) && ratio > 0 ? Math.round(ratio * 1000) / 1000 : 1;
}

/**
 * How many columns a tile takes: as many as come nearest the width its image
 * would have at the tiles' height, so it is cropped least - a vertical one
 * one, a wide one from 2 up to MAX_SPAN, and never more than there are.
 *
 * spanFor(1.46, 200, 12, 300, 6) is 2 - 438px wide, near two columns and
 * the gap (412) - 16:9 is 3, 3:1 is 4.
 */
export function spanFor(ratio, columnWidth, gap, imageHeight, columns) {
    if (!(ratio > 1) || !(columnWidth > 0)) return 1;
    const ideal = Math.round((imageHeight * ratio + gap) / (columnWidth + gap));
    return Math.min(Math.max(2, Math.min(ideal, MAX_SPAN)), Math.max(columns, 1));
}

/**
 * Give every wide tile in `grid` its columns, as the grid now is: its column
 * width, gap, tile height and how many columns fit. Again on every resize - a
 * narrower window has fewer. Nothing while the tab is hidden, where every
 * width reads 0; the stylesheet's two columns stand until then. `oneColumn`
 * (the Generations tab's Preserve order): every tile one column.
 */
export function applySpans(grid, { oneColumn = false } = {}) {
    const width = grid?.getBoundingClientRect?.().width || 0;
    const style = grid && window.getComputedStyle?.(grid);
    const px = (name) => parseFloat(style?.getPropertyValue(name)) || 0;
    const column = px('--gen-column-width');
    const gap = px('--gen-gap');
    const height = px('--gen-image-height');
    if (!width || !column || !height) return;
    const columns = Math.floor((width + gap) / (column + gap));
    for (const tile of grid.querySelectorAll('.gen-tile.gen-wide')) {
        const span = oneColumn ? 1
            : spanFor(Number(tile.getAttribute('data-aspect')), column, gap, height, columns);
        tile.style.gridColumn = `span ${span}`;
    }
}

/**
 * Make a column as wide as a tile's buttons need, in one row, if that is more
 * than the gallery's image width: however the fonts and buttons come out, the
 * row stays one row. Measured, since it cannot be known from here; nothing is
 * measured while the tab is hidden, where every width reads 0.
 */
export function fitColumns(app, grid) {
    const tile = grid?.querySelector('.gen-tile:not(.gen-wide)') || grid?.querySelector('.gen-tile');
    const actions = tile?.querySelector('.gen-actions');
    if (!app || !actions || !actions.scrollWidth) return;
    const style = window.getComputedStyle?.(tile);
    const frame = ['paddingLeft', 'paddingRight', 'borderLeftWidth', 'borderRightWidth']
        .reduce((sum, key) => sum + (parseFloat(style?.[key]) || 0), 0);
    const needed = Math.ceil(actions.scrollWidth + frame);
    const current = parseFloat(window.getComputedStyle?.(app)?.getPropertyValue('--gen-column-width')) || 0;
    if (needed > current) app.style.setProperty('--gen-column-width', `${needed}px`);
}

/** Columns wide enough for the buttons, then each tile's span over them. */
export function layoutTiles(app, grid, options = {}) {
    fitColumns(app, grid);
    applySpans(grid, options);
}

/**
 * The header of a level inside another: Back - `back`, the action it calls -
 * the way here, and what the level is, in `facts`.
 */
export function pathHtml({ trail, facts = [], back }) {
    return `
        <div class="gen-path">
            <button type="button" class="mm-btn secondary mm-btn-small" data-action="${escapeHtml(back)}"
                    title="Back to where you were (Esc)">← Back</button>
            <div class="gen-path-text">
                <div class="gen-path-trail">${trail.map((t) => `<span>${escapeHtml(t)}</span>`).join(' <span class="gen-path-sep">›</span> ')}</div>
                ${facts.length ? `<div class="gen-path-facts">${escapeHtml(facts.join(' · '))}</div>` : ''}
            </div>
        </div>`;
}

/**
 * Whether the end of the grid - `sentinel`, an element after it - is near
 * enough to ask for the next part. Never while the tab is hidden, where
 * everything reads as in view.
 */
export function endIsNear(sentinel) {
    if (!sentinel || sentinel.offsetParent === null) return false;
    const top = sentinel.getBoundingClientRect?.().top;
    return typeof top === 'number' && top < (window.innerHeight || 0) + LOAD_AHEAD_PX;
}

/**
 * Call `near` as the end of the grid comes into sight - scrolled to, or an
 * observer's word - through `scope`, which takes both back when the tab
 * stops. The caller asks again after every part: the observer only tells of
 * a change, and a part that leaves the end in view would be the last.
 */
export function watchEnd(scope, sentinel, near) {
    if (!sentinel || !('IntersectionObserver' in window)) return;
    scope.observe(new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) near();
    }, { rootMargin: `${LOAD_AHEAD_PX}px 0px` })).observe(sentinel);
    scope.listen(window, 'scroll', near, { passive: true });
}

/** How far the page is scrolled. */
export function currentScroll() {
    return window.scrollY || document.documentElement?.scrollTop || 0;
}

/** Where `app` starts on the page, to show a new level from its top. */
export function topOf(app) {
    const top = app?.getBoundingClientRect?.().top;
    return typeof top === 'number' ? Math.max(0, top + currentScroll()) : 0;
}

// ------------------------------------------------------------ Fast: placed by the tab
// A grid the browser places packs every tile again whenever one is added:
// at 75,684 tiles one part froze the page for up to 42 s (#240). Fast places
// each tile here instead, by the browser's own rule, and keeps on the page
// only the rows near the view - the rest are numbers in a table.

// How far above and below the view rows stay on the page.
export const DRAW_AHEAD_PX = 3000;

/**
 * An empty placement for `columns` columns. `dense`: each tile goes in the
 * first free spot from the grid's top, as `grid-auto-flow: row dense` puts
 * it, so a narrow tile fills the hole a wide one left; otherwise on from the
 * last one, as `row` does - Preserve order, and sections, where nothing is
 * packed back above.
 */
export function newPlacement(columns, { dense = true } = {}) {
    return { columns: Math.max(1, columns), dense, rows: [], heads: [], spots: [], first: [], row: 0, col: 0 };
}

function placementRow(p, r) {
    while (p.rows.length <= r) {
        p.rows.push(new Uint8Array(p.columns));
        p.heads.push(false);
    }
    return p.rows[r];
}

/** The first column from `from` where `span` columns of `row` are free, or -1. */
function freeColumn(row, span, from = 0) {
    for (let col = from; col + span <= row.length; col += 1) {
        let free = true;
        for (let c = col; c < col + span && free; c += 1) free = !row[c];
        if (free) return col;
    }
    return -1;
}

/**
 * Place `items` - each `{span, head}`, `head` when a section's header comes
 * before it on a row of its own - after the tiles placed before, and return
 * their spots: `{row, col, span, head}`, `head` the header's row or -1. The
 * browser's grid places the same items in the same spots: a header's column
 * is set, so it goes to the next empty row; a tile's is not, so it goes to
 * the first spot it fits, from the top or from the last tile.
 */
export function placeTiles(p, items) {
    return items.map(({ span = 1, head = false }) => {
        const width = Math.min(Math.max(1, Math.floor(span) || 1), p.columns);
        let headRow = -1;
        if (head) {
            let r = p.dense ? p.rows.length : p.row + (p.col > 0 ? 1 : 0);
            while (r < p.rows.length && p.rows[r].some(Boolean)) r += 1;
            placementRow(p, r).fill(1);
            p.heads[r] = true;
            headRow = r;
            p.row = r;
            p.col = 0;
        }
        let row;
        let col;
        if (p.dense) {
            // The rows before first[width] are too full for this width, and
            // stay so: rows only fill.
            row = p.first[width] || 0;
            for (;; row += 1) {
                col = freeColumn(placementRow(p, row), width);
                if (col >= 0) break;
            }
            p.first[width] = row;
        } else {
            row = p.row;
            col = p.col;
            for (;;) {
                const at = freeColumn(placementRow(p, row), width, col);
                if (at >= 0) {
                    col = at;
                    break;
                }
                row += 1;
                col = 0;
            }
            p.row = row;
            p.col = col;
        }
        p.rows[row].fill(1, col, col + width);
        const spot = { row, col, span: width, head: headRow };
        p.spots.push(spot);
        return spot;
    });
}

/**
 * One tab's grid, placed by the tab: its tiles' spots, and the rows near the
 * view on the page. The tab keeps its tiles and draws each one; this asks it
 * for them by number.
 *
 * - `grid()`, `app()`: the grid and the tab's box, found afresh each time.
 * - `count()`: how many tiles the tab holds; `html(index)`: a tile's set, as
 *   the tab draws it; `imageOf(index)`: the image its width goes by.
 * - `head(index)`: whether its set starts with a section's header.
 * - `oneColumn()`: every tile one column (Preserve order); `dense()`: whether
 *   later tiles may fill holes above.
 * - `drawn(grid)`: after sets came onto the page - their images to load.
 *
 * What it adds to the page - its scroll listener - goes through `scope`.
 */
export function placedGrid({ scope, grid, app, count, html, imageOf, head = () => false,
                             oneColumn = () => false, dense = () => true, drawn = () => {} }) {
    let p = null;               // the placement, null until the grid can be measured
    let size = null;            // what it was placed for
    let rowSets = [];           // the tiles on each row
    let tops = [];              // each row's top, in the grid
    let tileHeight = 0;         // the tallest tile drawn since the placement began
    let headHeight = 0;
    let measured = false;       // whether tileHeight is a tile's, or a guess
    let height = -1;
    const shown = new Map();    // a tile's number -> its set on the page
    let frame = 0;

    function measure(el) {
        const width = el?.getBoundingClientRect?.().width || 0;
        const style = window.getComputedStyle?.(el);
        const px = (name) => parseFloat(style?.getPropertyValue(name)) || 0;
        const column = px('--gen-column-width');
        const gap = px('--gen-gap');
        if (!width || !column) return null;
        return { column, gap, image: px('--gen-image-height'), sectionGap: px('--gen-section-gap'),
                 columns: Math.max(1, Math.floor((width + gap) / (column + gap))) };
    }

    const sameSize = (a, b) => a && b && a.column === b.column && a.gap === b.gap
        && a.image === b.image && a.columns === b.columns;

    function spanOf(index) {
        const image = imageOf(index);
        if (oneColumn() || !wide(image)) return 1;
        return spanFor(aspect(image), size.column, size.gap, size.image, size.columns);
    }

    const rowHeight = (r) => (p.heads[r] ? (r ? size.sectionGap : 0) + headHeight : tileHeight);

    function setTops() {
        tops = new Array(p.rows.length);
        let y = 0;
        for (let r = 0; r < p.rows.length; r += 1) {
            tops[r] = y;
            y += rowHeight(r) + size.gap;
        }
        const total = p.rows.length ? y - size.gap : 0;
        if (total !== height) {
            height = total;
            const el = grid();
            if (el) el.style.height = `${total}px`;
        }
    }

    function place(from) {
        const items = [];
        for (let i = from; i < count(); i += 1) items.push({ span: spanOf(i), head: Boolean(head(i)) });
        placeTiles(p, items).forEach((spot, k) => {
            (rowSets[spot.row] ||= []).push(from + k);
            if (spot.head >= 0) (rowSets[spot.head] ||= []).push(from + k);
        });
        setTops();
    }

    /** Place every tile the tab holds, if the grid can be measured: not while the tab is hidden. */
    function begin() {
        const el = grid();
        size = measure(el);
        if (!size) return false;
        el.classList.add('gen-placed');
        // Until a tile is drawn and measured: its image and a row of buttons.
        tileHeight ||= size.image + 40;
        headHeight ||= 30;
        p = newPlacement(size.columns, { dense: dense() });
        place(0);
        return true;
    }

    function forget() {
        shown.forEach((set) => set.remove());
        shown.clear();
        p = null;
        rowSets = [];
        tops = [];
    }

    // The first row whose bottom is below `y`.
    function rowAt(y) {
        let lo = 0;
        let hi = tops.length;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (tops[mid] + rowHeight(mid) <= y) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    const topOfTile = (index) => tops[p.spots[index].head >= 0 ? p.spots[index].head : p.spots[index].row];

    /** Run `change`, the tile at the top of the view kept where it is on the screen. */
    function keepingPlace(change) {
        const top = grid()?.getBoundingClientRect?.().top;
        let anchor = -1;
        let before = 0;
        if (p && typeof top === 'number' && top < 0) {
            anchor = (rowSets[rowAt(-top)] || [])[0] ?? -1;
            if (anchor >= 0) before = topOfTile(anchor);
        }
        change();
        if (anchor >= 0 && p?.spots[anchor]) {
            const moved = topOfTile(anchor) - before;
            if (moved) window.scrollTo?.(0, currentScroll() + moved);
        }
    }

    function position(index, set) {
        const spot = p.spots[index];
        const tile = set.querySelector?.('.gen-tile');
        if (tile) {
            tile.style.left = `${spot.col * (size.column + size.gap)}px`;
            tile.style.top = `${tops[spot.row]}px`;
            tile.style.width = `${spot.span * size.column + (spot.span - 1) * size.gap}px`;
        }
        const header = spot.head >= 0 && set.querySelector?.('.gen-section-head');
        if (header) {
            header.style.left = '0px';
            header.style.top = `${tops[spot.head] + (spot.head ? size.sectionGap : 0)}px`;
            header.style.width = `${size.columns * size.column + (size.columns - 1) * size.gap}px`;
        }
    }

    function setsOf(indexes) {
        const box = document.createElement('div');
        box.innerHTML = indexes.map((i) => html(i)).join('');
        return [...box.children];
    }

    // New sets go in among those shown in order, so the page reads in order.
    function insert(el, missing) {
        const after = [...shown.keys()].sort((a, b) => a - b);
        let k = 0;
        let run = [];
        let next = null;
        const flush = () => {
            if (!run.length) return;
            const sets = setsOf(run);
            sets.forEach((set, n) => {
                shown.set(run[n], set);
                position(run[n], set);
            });
            const part = document.createDocumentFragment();
            sets.forEach((set) => part.appendChild(set));
            el.insertBefore(part, next);
            run = [];
        };
        for (const index of missing) {
            while (k < after.length && after[k] < index) k += 1;
            const before = k < after.length ? shown.get(after[k]) : null;
            if (run.length && before !== next) flush();
            next = before;
            run.push(index);
        }
        flush();
    }

    /**
     * Rows are as tall as the tallest tile drawn: tiles differ only by the
     * rating row. A taller one moves the rows, the view kept on its tile.
     */
    function measureDrawn() {
        let tallest = 0;
        let header = 0;
        shown.forEach((set) => {
            tallest = Math.max(tallest, set.querySelector?.('.gen-tile')?.offsetHeight || 0);
            header = Math.max(header, set.querySelector?.('.gen-section-head')?.offsetHeight || 0);
        });
        const taller = tallest && (!measured || tallest > tileHeight);
        if (!taller && (!header || header === headHeight)) return false;
        keepingPlace(() => {
            if (taller) {
                tileHeight = tallest;
                measured = true;
            }
            if (header) headHeight = header;
            setTops();
            shown.forEach((set, index) => position(index, set));
        });
        return true;
    }

    /** The rows near the view on the page, and no others. */
    function draw() {
        frame = 0;
        const el = grid();
        // Hidden, the grid measures nothing: a scroll in another tab leaves it as it is.
        if (!p || !el || !measure(el)) return;
        const top = el.getBoundingClientRect?.().top || 0;
        const from = -top - DRAW_AHEAD_PX;
        const to = -top + (window.innerHeight || 0) + DRAW_AHEAD_PX;
        // A set the tab took off the page itself - the grid emptied - is drawn again.
        shown.forEach((set, index) => {
            if (set.parentNode !== el) shown.delete(index);
        });
        const near = new Set();
        const held = count();
        for (let r = rowAt(from); r < tops.length && tops[r] < to; r += 1) {
            (rowSets[r] || []).forEach((index) => { if (index < held) near.add(index); });
        }
        shown.forEach((set, index) => {
            if (!near.has(index)) {
                set.remove();
                shown.delete(index);
            }
        });
        const missing = [...near].filter((index) => !shown.has(index)).sort((a, b) => a - b);
        if (!missing.length) return;
        insert(el, missing);
        drawn(el);
        // Columns as wide as a tile's buttons need: measured on a drawn one.
        fitColumns(app(), el);
        if (!sameSize(measure(el), size)) {
            replace();
            return;
        }
        if (measureDrawn()) draw();
    }

    function schedule() {
        if (frame || !p) return;
        const later = window.requestAnimationFrame || ((fn) => setTimeout(fn, 16));
        frame = later(draw);
    }

    /** Every tile placed again: the columns, a width or the order changed. */
    function replace() {
        keepingPlace(() => {
            forget();
            if (count()) begin();
        });
        draw();
    }

    scope?.listen(window, 'scroll', schedule, { passive: true });

    return {
        /** Place the tiles the tab added since, and draw what is near. */
        add() {
            if (!p) {
                if (begin()) draw();
                return;
            }
            if (p.dense !== dense()) {
                replace();
                return;
            }
            place(p.spots.length);
            draw();
        },
        /** One tile drawn again, as the tab now draws it: where it is, if it is on the page. */
        redraw(index) {
            if (!p || !p.spots[index]) return;
            if (Math.min(spanOf(index), p.columns) !== p.spots[index].span
                || Boolean(head(index)) !== (p.spots[index].head >= 0)) {
                replace();
                return;
            }
            const set = shown.get(index);
            if (!set) return;
            const [fresh] = setsOf([index]);
            if (!fresh) return;
            set.replaceWith(fresh);
            shown.set(index, fresh);
            position(index, fresh);
            drawn(grid());
            if (measureDrawn()) draw();
        },
        replace,
        /**
         * The grid emptied: start again from its first tile. New tiles - a
         * reload - and it is as tall as nothing until they are placed, as
         * the browser's grid is. The same tiles drawn again - Rate, Select,
         * one taken out - and it keeps its height until they are: measuring
         * it collapsed, the browser would pull the page back to the top. The
         * tiles' height last measured stands until a tile is measured again.
         */
        reset({ keepHeight = false } = {}) {
            forget();
            measured = false;
            height = -1;
            const el = grid();
            if (el && !keepHeight) el.style.height = '';
        },
        /** The grid measured again: a resize, or the tab shown. */
        relayout() {
            if (!p) {
                if (count() && begin()) draw();
                return;
            }
            const now = measure(grid());
            if (!now) return;
            if (!sameSize(now, size)) replace();
            else schedule();
        },
        /** Bring a tile into view, as `scrollIntoView` with `nearest` would, and draw it. */
        scrollTo(index) {
            const el = grid();
            if (!p || !el || !p.spots[index]) return;
            const spot = p.spots[index];
            const top = (el.getBoundingClientRect?.().top || 0) + topOfTile(index);
            const bottom = (el.getBoundingClientRect?.().top || 0) + tops[spot.row] + rowHeight(spot.row);
            const view = window.innerHeight || 0;
            if (top < 0) window.scrollTo?.(0, currentScroll() + top);
            else if (bottom > view) window.scrollTo?.(0, currentScroll() + bottom - view);
            draw();
        },
        /** Back to the browser's own grid. */
        off() {
            forget();
            height = -1;
            const el = grid();
            el?.classList.remove('gen-placed');
            if (el) el.style.height = '';
        },
        /** Whether the tile is on the page now. */
        isDrawn: (index) => shown.has(index),
    };
}
