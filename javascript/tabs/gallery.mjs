/**
 * The Civitai Images tab (#209): the Civitai images stored for the models in your
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
    'tiles.mjs', 'previous_position.mjs', 'grouping.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { apiCall, escapeHtml, safeId, setText } = await shared('core.mjs');
const { tabWork, open } = await shared('loading.mjs');
const { galleryDefaults, nsfwModelNote, asUploaded } = await shared('ui_options.mjs');
const { showNotes } = await shared('notes.mjs');
const { renderFilterBanner } = await shared('gallery.mjs');
const {
    setupLazyMedia, sizedMediaUrl, IMAGE_PLACEHOLDER_SVG, isVideoUrl, videoPosterUrl, originalMediaUrl,
    mediaFallback, mediaShape, viewerVideoUrl,
} = await shared('media.mjs');
const { nsfwBadge } = await shared('nsfw.mjs');
const { imageDetailsHtml, showImageMeta } = await shared('image_card.mjs');
const { showImageResources, resourceButtonLabel } = await shared('resources.mjs');
const { sendGalleryImage, cannotSend } = await shared('send.mjs');
const { wide, aspect, layoutTiles, pathHtml, endIsNear, watchEnd: watchGridEnd, currentScroll, topOf, MAX_SPAN,
    placedGrid, showTile } = await shared('tiles.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The image viewer every gallery opens.
const { openViewer, closeViewer, viewerIsOpen, dialogShowing } = await shared('viewer.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// Previous Position (#250): Send and Show model note where the page was, and
// the toolbar's button goes back there.
const { previousPosition } = await shared('previous_position.mjs');
const { groupChain: chainOf, groupMenu: makeGroupMenu, startSearchBox } = await shared('grouping.mjs');
const previousPlace = previousPosition({ id: 'gal_scroll_restore_btn', action: 'gallery.previousPosition',
                                         row: '#gallery_app .gen-toolbar', before: 'gal_refresh_btn' });

// What this tab uses that has work of its own: the loading module starts each
// once for the page, before this tab (#182, #183).
export const STARTS = ['core.mjs', 'ui_options.mjs', 'notes.mjs', 'media.mjs', 'image_card.mjs', 'resources.mjs',
    'send.mjs', 'update_notice.mjs', 'settings.mjs'];

// What this tab does once started, done by start(scope) through the scope.
const work = tabWork();
let tabScope = null;

// "Group by", remembered in this browser.
const GROUP_BY_KEY = 'mm_gallery_group_by';
// How the grid is placed (#240), as Settings -> Model Manager says.
const GRID_SETTING = 'model_manager_gallery_grid';
// What this tab shows, above it until closed - closed, remembered in this browser.
const ABOUT_CLOSED_KEY = 'mm_gallery_about_closed';
// What a group is called, by what the images are grouped by (GROUPINGS on the server).
// What a group is called, by what the images are grouped by (GROUPINGS on the server): the
// gallery's model, its base model, its file's type; the image's size, prompt, LoRAs, day (#283).
const GROUP_NAMES = {
    model: 'Model', base_model: 'Base model', type: 'Type', size: 'Size',
    prompt: 'Prompt', loras: 'LoRA combination', day: 'Day',
};
const GROUP_PLURALS = {
    model: 'models', base_model: 'base models', type: 'types', size: 'sizes',
    prompt: 'prompts', loras: 'LoRA combinations', day: 'days',
};
// A tile's column and its image's height, as the stylesheet draws them
// (--gen-column-width, --gen-image-height): what a copy is sized for.
const COLUMN_WIDTH = 200;
const IMAGE_HEIGHT = 300;
// What a type is called, as the Type menus in the Model Manager and the
// Civitai Browser call it; any other type by its own name.
const TYPE_NAMES = { TextualInversion: 'Embedding', Controlnet: 'ControlNet' };

let groupBy = chainOf(readSetting(GROUP_BY_KEY, ''), GROUP_NAMES).length ? readSetting(GROUP_BY_KEY, '') : '';
let search = '';
let hideNsfw = true;
// How the grid is placed, as the settings say (#240): Fast, by the tab - its
// placement, from start() - or Classic, by the browser.
let fast = true;
let placed = null;
let seed = null;            // as the server last said
// The level shown: its tiles, as loaded, and where it is. The level above,
// when a group is open, is kept whole for Back.
let tiles = [];
let state = null;           // the totals, for the banner
let scope = null;           // what the level is, for its header
let part = 0;
let more = true;
let at = {};                // the groups opened: {in_group, in_subgroup}
let title = '';             // the level's title, in the path
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

// Kept here too: where the browser stores nothing, a Close holds for this visit.
let aboutClosed = readSetting(ABOUT_CLOSED_KEY, '') === 'true';

/** The message on what this tab shows: until it is closed. Written only when it differs. */
function showAbout() {
    const about = byId('gal_about');
    if (about && about.hidden !== aboutClosed) about.hidden = aboutClosed;
}

function closeAbout() {
    aboutClosed = true;
    writeSetting(ABOUT_CLOSED_KEY, 'true');
    showAbout();
}

// ------------------------------------------------------------- Group by
/** What a Group by value groups by, in order: one grouping or two (shared/grouping.mjs). */
function groupChain(value) {
    return chainOf(value, GROUP_NAMES);
}

// The menu, its "then by" lists and its listeners: shared/grouping.mjs.
const groupMenu = makeGroupMenu(work, {
    app: '#gallery_app', button: 'gal_group_by', names: GROUP_NAMES,
    current: () => groupBy, choose: (value) => setGroupBy(value),
});
const showGroupChoice = () => groupMenu.showChoice();
const closeGroupMenu = () => groupMenu.close();

// ------------------------------------------------------------- loading
/** This level again from its first part: a switch, a seed, Refresh, or opening. */
async function reload() {
    closeViewer();
    // Previous Position is a height in the grid that goes now.
    previousPlace.clear();
    tiles = [];
    part = 0;
    more = true;
    loading = false;
    request += 1;
    const grid = byId('gal_grid');
    if (grid) grid.innerHTML = '';
    placed?.reset();
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
            page: part + 1, hide_nsfw_images: hideNsfw, group: groupBy,
            in_group: at.in_group ?? '', in_subgroup: at.in_subgroup ?? '', search,
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
    if (search && !(state && state.total)) return 'No image matches the search.';
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
    at = {};
    title = '';
    scope = null;
    window.scrollTo?.(0, topOf(byId('gallery_app')));
    return reload();
}

/** Open a group in a grid of its own; this level is kept as it is, for Back. */
async function openTile(index) {
    const tile = tiles[index];
    if (!tile || tile.kind !== 'group') return;
    levels.push({ tiles, state, scope, part, more, at, title, scrollY: currentScroll() });
    // A group of the first grouping opens onto the second's groups, when there is one.
    const key = String(tile.group.key ?? '');
    at = at.in_group !== undefined ? { in_group: at.in_group, in_subgroup: key } : { in_group: key };
    title = groupTitle(tile.group.value, tile.group.by);
    scope = null;
    window.scrollTo?.(0, topOf(byId('gallery_app')));
    await reload();
}

/** Back to the level above, where it was left: the same tiles, drawn again. */
function goBack() {
    if (!levels.length) return;
    closeViewer();
    previousPlace.clear();
    request += 1;
    loading = false;
    const above = levels.pop();
    ({ tiles, state, scope, part, more, at, title } = above);
    const grid = byId('gal_grid');
    if (grid) grid.innerHTML = '';
    placed?.reset();
    appendTiles(0);
    renderBanner();
    renderPath();
    setStatus(tiles.length ? '' : emptyText());
    window.scrollTo?.(0, above.scrollY);
}

/** "Model: xyz" - `by`, what the group's images share; the first grouping if not said. */
function groupTitle(value, by = groupChain(groupBy)[0]) {
    return `${GROUP_NAMES[by] || 'Group'}: ${value || emptyGroupValue(by)}`;
}

/** What a group of images that share nothing of `by` is called. */
function emptyGroupValue(by) {
    return by === 'loras' ? 'No LoRAs' : by === 'prompt' ? 'No prompt' : 'Unknown';
}

/** Inside a group: Back, the way here, how many images. */
function renderPath() {
    const path = byId('gal_path');
    if (!path) return;
    if (!levels.length) {
        path.innerHTML = '';
        return;
    }
    const facts = scope ? [`${scope.count} image${scope.count === 1 ? '' : 's'}`] : [];
    const trail = ['Civitai Images', ...levels.slice(1).map((level) => level.title), title];
    path.innerHTML = pathHtml({ trail, facts, back: 'gallery.back' });
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
    const image = tileImage(tile);
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
            + `${escapeHtml(tile.group.value || emptyGroupValue(tile.group.by))}</span>`;
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

/** The image a tile shows first, which its width goes by. */
function tileImage(tile) {
    return tile?.images?.[0] || tile?.image || {};
}

function setHtml(index) {
    return `<div class="gen-set" data-tile="${index}">${tileHtml(tiles[index], index)}</div>`;
}

function layout() {
    if (fast) placed?.relayout();
    else layoutTiles(byId('gallery_app'), byId('gal_grid'));
}

function appendTiles(from) {
    const grid = byId('gal_grid');
    if (!grid) return;
    if (fast && placed) {
        placed.add();
        return;
    }
    grid.insertAdjacentHTML('beforeend', tiles.slice(from).map((_, i) => setHtml(from + i)).join(''));
    setupLazyMedia(grid);
    layout();
}

/**
 * Fast or Classic, as the setting now says: the tiles held drawn again the
 * new way, the page where it was.
 */
function switchGrid(on) {
    if (on === fast) return;
    fast = on;
    const grid = byId('gal_grid');
    if (!grid) return;
    const y = currentScroll();
    placed?.off();
    grid.innerHTML = '';
    appendTiles(0);
    window.scrollTo?.(0, y);
    if (fast) placed?.relayout();
}

function renderBanner() {
    const banner = byId('gal_banner');
    if (!banner || !state) return;
    const onScreen = tiles.reduce((sum, t) => sum + (t.kind === 'group' ? t.matching_count || 0 : 1), 0);
    banner.innerHTML = renderFilterBanner({
        matching: state.filtered || 0,
        total: state.total || 0,
        onScreen,
        // Searching, the total is what the search found, not all that is stored.
        word: search ? 'found by the search' : 'stored',
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
    // Once it has closed: closing brought the image it showed last into
    // view, so the place is the image sent.
    previousPlace.remember();
    return sendGalleryImage({ img: tile.image, model: tile.model, version: tile.version });
}

/** Its model in the Model Manager, at the version the image is of, through the loading module (#184). */
function showModel(tile) {
    if (!tile?.version?.id) return undefined;
    closeViewer();
    previousPlace.remember();
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
        // What a Civitai image's card offers in the other tabs' viewers, in its order (#267).
        const image = place.image;
        const resources = resourceButtonLabel(image, tile?.version?.id);
        return `<button type="button" class="mm-btn primary mm-btn-small" data-gal-send
                        ${blocked ? `disabled title="${escapeHtml(blocked)}"` : ''}>Send to txt2img</button>
            <button type="button" class="mm-btn secondary mm-btn-small" data-copy="${escapeHtml(image.meta?.prompt || '')}">Copy Prompt</button>
            <button type="button" class="mm-btn secondary mm-btn-small" data-gal-show-all>Show All</button>
            ${image.id ? `<button type="button" class="mm-btn secondary mm-btn-small" data-open-url="https://civitai.com/images/${safeId(image.id)}">View on Civitai</button>` : ''}
            ${resources ? `<button type="button" class="mm-btn secondary mm-btn-small" data-gal-resources>${escapeHtml(resources)}</button>` : ''}
            ${tile ? '<button type="button" class="mm-btn secondary mm-btn-small" data-gal-model>Show model</button>' : ''}`;
    },
    details: (index) => {
        const place = viewerImages()[index];
        if (!place) return '';
        const tile = place.tile.kind === 'image' ? place.tile : null;
        const heading = tile?.model?.name
            ? `<div class="gen-info-heading">Model</div><div class="gen-info-value">${escapeHtml(
                [tile.model.name, tile.version?.name].filter(Boolean).join(' · '))}</div>` : '';
        return heading + imageDetailsHtml(place.image);
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
        if (event.target.closest?.('[data-gal-show-all]')) {
            showImageMeta(place.image);
            return true;
        }
        if (event.target.closest?.('[data-gal-resources]')) {
            showImageResources(place.image, tile?.version?.id, { leaving: () => previousPlace.remember() });
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
        if (!place) return;
        if (fast && placed) placed.scrollTo(place.t);
        else showTile(byId('gal_grid'), place.t);
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
    const next = groupChain(value).length ? value : '';
    if (next === groupBy && !levels.length) return undefined;
    groupBy = next;
    writeSetting(GROUP_BY_KEY, groupBy);
    showGroupChoice();
    return toTop();
}

/** Search, or show everything again: the tab starts again from its top level. */
function setSearch(value) {
    const text = String(value || '').trim();
    if (text === search) return undefined;
    search = text;
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
work.provide('gallery.search', (data, box) => setSearch(box.value));
work.provide('gallery.showNsfw', (data, box) => showNsfw(box.checked));
work.provide('gallery.back', () => goBack());
work.provide('gallery.open', ({ tile }) => openTile(Number(tile)));
work.provide('gallery.view', ({ tile }) => viewTile(Number(tile)));
work.provide('gallery.send', ({ tile }) => sendTile(tiles[Number(tile)]));
work.provide('gallery.showModel', ({ tile }) => showModel(tiles[Number(tile)]));
work.provide('gallery.previousPosition', () => previousPlace.restore());
work.provide('gallery.closeAbout', () => closeAbout());
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
    showAbout();
    showGroupChoice();
    startSearchBox(byId('gal_search'), setSearch);
    placed = placedGrid({
        scope: tabScope,
        grid: () => byId('gal_grid'),
        app: () => byId('gallery_app'),
        count: () => tiles.length,
        html: setHtml,
        imageOf: (index) => tileImage(tiles[index]),
        drawn: (grid) => setupLazyMedia(grid),
    });
    try {
        const defaults = await galleryDefaults();
        hideNsfw = defaults.hideNsfw;
        fast = defaults.galleryFast;
    } catch (e) { /* the gallery's default: hidden; the grid Fast */ }
    // The grid setting saved, in the settings window or on the Settings page.
    const followGrid = (changed) => {
        if (!changed.includes(GRID_SETTING)) return;
        galleryDefaults().then((defaults) => switchGrid(defaults.galleryFast)).catch(() => {});
    };
    tabScope.listen(window, 'mm-settings-saved', (event) => followGrid(event.detail?.changed || []));
    tabScope.listen(window, 'mm-settings-page-applied', (event) => followGrid(event.detail?.changed || []));
    watchGridEnd(tabScope, byId('gal_sentinel'), loadIfNearEnd);
    tabScope.listen(document, 'keydown', onKey);
    // Hidden, nothing could be measured: measure again once it is shown.
    tabScope.listen(window, 'resize', layout);
    tabScope.afterUpdate(layout);
    tabScope.afterUpdate(showGroupChoice);
    tabScope.afterUpdate(showAbout);
    await reload();
}
