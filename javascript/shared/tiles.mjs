/**
 * The tile grid both the Generations tab and the Gallery tab draw (#209): tiles
 * in columns, a wide image's tile across as many as fit it, the header of a
 * level opened inside another - Back, the way there, what it is - and the next
 * part asked for as the grid's end comes near. Each tab keeps its own tiles,
 * levels and parts, and draws its own tiles' insides; what they draw alike is
 * here, once, so a fix lands in both.
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
