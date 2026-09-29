/**
 * The Generations tab: every image you have generated, newest first.
 *
 * A tile per generation - its first images, and how many it has - which a
 * click opens out into all of them, each a tile the same size, and a click on
 * the first folds back - by its count. A click on an image opens it in the
 * viewer, large, with ← and → through them all and its information beside it.
 * Each tile sends its own infotext back to the tab it was made in, or is
 * deleted. The grid scrolls: the next part loads as its
 * end comes near. Only the NSFW switch applies; nothing is hidden here for its
 * prompt.
 *
 * The server does the filtering and the parts (api/generations.browse_page).
 * The paste into txt2img or img2img is the Model Manager's, on window
 * (window.mmSendInfotext): it lives in that tab's script, loaded with this.
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
    IMAGE_PLACEHOLDER_SVG,
} = await import(sharedModule.href);

const settingsModule = new URL('./shared/settings.mjs', import.meta.url);
settingsModule.search = sharedModule.search;
await import(settingsModule.href);

// "Preserve order", remembered in this browser.
const PRESERVE_ORDER_KEY = 'mm_generations_preserve_order';
// How near the end of the grid the next part is asked for.
const LOAD_AHEAD_PX = 800;
// The most columns a wide image's tile takes.
const MAX_SPAN = 4;

let preserveOrder = readFlag(PRESERVE_ORDER_KEY);
let hideNsfw = true;
let tiles = [];          // each {generation, images, matching_count, expanded: images or null}
let state = null;        // the totals, for the banner
let part = 0;            // the last part loaded
let more = true;
let loading = false;
let request = 0;         // a newer load drops an older one's answer
let started = false;

function readFlag(key) {
    try {
        return localStorage.getItem(key) === 'true';
    } catch (e) {
        return false;
    }
}

function writeFlag(key, value) {
    try {
        localStorage.setItem(key, String(value));
    } catch (e) { /* remembered for this visit only */ }
}

const byId = (id) => document.getElementById(id);

// ------------------------------------------------------------- loading
/** Everything again from the first part: a switch, Refresh, or opening. */
async function reload() {
    closeViewer();
    tiles = [];
    part = 0;
    more = true;
    loading = false;
    request += 1;
    const grid = byId('gen_grid');
    if (grid) grid.innerHTML = '';
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
            page: part + 1, hide_nsfw_images: hideNsfw,
        } });
        if (asked !== request) return;
        if (!data.success) {
            setStatus(`Could not load your generations: ${data.error || 'no answer'}`);
            return;
        }
        part += 1;
        more = !!data.more;
        state = data.state;
        const first = tiles.length;
        tiles = tiles.concat((data.tiles || []).map((tile) => ({ ...tile, expanded: null })));
        appendTiles(first);
        renderBanner();
        setStatus(tiles.length ? '' : emptyText());
    } catch (error) {
        if (asked === request) setStatus(`Could not load your generations: ${error.message}`);
    } finally {
        if (asked === request) loading = false;
    }
    if (asked === request) loadIfNearEnd();
}

function emptyText() {
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

// ------------------------------------------------------------- drawing
/**
 * One tile: a generation of several images, folded (its first four, and how
 * many), or one image - of a generation opened out (member), or on its own.
 * `at` is where its actions find it: the tile's place, and the image's
 * within its generation when opened out.
 */
function tileHtml(tile, at) {
    const generation = tile.generation || {};
    const group = !tile.expanded && tile.matching_count > 1;
    const mode = generation.mode === 'img2img' ? 'img2img' : 'txt2img';
    const image = tile.images?.[0] || {};

    // A click on an image opens the viewer on it - a folded batch on its
    // first. The count opens a batch out in the grid, and on its first image
    // folds it back.
    const view = `onclick="window.genView(${at.tile}, ${Math.max(at.member ?? 0, 0)})"`;
    let media;
    if (group) {
        const preview = tile.images.slice(0, 4);
        media = `
            <div class="mm-generation-preview mm-generation-preview-${preview.length} gen-group-preview gen-viewable"
                 ${view} title="View">
                ${preview.map((img) => imageHtml(img)).join('')}
            </div>
            <button type="button" class="gen-count" title="Show all ${tile.matching_count} images here"
                    onclick="event.stopPropagation(); window.genToggle(${at.tile})">×${tile.matching_count}</button>`;
    } else {
        media = `<div class="gen-viewable" ${view} title="View">${imageHtml(image)}</div>`;
        if (at.member === 0) {
            media += `<button type="button" class="gen-count" title="Fold the generation back"
                    onclick="event.stopPropagation(); window.genToggle(${at.tile})">×${tile.expanded.length}</button>`;
        }
    }

    const when = generation.created_at
        ? new Date(generation.created_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
        : '';
    // Its size after the date: a folded batch's is its first image's.
    const size = image.width && image.height ? `${Number(image.width)}×${Number(image.height)}` : '';
    const label = [when, size].filter(Boolean).join(' · ');
    if (label) media += `<span class="gen-date">${escapeHtml(label)}</span>`;

    const classes = ['gen-tile', wide(image) && 'gen-wide', group && 'gen-group',
                     at.member !== undefined && 'gen-member', at.member === 0 && 'gen-member-first']
        .filter(Boolean).join(' ');
    const args = `${at.tile}, ${at.member ?? -1}`;
    return `
        <div class="${classes}" data-generation="${Number(generation.id)}" data-aspect="${aspect(image)}">
            <div class="gen-media">${media}</div>
            <div class="gen-actions">
                <button type="button" class="mm-btn primary mm-btn-small" title="Send to ${mode}"
                        onclick="window.genSend(${args})">${mode}</button>
                <button type="button" class="mm-btn secondary mm-btn-small" onclick="window.genDelete(${args})">Delete</button>
            </div>
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
    const tile = tiles[index];
    const inner = tile.expanded
        ? tile.expanded.map((img, member) => tileHtml({ ...tile, images: [img] }, { tile: index, member })).join('')
        : tileHtml(tile, { tile: index });
    return `<div class="gen-set" data-tile="${index}">${inner}</div>`;
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
    const onScreen = tiles.reduce((sum, t) => sum + (t.expanded ? t.expanded.length : t.matching_count), 0);
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
/** The image an action is for: a folded generation's first, or the one opened out. */
function imageAt(index, member) {
    const tile = tiles[index];
    if (!tile) return null;
    return member >= 0 ? tile.expanded?.[member] : tile.images?.[0];
}

/** Open a generation out into all its images, or fold it back. */
window.genToggle = async function(index) {
    const tile = tiles[index];
    if (!tile) return;
    if (tile.expanded) {
        tile.expanded = null;
        redrawTile(index);
        renderBanner();
        return;
    }
    try {
        const data = await apiCall({ endpoint: `/model-manager/generations/${Number(tile.generation.id)}/images`,
                                     params: { hide_nsfw_images: hideNsfw } });
        if (!data.success) return;
        tile.expanded = data.images || [];
        if (tile.expanded.length < 2) tile.expanded = null;
        redrawTile(index);
        renderBanner();
    } catch (error) {
        console.error('[ModelManager] Could not open a generation out:', error);
    }
};

/** Send the image's own infotext back to the tab its generation was made in. */
window.genSend = async function(index, member) {
    const tile = tiles[index];
    const image = imageAt(index, member);
    if (!tile || !image) return;
    await sendImage(tile, image);
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
};

// ------------------------------------------------------------- the viewer
// An image over the page, as large as it goes, with ← and → through every
// image in the grid's order - a folded batch's too, fetched when reached -
// and on, loading the next part into the grid, past the last. Send and
// Delete below it; beside it, everything recorded, in a panel that folds away
// (remembered). Esc closes it.
const VIEWER_PANEL_KEY = 'mm_generations_viewer_panel_closed';
// The wheel: how far it has to turn for one image, and how soon the next.
const WHEEL_STEP = 50;
const WHEEL_PAUSE_MS = 150;
let viewer = null;       // {tile, image, element}: where it is, and its markup

/** A generation's images as far as they are here: all of them, once fetched. */
function imagesOf(tile) {
    return tile.expanded || tile.all || tile.images || [];
}

function countOf(tile) {
    return (tile.expanded || tile.all)?.length ?? tile.matching_count ?? imagesOf(tile).length;
}

/** Fetch every image of a folded batch, for the viewer, without opening it out. */
async function fetchAll(tile) {
    if (tile.expanded || tile.all || countOf(tile) <= imagesOf(tile).length) return;
    try {
        const data = await apiCall({ endpoint: `/model-manager/generations/${Number(tile.generation.id)}/images`,
                                     params: { hide_nsfw_images: hideNsfw } });
        if (data.success && data.images?.length) tile.all = data.images;
    } catch (error) {
        console.error('[ModelManager] Could not fetch a generation\'s images:', error);
    }
}

/** Open the viewer on image `image` of tile `index`. */
window.genView = async function(index, image = 0) {
    if (!tiles[index]) return;
    if (!viewer) openViewer();
    await showInViewer(index, image);
};

function openViewer() {
    const element = document.createElement('div');
    element.className = 'gen-viewer' + (readFlag(VIEWER_PANEL_KEY) ? ' gen-viewer-collapsed' : '');
    element.setAttribute('role', 'dialog');
    element.innerHTML = `
        <div class="gen-viewer-stage">
            <button type="button" class="gen-viewer-step gen-viewer-prev" data-step="-1" title="Previous (←)">‹</button>
            <div class="gen-viewer-main">
                <div class="gen-viewer-frame"><img class="gen-viewer-image" alt="Generated image"></div>
                <div class="gen-viewer-bar">
                    <span class="gen-viewer-where"></span>
                    <span class="gen-viewer-actions">
                        <button type="button" class="mm-btn primary mm-btn-small" data-send></button>
                        <button type="button" class="mm-btn secondary mm-btn-small" data-delete>Delete</button>
                    </span>
                </div>
            </div>
            <button type="button" class="gen-viewer-step gen-viewer-next" data-step="1" title="Next (→)">›</button>
        </div>
        <aside class="gen-viewer-panel">
            <button type="button" class="gen-viewer-panel-toggle" data-panel title="Show or hide the details"></button>
            <div class="gen-viewer-info"></div>
        </aside>
        <button type="button" class="gen-viewer-close" data-close title="Close (Esc)">×</button>`;
    element.addEventListener('click', (event) => {
        const target = event.target;
        const step = target.closest?.('[data-step]');
        if (step) return stepViewer(Number(step.getAttribute('data-step')));
        if (target.closest?.('[data-close]')) return closeViewer();
        if (target.closest?.('[data-panel]')) {
            const closed = element.classList.toggle('gen-viewer-collapsed');
            writeFlag(VIEWER_PANEL_KEY, closed);
            return undefined;
        }
        if (target.closest?.('[data-send]')) return sendFromViewer();
        if (target.closest?.('[data-delete]')) return deleteFromViewer();
        // Around the image - not on it, a button or the details - closes it.
        if (target.matches?.('.gen-viewer, .gen-viewer-stage, .gen-viewer-main, .gen-viewer-frame, '
                             + '.gen-viewer-bar, .gen-viewer-where')) return closeViewer();
        return undefined;
    });
    element.addEventListener('wheel', onViewerWheel, { passive: false });
    document.addEventListener('keydown', onViewerKey);
    document.body.appendChild(element);
    // The page under it stays where it is: the wheel is the viewer's.
    document.body.classList.add('mm-modal-open');
    viewer = { tile: 0, image: 0, element, wheel: 0, wheelAt: 0 };
}

/**
 * The wheel steps through the images - down on, up back - one at a time
 * however hard it turns: a trackpad sends many small turns, a wheel a few
 * large ones. Over the details it scrolls them, while they have further to go.
 */
function onViewerWheel(event) {
    if (!viewer) return;
    const info = event.target.closest?.('.gen-viewer-info');
    if (info && info.scrollHeight > info.clientHeight) {
        const atTop = info.scrollTop <= 0;
        const atBottom = info.scrollTop + info.clientHeight >= info.scrollHeight - 1;
        if ((event.deltaY < 0 && !atTop) || (event.deltaY > 0 && !atBottom)) return;
    }
    event.preventDefault();
    const now = Date.now();
    viewer.wheel += event.deltaY;
    if (Math.abs(viewer.wheel) < WHEEL_STEP || now - viewer.wheelAt < WHEEL_PAUSE_MS) return;
    const by = viewer.wheel > 0 ? 1 : -1;
    viewer.wheel = 0;
    viewer.wheelAt = now;
    stepViewer(by);
}

function onViewerKey(event) {
    if (!viewer || document.querySelector('.mm-dialog-backdrop')) return;   // a question is open
    if (event.key === 'ArrowLeft') stepViewer(-1);
    else if (event.key === 'ArrowRight') stepViewer(1);
    else if (event.key === 'Escape') closeViewer();
    else return;
    event.preventDefault?.();
}

/** Close the viewer, with the grid showing the tile it was on. */
function closeViewer() {
    if (!viewer) return;
    const at = viewer.tile;
    viewer.element.remove();
    document.removeEventListener('keydown', onViewerKey);
    document.body.classList.remove('mm-modal-open');
    viewer = null;
    document.querySelector(`#gen_grid .gen-set[data-tile="${at}"]`)?.scrollIntoView?.({ block: 'nearest' });
}

async function showInViewer(index, image) {
    const tile = tiles[index];
    if (!viewer || !tile) return;
    await fetchAll(tile);
    viewer.tile = index;
    viewer.image = Math.max(0, Math.min(image, imagesOf(tile).length - 1));
    renderViewer();
}

/**
 * One image on: the next in its generation, or the next generation's first -
 * a previous one's last going back. Past the last loaded, the next part is
 * loaded into the grid first.
 */
async function stepViewer(by) {
    if (!viewer) return;
    const tile = tiles[viewer.tile];
    const next = viewer.image + by;
    if (next >= 0 && next < imagesOf(tile).length) return showInViewer(viewer.tile, next);
    let index = viewer.tile + by;
    if (index >= tiles.length && more) {
        while (loading) await new Promise((resolve) => setTimeout(resolve, 50));
        await loadNext();
    }
    if (index < 0 || index >= tiles.length) return undefined;
    if (by < 0) {
        await fetchAll(tiles[index]);
        return showInViewer(index, imagesOf(tiles[index]).length - 1);
    }
    return showInViewer(index, 0);
}

function renderViewer() {
    const tile = tiles[viewer.tile];
    const image = imagesOf(tile)[viewer.image];
    const root = viewer.element;
    if (!tile || !image) return closeViewer();
    const url = new URL(image.url || '', window.location.origin).href;
    const img = root.querySelector('.gen-viewer-image');
    img.setAttribute('src', image.exists ? url : IMAGE_PLACEHOLDER_SVG);
    const mode = tile.generation.mode === 'img2img' ? 'img2img' : 'txt2img';
    const send = root.querySelector('[data-send]');
    send.textContent = `Send to ${mode}`;
    const count = countOf(tile);
    root.querySelector('.gen-viewer-where').textContent = count > 1 ? `${viewer.image + 1} of ${count} in this generation` : '';
    const last = viewer.tile === tiles.length - 1 && viewer.image === imagesOf(tile).length - 1 && !more;
    root.querySelector('.gen-viewer-prev').disabled = viewer.tile === 0 && viewer.image === 0;
    root.querySelector('.gen-viewer-next').disabled = last;
    root.querySelector('.gen-viewer-info').innerHTML = infoHtml(tile, image, url);
}

/**
 * Everything recorded about an image, for the viewer's panel: each field its
 * title over its value, which has the panel's whole width - beside its title,
 * in a table, a long value had a sliver of it.
 */
function infoHtml(tile, image, url) {
    const generation = tile.generation || {};
    const meta = image.meta || {};
    const when = generation.created_at
        ? new Date(generation.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
        : '';
    const checkpoint = (generation.checkpoint_path || '').split(/[\\/]/).pop();
    const rows = [
        ['Made', [when, generation.mode].filter(Boolean).join(' · ')],
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
        <div class="gen-info-buttons">
            ${image.infotext ? `<button type="button" class="mm-btn secondary mm-btn-small"
                data-copy="${escapeHtml(image.infotext)}">Copy infotext</button>` : ''}
            ${image.exists ? `<a class="mm-btn secondary mm-btn-small" href="${escapeHtml(url)}" target="_blank"
                rel="noopener">Open full size</a>` : ''}
        </div>`;
}

/** Send the image shown - closing the viewer, as the page goes to txt2img or img2img. */
async function sendFromViewer() {
    if (!viewer) return;
    const { tile, image } = viewer;
    const img = imagesOf(tiles[tile])[image];
    closeViewer();
    await sendImage(tiles[tile], img);
}

/** Delete the image shown, and show the one after it - or before it, if it was the last. */
async function deleteFromViewer() {
    if (!viewer) return;
    const index = viewer.tile;
    const tile = tiles[index];
    const image = imagesOf(tile)[viewer.image];
    if (!image || !await deleteImage(index, image)) return;
    if (!viewer) return;
    if (!tiles.length) return closeViewer();
    if (index >= tiles.length) {
        await fetchAll(tiles[tiles.length - 1]);
        return showInViewer(tiles.length - 1, imagesOf(tiles[tiles.length - 1]).length - 1);
    }
    // Its generation still there, the image now in its place; else the next generation's first.
    return showInViewer(index, tiles[index] === tile ? viewer.image : 0);
}

/**
 * Delete a folded generation - every image - or one image, asking first, and
 * whether the files go too.
 */
window.genDelete = async function(index, member) {
    const tile = tiles[index];
    if (!tile) return;
    if (member >= 0 || countOf(tile) === 1) {
        await deleteImage(index, imageAt(index, member));
        return;
    }
    const n = tile.generation.image_count || tile.matching_count || 1;
    const answer = await askDelete(`Delete this generation of ${n} image${n === 1 ? '' : 's'}?`, n);
    if (!answer) return;
    if (await postDelete(`/model-manager/generations/${Number(tile.generation.id)}/delete`, answer)) {
        tiles.splice(index, 1);
        redrawAll();
        if (!tiles.length) setStatus(emptyText());
        await refreshTotals();
    }
};

/** Delete one image, asking first; true once it is gone, from the grid too. */
async function deleteImage(index, image) {
    if (!image) return false;
    const answer = await askDelete('Delete this image?', 1);
    if (!answer) return false;
    if (!await postDelete(`/model-manager/generations/images/${Number(image.id)}/delete`, answer)) return false;
    forgetImage(index, image.id);
    await refreshTotals();
    return true;
}

/** Ask the server to delete; true if it did. */
async function postDelete(endpoint, answer) {
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `delete_files=${answer.withFiles}`,
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

/**
 * Take a deleted image off the grid: out of its generation, opened out or
 * folded, and the generation's tile with its last image.
 */
function forgetImage(index, imageId) {
    const tile = tiles[index];
    if (!tile) return;
    const keep = (list) => list && list.filter((img) => img.id !== imageId);
    const left = keep(imagesOf(tile));
    tile.expanded = keep(tile.expanded);
    tile.all = keep(tile.all);
    tile.matching_count = Math.max(0, (tile.expanded || tile.all) ? left.length : tile.matching_count - 1);
    tile.images = left.slice(0, 4);
    if (tile.generation.image_count) tile.generation.image_count -= 1;
    if (tile.expanded && tile.expanded.length < 2) tile.expanded = null;
    if (tile.matching_count > 0 && tile.images.length) {
        redrawTile(index);
        return;
    }
    tiles.splice(index, 1);
    redrawAll();
    if (!tiles.length) setStatus(emptyText());
}

/** The banner's totals again, after a delete, without reloading the grid. */
async function refreshTotals() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/generations/browse', params: {
            page: 1, hide_nsfw_images: hideNsfw,
        } });
        if (data.success) {
            state = data.state;
            renderBanner();
        }
    } catch (error) {
        console.warn('[ModelManager] Could not count your generations again:', error);
    }
}

// ------------------------------------------------------------- dialogs
/**
 * A window over the page; [data-close] inside it, the backdrop or Escape
 * closes it, and onClose is told.
 */
function openDialog(html, onClose = () => {}) {
    const backdrop = document.createElement('div');
    backdrop.className = 'mm-dialog-backdrop';
    backdrop.innerHTML = html;
    const close = () => {
        if (!backdrop.isConnected) return;
        backdrop.remove();
        document.removeEventListener('keydown', onKey);
        onClose();
    };
    const onKey = (event) => { if (event.key === 'Escape') close(); };
    backdrop.addEventListener('click', (event) => {
        if (event.target === backdrop || event.target.closest?.('[data-close]')) close();
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(backdrop);
    return { element: backdrop, close };
}

/** Ask to delete, and whether the image files go too. Resolves to {withFiles}, or null. */
function askDelete(question, n) {
    return new Promise((resolve) => {
        let answer = null;
        const dialog = openDialog(`
            <div class="mm-dialog gen-delete">
                <h3>${escapeHtml(question)}</h3>
                <label class="gen-delete-files">
                    <input type="checkbox" data-files>
                    Also delete the image file${n === 1 ? '' : 's'} from disk
                </label>
                <p class="gen-delete-note">Otherwise only the record goes; the file${n === 1 ? ' stays' : 's stay'} where ${n === 1 ? 'it was' : 'they were'} saved.</p>
                <div class="gen-info-buttons">
                    <button type="button" class="mm-btn secondary" data-close>Cancel</button>
                    <button type="button" class="mm-btn danger" data-confirm>Delete</button>
                </div>
            </div>`, () => resolve(answer));
        dialog.element.querySelector('[data-confirm]').addEventListener('click', () => {
            answer = { withFiles: !!dialog.element.querySelector('[data-files]')?.checked };
            dialog.close();
        });
    });
}

// ------------------------------------------------------------- the switches
window.genSetPreserveOrder = function(checked) {
    preserveOrder = !!checked;
    writeFlag(PRESERVE_ORDER_KEY, preserveOrder);
    const grid = byId('gen_grid');
    grid?.classList.toggle('gen-ordered', preserveOrder);
    applySpans();
};

window.genShowNsfw = function(checked) {
    hideNsfw = !checked;
    window.scrollTo?.(0, 0);
    return reload();
};

window.genRefresh = () => reload();

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
    byId('gen_grid')?.classList.toggle('gen-ordered', preserveOrder);
    try {
        hideNsfw = (await galleryDefaults()).hideNsfw;
    } catch (e) { /* the gallery's default: hidden */ }
    watchEnd();
    // Hidden, nothing could be measured: measure again once it is shown.
    window.addEventListener('resize', layout);
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(layout);
    await reload();
});
