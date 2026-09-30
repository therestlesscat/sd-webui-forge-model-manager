/**
 * The Generations tab: every image you have generated, newest first.
 *
 * A tile per generation - a batch its first four images and how many it has
 * - or, with "Group by", a tile per group of images: the same prompt, model,
 * LoRAs, size or day, whatever generations they are of. A click on a batch or
 * a group opens it in a grid of its own, in place of this one - a group onto
 * its generations, a batch onto its images, as deep as it goes - with Back,
 * which lands where the grid was left. A click on an image opens the viewer,
 * large, with ← and → through the images the grid shows and its information
 * beside it. Each image sends its own infotext back to the tab it was made
 * in, or is deleted. The grid scrolls: the next part loads as its end comes
 * near. Only the NSFW switch applies; nothing is hidden here for its prompt.
 *
 * The server does the filtering, the grouping and the parts
 * (api/generations.browse_page). The paste into txt2img or img2img is the
 * Model Manager's, on window (window.mmSendInfotext): it lives in that tab's
 * script, loaded with this.
 */

// The shared module, asked for with this script's own version: see the top of
// civitai_browser.mjs for why this is not a plain import.
const sharedModule = new URL('./shared/common.mjs', import.meta.url);
sharedModule.search = new URL(import.meta.url).search;

const {
    onReady,
    apiCall,
    escapeHtml,
    mediaFallback,
    setupLazyMedia,
    renderFilterBanner,
    nsfwBadgeLabel,
    nsfwModelNote,
    galleryDefaults,
    ratingRowHtml,
    IMAGE_PLACEHOLDER_SVG,
} = await import(sharedModule.href);

const viewerModule = new URL('./shared/viewer.mjs', import.meta.url);
viewerModule.search = sharedModule.search;
const {
    openViewer, closeViewer, showImage, viewerIndex, viewerIsOpen, askToDelete, dialogShowing,
} = await import(viewerModule.href);

const settingsModule = new URL('./shared/settings.mjs', import.meta.url);
settingsModule.search = sharedModule.search;
await import(settingsModule.href);

// "Preserve order" and "Group by", remembered in this browser.
const PRESERVE_ORDER_KEY = 'mm_generations_preserve_order';
const GROUP_BY_KEY = 'mm_generations_group_by';
// How near the end of the grid the next part is asked for.
const LOAD_AHEAD_PX = 800;
// The most columns a wide image's tile takes.
const MAX_SPAN = 4;
// What a group is called, by what the images are grouped by (GROUPINGS on the server).
const GROUP_NAMES = {
    prompt_written: 'Prompt, as written', prompt: 'Prompt, as generated', model: 'Model',
    loras: 'LoRA combination', size: 'Size', day: 'Day',
};

let preserveOrder = readFlag(PRESERVE_ORDER_KEY);
let rating = false;      // "Rate": a row of levels under every image - not remembered
let groupBy = readSetting(GROUP_BY_KEY, '');
let hideNsfw = true;
// The level shown: its tiles, as loaded, and where it is. The levels above it
// are kept whole in `levels`, so Back draws them again as they were left.
let tiles = [];          // each {kind, generation, group, images, matching_count}
let state = null;        // the totals, for the banner
let scope = null;        // what the level is, for its header
let part = 0;            // the last part loaded
let more = true;
let at = {};             // what the level is inside: {in_group, generation}
let title = '';          // what the path calls it
const levels = [];       // the levels above, each as it was left
let loading = false;
let request = 0;         // a newer load drops an older one's answer
let started = false;

function readFlag(key) {
    return readSetting(key, 'false') === 'true';
}

function readSetting(key, fallback) {
    try {
        return localStorage.getItem(key) ?? fallback;
    } catch (e) {
        return fallback;
    }
}

function writeFlag(key, value) {
    try {
        localStorage.setItem(key, String(value));
    } catch (e) { /* remembered for this visit only */ }
}

const byId = (id) => document.getElementById(id);

// ------------------------------------------------------------- loading
/** This level again from its first part: a switch, Refresh, or opening. */
async function reload() {
    closeViewer();
    tiles = [];
    part = 0;
    more = true;
    loading = false;
    request += 1;
    const grid = byId('gen_grid');
    if (grid) grid.innerHTML = '';
    renderPath();
    setStatus('Loading...');
    await loadNext();
}

/** The next part, added to the end of the grid. */
async function loadNext() {
    if (loading || !more) return;
    loading = true;
    const asked = ++request;
    try {
        const data = await apiCall({ endpoint: '/model-manager/generations/browse', params: {
            page: part + 1, hide_nsfw_images: hideNsfw, group: groupBy,
            in_group: at.in_group, generation: at.generation,
        } });
        if (asked !== request) return;
        if (!data.success) {
            setStatus(`Could not load your generations: ${data.error || 'no answer'}`);
            return;
        }
        part += 1;
        more = !!data.more;
        state = data.state;
        scope = data.scope;
        const first = tiles.length;
        tiles = tiles.concat(data.tiles || []);
        appendTiles(first);
        renderBanner();
        renderPath();
        setStatus(tiles.length ? '' : emptyText());
    } catch (error) {
        if (asked === request) setStatus(`Could not load your generations: ${error.message}`);
    } finally {
        if (asked === request) loading = false;
    }
    if (asked === request) loadIfNearEnd();
}

function emptyText() {
    if (levels.length) return 'Nothing left here.';
    if (state && state.total) return 'Every image is hidden by the NSFW filter.';
    return 'Nothing recorded yet: images you generate from now on appear here.';
}

function setStatus(text) {
    const status = byId('gen_status');
    if (status) status.textContent = text;
}

/**
 * Load the next part if the end of the grid is in sight - asked after every
 * part, since the observer only tells of a change: a part that leaves the end
 * still in view would otherwise be the last. Never while the tab is hidden,
 * where everything reads as in view.
 */
function loadIfNearEnd() {
    const sentinel = byId('gen_sentinel');
    if (!more || loading || !sentinel || sentinel.offsetParent === null) return;
    const top = sentinel.getBoundingClientRect?.().top;
    if (typeof top === 'number' && top < (window.innerHeight || 0) + LOAD_AHEAD_PX) loadNext();
}

function watchEnd() {
    const sentinel = byId('gen_sentinel');
    if (!sentinel || !('IntersectionObserver' in window)) return;
    new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadIfNearEnd();
    }, { rootMargin: `${LOAD_AHEAD_PX}px 0px` }).observe(sentinel);
    window.addEventListener('scroll', loadIfNearEnd, { passive: true });
}

// ------------------------------------------------------------- levels
/**
 * Open a batch or a group in a grid of its own, in place of this one. This
 * level is kept as it is - its tiles and where the page was scrolled - for
 * Back.
 */
window.genOpen = async function(index) {
    const tile = tiles[index];
    if (!tile) return;
    levels.push({ tiles, state, scope, part, more, at, title, scrollY: currentScroll(), dirty: false });
    if (tile.kind === 'group') {
        at = { in_group: tile.group.id };
        title = groupTitle(tile.group.value);
    } else {
        at = { in_group: at.in_group, generation: tile.generation.id };
        title = `${formatWhen(tile.generation.created_at)} · ${tile.matching_count} images`;
    }
    scope = null;
    window.scrollTo?.(0, topOfTab());
    await reload();
};

/**
 * Back to the level above, where it was left: the same tiles, drawn again, and
 * the page scrolled where it was. Loaded again only if something was deleted
 * inside - and then as far as it had been, so the place is the same.
 */
window.genBack = async function() {
    if (!levels.length) return;
    closeViewer();
    request += 1;
    loading = false;
    const above = levels.pop();
    ({ tiles, state, scope, part, more, at, title } = above);
    if (above.dirty) {
        await reloadKeepingPlace();
    } else {
        redrawAll();
        renderBanner();
    }
    renderPath();
    setStatus(tiles.length ? '' : emptyText());
    window.scrollTo?.(0, above.scrollY);
};

/** Something above this level may have changed: it loads again on Back. */
function markAboveChanged() {
    for (const level of levels) level.dirty = true;
}

function currentScroll() {
    return window.scrollY || document.documentElement?.scrollTop || 0;
}

/** Where the tab starts on the page, to show a new level from its top. */
function topOfTab() {
    const app = byId('generations_app');
    const top = app?.getBoundingClientRect?.().top;
    return typeof top === 'number' ? Math.max(0, top + currentScroll()) : 0;
}

function groupTitle(value) {
    const name = GROUP_NAMES[groupBy] || 'Group';
    const shown = value || (groupBy === 'loras' ? 'No LoRAs' : 'None');
    return `${name}: ${shown}`;
}

function formatWhen(when, style = 'short') {
    return when ? new Date(when).toLocaleString(undefined, { dateStyle: style, timeStyle: 'short' }) : '';
}

/**
 * The header of a level inside another: Back, the way here, and what the
 * level is - its whole prompt, if it is one, how many images, and when.
 */
function renderPath() {
    const path = byId('gen_path');
    if (!path) return;
    if (!levels.length) {
        path.innerHTML = '';
        return;
    }
    const trail = ['Generations', ...levels.slice(1).map((l) => l.title), title];
    const facts = [];
    if (scope) {
        facts.push(`${scope.count} image${scope.count === 1 ? '' : 's'}`);
        const first = formatWhen(scope.first);
        const last = formatWhen(scope.last);
        if (first) facts.push(first === last ? first : `${first} – ${last}`);
        const generation = scope.generation;
        if (generation) {
            facts.push(generation.mode);
            const checkpoint = (generation.checkpoint_path || '').split(/[\\/]/).pop();
            if (checkpoint) facts.push(checkpoint);
        }
    }
    path.innerHTML = `
        <div class="gen-path">
            <button type="button" class="mm-btn secondary mm-btn-small" onclick="window.genBack()"
                    title="Back to where you were (Esc)">← Back</button>
            <div class="gen-path-text">
                <div class="gen-path-trail">${trail.map((t) => `<span>${escapeHtml(t)}</span>`).join(' <span class="gen-path-sep">›</span> ')}</div>
                ${facts.length ? `<div class="gen-path-facts">${escapeHtml(facts.join(' · '))}</div>` : ''}
            </div>
        </div>`;
}

// ------------------------------------------------------------- drawing
/**
 * One tile: a group, or a batch - its first four images, how many there are,
 * and a click opens it - or one image, which a click shows in the viewer.
 */
function tileHtml(tile, index) {
    const generation = tile.generation || {};
    const folded = tile.kind === 'group' || (tile.kind === 'generation' && tile.matching_count > 1);
    const mode = generation.mode === 'img2img' ? 'img2img' : 'txt2img';
    const image = tile.images?.[0] || {};

    let media;
    if (folded) {
        const preview = tile.images.slice(0, 4);
        const what = tile.kind === 'group' ? 'group' : 'generation';
        media = `
            <div class="mm-generation-preview mm-generation-preview-${preview.length} gen-group-preview gen-openable"
                 onclick="window.genOpen(${index})" title="Open this ${what}: all ${tile.matching_count} images">
                ${preview.map((img) => imageHtml(img)).join('')}
            </div>
            <span class="gen-count">×${tile.matching_count}</span>`;
        if (tile.kind === 'group') {
            media += `<span class="gen-group-name" title="${escapeHtml(groupTitle(tile.group.value))}">`
                + `${escapeHtml(tile.group.value || (groupBy === 'loras' ? 'No LoRAs' : 'None'))}</span>`;
        }
    } else {
        media = `<div class="gen-viewable" onclick="window.genView(${index}, 0)" title="View">${imageHtml(image)}</div>`;
    }

    // More, behind ⋯ - while there is anything to offer.
    if (tileMenu(tile).length) {
        media += `<button type="button" class="gen-menu-btn" title="More"
                          onclick="event.stopPropagation(); window.genMenu(${index}, this)">⋯</button>`;
    }

    // When, and its size: a group's newest image's, a batch's first's.
    const when = formatWhen(tile.kind === 'group' ? tile.group.latest : generation.created_at);
    const size = image.width && image.height ? `${Number(image.width)}×${Number(image.height)}` : '';
    const label = [when, size].filter(Boolean).join(' · ');
    if (label) media += `<span class="gen-date">${escapeHtml(label)}</span>`;

    // A group is not rated whole: its images are of any prompt and settings.
    const rateRow = rating && tile.kind !== 'group'
        ? ratingRowHtml(folded ? tile : image, `window.genRate(${index}, %)`) : '';

    const classes = ['gen-tile', wide(image) && 'gen-wide', folded && 'gen-group',
                     tile.kind === 'group' && 'gen-grouping'].filter(Boolean).join(' ');
    // A group is a way in, not something to act on: its images are of any
    // prompt and settings - Send would send one image as if it stood for them
    // all, and Delete would take many at once. Its row says what it holds.
    const actions = tile.kind === 'group'
        ? `<div class="gen-actions gen-group-facts">${tile.matching_count} image${tile.matching_count === 1 ? '' : 's'}`
          + ` · ${tile.group.generations} generation${tile.group.generations === 1 ? '' : 's'}</div>`
        : `<div class="gen-actions">
                <button type="button" class="mm-btn primary mm-btn-small" title="Send to ${mode}"
                        onclick="window.genSend(${index})">${mode}</button>
                <button type="button" class="mm-btn secondary mm-btn-small" onclick="window.genDelete(${index})">Delete</button>
            </div>`;
    return `
        <div class="${classes}" data-generation="${Number(generation.id)}" data-aspect="${aspect(image)}">
            <div class="gen-media">${media}</div>
            ${rateRow}
            ${actions}
        </div>`;
}

/**
 * Whether an image gets a horizontal card - two columns or more, as tall as
 * the rest - rather than a vertical one: wider than it is tall. A folded
 * batch goes by its first image.
 */
function wide(image) {
    return Number(image?.width) > Number(image?.height);
}

/** An image's width over its height, or 1 when it is not known. */
function aspect(image) {
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
function spanFor(ratio, columnWidth, gap, imageHeight, columns) {
    if (!(ratio > 1) || !(columnWidth > 0)) return 1;
    const ideal = Math.round((imageHeight * ratio + gap) / (columnWidth + gap));
    return Math.min(Math.max(2, Math.min(ideal, MAX_SPAN)), Math.max(columns, 1));
}
window.genSpanFor = spanFor;            // for tests

/**
 * Give every wide tile its columns, as the grid now is: its column width,
 * gap, tile height and how many columns fit. Again on every resize - a
 * narrower window has fewer. Nothing while the tab is hidden, where every
 * width reads 0; the stylesheet's two columns stand until then.
 *
 * With "Preserve order", every tile is one column: the grid fills a gap a
 * wide tile leaves with a later tile, so the order is only roughly newest
 * first, and fitting wide tiles to their rows instead still left gaps, and
 * drew images of one size at different sizes.
 */
function applySpans() {
    const grid = byId('gen_grid');
    const width = grid?.getBoundingClientRect?.().width || 0;
    const style = grid && window.getComputedStyle?.(grid);
    const px = (name) => parseFloat(style?.getPropertyValue(name)) || 0;
    const column = px('--gen-column-width');
    const gap = px('--gen-gap');
    const height = px('--gen-image-height');
    if (!width || !column || !height) return;
    const columns = Math.floor((width + gap) / (column + gap));
    for (const tile of grid.querySelectorAll('.gen-tile.gen-wide')) {
        const span = preserveOrder ? 1
            : spanFor(Number(tile.getAttribute('data-aspect')), column, gap, height, columns);
        tile.style.gridColumn = `span ${span}`;
    }
}

/** Columns wide enough for the buttons, then each tile's span over them. */
function layout() {
    fitColumns();
    applySpans();
}

/** An image of a tile, or word that its file is gone. */
function imageHtml(img) {
    const url = new URL(img.url || '', window.location.origin).href;
    const level = nsfwBadgeLabel(img, 'Unknown');
    const badge = level !== 'PG' && level !== 'Unknown' && level !== 'None'
        ? `<span class="mm-nsfw-badge">${escapeHtml(level)}</span>` : '';
    const image = img.exists
        ? `<img data-src="${escapeHtml(url)}" class="mm-lazy-media" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Generated image" loading="lazy"
                ${mediaFallback('', IMAGE_PLACEHOLDER_SVG)}>`
        : `<img src="${IMAGE_PLACEHOLDER_SVG}" alt="Image unavailable"
                title="Image unavailable: its file is no longer where it was saved">`;
    return `<div class="mm-generation-tile">${image}${badge}</div>`;
}

/** A tile's place in the grid: a wrapper the grid does not see, so it can be redrawn alone. */
function setHtml(index) {
    return `<div class="gen-set" data-tile="${index}">${tileHtml(tiles[index], index)}</div>`;
}

function appendTiles(from) {
    const grid = byId('gen_grid');
    if (!grid) return;
    grid.insertAdjacentHTML('beforeend', tiles.slice(from).map((_, i) => setHtml(from + i)).join(''));
    setupLazyMedia(grid);
    layout();
}

/**
 * Make a column as wide as a tile's buttons need, in one row, if that is more
 * than the gallery's image width: however the fonts and buttons come out, the
 * row stays one row. Measured, since it cannot be known from here; nothing is
 * measured while the tab is hidden, where every width reads 0.
 */
function fitColumns() {
    const app = byId('generations_app');
    const tile = document.querySelector('#gen_grid .gen-tile:not(.gen-wide)')
        || document.querySelector('#gen_grid .gen-tile');
    const actions = tile?.querySelector('.gen-actions');
    if (!app || !actions || !actions.scrollWidth) return;
    const style = window.getComputedStyle?.(tile);
    const frame = ['paddingLeft', 'paddingRight', 'borderLeftWidth', 'borderRightWidth']
        .reduce((sum, key) => sum + (parseFloat(style?.[key]) || 0), 0);
    const needed = Math.ceil(actions.scrollWidth + frame);
    const current = parseFloat(window.getComputedStyle?.(app)?.getPropertyValue('--gen-column-width')) || 0;
    if (needed > current) app.style.setProperty('--gen-column-width', `${needed}px`);
}

function redrawTile(index) {
    const set = document.querySelector(`#gen_grid .gen-set[data-tile="${index}"]`);
    if (!set) return;
    set.outerHTML = setHtml(index);
    setupLazyMedia(byId('gen_grid'));
    layout();
}

/** Draw every tile again, from the first: after one is taken out, the places move. */
function redrawAll() {
    const grid = byId('gen_grid');
    if (!grid) return;
    grid.innerHTML = '';
    appendTiles(0);
}

function renderBanner() {
    const banner = byId('gen_banner');
    if (!banner || !state) return;
    const onScreen = tiles.reduce((sum, t) => sum + (t.matching_count || 0), 0);
    banner.innerHTML = renderFilterBanner({
        matching: state.filtered || 0,
        total: state.total || 0,
        onScreen,
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        switches: [{
            id: 'gen_show_nsfw', label: 'Show NSFW', reason: 'NSFW filter',
            showing: !hideNsfw, hidden: state.hidden_nsfw || 0, count: state.nsfw_count || 0,
            onchange: 'window.genShowNsfw(this.checked)', note: nsfwModelNote(),
        }],
    });
}

// ------------------------------------------------------------- the tiles' actions
/** Send a tile's image - a batch's first - back to the tab it was made in. Not a group's. */
window.genSend = async function(index) {
    const tile = tiles[index];
    if (!tile?.images?.[0] || tile.kind === 'group') return;
    await sendImage(tile, tile.images[0]);
};

async function sendImage(tile, image) {
    if (typeof window.mmSendInfotext !== 'function') {
        console.error('[ModelManager] The Model Manager tab is not loaded; cannot send');
        return;
    }
    if (!await window.mmSendInfotext({ infotext: image.infotext, mode: tile.generation.mode, meta: image.meta,
                                       generationId: tile.generation.id })) {
        console.error('[ModelManager] Could not send generated image', image.id);
    }
}

// ------------------------------------------------------------- rating
/**
 * Rate a tile: its image, or - a batch - every image of it the tab shows.
 * Your rating again clears it. An image the NSFW switch now hides leaves the
 * grid at once. A group is not rated whole - too easily misrated; its
 * batches and images are, once it is opened.
 */
window.genRate = async function(index, value) {
    const tile = tiles[index];
    if (!tile || tile.kind === 'group') return;
    const single = tile.kind === 'image' || (tile.kind === 'generation' && tile.matching_count <= 1);
    if (single) {
        await rateImage(index, tile.images[0], value);
        return;
    }
    const level = tile.user_level === value ? '' : value;
    const scope = { group: groupBy, in_group: at.in_group, generation: tile.generation.id };
    if (await postRating({ ...scope, level })) {
        markAboveChanged();
        await reloadKeepingPlace();
    }
};

/**
 * Rate one image, and draw it as it now is - taken off its tile if the NSFW
 * switch now hides it. True if it is still shown.
 */
async function rateImage(index, image, value) {
    const level = image.user_level === value ? '' : value;
    const answer = await postRating({ image_id: image.id, level });
    if (!answer?.image) return true;
    Object.assign(image, answer.image);
    markAboveChanged();
    if (!answer.visible) {
        hideImage(index, image.id);
        await refreshTotals();
        return false;
    }
    const tile = tiles[index];
    if (tile && tile.matching_count <= 1) {
        tile.level = image.mm_level;
        tile.user_level = image.user_level;
    }
    redrawTile(index);
    return true;
}

async function postRating(fields) {
    try {
        const body = new URLSearchParams({ hide_nsfw_images: String(hideNsfw) });
        for (const [key, value] of Object.entries(fields)) {
            if (value !== undefined && value !== null) body.set(key, String(value));
        }
        const response = await fetch('/model-manager/generations/rate', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });
        const answer = await response.json();
        if (!answer.success) {
            setStatus(`Could not rate: ${answer.error || 'no answer'}`);
            return null;
        }
        return answer;
    } catch (error) {
        setStatus(`Could not rate: ${error.message}`);
        return null;
    }
}

/** An image the NSFW switch now hides: off its tile, and the tile with its last. */
function hideImage(index, imageId) {
    const tile = tiles[index];
    if (!tile) return;
    tile.images = tile.images.filter((img) => img.id !== imageId);
    tile.matching_count = Math.max(0, (tile.matching_count || 1) - 1);
    if (tile.matching_count > 0 && tile.images.length) redrawTile(index);
    else removeTile(index);
}

/**
 * This level again, as far as it had been loaded, and the page where it was:
 * after a batch or a group was rated, what each tile holds may have changed.
 */
async function reloadKeepingPlace() {
    const y = currentScroll();
    const parts = part;
    closeMenu();
    request += 1;
    loading = false;
    tiles = [];
    part = 0;
    more = true;
    const grid = byId('gen_grid');
    if (grid) grid.innerHTML = '';
    while (part < parts && more) {
        const before = part;
        await loadNext();
        if (part === before) break;
    }
    setStatus(tiles.length ? '' : emptyText());
    window.scrollTo?.(0, y);
}

window.genSetRating = function(checked) {
    rating = !!checked;
    redrawAll();
};

// ------------------------------------------------------------- the ⋯ menu
// More that can be done with a tile or the image in the viewer, in a menu
// under its ⋯ - which is not drawn when there is nothing in it.

/** What a tile's menu offers: its checkpoint, if its images share one. */
function tileMenu(tile) {
    return menuFor(tile.checkpoint_path);
}

function menuFor(checkpoint) {
    const items = [];
    if (checkpoint) items.push({ label: 'Show model in Model Manager', run: () => showModel(checkpoint) });
    return items;
}

window.genMenu = function(index, button) {
    const tile = tiles[index];
    if (tile) openMenu(button, tileMenu(tile));
};

let menu = null;

/** The menu, under the button that opened it; a click anywhere else, or Esc, closes it. */
function openMenu(anchor, items) {
    closeMenu();
    if (!items.length) return;
    const element = document.createElement('div');
    element.className = 'gen-menu';
    element.setAttribute('role', 'menu');
    element.innerHTML = items.map((item, i) => `<button type="button" role="menuitem" data-item="${i}">`
        + `${escapeHtml(item.label)}</button>`).join('');
    element.addEventListener('click', (event) => {
        const chosen = event.target.closest?.('[data-item]');
        if (!chosen) return;
        closeMenu();
        items[Number(chosen.getAttribute('data-item'))].run();
    });
    const box = anchor.getBoundingClientRect?.() || { right: 0, bottom: 0 };
    element.style.top = `${Math.round(box.bottom + 4)}px`;
    element.style.right = `${Math.max(8, Math.round((window.innerWidth || 0) - box.right))}px`;
    document.body.appendChild(element);
    const away = (event) => {
        if (!element.contains(event.target)) closeMenu();
    };
    setTimeout(() => document.addEventListener('click', away, true), 0);
    menu = { element, away };
}

function closeMenu() {
    if (!menu) return false;
    menu.element.remove();
    document.removeEventListener('click', menu.away, true);
    menu = null;
    return true;
}

/** This model, in the Model Manager tab: the file's own version. */
function showModel(path) {
    closeViewer();
    if (typeof window.mmShowFile !== 'function') {
        setStatus('The Model Manager tab has not started yet: open it once and try again.');
        return;
    }
    window.mmShowFile(path);
}

// ------------------------------------------------------------- the viewer
// The shared viewer (shared/viewer.mjs), through the images the grid shows -
// a batch's or a group's first four, as on its tile - and on, loading the
// next part into the grid, past the last. Below the image: Send, Delete, ⋯
// and the rating row; beside it, everything recorded.

/** The grid's images in order, each by its tile and its place on it. */
function viewerImages() {
    const list = [];
    tiles.forEach((tile, t) => (tile.images || []).forEach((image, i) => list.push({ t, i })));
    return list;
}

function viewerAt(index) {
    const place = viewerImages()[index];
    if (!place) return {};
    const tile = tiles[place.t];
    return { t: place.t, tile, image: tile.images[place.i], i: place.i };
}

const viewerSource = {
    count: () => viewerImages().length,
    media: (index) => {
        const { image } = viewerAt(index);
        return { url: image?.exists ? new URL(image.url || '', window.location.origin).href : IMAGE_PLACEHOLDER_SVG,
                 video: false };
    },
    buttons: (index) => {
        const { tile, image } = viewerAt(index);
        if (!image) return '';
        const mode = tile.generation.mode === 'img2img' ? 'img2img' : 'txt2img';
        return `${ratingRowHtml(image, 'window.genRateInViewer(%)')}
            <button type="button" class="mm-btn primary mm-btn-small" data-gen-send>Send to ${mode}</button>
            <button type="button" class="mm-btn secondary mm-btn-small" data-gen-delete>Delete</button>
            ${menuFor(image.checkpoint_path).length
                ? '<button type="button" class="mm-btn secondary mm-btn-small" data-gen-menu title="More">⋯</button>' : ''}`;
    },
    details: (index) => {
        const { tile, image } = viewerAt(index);
        return image ? infoHtml(tile, image, new URL(image.url || '', window.location.origin).href) : '';
    },
    where: (index) => {
        const { tile, i } = viewerAt(index);
        if (!tile) return '';
        const shown = tile.images.length;
        const count = tile.matching_count || shown;
        const what = tile.kind === 'group' ? 'this group' : 'this generation';
        if (count <= 1) return '';
        return shown < count ? `${i + 1} of the ${shown} shown · ${count} in ${what}` : `${i + 1} of ${count} in ${what}`;
    },
    more: () => more,
    loadMore: async () => {
        while (loading) await new Promise((resolve) => setTimeout(resolve, 50));
        await loadNext();
    },
    onClick: (event, index) => {
        const { tile, image } = viewerAt(index);
        if (!image) return false;
        if (event.target.closest?.('[data-gen-send]')) {
            closeViewer();
            sendImage(tile, image);
            return true;
        }
        if (event.target.closest?.('[data-gen-delete]')) {
            deleteFromViewer();
            return true;
        }
        const more = event.target.closest?.('[data-gen-menu]');
        if (more) {
            openMenu(more, menuFor(image.checkpoint_path));
            return true;
        }
        return false;
    },
    onClose: (index) => {
        closeMenu();
        const { t } = viewerAt(index);
        if (t !== undefined) document.querySelector(`#gen_grid .gen-set[data-tile="${t}"]`)?.scrollIntoView?.({ block: 'nearest' });
    },
};

/** Open the viewer on image `image` of tile `index`. */
window.genView = function(index, image = 0) {
    const at = viewerImages().findIndex((place) => place.t === index && place.i === image);
    if (at >= 0) openViewer(viewerSource, at);
};

/**
 * The keys this tab has besides the viewer's: Esc closes the ⋯ menu, or -
 * no viewer open - goes back up a level, while this tab is the one shown.
 */
function onKey(event) {
    if (dialogShowing() && !document.querySelector('.gen-menu')) return;     // a question is open
    if (event.key === 'Escape' && closeMenu()) {
        event.preventDefault?.();
        event.stopImmediatePropagation?.();
        return;
    }
    if (viewerIsOpen()) return;
    if (event.key === 'Escape' && levels.length && byId('gen_grid')?.offsetParent !== null) {
        event.preventDefault?.();
        window.genBack();
    }
}

/**
 * Everything recorded about an image, for the viewer's panel: each field its
 * title over its value, which has the panel's whole width - beside its title,
 * in a table, a long value had a sliver of it.
 */
function infoHtml(tile, image, url) {
    const generation = tile.generation || {};
    const meta = image.meta || {};
    const checkpoint = (generation.checkpoint_path || '').split(/[\\/]/).pop();
    const rows = [
        ['Made', [formatWhen(generation.created_at, 'medium'), generation.mode].filter(Boolean).join(' · ')],
        ['Checkpoint', checkpoint],
        ['Size', image.width && image.height ? `${image.width}×${image.height}` : ''],
        ['Seed', image.seed ?? ''],
        ...Object.entries(meta)
            .filter(([key, value]) => !['prompt', 'negativePrompt'].includes(key)
                    && value !== null && value !== '' && typeof value !== 'object')
            .map(([key, value]) => [key, value]),
    ].filter(([, value]) => value !== '' && value !== undefined && value !== null);
    return `
        ${meta.prompt ? `<div class="gen-info-heading">Prompt</div>
            <div class="gen-info-prompt">${escapeHtml(meta.prompt)}</div>` : ''}
        ${meta.negativePrompt ? `<div class="gen-info-heading">Negative prompt</div>
            <div class="gen-info-prompt">${escapeHtml(meta.negativePrompt)}</div>` : ''}
        <div class="gen-info-fields">
            ${rows.map(([key, value]) => `<div class="gen-info-field">
                <div class="gen-info-heading">${escapeHtml(key)}</div>
                <div class="gen-info-value">${escapeHtml(String(value))}</div></div>`).join('')}
        </div>
        <div class="mm-dialog-buttons gen-info-buttons">
            ${image.infotext ? `<button type="button" class="mm-btn secondary mm-btn-small"
                data-copy="${escapeHtml(image.infotext)}">Copy infotext</button>` : ''}
            ${image.exists ? `<a class="mm-btn secondary mm-btn-small" href="${escapeHtml(url)}" target="_blank"
                rel="noopener">Open full size</a>` : ''}
        </div>`;
}

/**
 * Rate the image shown. If the NSFW switch now hides it, the viewer shows the
 * one now in its place - the next - or the last, as after a delete.
 */
window.genRateInViewer = async function(value) {
    const index = viewerIndex();
    const { t, image } = viewerAt(index);
    if (!image) return;
    await rateImage(t, image, value);
    if (viewerIndex() === index) showImage(index);
};

/** Delete the image shown, and show the one now in its place - or the last. */
async function deleteFromViewer() {
    const index = viewerIndex();
    const { t, image } = viewerAt(index);
    if (!image || !await deleteImage(t, image)) return;
    if (viewerIndex() === index) showImage(index);
}

// ------------------------------------------------------------- deleting
/**
 * Delete a tile: one image, or a batch - every image of it - asking first,
 * and whether the files go too. A group is not deleted from here: its images
 * are of any number of generations.
 */
window.genDelete = async function(index) {
    const tile = tiles[index];
    if (!tile || tile.kind === 'group') return;
    if (tile.matching_count <= 1 || tile.kind === 'image') {
        await deleteImage(index, tile.images[0]);
        return;
    }
    const n = tile.generation.image_count || tile.matching_count || 1;
    const answer = await askToDelete(`Delete this generation of ${n} image${n === 1 ? '' : 's'}?`, n);
    if (!answer) return;
    if (await postDelete(`/model-manager/generations/${Number(tile.generation.id)}/delete`, answer)) {
        removeTile(index);
        markAboveChanged();
        await refreshTotals();
    }
};

/** Delete one image, asking first; true once it is gone, from the grid too. */
async function deleteImage(index, image) {
    if (!image) return false;
    const answer = await askToDelete('Delete this image?', 1);
    if (!answer) return false;
    if (!await postDelete(`/model-manager/generations/images/${Number(image.id)}/delete`, answer)) return false;
    forgetImage(index, image.id);
    markAboveChanged();
    await refreshTotals();
    return true;
}

/** Ask the server to delete; true if it did. */
async function postDelete(endpoint, answer, fields = {}) {
    try {
        const body = new URLSearchParams({ ...fields, delete_files: String(answer.withFiles) });
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });
        const data = await response.json();
        if (!data.success) {
            setStatus(`Delete failed: ${data.error || 'unknown error'}`);
            return false;
        }
        if (data.failed?.length) setStatus(`${data.failed.length} file(s) could not be deleted`);
        return true;
    } catch (error) {
        setStatus(`Delete failed: ${error.message}`);
        return false;
    }
}

/** Take a deleted image off the grid: off its tile, and the tile with its last. */
function forgetImage(index, imageId) {
    const tile = tiles[index];
    if (!tile) return;
    tile.images = tile.images.filter((img) => img.id !== imageId);
    tile.matching_count = Math.max(0, (tile.matching_count || 1) - 1);
    if (tile.generation?.image_count) tile.generation.image_count -= 1;
    if (tile.matching_count > 0 && tile.images.length) {
        redrawTile(index);
        return;
    }
    removeTile(index);
}

function removeTile(index) {
    tiles.splice(index, 1);
    redrawAll();
    if (!tiles.length) setStatus(emptyText());
}

/** The banner's totals again, after a delete, without reloading the grid. */
async function refreshTotals() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/generations/browse', params: {
            page: 1, hide_nsfw_images: hideNsfw, group: groupBy, in_group: at.in_group, generation: at.generation,
        } });
        if (data.success) {
            state = data.state;
            scope = data.scope;
            renderBanner();
            renderPath();
        }
    } catch (error) {
        console.warn('[ModelManager] Could not count your generations again:', error);
    }
}

// ------------------------------------------------------------- the switches
window.genSetPreserveOrder = function(checked) {
    preserveOrder = !!checked;
    writeFlag(PRESERVE_ORDER_KEY, preserveOrder);
    const grid = byId('gen_grid');
    grid?.classList.toggle('gen-ordered', preserveOrder);
    applySpans();
};

/** Group by something else, or nothing: the tab starts again from its top level. */
window.genSetGroupBy = function(value) {
    groupBy = GROUP_NAMES[value] ? value : '';
    writeFlag(GROUP_BY_KEY, groupBy);
    levels.length = 0;
    at = {};
    title = '';
    scope = null;
    return reload();
};

window.genShowNsfw = function(checked) {
    hideNsfw = !checked;
    markAboveChanged();
    window.scrollTo?.(0, 0);
    return reload();
};

window.genRefresh = () => {
    markAboveChanged();
    return reload();
};

/** For tests, and anything else that wants the next part now. */
window.genLoadMore = () => loadNext();

/**
 * The tab's markup, once Gradio has drawn it. The script runs when the page
 * is ready and Gradio draws the tab after, so the first load found no grid
 * and the tab stayed empty until Refresh; the other tabs never met this, as
 * they load only on a click.
 */
function markupDrawn(tries = 240) {
    return new Promise((resolve) => {
        const look = (left) => {
            if (byId('gen_grid') || left <= 0) resolve(!!byId('gen_grid'));
            else setTimeout(() => look(left - 1), 250);
        };
        look(tries);
    });
}

onReady(async () => {
    if (started) return;
    started = true;
    if (!await markupDrawn()) {
        console.warn('[ModelManager] The Generations tab never appeared; not loading it');
        return;
    }
    const order = byId('gen_preserve_order');
    if (order) order.checked = preserveOrder;
    // "Rate" starts off, whatever the browser kept ticked from before.
    const rate = byId('gen_rate');
    if (rate) rate.checked = false;
    const group = byId('gen_group_by');
    if (group) group.value = groupBy;
    byId('gen_grid')?.classList.toggle('gen-ordered', preserveOrder);
    try {
        hideNsfw = (await galleryDefaults()).hideNsfw;
    } catch (e) { /* the gallery's default: hidden */ }
    watchEnd();
    document.addEventListener('keydown', onKey);
    // Hidden, nothing could be measured: measure again once it is shown.
    window.addEventListener('resize', layout);
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(layout);
    await reload();
});
