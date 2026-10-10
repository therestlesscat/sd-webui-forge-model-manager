/**
 * The Gallery tab (#209): the Civitai images stored for the models in your
 * library, laid out as the Generations tab lays out your own, in an order a
 * sorting seed picks.
 *
 * The seed is the server's, kept in the database: the same seed always gives
 * the same order, and the toolbar changes it - typed, or New seed - starting
 * the grid again from its top. "Group by" gathers the images of one model,
 * base model, type or size into a tile, its first four images and how many it
 * has; a click opens it in a grid of its own, with Back. A click on an image
 * opens the viewer every gallery uses: Send, Resources, Show model, and its
 * text beside it. The grid scrolls: the next part loads as its end comes near.
 * Only the NSFW switch hides.
 *
 * The order, the groups and the parts are the server's (api/gallery.py); the
 * grid's layout is the Generations tab's (shared/tiles.mjs).
 */

// The shared modules, under the version this script was asked for under (loader.mjs).
const shared = (name) => import(new URL(`../shared/${name}${new URL(import.meta.url).search}`, import.meta.url).href);

// Asked for all at once, then taken one by one below.
const SHARED_MODULES = ['core.mjs', 'loading.mjs', 'ui_options.mjs', 'notes.mjs', 'gallery.mjs', 'media.mjs',
    'nsfw.mjs', 'image_card.mjs', 'resources.mjs', 'send.mjs', 'update_notice.mjs', 'viewer.mjs', 'settings.mjs',
    'tiles.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { apiCall, escapeHtml, setText } = await shared('core.mjs');
const { tabWork, open } = await shared('loading.mjs');
const { galleryDefaults, nsfwModelNote, asUploaded } = await shared('ui_options.mjs');
const { showNotes } = await shared('notes.mjs');
const { renderFilterBanner } = await shared('gallery.mjs');
const {
    setupLazyMedia, sizedMediaUrl, IMAGE_PLACEHOLDER_SVG, isVideoUrl, videoPosterUrl, originalMediaUrl,
    mediaFallback, mediaShape, viewerVideoUrl,
} = await shared('media.mjs');
const { nsfwBadge } = await shared('nsfw.mjs');
const { imageTextHtml } = await shared('image_card.mjs');
const { showImageResources } = await shared('resources.mjs');
const { sendGalleryImage, cannotSend } = await shared('send.mjs');
const { wide, aspect, layoutTiles, pathHtml, endIsNear, watchEnd: watchGridEnd, currentScroll, topOf, MAX_SPAN } =
    await shared('tiles.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The image viewer every gallery opens.
const { openViewer, closeViewer, viewerIsOpen, dialogShowing } = await shared('viewer.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// What this tab uses that has work of its own: the loading module starts each
// once for the page, before this tab (#182, #183).
export const STARTS = ['core.mjs', 'ui_options.mjs', 'notes.mjs', 'media.mjs', 'image_card.mjs', 'resources.mjs',
    'send.mjs', 'update_notice.mjs', 'settings.mjs'];

// What this tab does once started, done by start(scope) through the scope.
const work = tabWork();
let tabScope = null;

// "Group by", remembered in this browser.
const GROUP_BY_KEY = 'mm_gallery_group_by';
// What a group is called, by what the images are grouped by (GROUPINGS on the server).
const GROUP_NAMES = { model: 'Model', base_model: 'Base model', type: 'Type', size: 'Size' };
const GROUP_PLURALS = { model: 'models', base_model: 'base models', type: 'types', size: 'sizes' };
// A tile's column and its image's height, as the stylesheet draws them
// (--gen-column-width, --gen-image-height): what a copy is sized for.
const COLUMN_WIDTH = 200;
const IMAGE_HEIGHT = 300;
// What a type is called, as the Type menus in the Model Manager and the
// Civitai Browser call it; any other type by its own name.
const TYPE_NAMES = { TextualInversion: 'Embedding', Controlnet: 'ControlNet' };

let groupBy = GROUP_NAMES[readSetting(GROUP_BY_KEY, '')] ? readSetting(GROUP_BY_KEY, '') : '';
let hideNsfw = true;
let seed = null;            // as the server last said
// The level shown: its tiles, as loaded, and where it is. The level above,
// when a group is open, is kept whole for Back.
let tiles = [];
let state = null;           // the totals, for the banner
let scope = null;           // what the level is, for its header
let part = 0;
let more = true;
let inGroup = null;         // the group opened: {key, value}
const levels = [];
let loading = false;
let request = 0;            // a newer load drops an older one's answer

function readSetting(key, fallback) {
    try {
        return localStorage.getItem(key) ?? fallback;
    } catch (e) {
        return fallback;
    }
}

function writeSetting(key, value) {
    try {
        localStorage.setItem(key, String(value));
    } catch (e) { /* remembered for this visit only */ }
}

const byId = (id) => document.getElementById(id);

// ------------------------------------------------------------- Group by
function groupLabel(value) {
    return GROUP_NAMES[value] || 'Nothing';
}

function groupList() {
    return document.querySelector('#gallery_app .gen-group-list');
}

function groupMenuHtml() {
    const pick = (value, text) => `<button type="button" data-group-pick="${escapeHtml(value)}"
        class="${value === groupBy ? 'gen-group-chosen' : ''}">${escapeHtml(text)}</button>`;
    return pick('', 'Nothing') + Object.entries(GROUP_NAMES).map(([value, text]) => pick(value, text)).join('');
}

/** The button says the grouping - writing nothing when it already does: this runs after every update. */
function showGroupChoice() {
    setText(byId('gal_group_by'), groupLabel(groupBy));
}

function closeGroupMenu() {
    const list = groupList();
    if (!list || list.hidden) return false;
    list.hidden = true;
    byId('gal_group_by')?.setAttribute('aria-expanded', 'false');
    return true;
}

work.listen(document, 'click', (event) => {
    const target = event.target;
    const list = groupList();
    if (!list) return;
    if (target.closest?.('#gal_group_by')) {
        if (!closeGroupMenu()) {
            list.innerHTML = groupMenuHtml();
            list.hidden = false;
            byId('gal_group_by')?.setAttribute('aria-expanded', 'true');
        }
        return;
    }
    if (list.hidden) return;
    const pick = target.closest?.('[data-group-pick]');
    if (pick && list.contains(pick)) {
        closeGroupMenu();
        setGroupBy(pick.dataset.groupPick);
        return;
    }
    if (!target.closest?.('#gallery_app .gen-group-menu')) closeGroupMenu();
});

// ------------------------------------------------------------- loading
/** This level again from its first part: a switch, a seed, Refresh, or opening. */
async function reload() {
    closeViewer();
    tiles = [];
    part = 0;
    more = true;
    loading = false;
    request += 1;
    const grid = byId('gal_grid');
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
        const data = await apiCall({ endpoint: '/model-manager/gallery/browse', params: {
            page: part + 1, hide_nsfw_images: hideNsfw, group: groupBy, in_group: inGroup ? inGroup.key : '',
        } });
        if (asked !== request) return;
        if (!data.success) {
            setStatus(`Could not load the gallery: ${data.error || 'no answer'}`);
            return;
        }
        part += 1;
        more = !!data.more;
        state = data.state;
        scope = data.scope;
        showSeed(data.seed);
        const first = tiles.length;
        tiles = tiles.concat(data.tiles || []);
        appendTiles(first);
        renderBanner();
        renderPath();
        setStatus(tiles.length ? '' : emptyText());
    } catch (error) {
        if (asked === request) setStatus(`Could not load the gallery: ${error.message}`);
    } finally {
        if (asked === request) loading = false;
    }
    if (asked === request) loadIfNearEnd();
}

function emptyText() {
    if (state && state.total) return 'Every image is hidden by the NSFW filter.';
    return 'No stored images yet: a sync with Civitai stores each model\'s images, and they appear here.';
}

function setStatus(text) {
    const status = byId('gal_status');
    if (status) status.textContent = text;
}

function loadIfNearEnd() {
    if (more && !loading && endIsNear(byId('gal_sentinel'))) loadNext();
}

// ------------------------------------------------------------- the seed
/** The seed in its box, as the server says - not while it is being typed in. */
function showSeed(value) {
    if (value === undefined || value === null) return;
    seed = Number(value);
    const box = byId('gal_seed');
    if (box && document.activeElement !== box && box.value !== String(seed)) box.value = String(seed);
}

/** Keep a seed - the one typed, or a new one - and start again from the top, in its order. */
async function keepSeed(value) {
    const body = new URLSearchParams();
    if (value !== null) body.set('seed', String(value));
    try {
        const response = await fetch('/model-manager/gallery/seed', { method: 'POST', body });
        const data = await response.json();
        if (!data.success) {
            setStatus(`Could not keep the seed: ${data.error || 'no answer'}`);
            return;
        }
        seed = Number(data.seed);
        const box = byId('gal_seed');
        if (box) box.value = String(seed);
    } catch (error) {
        setStatus(`Could not keep the seed: ${error.message}`);
        return;
    }
    await toTop();
}

/** A seed typed: kept if it is a whole number from 1; anything else puts the kept one back. */
function typedSeed(box) {
    const value = Number(box.value);
    if (!Number.isInteger(value) || value < 1) {
        if (seed !== null) box.value = String(seed);
        return undefined;
    }
    if (value === seed) return undefined;
    return keepSeed(value);
}

// ------------------------------------------------------------- levels
/** The top level again, from its first part: the order or the grouping changed. */
function toTop() {
    levels.length = 0;
    inGroup = null;
    scope = null;
    window.scrollTo?.(0, topOf(byId('gallery_app')));
    return reload();
}

/** Open a group in a grid of its own; this level is kept as it is, for Back. */
async function openTile(index) {
    const tile = tiles[index];
    if (!tile || tile.kind !== 'group') return;
    levels.push({ tiles, state, scope, part, more, inGroup, scrollY: currentScroll() });
    inGroup = { key: tile.group.key, value: tile.group.value };
    scope = null;
    window.scrollTo?.(0, topOf(byId('gallery_app')));
    await reload();
}

/** Back to the level above, where it was left: the same tiles, drawn again. */
function goBack() {
    if (!levels.length) return;
    closeViewer();
    request += 1;
    loading = false;
    const above = levels.pop();
    ({ tiles, state, scope, part, more, inGroup } = above);
    const grid = byId('gal_grid');
    if (grid) grid.innerHTML = '';
    appendTiles(0);
    renderBanner();
    renderPath();
    setStatus(tiles.length ? '' : emptyText());
    window.scrollTo?.(0, above.scrollY);
}

function groupTitle(value, by = groupBy) {
    return `${GROUP_NAMES[by] || 'Group'}: ${value || 'Unknown'}`;
}

/** Inside a group: Back, the way here, how many images. */
function renderPath() {
    const path = byId('gal_path');
    if (!path) return;
    if (!levels.length || !inGroup) {
        path.innerHTML = '';
        return;
    }
    const facts = scope ? [`${scope.count} image${scope.count === 1 ? '' : 's'}`] : [];
    path.innerHTML = pathHtml({ trail: ['Gallery', groupTitle(inGroup.value)], facts, back: 'gallery.back' });
}

// ------------------------------------------------------------- drawing
/**
 * How wide a tile draws an image: as wide as its height makes it, at least a
 * column, at most MAX_SPAN of them. A wide one's tile spans columns: asked
 * for at one column's width, a 16:9 image drawn 600px wide came as a copy
 * 320 wide, and soft.
 */
function drawnWidth(image) {
    return Math.min(Math.max(COLUMN_WIDTH, IMAGE_HEIGHT * aspect(image)), COLUMN_WIDTH * MAX_SPAN);
}

/** One image, lazily, as a copy the size the tile draws it - or as uploaded, where the settings say so. */
function imageHtml(image) {
    const src = image.url || '';
    const shown = sizedMediaUrl(src, { cssWidth: drawnWidth(image), originalWidth: image.width, type: image.type,
                                       asUploaded: asUploaded().gallery });
    const level = nsfwBadge(image);
    const badge = level ? `<span class="mm-nsfw-badge">${escapeHtml(level)}</span>` : '';
    const media = isVideoUrl({ url: src, type: image.type })
        ? `<video data-src="${escapeHtml(shown)}" data-poster="${escapeHtml(videoPosterUrl(src))}" class="mm-lazy-media"
                  preload="none" muted loop ${mediaShape(image)} ${mediaFallback(originalMediaUrl(src))}></video>`
        : `<img data-src="${escapeHtml(shown || IMAGE_PLACEHOLDER_SVG)}" class="mm-lazy-media"
                src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Civitai image" loading="lazy"
                ${mediaShape(image)} ${mediaFallback(originalMediaUrl(src), IMAGE_PLACEHOLDER_SVG)}>`;
    return `<div class="mm-generation-tile">${media}${badge}</div>`;
}

/**
 * One tile: a group - its first four images, how many, and a click opens it -
 * or one image, which a click shows in the viewer, with Send and Show model.
 */
function tileHtml(tile, index) {
    const image = tile.images?.[0] || tile.image || {};
    let media;
    let actions;
    if (tile.kind === 'group') {
        const preview = tile.images.slice(0, 4);
        media = `
            <div class="mm-generation-preview mm-generation-preview-${preview.length} gen-group-preview gen-openable"
                 data-action="gallery.open" data-tile="${index}" title="Open this group: all ${tile.matching_count} images">
                ${preview.map((img) => imageHtml(img)).join('')}
            </div>
            <span class="gen-count">×${tile.matching_count}</span>
            <span class="gen-group-name" title="${escapeHtml(groupTitle(tile.group.value, tile.group.by))}">`
            + `${escapeHtml(tile.group.value || 'Unknown')}</span>`;
        actions = `<div class="gen-actions gen-group-facts">${tile.matching_count} image${tile.matching_count === 1 ? '' : 's'}</div>`;
    } else {
        media = `<div class="gen-viewable" data-action="gallery.view" data-tile="${index}" title="View">${imageHtml(image)}</div>`;
        const blocked = cannotSend(image, tile.model, tile.version);
        actions = `<div class="gen-actions">
                <button type="button" class="mm-btn primary mm-btn-small" data-action="gallery.send" data-tile="${index}"
                        ${blocked ? `disabled title="${escapeHtml(blocked)}"` : 'title="Send to txt2img"'}>Send</button>
                <button type="button" class="mm-btn secondary mm-btn-small" data-action="gallery.showModel" data-tile="${index}"
                        title="Open ${escapeHtml(tile.model?.name || 'its model')} in the Model Manager">Model</button>
            </div>`;
        // What kind of model it is from, which, and the image's size: "LORA · A LoRA · 512×768".
        const size = image.width && image.height ? `${Number(image.width)}×${Number(image.height)}` : '';
        const type = tile.model?.model_type;
        const label = [TYPE_NAMES[type] || type, tile.model?.name, size].filter(Boolean).join(' · ');
        if (label) media += `<span class="gen-date">${escapeHtml(label)}</span>`;
    }
    const classes = ['gen-tile', wide(image) && 'gen-wide', tile.kind === 'group' && 'gen-group gen-grouping']
        .filter(Boolean).join(' ');
    return `
        <div class="${classes}" data-aspect="${aspect(image)}">
            <div class="gen-media">${media}</div>
            ${actions}
        </div>`;
}

function layout() {
    layoutTiles(byId('gallery_app'), byId('gal_grid'));
}

function appendTiles(from) {
    const grid = byId('gal_grid');
    if (!grid) return;
    grid.insertAdjacentHTML('beforeend', tiles.slice(from)
        .map((tile, i) => `<div class="gen-set" data-tile="${from + i}">${tileHtml(tile, from + i)}</div>`).join(''));
    setupLazyMedia(grid);
    layout();
}

function renderBanner() {
    const banner = byId('gal_banner');
    if (!banner || !state) return;
    const onScreen = tiles.reduce((sum, t) => sum + (t.kind === 'group' ? t.matching_count || 0 : 1), 0);
    banner.innerHTML = renderFilterBanner({
        matching: state.filtered || 0,
        total: state.total || 0,
        onScreen,
        word: 'stored',
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        switches: [{
            id: 'gal_show_nsfw', label: 'Show NSFW', reason: 'NSFW filter',
            showing: !hideNsfw, hidden: state.hidden_nsfw || 0, count: state.nsfw_count || 0,
            action: 'gallery.showNsfw', note: nsfwModelNote(),
        }],
    });
}

// ------------------------------------------------------------- the tiles' actions
function sendTile(tile) {
    if (!tile || tile.kind !== 'image') return undefined;
    closeViewer();
    return sendGalleryImage({ img: tile.image, model: tile.model, version: tile.version });
}

/** Its model in the Model Manager, at the version the image is of, through the loading module (#184). */
function showModel(tile) {
    if (!tile?.version?.id) return undefined;
    closeViewer();
    return open('modelManager', 'showVersion', tile.version.id, tile.version.file_path);
}

// ------------------------------------------------------------- the viewer
// The images the grid shows, in order - a group's first four, as on its tile -
// and on, loading the next part into the grid, past the last.

function viewerImages() {
    const list = [];
    tiles.forEach((tile, t) => {
        if (tile.kind === 'image') list.push({ t, image: tile.image, tile });
        else (tile.images || []).forEach((image) => list.push({ t, image, tile }));
    });
    return list;
}

const viewerSource = {
    count: () => viewerImages().length,
    media: (index) => {
        const image = viewerImages()[index]?.image;
        return { url: image ? originalMediaUrl(image.url || '') : IMAGE_PLACEHOLDER_SVG,
                 video: image ? isVideoUrl({ url: image.url, type: image.type }) : false,
                 width: Number(image?.width) || 0, height: Number(image?.height) || 0 };
    },
    videoUrl: (media, box) => viewerVideoUrl(media.url, media, box),
    buttons: (index) => {
        const place = viewerImages()[index];
        if (!place) return '';
        // A group's image is sent as its own: its model and version come with the tile it opens onto.
        const tile = place.tile.kind === 'image' ? place.tile : null;
        const blocked = tile ? cannotSend(place.image, tile.model, tile.version) : 'Open the group to send its images';
        return `<button type="button" class="mm-btn primary mm-btn-small" data-gal-send
                        ${blocked ? `disabled title="${escapeHtml(blocked)}"` : ''}>Send to txt2img</button>
            <button type="button" class="mm-btn secondary mm-btn-small" data-gal-resources>Resources</button>
            ${tile ? '<button type="button" class="mm-btn secondary mm-btn-small" data-gal-model>Show model</button>' : ''}`;
    },
    details: (index) => {
        const place = viewerImages()[index];
        if (!place) return '';
        const tile = place.tile.kind === 'image' ? place.tile : null;
        const heading = tile?.model?.name
            ? `<div class="gen-info-heading">Model</div><div class="gen-info-value">${escapeHtml(
                [tile.model.name, tile.version?.name].filter(Boolean).join(' · '))}</div>` : '';
        return heading + imageTextHtml(place.image);
    },
    where: () => '',
    more: () => more,
    loadMore: async () => {
        while (loading) await tabScope.sleep(50);
        await loadNext();
    },
    onClick: (event, index) => {
        const place = viewerImages()[index];
        if (!place) return false;
        const tile = place.tile.kind === 'image' ? place.tile : null;
        if (event.target.closest?.('[data-gal-send]')) {
            if (tile) sendTile(tile);
            return true;
        }
        if (event.target.closest?.('[data-gal-resources]')) {
            showImageResources(place.image, tile?.version?.id);
            return true;
        }
        if (event.target.closest?.('[data-gal-model]')) {
            if (tile) showModel(tile);
            return true;
        }
        return false;
    },
    onClose: (index) => {
        const place = viewerImages()[index];
        if (place) document.querySelector(`#gal_grid .gen-set[data-tile="${place.t}"]`)?.scrollIntoView?.({ block: 'nearest' });
    },
};

function viewTile(index) {
    const at = viewerImages().findIndex((place) => place.t === index);
    if (at >= 0) openViewer(viewerSource, at);
}

/** Esc closes the Group by menu, or - no viewer open - goes back up a level, while this tab is shown. */
function onKey(event) {
    if (dialogShowing()) return;
    if (event.key === 'Escape' && closeGroupMenu()) {
        event.preventDefault?.();
        event.stopImmediatePropagation?.();
        return;
    }
    if (viewerIsOpen()) return;
    if (event.key === 'Escape' && levels.length && byId('gal_grid')?.offsetParent !== null) {
        event.preventDefault?.();
        goBack();
    }
}

// ------------------------------------------------------------- the switches
/** Group by something else, or nothing: the tab starts again from its top level. */
function setGroupBy(value) {
    const next = GROUP_NAMES[value] ? value : '';
    if (next === groupBy && !levels.length) return undefined;
    groupBy = next;
    writeSetting(GROUP_BY_KEY, groupBy);
    showGroupChoice();
    return toTop();
}

function showNsfw(checked) {
    hideNsfw = !checked;
    return reload();
}

// ---------------------------------------------------------------- markup
// What this tab's markup does, by name (shared/calls.mjs, #95).
work.provide('gallery.seed', (data, box) => typedSeed(box));
work.provide('gallery.newSeed', () => keepSeed(null));
work.provide('gallery.refresh', () => reload());
work.provide('gallery.showNsfw', (data, box) => showNsfw(box.checked));
work.provide('gallery.back', () => goBack());
work.provide('gallery.open', ({ tile }) => openTile(Number(tile)));
work.provide('gallery.view', ({ tile }) => viewTile(Number(tile)));
work.provide('gallery.send', ({ tile }) => sendTile(tiles[Number(tile)]));
work.provide('gallery.showModel', ({ tile }) => showModel(tiles[Number(tile)]));
// Not markup's: for code, and tests - grouping, and the next part now.
work.provide('gallery.groupBy', (value) => setGroupBy(value));
work.provide('gallery.loadMore', () => loadNext());

/**
 * Started by the loading module once Gradio has drawn the tab (#183): what is
 * declared above, then the grid and its first part.
 */
export async function start(startScope) {
    tabScope = startScope;
    work.start(startScope);
    showNotes('gallery', 'gal_notes');
    showGroupChoice();
    try {
        hideNsfw = (await galleryDefaults()).hideNsfw;
    } catch (e) { /* the gallery's default: hidden */ }
    watchGridEnd(tabScope, byId('gal_sentinel'), loadIfNearEnd);
    tabScope.listen(document, 'keydown', onKey);
    // Hidden, nothing could be measured: measure again once it is shown.
    tabScope.listen(window, 'resize', layout);
    tabScope.afterUpdate(layout);
    tabScope.afterUpdate(showGroupChoice);
    await reload();
}
