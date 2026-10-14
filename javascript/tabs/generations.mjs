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
 * near. A search narrows it to the images whose prompt or negative prompt
 * holds its words, or that a task of the Queue made (task:17). Only the NSFW
 * switch hides; nothing is hidden here for its prompt.
 *
 * The server does the filtering, the grouping and the parts
 * (api/generations.browse_page). The paste into txt2img or img2img is
 * shared/send.mjs's, as the Model Manager's is.
 */

// The shared modules, under the version this script was asked for under: the
// loading module imports it with the one the loader asked the server for
// (loader.mjs), so every tab and the loading module use one copy of each.
const shared = (name) => import(new URL(`../shared/${name}${new URL(import.meta.url).search}`, import.meta.url).href);

// Asked for all at once, then taken one by one below. Awaited in turn, each
// module waited a round trip of its own before the next was asked for. An
// import of a URL already asked for is the same module, so the awaits find
// them on their way. A failure still stops the tab at its await; the catch
// here only keeps it from being reported twice.
const SHARED_MODULES = ['core.mjs', 'loading.mjs', 'calls.mjs', 'tabs.mjs', 'ui_options.mjs', 'notes.mjs',
    'gallery.mjs', 'media.mjs', 'nsfw.mjs', 'chips.mjs', 'wan.mjs', 'generations.mjs', 'samplers.mjs',
    'send.mjs', 'update_notice.mjs', 'viewer.mjs', 'settings.mjs', 'tiles.mjs', 'previous_position.mjs', 'resources.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { TIMING, apiCall, escapeHtml, setText } = await shared('core.mjs');
const { ready, call } = await shared('calls.mjs');
const { tabWork, available, open, unavailableReason } = await shared('loading.mjs');
const { showTab } = await shared('tabs.mjs');
const { sendInfotext } = await shared('send.mjs');
const { showImageResources, resourceButtonLabel } = await shared('resources.mjs');
const { nsfwModelNote, galleryDefaults, shownPath } = await shared('ui_options.mjs');
const { showNotes } = await shared('notes.mjs');
const { renderFilterBanner } = await shared('gallery.mjs');
const { setupLazyMedia, IMAGE_PLACEHOLDER_SVG } = await shared('media.mjs');
// The grid both this tab and the Civitai Images tab draw (#209).
const {
    wide, aspect, spanFor, applySpans: spanTiles, layoutTiles, pathHtml, endIsNear, watchEnd: watchGridEnd,
    currentScroll, topOf, placedGrid, showTile,
} = await shared('tiles.mjs');
const {
    ratingRowHtml, selectBarHtml, bulkDeleteQuestion, deleteManyGenerations, bulkDeleteReport,
    generationImageHtml, requestRating, requestImageDelete, requestGenerationDelete, pickRange,
} = await shared('generations.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The image viewer every gallery opens.
const {
    openViewer, closeViewer, showImage, viewerIndex, viewerIsOpen, askToDelete, dialogShowing,
} = await shared('viewer.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// Previous Position (#250): Send and the ⋯ menu's links note where the page
// was, and the toolbar's button goes back there.
const { previousPosition } = await shared('previous_position.mjs');
const previousPlace = previousPosition({ id: 'gen_scroll_restore_btn', action: 'generations.previousPosition',
                                         row: '#generations_app .gen-toolbar', before: 'gen_sync_btn' });

// What this tab uses that has work of its own - a listener, a request: the
// loading module starts each once for the page, before this tab (#182, #183).
export const STARTS = ['core.mjs', 'calls.mjs', 'ui_options.mjs', 'notes.mjs', 'media.mjs', 'send.mjs',
    'update_notice.mjs', 'settings.mjs'];

// What this tab does once started, declared where it belongs below and done by
// start(scope) through the scope (shared/loading.mjs, #183): nothing runs as
// this script is imported, and all it added goes when the tab stops.
const work = tabWork();
let tabScope = null;        // this tab's, from start()

// "Preserve order" and "Group by", remembered in this browser.
const PRESERVE_ORDER_KEY = 'mm_generations_preserve_order';
// "Expand generations" (#252): a tile per image where a level lists generations.
// How the grid is placed (#240), as Settings -> Model Manager says.
const GRID_SETTING = 'model_manager_generations_grid';
const EXPAND_KEY = 'mm_generations_expand';
const GROUP_BY_KEY = 'mm_generations_group_by';
// What a group is called, by what the images are grouped by (GROUPINGS on the server).
const GROUP_NAMES = {
    prompt_written: 'Prompt, as written', prompt: 'Prompt, as generated', base_model: 'Base model',
    model: 'Model', loras: 'LoRA combination', size: 'Size', day: 'Day',
};

/**
 * What a Group by value groups by, in order: one grouping, or two joined by
 * ">" ("model>prompt_written"), a group of the first opening onto groups of
 * the second. Anything else is no grouping - grouping_chain() on the server.
 */
function groupChain(value) {
    const keys = String(value || '').split('>');
    return keys.length <= 2 && keys.every((key) => GROUP_NAMES[key]) ? keys : [];
}

// ------------------------------------------------------------- Group by
// A menu rather than a list: the groupings - a click groups by one - and
// beside each, on hover, what to group its groups by then: any other. Built
// here, from GROUP_NAMES, into the tab's empty list, each time it opens.

function groupLabel(value) {
    const chain = groupChain(value);
    return chain.length ? chain.map((key) => GROUP_NAMES[key]).join(' › ') : 'Nothing';
}

function groupMenuHtml() {
    const keys = Object.keys(GROUP_NAMES);
    const chain = groupChain(groupBy);
    const pick = (value, text) => `<button type="button" data-group-pick="${escapeHtml(value)}"
        class="${value === groupBy ? 'gen-group-chosen' : ''}">${escapeHtml(text)}</button>`;
    return pick('', 'Nothing') + keys.map((first) => `
        <div class="gen-group-item" data-group-first="${first}">
            <button type="button" data-group-pick="${first}" class="${chain[0] === first ? 'gen-group-chosen' : ''}"
                    aria-haspopup="true">${escapeHtml(GROUP_NAMES[first])}<span>▸</span></button>
            <div class="gen-group-sub gen-menu-panel" hidden>
                <div class="gen-group-sub-title">then by</div>
                ${keys.filter((key) => key !== first).map((key) => pick(`${first}>${key}`, GROUP_NAMES[key])).join('')}
            </div>
        </div>`).join('');
}

/**
 * The button says the grouping, after Gradio redraws the tab too - and writes
 * nothing when it already does: this runs after every update. The list is
 * drawn when the menu opens, marking the choice then.
 */
function showGroupChoice() {
    setText(byId('gen_group_by'), groupLabel(groupBy));
}

function groupList() {
    return document.querySelector('#generations_app .gen-group-list');
}

/** The "then by" list of one grouping open, any other closed. */
function openGroupItem(item) {
    groupList()?.querySelectorAll('.gen-group-item').forEach((other) => {
        const open = other === item;
        other.classList.toggle('gen-group-open', open);
        const sub = other.querySelector('.gen-group-sub');
        if (sub) sub.hidden = !open;
    });
}

function closeGroupMenu() {
    const list = groupList();
    if (!list || list.hidden) return false;
    list.hidden = true;
    byId('gen_group_by')?.setAttribute('aria-expanded', 'false');
    return true;
}

work.listen(document, 'click', (event) => {
    const target = event.target;
    const list = groupList();
    if (!list) return;
    if (target.closest?.('#gen_group_by')) {
        if (!closeGroupMenu()) {
            list.innerHTML = groupMenuHtml();
            list.hidden = false;
            byId('gen_group_by')?.setAttribute('aria-expanded', 'true');
            // The chosen grouping's "then by" list open, to change the second.
            openGroupItem(list.querySelector('.gen-group-item > .gen-group-chosen')?.parentElement || null);
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
    const item = target.closest?.('.gen-group-item');
    if (item && list.contains(item)) {
        openGroupItem(item);
        return;
    }
    if (!target.closest?.('.gen-group-menu')) closeGroupMenu();
});

work.listen(document, 'mouseover', (event) => {
    const item = event.target.closest?.('.gen-group-item');
    if (item && groupList()?.contains(item) && !item.classList.contains('gen-group-open')) openGroupItem(item);
});

// What a section's groups are, counted in its header: "5 prompts".
const GROUP_PLURALS = {
    prompt_written: ['prompt', 'prompts'], prompt: ['prompt', 'prompts'],
    base_model: ['base model', 'base models'], model: ['model', 'models'],
    loras: ['LoRA combination', 'LoRA combinations'], size: ['size', 'sizes'], day: ['day', 'days'],
};

/**
 * What a group whose value is empty is called: no LoRAs; a checkpoint the
 * library has no base model for, Unknown; else none.
 */
function emptyGroupValue(by) {
    return by === 'loras' ? 'No LoRAs' : by === 'base_model' ? 'Unknown' : 'None';
}

let preserveOrder = readFlag(PRESERVE_ORDER_KEY);
let expand = readFlag(EXPAND_KEY);
let rating = false;      // "Rate": a row of levels under every image - not remembered
// How the grid is placed, as the settings say (#240): Fast, by the tab - its
// placement, from start() - or Classic, by the browser.
let fast = true;
let placed = null;
// "Select": a tick on every batch and image, and one Delete for all. The
// ticks, by what they pick (tileKey) - places move as tiles go - and the
// last one ticked, for shift-click. Not remembered, and cleared on any
// change of level.
let selecting = false;
const selected = new Set();
let lastPicked = -1;
let groupBy = groupChain(readSetting(GROUP_BY_KEY, '')).length ? readSetting(GROUP_BY_KEY, '') : '';
let hideNsfw = true;
// What the images must match: words in their prompts, or task:<id>. Not remembered.
let search = '';
// The level shown: its tiles, as loaded, and where it is. The levels above it
// are kept whole in `levels`, so Back draws them again as they were left.
let tiles = [];          // each {kind, generation, group, images, matching_count}
let state = null;        // the totals, for the banner
let scope = null;        // what the level is, for its header
let part = 0;            // the last part loaded
let more = true;
let at = {};             // what the level is inside: {in_group, in_subgroup, generation}
let title = '';          // what the path calls it
const levels = [];       // the levels above, each as it was left
let loading = false;
let request = 0;         // a newer load drops an older one's answer

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
    clearSelection();
    // Previous Position is a height in the grid that goes now.
    previousPlace.clear();
    tiles = [];
    part = 0;
    more = true;
    loading = false;
    request += 1;
    const grid = byId('gen_grid');
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
        const data = await apiCall({ endpoint: '/model-manager/generations/browse', params: {
            page: part + 1, hide_nsfw_images: hideNsfw, group: groupBy,
            in_group: at.in_group, in_subgroup: at.in_subgroup, generation: at.generation, search, expand,
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
    if (search && !(state && state.total)) return 'No image matches the search.';
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
    if (more && !loading && endIsNear(byId('gen_sentinel'))) loadNext();
}

function watchEnd() {
    watchGridEnd(tabScope, byId('gen_sentinel'), loadIfNearEnd);
}

// ------------------------------------------------------------- levels
/**
 * Open a batch or a group in a grid of its own, in place of this one. This
 * level is kept as it is - its tiles and where the page was scrolled - for
 * Back.
 */
async function openTile(index) {
    // Selecting, a batch's click ticks it (the listener beside Select); a group still opens.
    if (selecting && tileKey(tiles[index])) return;
    clearSelection();
    const tile = tiles[index];
    if (!tile) return;
    levels.push({ tiles, state, scope, part, more, at, title, scrollY: currentScroll(), dirty: false });
    if (tile.kind === 'group') {
        // Grouped twice, a group of the first grouping opens onto groups of
        // the second, and one of those onto its batches.
        // In a section, straight to the group's batches: it is inside the section.
        if (tile.section) {
            at = { in_group: tile.section.id, in_subgroup: tile.group.id };
            title = `${groupTitle(tile.section.value, tile.section.by)} › ${groupTitle(tile.group.value, tile.group.by)}`;
        } else {
            at = at.in_group ? { in_group: at.in_group, in_subgroup: tile.group.id } : { in_group: tile.group.id };
            title = groupTitle(tile.group.value, tile.group.by);
        }
    } else {
        at = { in_group: at.in_group, in_subgroup: at.in_subgroup, generation: tile.generation.id };
        title = `${formatWhen(tile.generation.created_at)} · ${tile.matching_count} images`;
    }
    scope = null;
    window.scrollTo?.(0, topOfTab());
    await reload();
}

/**
 * Back to the level above, where it was left: the same tiles, drawn again, and
 * the page scrolled where it was. Loaded again only if something was deleted
 * inside - and then as far as it had been, so the place is the same.
 */
async function goBack() {
    clearSelection();
    if (!levels.length) return;
    closeViewer();
    previousPlace.clear();
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
}

/** Something above this level may have changed: it loads again on Back. */
function markAboveChanged() {
    for (const level of levels) level.dirty = true;
}

/** Where the tab starts on the page, to show a new level from its top. */
function topOfTab() {
    return topOf(byId('generations_app'));
}

/** "Model: xyz" - `by`, what the group's images share; the first grouping if not said. */
function groupTitle(value, by = groupChain(groupBy)[0]) {
    return `${GROUP_NAMES[by] || 'Group'}: ${value || emptyGroupValue(by)}`;
}

function formatWhen(when, style = 'short') {
    return when ? new Date(when).toLocaleString(undefined, { dateStyle: style, timeStyle: 'short' }) : '';
}

/**
 * The header of a level inside another: Back, the way here, and what the
 * level is - its whole prompt, if it is one, how many images, and when.
 */
function renderPath() {
    showSelectSwitch();
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
    path.innerHTML = pathHtml({ trail, facts, back: 'generations.back' });
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
    const image = tileImage(tile);
    // Selecting, a click on a batch or an image ticks it (the listener beside
    // Select): it says so, and no zoom-in cursor says it opens the viewer (#114).
    const key = tileKey(tile);
    const picks = selecting && key;

    let media;
    if (folded) {
        const preview = tile.images.slice(0, 4);
        const what = tile.kind === 'group' ? 'group' : 'generation';
        media = `
            <div class="mm-generation-preview mm-generation-preview-${preview.length} gen-group-preview ${picks ? 'gen-pickable' : 'gen-openable'}"
                 data-action="generations.open" data-tile="${index}" title="${picks ? 'Select' : 'Open'} this ${what}: all ${tile.matching_count} images">
                ${preview.map((img) => generationImageHtml(img)).join('')}
            </div>
            <span class="gen-count">×${tile.matching_count}</span>`;
        if (tile.kind === 'group') {
            const by = tile.group.by || groupChain(groupBy)[0];
            media += `<span class="gen-group-name" title="${escapeHtml(groupTitle(tile.group.value, by))}">`
                + `${escapeHtml(tile.group.value || emptyGroupValue(by))}</span>`;
        }
    } else {
        media = `<div class="${picks ? 'gen-pickable' : 'gen-viewable'}" data-action="generations.view" data-tile="${index}" title="${picks ? 'Select' : 'View'}">${generationImageHtml(image)}</div>`;
    }

    // Select's tick: a batch or an image, never a group - open it, and pick inside.
    // Its click has to reach the page's listener, which counts it: nothing
    // stops it here, and the tile's own click does nothing while selecting.
    if (picks) {
        media += `<label class="mm-select-tick" title="Select">
                      <input type="checkbox" data-gen-pick="${index}" ${selected.has(key) ? 'checked' : ''}></label>`;
    }

    // More, behind ⋯ - while there is anything to offer.
    if (tileMenu(tile).length) {
        media += `<button type="button" class="gen-menu-btn" title="More"
                          data-action="generations.menu" data-tile="${index}">⋯</button>`;
    }

    // When, and its size: a group's newest image's, a batch's first's.
    const when = formatWhen(tile.kind === 'group' ? tile.group.latest : generation.created_at);
    const size = image.width && image.height ? `${Number(image.width)}×${Number(image.height)}` : '';
    const label = [when, size].filter(Boolean).join(' · ');
    if (label) media += `<span class="gen-date">${escapeHtml(label)}</span>`;

    // A group is not rated whole: its images are of any prompt and settings.
    const rateRow = rating && tile.kind !== 'group'
        ? ratingRowHtml(folded ? tile : image, 'generations.rate', { tile: index }) : '';

    const classes = ['gen-tile', wide(image) && 'gen-wide', folded && 'gen-group',
                     tile.kind === 'group' && 'gen-grouping'].filter(Boolean).join(' ');
    // A group is a way in, not something to act on: its images are of any
    // prompt and settings - Send would send one image as if it stood for them
    // all, and Delete would take many at once. Its row says what it holds.
    const actions = tile.kind === 'group'
        ? `<div class="gen-actions gen-group-facts">${tile.matching_count} image${tile.matching_count === 1 ? '' : 's'}`
          + ` · ${tile.group.generations} generation${tile.group.generations === 1 ? '' : 's'}</div>`
        : `<div class="gen-actions">
                ${sendHtml(image, mode, `data-action="generations.send" data-tile="${index}"`)}${mode}</button>
                <button type="button" class="mm-btn danger mm-btn-small" data-action="generations.delete" data-tile="${index}">Delete</button>
            </div>`;
    return `
        <div class="${classes}" data-generation="${Number(generation.id)}" data-aspect="${aspect(image)}">
            <div class="gen-media">${media}</div>
            ${rateRow}
            ${actions}
        </div>`;
}

/**
 * Every wide tile's columns, as the grid now is; with "Preserve order", every
 * tile one column: the grid fills a gap a wide tile leaves with a later tile,
 * so the order is only roughly newest first, and fitting wide tiles to their
 * rows instead still left gaps, and drew images of one size at different sizes.
 */
function applySpans() {
    if (fast) placed?.replace();
    else spanTiles(byId('gen_grid'), { oneColumn: preserveOrder });
}

/** Columns wide enough for the buttons, then each tile's span over them. */
function layout() {
    if (fast) placed?.relayout();
    else layoutTiles(byId('generations_app'), byId('gen_grid'), { oneColumn: preserveOrder });
}

/** The image a tile shows first, which its width goes by. */
function tileImage(tile) {
    return tile?.images?.[0] || {};
}

/** Whether a tile starts its section, grouped twice: its header comes before it. */
function startsSection(index) {
    const section = tiles[index]?.section;
    return Boolean(section) && (index === 0 || tiles[index - 1].section?.id !== section.id);
}

/**
 * A tile's place in the grid: a wrapper the grid does not see, so it can be
 * redrawn alone. Grouped twice, the first tile of a section carries the
 * section's header, a row across the grid.
 */
function setHtml(index) {
    const tile = tiles[index];
    const head = startsSection(index) ? sectionHeadHtml(tile.section, tile.group?.by) : '';
    return `<div class="gen-set" data-tile="${index}">${head}${tileHtml(tile, index)}</div>`;
}

function sectionHeadHtml(section, by) {
    const [one, many] = GROUP_PLURALS[by] || ['group', 'groups'];
    const facts = [`${section.groups} ${section.groups === 1 ? one : many}`,
                   `${section.count} image${section.count === 1 ? '' : 's'}`];
    return `<div class="gen-section-head"><span class="gen-section-name">${escapeHtml(groupTitle(section.value, section.by))}</span>`
        + `<span class="gen-section-facts">${escapeHtml(facts.join(' · '))}</span></div>`;
}

function appendTiles(from) {
    const grid = byId('gen_grid');
    if (!grid) return;
    // In sections, no tile is packed into a hole above its section's header.
    grid.classList.toggle('gen-sectioned', tiles.some((t) => t.section));
    if (fast && placed) {
        placed.add();
        return;
    }
    grid.insertAdjacentHTML('beforeend', tiles.slice(from).map((_, i) => setHtml(from + i)).join(''));
    setupLazyMedia(grid);
    layout();
}

function redrawTile(index) {
    if (fast && placed) {
        placed.redraw(index);
        return;
    }
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
    placed?.reset({ keepHeight: true });
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
        // Searching, the total is what the search found, not all that is stored.
        word: search ? 'found by the search' : 'stored',
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        switches: [{
            id: 'gen_show_nsfw', label: 'Show NSFW', reason: 'NSFW filter',
            showing: !hideNsfw, hidden: state.hidden_nsfw || 0, count: state.nsfw_count || 0,
            action: 'generations.showNsfw', note: nsfwModelNote(),
        }],
    });
}

// ------------------------------------------------------------- the tiles' actions
/** Ask the server to rate: the switch this tab counts under goes with it (shared/generations.mjs). */
function postRating(fields) {
    return requestRating({ hide_nsfw_images: hideNsfw, ...fields }, setStatus);
}

// An image a sync brought with no generation text (#233) has nothing for
// Send to paste: its button is disabled, saying so, where it once did
// nothing at all - seen on 7880.
const NO_TEXT = 'This image has no infotext - Sync images found none in the file - so there is nothing to send.';

function sendHtml(image, mode, attributes) {
    const why = image?.infotext ? '' : NO_TEXT;
    return `<button type="button" class="mm-btn primary mm-btn-small" ${attributes}`
        + ` title="${escapeHtml(why || `Send to ${mode}`)}"${why ? ' disabled' : ''}>`;
}

/** Send a tile's image - a batch's first - back to the tab it was made in. Not a group's. */
async function sendTile(index) {
    const tile = tiles[index];
    if (!tile?.images?.[0] || tile.kind === 'group') return;
    previousPlace.remember();
    await sendImage(tile, tile.images[0]);
}

async function sendImage(tile, image) {
    if (!await sendInfotext({ infotext: image.infotext, mode: tile.generation.mode, meta: image.meta,
                              generationId: tile.generation.id, imageId: image.id })) {
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
async function rateTile(index, value) {
    const tile = tiles[index];
    if (!tile || tile.kind === 'group') return;
    const single = tile.kind === 'image' || (tile.kind === 'generation' && tile.matching_count <= 1);
    if (single) {
        await rateImage(index, tile.images[0], value);
        return;
    }
    const level = tile.user_level === value ? '' : value;
    const batch = { group: groupBy, in_group: at.in_group, in_subgroup: at.in_subgroup,
                    generation: tile.generation.id, search };
    const answer = await postRating({ ...batch, level });
    if (!answer) return;
    markAboveChanged();
    // The answer carries the batch's tile as its level now draws it, and the
    // level's totals (#239): that tile alone changes, where every part loaded
    // was asked for again. A server not yet restarted sends no tile.
    if (!('tile' in answer)) {
        await reloadKeepingPlace();
        return;
    }
    if (answer.tile) {
        tiles[index] = answer.tile;
        redrawTile(index);
    } else {
        removeTile(index);
    }
    state = answer.state;
    scope = answer.scope;
    renderBanner();
    renderPath();
}

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
    placed?.reset();
    while (part < parts && more) {
        const before = part;
        await loadNext();
        if (part === before) break;
    }
    setStatus(tiles.length ? '' : emptyText());
    window.scrollTo?.(0, y);
}

/**
 * Fast or Classic, as the setting now says: the tiles held drawn again the
 * new way, the page where it was.
 */
function switchGrid(on) {
    if (on === fast) return;
    fast = on;
    const grid = byId('gen_grid');
    if (!grid) return;
    const y = currentScroll();
    placed?.off();
    redrawAll();
    window.scrollTo?.(0, y);
    if (fast) placed?.relayout();
}

function switchRating(checked) {
    rating = !!checked;
    if (rating && selecting) setSelecting(false);
    redrawAll();
}

// ------------------------------------------------------------- selecting
/**
 * What a tile's tick picks: a batch the whole generation, as its Delete - g:
 * - and an image, or a batch of one shown, that image - i:. A group nothing.
 */
function tileKey(tile) {
    if (!tile || tile.kind === 'group') return null;
    if (tile.kind === 'image' || (tile.matching_count || 0) <= 1) {
        return tile.images?.[0] ? `i:${tile.images[0].id}` : null;
    }
    return tile.generation?.id ? `g:${tile.generation.id}` : null;
}

/** What the ticks come to: images (hidden ones too), generations, and the ids to send. */
function selection() {
    const out = { images: 0, hidden: 0, generations: new Set(), generationIds: [], imageIds: [] };
    for (const tile of tiles) {
        const key = tileKey(tile);
        if (!key || !selected.has(key)) continue;
        const id = Number(key.slice(2));
        if (key.startsWith('g:')) {
            const all = tile.generation.image_count || tile.matching_count || 1;
            out.images += all;
            out.hidden += Math.max(0, all - (tile.matching_count || 0));
            out.generationIds.push(id);
        } else {
            out.images += 1;
            out.imageIds.push(id);
        }
        if (tile.generation?.id) out.generations.add(tile.generation.id);
    }
    return out;
}

function updateSelectBar() {
    const bar = byId('gen_select_bar');
    if (!bar) return;
    bar.hidden = !selecting;
    bar.innerHTML = selecting ? selectBarHtml(selection().images, { all: 'generations.selectAll',
        clear: 'generations.selectClear', delete: 'generations.deleteSelected' }) : '';
}

/** The ticks drawn as the selection is: after a range or Select all. */
function showTicks() {
    document.querySelectorAll('#gen_grid [data-gen-pick]').forEach((box) => {
        box.checked = selected.has(tileKey(tiles[Number(box.dataset.genPick)]));
    });
    updateSelectBar();
}

function clearSelection() {
    selected.clear();
    lastPicked = -1;
    updateSelectBar();
}

/**
 * Select only where there is something to tick: grouped, the top level is all
 * groups, which have none - and grouped twice, so is the level a group opens
 * onto. So its switch is hidden there, and turned off coming back to it;
 * opening a group down to its batches brings it back.
 */
function levelIsGroups() {
    const chain = groupChain(groupBy);
    if (!chain.length || at.generation) return false;
    return !at.in_group || (chain.length === 2 && !at.in_subgroup);
}

function showSelectSwitch() {
    const label = byId('gen_select')?.closest('label');
    if (!label) return;
    const onlyGroups = levelIsGroups();
    label.hidden = onlyGroups;
    if (onlyGroups && selecting) setSelecting(false);
}

function setSelecting(on) {
    selecting = on;
    const box = byId('gen_select');
    if (box) box.checked = on;
    clearSelection();
}

function switchSelecting(checked) {
    setSelecting(!!checked);
    if (selecting && rating) {
        rating = false;
        const rate = byId('gen_rate');
        if (rate) rate.checked = false;
    }
    redrawAll();
}

/**
 * Tick tile `index`, or untick it - or with shift every tile from the last
 * one ticked, as this one now is.
 */
function pickTile(index, on, shift) {
    const range = pickRange(lastPicked, index, shift);
    for (let i = range[0]; i <= range[1]; i++) {
        const key = tileKey(tiles[i]);
        if (!key) continue;
        if (on) selected.add(key);
        else selected.delete(key);
    }
    lastPicked = index;
    showTicks();
}

work.listen(document, 'click', (event) => {
    const box = event.target.closest?.('[data-gen-pick]');
    if (!box) return;
    pickTile(Number(box.dataset.genPick), box.checked, event.shiftKey);
});

// Selecting, a click anywhere on a tile's image ticks it - it neither opens
// the viewer nor, on a batch, the batch. Caught on the way down, before the
// image's own click; a group, which has no tick, still opens, and ⋯ is ⋯.
work.listen(document, 'click', (event) => {
    if (!selecting) return;
    const media = event.target.closest?.('#gen_grid .gen-media');
    if (!media || event.target.closest('[data-gen-pick], .gen-menu-btn, .gen-menu')) return;
    const index = Number(media.closest('.gen-set')?.dataset.tile);
    const key = tileKey(tiles[index]);
    if (!key) return;
    event.stopPropagation();
    event.preventDefault();
    pickTile(index, !selected.has(key), event.shiftKey);
}, true);

function selectAll() {
    for (const tile of tiles) {
        const key = tileKey(tile);
        if (key) selected.add(key);
    }
    showTicks();
}

function selectClear() {
    clearSelection();
    showTicks();
}

/** The one Delete: asked once, with how many and the files option. */
async function deleteSelected() {
    const picked = selection();
    if (!picked.images) return;
    const answer = await askToDelete(bulkDeleteQuestion(picked.images, picked.generations.size, picked.hidden),
                                     picked.images);
    if (!answer) return;
    const data = await deleteManyGenerations({ generationIds: picked.generationIds, imageIds: picked.imageIds,
                                               withFiles: answer.withFiles });
    if (!data.success) {
        setStatus(`Delete failed: ${data.error || 'no answer'}`);
        return;
    }
    tiles = tiles.filter((tile) => !selected.has(tileKey(tile)));
    clearSelection();
    redrawAll();
    markAboveChanged();
    await refreshTotals();
    setStatus(tiles.length ? bulkDeleteReport(data, answer.withFiles) : emptyText());
}

// ------------------------------------------------------------- the ⋯ menu
// More that can be done with a tile or the image in the viewer, in a menu
// under its ⋯ - which is not drawn when there is nothing in it.

/** What a tile's menu offers: its checkpoint, if its images share one, and the LoRAs they used. */
function tileMenu(tile) {
    return menuFor(tile);
}

/**
 * The menu for a tile or an image: its checkpoint in the Model Manager and
 * the Civitai Browser, and each LoRA in the Model Manager - by version, as
 * the server names them (file_ref): a path only for a file Civitai does not
 * know. One the library no longer holds is offered greyed, saying so,
 * rather than as a search that finds nothing.
 */
function menuFor(subject) {
    const items = [];
    const checkpoint = subject?.checkpoint;
    if (checkpoint) {
        items.push(showItem('Show model in Model Manager', checkpoint));
        if (checkpoint.model_id) {
            items.push(toTab('civitaiBrowser', { label: 'Show model in Civitai Browser',
                                                  run: () => showOnCivitai(checkpoint) }));
        }
    }
    for (const lora of subject?.loras || []) items.push(showItem(`Show LoRA ${lora.name} in Model Manager`, lora));
    return items;
}

function showItem(label, file) {
    return file.in_library
        ? toTab('modelManager', { label, run: () => showModel(file) })
        : { label, disabled: true, title: `${file.name} is not in the library: deleted, moved, or never scanned` };
}

/** An item opening another tab: greyed, saying why, while that tab is not available (#184). */
function toTab(name, item) {
    return available(name) ? item : { label: item.label, disabled: true, title: unavailableReason(name) };
}

function openTileMenu(index, button) {
    const tile = tiles[index];
    if (tile) openMenu(button, tileMenu(tile));
}

let menu = null;

/** The menu, under the button that opened it; a click anywhere else, or Esc, closes it. */
function openMenu(anchor, items) {
    closeMenu();
    if (!items.length) return;
    const element = document.createElement('div');
    element.className = 'gen-menu';
    element.setAttribute('role', 'menu');
    element.innerHTML = items.map((item, i) => `<button type="button" role="menuitem" data-item="${i}"`
        + `${item.disabled ? ' disabled' : ''}${item.title ? ` title="${escapeHtml(item.title)}"` : ''}>`
        + `${escapeHtml(item.label)}</button>`).join('');
    element.addEventListener('click', (event) => {
        const chosen = event.target.closest?.('[data-item]');
        if (!chosen || chosen.disabled) return;
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
    // A moment later, so the click that opened it does not close it - and only
    // while it is still open: an item clicked at once had closed it, and its
    // listener stayed, closing the next menu at a click inside it (#184).
    tabScope.later(() => {
        if (menu?.away === away) tabScope.listen(document, 'click', away, true);
    }, 0);
    menu = { element, away };
}

function closeMenu() {
    if (!menu) return false;
    menu.element.remove();
    tabScope.unlisten(document, 'click', menu.away, true);
    menu = null;
    return true;
}

/**
 * This model, in the Model Manager tab - by its version, or by its file where
 * Civitai does not know it - through the loading module (#184).
 */
function showModel(file) {
    closeViewer();
    previousPlace.remember();
    return file.version_id ? open('modelManager', 'showVersion', file.version_id, file.path)
        : open('modelManager', 'showFile', file.path);
}

/** Its model and version in the Civitai Browser tab, through the loading module (#184). */
function showOnCivitai(file) {
    closeViewer();
    previousPlace.remember();
    return open('civitaiBrowser', 'showModel', file.version_id ? `model:${file.model_id} version:${file.version_id}`
        : `model:${file.model_id}`);
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
        return `${ratingRowHtml(image, 'generations.rateInViewer')}
            ${sendHtml(image, mode, 'data-gen-send')}Send to ${mode}</button>
            <button type="button" class="mm-btn danger mm-btn-small" data-gen-delete>Delete</button>
            ${viewerResourcesHtml(image)}${viewerModelHtml(image)}`;
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
        while (loading) await tabScope.sleep(50);
        await loadNext();
    },
    onClick: (event, index) => {
        const { tile, image } = viewerAt(index);
        if (!image) return false;
        if (event.target.closest?.('[data-gen-send]')) {
            if (!image.infotext) return true;
            closeViewer();
            // Once it has closed: closing brought the image it showed last
            // into view, so the place is the image sent.
            previousPlace.remember();
            sendImage(tile, image);
            return true;
        }
        if (event.target.closest?.('[data-gen-delete]')) {
            deleteFromViewer();
            return true;
        }
        if (event.target.closest?.('[data-gen-resources]')) {
            showImageResources(image, null, { leaving: () => previousPlace.remember() });
            return true;
        }
        if (event.target.closest?.('[data-gen-model]')) {
            if (image.checkpoint?.in_library) showModel(image.checkpoint);
            return true;
        }
        return false;
    },
    onClose: (index) => {
        closeMenu();
        const { t } = viewerAt(index);
        if (t === undefined) return;
        if (fast && placed) placed.scrollTo(t);
        else showTile(byId('gen_grid'), t);
    },
};

// The viewer's buttons for an image's models, as the other viewers have them
// (#267): Resources - its checkpoint, LoRAs and embeddings, from its own
// meta.resources (api/generations.image_resources) - and Show model, its
// checkpoint in the Model Manager. They took the place of a ⋯ menu.
function viewerResourcesHtml(image) {
    const label = resourceButtonLabel(image, null);
    return label ? `<button type="button" class="mm-btn secondary mm-btn-small" data-gen-resources>${escapeHtml(label)}</button>` : '';
}

function viewerModelHtml(image) {
    const checkpoint = image.checkpoint;
    const why = !checkpoint ? 'This image does not say which checkpoint it was made with'
        : !checkpoint.in_library ? `${checkpoint.name} is not in the library: deleted, moved, or never scanned`
        : !available('modelManager') ? unavailableReason('modelManager') : '';
    return `<button type="button" class="mm-btn secondary mm-btn-small" data-gen-model`
        + `${why ? ` disabled title="${escapeHtml(why)}"` : ' title="Open its checkpoint in the Model Manager"'}>Show model</button>`;
}

/** Open the viewer on image `image` of tile `index`. */
function viewTile(index, image = 0) {
    if (selecting && tileKey(tiles[index])) return;          // a click ticks it instead
    const at = viewerImages().findIndex((place) => place.t === index && place.i === image);
    if (at >= 0) openViewer(viewerSource, at);
}

/**
 * The keys this tab has besides the viewer's: Esc closes the ⋯ menu, or -
 * no viewer open - goes back up a level, while this tab is the one shown.
 */
function onKey(event) {
    if (dialogShowing() && !document.querySelector('.gen-menu')) return;     // a question is open
    if (event.key === 'Escape' && (closeGroupMenu() || closeMenu())) {
        event.preventDefault?.();
        event.stopImmediatePropagation?.();
        return;
    }
    if (viewerIsOpen()) return;
    if (event.key === 'Escape' && levels.length && byId('gen_grid')?.offsetParent !== null) {
        event.preventDefault?.();
        goBack();
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
        // To name one image when reporting what it did.
        ['Image ID', image.id ?? ''],
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
            ${image.exists ? `<button type="button" class="mm-btn secondary mm-btn-small"
                data-open-url="${escapeHtml(url)}">Open full size</button>` : ''}
        </div>`;
}

/**
 * Rate the image shown. If the NSFW switch now hides it, the viewer shows the
 * one now in its place - the next - or the last, as after a delete.
 */
async function rateInViewer(value) {
    const index = viewerIndex();
    const { t, image } = viewerAt(index);
    if (!image) return;
    await rateImage(t, image, value);
    if (viewerIndex() === index) showImage(index);
}

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
async function deleteTile(index) {
    const tile = tiles[index];
    if (!tile || tile.kind === 'group') return;
    if (tile.matching_count <= 1 || tile.kind === 'image') {
        await deleteImage(index, tile.images[0]);
        return;
    }
    const n = tile.generation.image_count || tile.matching_count || 1;
    const answer = await askToDelete(`Delete this generation of ${n} image${n === 1 ? '' : 's'}?`, n);
    if (!answer) return;
    if (await postDelete(requestGenerationDelete(tile.generation.id, answer.withFiles, setStatus))) {
        removeTile(index);
        markAboveChanged();
        await refreshTotals();
    }
}

/** Delete one image, asking first; true once it is gone, from the grid too. */
async function deleteImage(index, image) {
    if (!image) return false;
    const answer = await askToDelete('Delete this image?', 1);
    if (!answer) return false;
    if (!await postDelete(requestImageDelete(image.id, answer.withFiles, setStatus))) return false;
    forgetImage(index, image.id);
    markAboveChanged();
    await refreshTotals();
    return true;
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

/** A Delete's answer (shared/generations.mjs): whether it went, and any file it could not delete, said. */
async function postDelete(asked) {
    const data = await asked;
    if (data?.failed?.length) setStatus(`${data.failed.length} file(s) could not be deleted`);
    return !!data;
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
            page: 1, hide_nsfw_images: hideNsfw, group: groupBy, in_group: at.in_group,
            in_subgroup: at.in_subgroup, generation: at.generation, search, expand,
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
function switchPreserveOrder(checked) {
    preserveOrder = !!checked;
    writeFlag(PRESERVE_ORDER_KEY, preserveOrder);
    const grid = byId('gen_grid');
    grid?.classList.toggle('gen-ordered', preserveOrder);
    applySpans();
}

/**
 * Expand generations, or back to batches: the level you are on loads again,
 * and those above it on Back. A batch already shows its images: nothing to
 * load there, but the levels above it change all the same.
 */
function switchExpand(checked) {
    expand = !!checked;
    writeFlag(EXPAND_KEY, expand);
    markAboveChanged();
    return at.generation ? undefined : reload();
}

/** Group by something else, or nothing: the tab starts again from its top level. */
function setGroupBy(value) {
    groupBy = groupChain(value).length ? value : '';
    writeFlag(GROUP_BY_KEY, groupBy);
    showGroupChoice();
    levels.length = 0;
    at = {};
    title = '';
    scope = null;
    return reload();
}

/** Search, or show everything again: the tab starts again from its top level. */
function setSearch(value) {
    const text = String(value || '').trim();
    if (text === search) return undefined;
    search = text;
    levels.length = 0;
    at = {};
    title = '';
    scope = null;
    window.scrollTo?.(0, 0);
    return reload();
}

/**
 * A task's images, asked for by the Queue's Show images: this tab, searched
 * by the task, with Group by at Nothing for this visit - the grouping chosen
 * before is still the one remembered.
 */
async function showTask(taskId) {
    await showTab('generations');
    groupBy = '';
    showGroupChoice();
    const text = `task:${Number(taskId)}`;
    const box = byId('gen_search');
    if (box) box.value = text;
    // Asked again for the same task, it is drawn again.
    search = '';
    return setSearch(text);
}

function showNsfw(checked) {
    hideNsfw = !checked;
    markAboveChanged();
    window.scrollTo?.(0, 0);
    return reload();
}

const refresh = () => {
    markAboveChanged();
    return reload();
};

// ---------------------------------------------------------------- markup
// What this tab's markup does, by name: a tile, a button or a field says it
// in data-action, and carries what it needs in data-* (shared/calls.mjs, #95).
work.provide('generations.preserveOrder', (data, box) => switchPreserveOrder(box.checked));
work.provide('generations.expand', (data, box) => switchExpand(box.checked));
work.provide('generations.rating', (data, box) => switchRating(box.checked));
work.provide('generations.selecting', (data, box) => switchSelecting(box.checked));
work.provide('generations.refresh', () => refresh());
work.provide('generations.search', (data, box) => setSearch(box.value));
work.provide('generations.showNsfw', (data, box) => showNsfw(box.checked));
work.provide('generations.rate', ({ tile, level }) => rateTile(Number(tile), Number(level)));
work.provide('generations.rateInViewer', ({ level }) => rateInViewer(Number(level)));
work.provide('generations.selectAll', () => selectAll());
work.provide('generations.selectClear', () => selectClear());
work.provide('generations.deleteSelected', () => deleteSelected());
work.provide('generations.back', () => goBack());
work.provide('generations.open', ({ tile }) => openTile(Number(tile)));
work.provide('generations.view', ({ tile, image = 0 }) => viewTile(Number(tile), Number(image)));
work.provide('generations.menu', ({ tile }, button) => openTileMenu(Number(tile), button));
work.provide('generations.send', ({ tile }) => sendTile(Number(tile)));
work.provide('generations.previousPosition', () => previousPlace.restore());
work.provide('generations.delete', ({ tile }) => deleteTile(Number(tile)));
// Not markup's: for code, and tests - grouping by a chain, the next part now,
// and how many columns a wide image spans.
work.provide('generations.groupBy', (value) => setGroupBy(value));
work.provide('generations.loadMore', () => loadNext());
work.provide('generations.spanFor', spanFor);
work.provide('generations.syncImages', () => openSyncDialog());
work.provide('generations.syncTick', ({ path }, box) => tickSyncFolder(path, box.checked));
work.provide('generations.startSync', () => startSync());
work.provide('generations.syncForce', () => { drawSyncFolders(); showSyncEstimate(); });
work.provide('generations.syncThumbs', () => { showThumbnailPlace(); showSyncEstimate(); });
work.provide('generations.syncThumbsPlace', () => showThumbnailPlace());
work.provide('generations.closeSyncDialog', () => closeSyncDialog());
work.provide('generations.syncDialogBackdrop', (data, element, event) => {
    if (event?.target === element) closeSyncDialog();
});
work.provide('generations.cancelSync', () => cancelSync());
work.provide('generations.addSyncFolder', () => addSyncFolder());
work.provide('generations.askRemoveSyncFolder', ({ path }) => askRemoveSyncFolder(path, true));
work.provide('generations.keepSyncFolder', ({ path }) => askRemoveSyncFolder(path, false));
work.provide('generations.removeSyncFolder', ({ path }) => removeSyncFolder(path));
work.provide('generations.closeSyncPanel', () => { const panel = byId('gen_sync_panel'); if (panel) panel.hidden = true; });

// ---------------------------------------------------------- Sync images (#233)
// The images already on disk, added to this tab as generations: from the
// folders Forge saves results into and folders added, a long job on the
// server (model_manager/image_sync.py), followed here until it ends.
const SYNC = '/model-manager/generations/sync';
// Reading one file's text took 0.7 ms in one library: 53 s for 76,148 files.
const SYNC_READ_SECONDS = 0.0007;
let syncFolders = [];           // as the server listed them, each with its tick and its count
let syncThumbsMissing = null;   // the library's images with no thumbnail yet (#5), once counted
let syncFollowing = null;       // the interval following a sync

function syncCount(n) {
    return Number(n || 0).toLocaleString();
}

function syncDuration(seconds) {
    if (seconds < 45) return 'under a minute';
    const minutes = Math.round(seconds / 60);
    return minutes === 1 ? 'about a minute' : `about ${minutes} minutes`;
}

async function syncPost(path, fields) {
    try {
        const response = await fetch(path, {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(fields) });
        return await response.json();
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function openSyncDialog() {
    const dialog = byId('gen_sync_dialog');
    if (!dialog) return;
    dialog.style.display = 'flex';
    const box = byId('gen_sync_add_path');
    if (box) box.value = '';
    // Force sync is asked for each time, never kept (#246).
    const force = byId('gen_sync_force');
    if (force) force.checked = false;
    showAddNote('');
    showAddButton();
    await loadSyncFolders(null);
}

/**
 * List the folders and count what is new in each. After an Add or a Remove
 * the ticks given meanwhile are kept (`ticks`, by path); the level and the
 * grouping box are left as they are.
 */
async function loadSyncFolders(ticks) {
    byId('gen_sync_start').disabled = true;
    setText(byId('gen_sync_estimate'), 'Looking at the folders...');
    const data = await apiCall({ endpoint: `${SYNC}/folders` }).catch((e) => ({ success: false, error: e.message }));
    if (!data.success) {
        setText(byId('gen_sync_estimate'), `Could not list the folders: ${data.error}`);
        return;
    }
    syncFolders = data.folders.map((folder) => ({
        ...folder, count: null, asking: false,
        ticked: ticks?.has(folder.path.toLowerCase()) ? ticks.get(folder.path.toLowerCase()) : folder.ticked }));
    if (!ticks) {
        byId('gen_sync_level').innerHTML = data.levels.map((name) =>
            `<option value="${escapeHtml(name)}"${name === data.level ? ' selected' : ''}>${escapeHtml(name)}</option>`).join('');
        byId('gen_sync_group').checked = Boolean(data.group);
        showThumbnailChoices(data);
    }
    syncThumbsMissing = null;
    drawSyncFolders();
    showSyncEstimate();
    const counted = await apiCall({ endpoint: `${SYNC}/estimate` }).catch((e) => ({ success: false, error: e.message }));
    if (!counted.success) {
        setText(byId('gen_sync_estimate'), `Could not count the new images: ${counted.error}`);
        return;
    }
    syncFolders.forEach((folder) => {
        folder.count = counted.counts[folder.path] ?? 0;
        folder.again = counted.again?.[folder.path] ?? 0;
    });
    syncThumbsMissing = counted.thumbnails ?? 0;
    drawSyncFolders();
    showSyncEstimate();
}

function drawSyncFolders() {
    const list = byId('gen_sync_folders');
    if (!list) return;
    if (!syncFolders.length) {
        list.innerHTML = '<div class="mm-dialog-note">Forge names no result folder in its settings.</div>';
        return;
    }
    list.innerHTML = syncFolders.map((folder) => {
        const path = escapeHtml(folder.path);
        if (folder.asking) {
            const n = folder.synced || 0;
            const question = n
                ? `Remove ${shownPath(folder.path)}, and the ${syncCount(n)} generation${n === 1 ? '' : 's'} synced from it? The image files stay.`
                : `Remove ${shownPath(folder.path)} from the list?`;
            return `<div class="gen-sync-remove">
                        <span>${escapeHtml(question)}</span>
                        <button type="button" class="mm-btn mm-btn-small secondary" data-action="generations.keepSyncFolder" data-path="${path}">Keep</button>
                        <button type="button" class="mm-btn mm-btn-small danger" data-action="generations.removeSyncFolder" data-path="${path}">Remove</button>
                    </div>`;
        }
        const title = folder.forge ? `Forge saves results here (its setting ${folder.key})` : 'A folder you added';
        const count = folder.count === null ? 'counting...'
            : `${syncCount(folder.count)} new` + (forcing() && folder.again ? ` · ${syncCount(folder.again)} again` : '');
        const line = `<label class="mm-dialog-option" title="${escapeHtml(title)}">
                    <input type="checkbox" data-action="generations.syncTick" data-path="${path}"${folder.ticked ? ' checked' : ''}>
                    <span>${escapeHtml(shownPath(folder.path))}</span>
                    <span class="mm-dialog-count">${escapeHtml(count)}</span>
                </label>`;
        // Forge's own folders are unticked, never removed: Forge saves there.
        if (folder.forge) return line;
        return `<div class="gen-sync-folder">${line}
                    <button type="button" class="mm-btn mm-btn-small secondary" data-action="generations.askRemoveSyncFolder" data-path="${path}"
                            title="Take it off the list, and remove the generations synced from it. The image files stay.">Remove</button>
                </div>`;
    }).join('');
}

function tickSyncFolder(path, ticked) {
    const folder = syncFolders.find((f) => f.path === path);
    if (folder) folder.ticked = ticked;
    showSyncEstimate();
}

function forcing() {
    return Boolean(byId('gen_sync_force')?.checked);
}

// ------------------------------------------------- thumbnails (#5)
/** The dialog's thumbnail box, place and folder, as the settings have them. */
function showThumbnailChoices(data) {
    const box = byId('gen_sync_thumbs');
    if (box) box.checked = Boolean(data.thumbnails);
    // A place no radio names - none yet, or an old value - is in a folder,
    // the default: a box ticked with neither place would say nothing.
    const radios = [...document.querySelectorAll('input[name="gen_sync_thumbs_place"]')];
    const known = radios.some((radio) => radio.value === data.thumbnails_place);
    radios.forEach((radio) => {
        radio.checked = radio.value === (known ? data.thumbnails_place : 'In a folder');
    });
    const folder = byId('gen_sync_thumbs_folder');
    if (folder) {
        folder.value = data.thumbnails_folder || '';
        // In full: the box takes a full path only, and a hint trimmed to the
        // WebUI's folder read as one it would take.
        folder.placeholder = data.thumbnails_default_folder
            ? `Empty: ${data.thumbnails_default_folder}` : 'Empty: beside the database';
    }
    showThumbnailPlace();
}

function makingThumbnails() {
    return Boolean(byId('gen_sync_thumbs')?.checked);
}

function thumbnailPlace() {
    return document.querySelector('input[name="gen_sync_thumbs_place"]:checked')?.value || 'In a folder';
}

/** The place shows once the box is ticked; the folder's box only for a folder. */
function showThumbnailPlace() {
    const where = byId('gen_sync_thumbs_where');
    if (where) where.hidden = !makingThumbnails();
    // The folder only for thumbnails kept in one, as the settings window has it.
    const row = byId('gen_sync_thumbs_folder_row');
    if (row) row.hidden = thumbnailPlace() !== 'In a folder';
    const count = byId('gen_sync_thumbs_count');
    if (count) setText(count, syncThumbsMissing === null ? '' : `${syncCount(syncThumbsMissing)} without`);
}

function showSyncEstimate() {
    const ticked = syncFolders.filter((f) => f.ticked);
    const counting = ticked.some((f) => f.count === null) || (makingThumbnails() && syncThumbsMissing === null);
    const fresh = ticked.reduce((sum, f) => sum + (f.count || 0), 0);
    const again = forcing() ? ticked.reduce((sum, f) => sum + (f.again || 0), 0) : 0;
    const total = fresh + again;
    // Images that will need a thumbnail: those without one, and the new ones.
    const thumbs = makingThumbnails() ? (syncThumbsMissing || 0) + fresh : 0;
    let text;
    if (!ticked.length && !makingThumbnails()) text = 'Tick a folder to sync.';
    else if (counting) text = 'Counting the new images...';
    else if (!total && !thumbs) text = forcing() ? 'No images in the ticked folders.' : 'No new images in the ticked folders.';
    else {
        text = !total ? 'No new images in the ticked folders.'
            : (again ? `${syncCount(fresh)} new, ${syncCount(again)} to read again.` : `${syncCount(total)} new images.`)
              + ` Reading their text takes ${syncDuration(total * SYNC_READ_SECONDS)}; writing them comes after.`;
        if (thumbs) text += ` Then about ${syncCount(thumbs)} thumbnail${thumbs === 1 ? '' : 's'} to make: several at once, minutes for tens of thousands.`;
    }
    setText(byId('gen_sync_estimate'), text);
    showThumbnailPlace();
    // Start would do nothing until there is something to add, read again or make.
    const start = byId('gen_sync_start');
    if (start) start.disabled = counting || (!total && !thumbs);
}

function showAddNote(text) {
    const note = byId('gen_sync_add_note');
    if (!note) return;
    note.hidden = !text;
    setText(note, text);
}

/** Add waits for a path: pressed on an empty box it would do nothing. */
function showAddButton() {
    const button = byId('gen_sync_add');
    if (button) button.disabled = !(byId('gen_sync_add_path')?.value || '').trim();
}

function currentTicks() {
    return new Map(syncFolders.map((f) => [f.path.toLowerCase(), f.ticked]));
}

async function addSyncFolder() {
    const box = byId('gen_sync_add_path');
    const path = (box?.value || '').trim();
    if (!path) return;
    const button = byId('gen_sync_add');
    if (button) button.disabled = true;
    const answer = await syncPost(`${SYNC}/folders/add`, { path });
    if (!answer.success) {
        showAddNote(`Not added: ${answer.error}`);
        showAddButton();
        return;
    }
    if (box) box.value = '';
    showAddNote('');
    showAddButton();
    await loadSyncFolders(currentTicks());
}

function askRemoveSyncFolder(path, asking) {
    syncFolders.forEach((f) => { f.asking = asking && f.path === path; });
    drawSyncFolders();
}

async function removeSyncFolder(path) {
    const answer = await syncPost(`${SYNC}/folders/remove`, { path });
    if (!answer.success) {
        askRemoveSyncFolder(path, false);
        showAddNote(`Not removed: ${answer.error}`);
        return;
    }
    showAddNote(answer.removed ? `Removed the folder, and ${syncCount(answer.removed)} generations.` : 'Removed the folder.');
    await loadSyncFolders(currentTicks());
    if (answer.removed) refresh();
}

function closeSyncDialog() {
    const dialog = byId('gen_sync_dialog');
    if (dialog) dialog.style.display = 'none';
}

async function startSync() {
    const start = byId('gen_sync_start');
    if (start) start.disabled = true;
    const answer = await syncPost(SYNC, {
        folders: JSON.stringify(syncFolders.filter((f) => f.ticked).map((f) => f.path)),
        level: byId('gen_sync_level')?.value || '',
        group: String(Boolean(byId('gen_sync_group')?.checked)),
        force: String(forcing()),
        make_thumbnails: String(makingThumbnails()),
        place: thumbnailPlace(),
        // Beside each image, the folder box is hidden: what it holds is
        // neither sent nor judged, and the folder setting stays as it is.
        ...(thumbnailPlace() === 'In a folder' ? { folder: byId('gen_sync_thumbs_folder')?.value || '' } : {}),
    });
    if (!answer.success) {
        setText(byId('gen_sync_estimate'), `Could not start: ${answer.error}`);
        if (start) start.disabled = false;
        return;
    }
    closeSyncDialog();
    followSync();
}

async function cancelSync() {
    const cancel = byId('gen_sync_cancel');
    if (cancel) cancel.disabled = true;
    setText(byId('gen_sync_text'), 'Cancelling: finishing the step under way...');
    await syncPost(`${SYNC}/cancel`, {});
}

function followSync() {
    if (syncFollowing === null) syncFollowing = tabScope.every(pollSync, TIMING.poll);
    pollSync();
}

async function pollSync() {
    const data = await apiCall({ endpoint: `${SYNC}/progress` }).catch(() => null);
    const progress = data?.progress;
    if (!progress) return;
    drawSyncPanel(progress);
    if (progress.is_complete && syncFollowing !== null) {
        clearInterval(syncFollowing);
        syncFollowing = null;
        if (progress.generations || progress.thumbs_made) refresh();
    }
}

function syncStatus(p) {
    const where = p.folder ? ` in ${shownPath(p.folder)}` : '';
    const thumbs = p.thumbs_made ? ` Made ${syncCount(p.thumbs_made)} thumbnail${p.thumbs_made === 1 ? '' : 's'}.` : '';
    if (p.state === 'done') {
        return `Added ${syncCount(p.images)} images as ${syncCount(p.generations)} generations`
            + (p.again ? `, ${syncCount(p.again)} of them read again.` : '.') + thumbs;
    }
    if (p.state === 'cancelled') {
        return `Cancelled. ${syncCount(p.images)} images were added as ${syncCount(p.generations)} generations `
               + 'before it stopped; the next sync adds the rest.' + thumbs;
    }
    if (p.state === 'failed') return `Sync images failed: ${p.error}`;
    if (p.cancelling) return 'Cancelling: finishing the step under way...';
    if (p.stage === 'walking') return `Looking for new images${where}...`;
    if (p.stage === 'reading') return `Reading ${syncCount(p.read)} of ${syncCount(p.total)} images${where}`;
    if (p.stage === 'thumbnails') {
        return p.thumbs_total ? `Making thumbnails: ${syncCount(p.thumbs_done)} of ${syncCount(p.thumbs_total)}`
                              : 'Looking for images without a thumbnail...';
    }
    return `Writing: ${syncCount(p.images)} of ${syncCount(p.total)} images so far, as ${syncCount(p.generations)} generations`;
}

function drawSyncPanel(p) {
    const panel = byId('gen_sync_panel');
    if (!panel) return;
    panel.hidden = false;
    setText(byId('gen_sync_text'), syncStatus(p));
    const thumbing = p.stage === 'thumbnails';
    const done = p.stage === 'reading' ? p.read : p.stage === 'writing' ? p.images : thumbing ? p.thumbs_done : 0;
    const of = thumbing ? p.thumbs_total : p.total;
    const fill = byId('gen_sync_fill');
    if (fill) fill.style.width = p.is_complete ? '100%' : `${of ? Math.round(100 * done / of) : 0}%`;
    const cancel = byId('gen_sync_cancel');
    if (cancel) {
        cancel.hidden = p.is_complete;
        cancel.disabled = Boolean(p.cancelling);
    }
    const close = byId('gen_sync_close');
    if (close) close.hidden = !p.is_complete;
    const button = byId('gen_sync_btn');
    if (button) {
        button.disabled = !p.is_complete;
        button.title = p.is_complete ? "Add the images already in Forge's result folders, and folders you add, to this tab. The files stay where they are."
                                     : 'Sync images is running';
    }
    const errors = byId('gen_sync_errors');
    if (errors) {
        errors.hidden = !p.error_count;
        setText(byId('gen_sync_errors_summary'), `${syncCount(p.error_count)} could not be read`);
        const list = byId('gen_sync_errors_list');
        if (list) list.innerHTML = (p.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join('')
            + (p.error_count > (p.errors || []).length ? `<li>... and ${syncCount(p.error_count - p.errors.length)} more</li>` : '');
    }
}

/** A sync still running when the page loads is followed from where it is. */
async function pickUpSync() {
    const data = await apiCall({ endpoint: `${SYNC}/progress` }).catch(() => null);
    if (data?.progress && !data.progress.is_complete) followSync();
}
// What the other tabs may open this one at, through the loading module
// (open, #184): the Queue's Show images, a task's images, here.
export const entries = { showTask, syncImages: () => openSyncDialog() };

/**
 * Started by the loading module once Gradio has drawn the tab (#183) - which
 * it draws after the page is ready: the first load once found no grid, and
 * the tab stayed empty until Refresh. What is declared above, then the boxes,
 * the grid and the first page.
 */
export async function start(scope) {
    tabScope = scope;
    work.start(scope);
    // A menu open as it stops goes with it: it is on the page's body, not in the tab.
    tabScope.onStop(() => closeMenu());
    showNotes('generations', 'gen_notes');
    const order = byId('gen_preserve_order');
    if (order) order.checked = preserveOrder;
    const expanded = byId('gen_expand');
    if (expanded) expanded.checked = expand;
    // "Rate" starts off, whatever the browser kept ticked from before.
    const rate = byId('gen_rate');
    if (rate) rate.checked = false;
    const select = byId('gen_select');
    if (select) select.checked = false;
    // The search starts empty, whatever the browser kept in the box. Its ×
    // empties it without a change, which a search event tells.
    const box = byId('gen_search');
    if (box) {
        box.value = '';
        box.addEventListener('search', () => setSearch(box.value));
    }
    showGroupChoice();
    byId('gen_grid')?.classList.toggle('gen-ordered', preserveOrder);
    placed = placedGrid({
        scope: tabScope,
        grid: () => byId('gen_grid'),
        app: () => byId('generations_app'),
        count: () => tiles.length,
        html: setHtml,
        imageOf: (index) => tileImage(tiles[index]),
        head: startsSection,
        oneColumn: () => preserveOrder,
        // As the browser's grid: nothing packed back with Preserve order, or above a section's header.
        dense: () => !preserveOrder && !tiles.some((t) => t.section),
        drawn: (grid) => setupLazyMedia(grid),
    });
    try {
        const defaults = await galleryDefaults();
        hideNsfw = defaults.generationsHideNsfw;
        fast = defaults.generationsFast;
    } catch (e) { /* the gallery's default: hidden; the grid Fast */ }
    // The grid setting saved, in the settings window or on the Settings page.
    const followGrid = (changed) => {
        if (!changed.includes(GRID_SETTING)) return;
        galleryDefaults().then((defaults) => switchGrid(defaults.generationsFast)).catch(() => {});
    };
    tabScope.listen(window, 'mm-settings-saved', (event) => followGrid(event.detail?.changed || []));
    tabScope.listen(window, 'mm-settings-page-applied', (event) => followGrid(event.detail?.changed || []));
    watchEnd();
    tabScope.listen(document, 'keydown', onKey);
    // Hidden, nothing could be measured: measure again once it is shown.
    tabScope.listen(window, 'resize', layout);
    tabScope.afterUpdate(layout);
    tabScope.afterUpdate(showGroupChoice);
    tabScope.onStop(() => { syncFollowing = null; });
    tabScope.listen(document, 'keydown', (event) => {
        if (event.key === 'Escape' && byId('gen_sync_dialog')?.style.display === 'flex') closeSyncDialog();
        if (event.key === 'Enter' && event.target?.id === 'gen_sync_add_path') addSyncFolder();
    });
    tabScope.listen(document, 'input', (event) => {
        if (event.target?.id !== 'gen_sync_add_path') return;
        // What a refusal said was about the text before.
        showAddNote('');
        showAddButton();
    });
    pickUpSync();
    await reload();
}
