/**
 * Both tabs' grids, and the settings window's card previews, are drawn here:
 * a card, the page strip under the grid, and the grid itself, its rows kept
 * even at the card size a tab sets. They take what to show and read no
 * setting; each tab turns its own data into that.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, formatNumber } = await shared('core.mjs');
const { mediaFallback } = await shared('media.mjs');

/**
 * A model's reception, as Civitai reports it since star ratings went away.
 *
 * Renders nothing when nobody has voted, so a card is not cluttered with
 * two zeroes. A down count of zero still shows once there are up votes,
 * because "52.9K up, 0 down" is worth knowing.
 */
export function renderThumbs(up, down) {
    const ups = Number(up) || 0;
    const downs = Number(down) || 0;
    if (!ups && !downs) return '';

    const total = ups + downs;
    const share = Math.round((ups / total) * 100);
    const title = `${ups.toLocaleString()} up, ${downs.toLocaleString()} down (${share}% positive)`;

    return `<span class="mm-thumbs" title="${escapeHtml(title)}">`
         + `<span class="mm-thumbs-up">▲ ${formatNumber(ups)}</span>`
         + `<span class="mm-thumbs-down">▼ ${formatNumber(downs)}</span>`
         + `</span>`;
}

/**
 * How many columns to lay a page of cards out in, so its rows come out even.
 *
 * Use the fewest rows the width allows, then spread the cards across them:
 * ten cards with room for nine is 5 + 5, not 9 + 1, and stays 5 + 5 down to
 * room for five. Only when another row is unavoidable does it change - room
 * for four is 4 + 4 + 2, which is as even as equal columns get.
 */
export function balancedColumns(cardCount, fit) {
    if (cardCount < 1 || fit < 1) return Math.max(fit, 1);
    const rows = Math.ceil(cardCount / fit);
    return Math.ceil(cardCount / rows);
}

/**
 * Keep a card grid's rows even: cap its card list at the balanced column
 * count, so the flex-wrap layout wraps there.
 *
 * Call it after each render. The first call also starts watching the grid's
 * width, so a resize re-balances it. The card width is measured from the
 * cards, so the card size setting needs no wiring of its own; a hidden tab
 * has no width and is left as it was until it is shown.
 *
 * @param {string} gridId - the element holding the .model-grid-inner list.
 */
export function balanceGridRows(gridId) {
    const grid = document.getElementById(gridId);
    const inner = grid?.querySelector('.model-grid-inner');
    if (!inner) return;
    watchGridWidth(gridId, grid);

    const cards = inner.querySelectorAll('.model-card');
    const cardWidth = cards[0]?.getBoundingClientRect().width || 0;
    const available = grid.clientWidth;
    if (!cards.length || !cardWidth || !available) return;

    const gap = parseFloat(window.getComputedStyle(inner).columnGap) || 0;
    const fit = Math.max(1, Math.floor((available + gap) / (cardWidth + gap)));
    const cols = balancedColumns(cards.length, fit);
    inner.style.maxWidth = `${Math.ceil(cols * cardWidth + (cols - 1) * gap)}px`;
    // For what sits over the grid and should line up with its cards - the
    // Model Manager's tabs.
    grid.parentElement?.style.setProperty('--mm-grid-width', inner.style.maxWidth);
}

// One observer per grid element. Capping the inner list's width does not
// change the grid's own, so an observer cannot feed itself.
const gridObservers = new Map();   // gridId -> { grid, observer }
function watchGridWidth(gridId, grid) {
    if (gridObservers.get(gridId)?.grid === grid || typeof ResizeObserver !== 'function') return;
    gridObservers.get(gridId)?.observer.disconnect();   // the tab's markup was replaced
    let lastWidth = -1;
    const observer = new ResizeObserver(() => {
        if (grid.clientWidth === lastWidth) return;
        lastWidth = grid.clientWidth;
        balanceGridRows(gridId);
    });
    observer.observe(grid);
    gridObservers.set(gridId, { grid, observer });
}

/**
 * Push a card size onto a container. Every card is sized by one rule from
 * --mm-card-width and --mm-card-height, so a card takes the size of the
 * container it is in: a tab, or the settings window's preview row.
 */
export function applyCardSize({ width, height, containerId, logTag }) {
    const container = document.getElementById(containerId);
    if (!container) return;
    setCardSize(container, width, height);
    console.log(`[${logTag}] Card size set to ${width}x${height}`);
}

/** The same, on an element already in hand. */
export function setCardSize(element, width, height) {
    element.style.setProperty('--mm-card-width', `${width}px`);
    element.style.setProperty('--mm-card-height', `${height}px`);
}

/** What a card shows when it has no image, or its image does not load. */
export const CARD_PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect fill='%23333' width='100' height='100'/%3E%3Ctext x='50' y='50' text-anchor='middle' dy='.3em' fill='%23666' font-size='10'%3ENo Image%3C/text%3E%3C/svg%3E";

// A card's name is cut to this many characters, with "..." after.
const CARD_NAME_LENGTH = 30;

/**
 * One model card.
 *
 * Every text is escaped here, and a name is cut before it is escaped, so an
 * entity is never cut in half. The markup - its classes and their nesting -
 * is what the stylesheet, balanceGridRows(), the selection highlight and the
 * bookmark star patched in place all look for.
 *
 * @param {object} card
 * @param {number} card.index - its place in the grid, as data-index.
 * @param {string} card.onclick - what a click runs, e.g. "window.mmSelectModel(3)".
 * @param {string} card.name - the model's name, in full; the card cuts it.
 * @param {{src: string, video: boolean, original?: string}} [card.media] - the
 *     card image's URL, as cardMediaUrl() gives it, and the upload's, to fall
 *     back to; none, or an empty src, shows the placeholder.
 * @param {string[]} [card.classes] - added to model-card: owned, nsfw-x, ...
 * @param {Object<string, string|number>} [card.data] - data- attributes.
 * @param {{cls: string, text: string, title?: string, onclick?: string}[]} [card.overlays] -
 *     on the image: Owned, No Civitai Data, the bookmark star. One with an
 *     onclick is a button, whose click is its own, not the card's.
 * @param {{cls: string, text: string, title?: string}[]} [card.badges] -
 *     under the name: type, base model, versions.
 * @param {({text: string, title?: string}|{html: string})[]} [card.stats] -
 *     the bottom row. `html` is for renderThumbs(), which escapes its own.
 * @returns {string} the card's HTML.
 */
export function renderModelCard({ index, onclick, name, media, classes = [], data = {},
                                  overlays = [], badges = [], stats = [] }) {
    const full = name || 'Unknown';
    const shown = full.length > CARD_NAME_LENGTH ? full.substring(0, CARD_NAME_LENGTH) + '...' : full;
    const title = (item) => (item.title ? ` title="${escapeHtml(item.title)}"` : '');
    const src = media?.src || '';
    const image = !src
        ? `<img src="${CARD_PLACEHOLDER}" alt="${escapeHtml(full)}">`
        : media.video
            ? `<video src="${escapeHtml(src)}" loop muted autoplay playsinline ${mediaFallback(media.original)}></video>`
            : `<img src="${escapeHtml(src)}" alt="${escapeHtml(full)}" loading="lazy" ${mediaFallback(media.original, CARD_PLACEHOLDER)}>`;
    const attributes = Object.entries(data)
        .map(([key, value]) => ` data-${key}="${escapeHtml(value ?? '')}"`).join('');
    return `
        <div class="${['model-card', ...classes.filter(Boolean)].join(' ')}" data-index="${Number(index)}"${attributes} onclick="${escapeHtml(onclick)}">
            <div class="model-card-image">
                ${image}
                ${overlays.map((o) => (o.onclick
                    ? `<button type="button" class="${escapeHtml(o.cls)}"${title(o)} onclick="event.stopPropagation(); ${escapeHtml(o.onclick)}">${escapeHtml(o.text)}</button>`
                    : `<div class="${escapeHtml(o.cls)}"${title(o)}>${escapeHtml(o.text)}</div>`)).join('')}
            </div>
            <div class="model-card-info">
                <div class="model-card-name" title="${escapeHtml(full)}">${escapeHtml(shown)}</div>
                <div class="model-card-meta">
                    ${badges.map((b) => `<span class="badge ${escapeHtml(b.cls)}"${title(b)}>${escapeHtml(b.text)}</span>`).join('')}
                </div>
                <div class="model-card-stats">
                    ${stats.map((s) => (s.html !== undefined ? s.html : `<span${title(s)}>${escapeHtml(s.text)}</span>`)).join('')}
                </div>
            </div>
        </div>
    `;
}

/**
 * The page strip under a grid: Prev, five page numbers around the current
 * one with the first and last beyond them, Next.
 *
 * It shows only the pages it is told exist and never works out a count: the
 * Model Manager knows its last page, the Civitai Browser only how far it has
 * been, and whether Civitai has more. Prev is disabled on page 1, Next when
 * there is no page after this one.
 *
 * @param {object} p
 * @param {number} p.current - the page shown.
 * @param {number} p.last - the highest page there is to go to.
 * @param {boolean} p.hasNext - whether there is a page after this one; it may
 *     not be numbered yet.
 * @param {string} p.goTo - the window function a page number calls, with it.
 * @param {string} p.prev - the window function Prev calls.
 * @param {string} p.next - the window function Next calls.
 */
export function renderGridPagination({ current, last, hasNext, goTo, prev, next }) {
    const visible = 5;
    let start = Math.max(1, current - Math.floor(visible / 2));
    const end = Math.min(last, start + visible - 1);
    if (end - start < visible - 1) start = Math.max(1, end - visible + 1);

    const pages = [];
    if (start > 1) {
        pages.push(1);
        if (start > 2) pages.push(null);
    }
    for (let page = start; page <= end; page++) pages.push(page);
    if (end < last) {
        if (end < last - 1) pages.push(null);
        pages.push(last);
    }

    const numbers = pages.map((page) => (page === null
        ? '<span class="mm-page-ellipsis">...</span>'
        : `<button class="mm-page-num ${page === current ? 'active' : ''}" onclick="window.${goTo}(${page})">${page}</button>`
    )).join('');
    return `
        <div class="mm-pagination">
            <button class="mm-btn mm-page-btn" onclick="window.${prev}()" ${current <= 1 ? 'disabled' : ''}>
                ← Prev
            </button>
            <div class="mm-page-numbers">
                ${numbers}
            </div>
            <button class="mm-btn mm-page-btn" onclick="window.${next}()" ${hasNext ? '' : 'disabled'}>
                Next →
            </button>
        </div>
    `;
}

/**
 * A grid: its cards and the page strip under them, or a line saying why
 * there are none. Its rows are then balanced.
 *
 * @param {object} g
 * @param {string} g.gridId - the element to draw into.
 * @param {string[]} g.cards - renderModelCard()'s HTML, one per card.
 * @param {string} g.empty - the line shown when there are no cards.
 * @param {string} [g.pagination] - renderGridPagination()'s HTML, if the tab shows it.
 */
export function renderModelGrid({ gridId, cards, empty, pagination = '' }) {
    const grid = document.getElementById(gridId);
    if (!grid) return;
    if (!cards.length) {
        grid.innerHTML = `<div class="model-grid-empty">${escapeHtml(empty)}</div>`;
        return;
    }
    grid.innerHTML = `<div class="model-grid-inner">${cards.join('')}</div>${pagination}`;
    balanceGridRows(gridId);
}
