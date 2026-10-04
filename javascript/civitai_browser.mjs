/**
 * Civitai Browser JavaScript
 * Handles searching, displaying, and downloading models from Civitai.
 * Layout matches Model Manager exactly.
 */


// The WebUI versions the tab scripts and nothing else: list_scripts() uses
// os.listdir(), which does not recurse, so javascript/shared/ is never listed
// and never gets a ?mtime. A plain import of it therefore resolved to a URL
// that never changed, a browser cached it forever, and an export added here
// was missing from the copy the browser held - which is a link error, so the
// whole tab script stopped running until someone happened to force a reload.
//
// So the shared modules are asked for with a version of their own, the newest
// mtime among them, which the server is asked for: this script's version, as
// they used to take, stayed the same when only a shared file changed, and
// Gradio's file route sends no Cache-Control, so a browser could keep the
// copy it held. All three tabs share the one answer, so each shared module is
// one URL and runs once, not once per tab. It is asked until it is answered:
// a page reloaded by "Apply and restart UI" comes back as soon as the WebUI's
// own routes answer, before the extensions' app_started adds ours, and each
// tab fell back to a version of its own - a copy of every shared module per
// tab, and a downloads list and a note pile each, for the session (#121). A
// dynamic import is the only way to build that URL at runtime, which is why
// this is not a plain import statement.
window.mmSharedVersion ||= (async () => {
    let waiting = false;
    for (;;) {
        try {
            // Not there yet - 404, the extension's app_started not run - is
            // waited out. Any other answer is taken, one without a version as
            // this tab's own, for every tab: still one copy.
            const response = await fetch('/model-manager/asset-version', { cache: 'no-store' });
            if (response.status !== 404) {
                const body = response.ok ? await response.json().catch(() => null) : null;
                return /^\d+$/.test(String(body?.version ?? '')) ? `?v=${body.version}`
                    : new URL(import.meta.url).search;
            }
        } catch (e) { /* the server is not answering at all */ }
        if (!waiting) {
            waiting = true;
            console.log("[ModelManager] waiting for the Model Manager's API...");
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
})();
const sharedVersion = await window.mmSharedVersion;
const shared = (name) => import(new URL(`./shared/${name}${sharedVersion}`, import.meta.url).href);

// Asked for all at once, then taken one by one below. Awaited in turn, each
// module waited a round trip of its own before the next was asked for. An
// import of a URL already asked for is the same module, so the awaits find
// them on their way. A failure still stops the tab at its await; the catch
// here only keeps it from being reported twice.
const SHARED_MODULES = ['core.mjs', 'calls.mjs', 'tabs.mjs', 'ui_options.mjs', 'notes.mjs', 'jobs.mjs',
    'filters.mjs', 'gallery.mjs', 'grid.mjs', 'media.mjs', 'nsfw.mjs', 'chips.mjs', 'downloads.mjs',
    'image_card.mjs', 'resources.mjs', 'samplers.mjs', 'update_notice.mjs', 'viewer.mjs', 'settings.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const {
    onReady, apiCall, apiCallTelling, readEvents, escapeHtml, dataAttributes, safeId, sanitizeHtml, formatNumber,
    formatBytes: formatFileSize, formatDay: formatDate, setText, setTitle,
} = await shared('core.mjs');
const { provide, ready, call } = await shared('calls.mjs');
const { showTab, tabButton, tabShowing } = await shared('tabs.mjs');
const {
    showApiKeyBanner, loadNsfwDetection, nsfwModelNote, galleryDefaults, refreshUiOptions,
} = await shared('ui_options.mjs');
const { showNotes } = await shared('notes.mjs');
const {
    savedSearch, saveSearch, sortBaseModels, sizeBound, flashSaveSearch, syncCheckpointType,
} = await shared('filters.mjs');
const {
    showGalleryLoading, dimGalleryWhileLoading, sayGalleryLoading, statusSayer, renderFilterBanner,
    createPagedGallery, scrollToImagesTop,
} = await shared('gallery.mjs');
const {
    renderThumbs, balanceGridRows, renderModelCard, renderGridPagination, renderModelGrid: renderSharedGrid,
    createCardSize,
} = await shared('grid.mjs');
const {
    isVideoUrl, cardMediaUrl, originalMediaUrl, viewerVideoUrl, galleryImageWidth, setupLazyMedia,
} = await shared('media.mjs');
const { nsfwImageLevel, isImageSafe } = await shared('nsfw.mjs');
const {
    paidAccessLabel, isPaid, primaryFileIndex, renderDownloadControls, showChosenFile, downloads,
} = await shared('downloads.mjs');
const { renderImageCard: sharedImageCard, showImageMeta } = await shared('image_card.mjs');
const {
    showImageResources, resourceButtonLabel: resourcesLabel, learnResourceHashes,
} = await shared('resources.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The image viewer every gallery opens.
const { openViewer, cardSource, dialogShowing, viewerIsOpen } = await shared('viewer.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// The download controls' ids, and the window functions they call
// (renderDownloadControls in shared/downloads.mjs).
const DOWNLOAD_CONTROLS = { prefix: 'cb', download: 'civitaiBrowser.download', selectFile: 'civitaiBrowser.selectFile' };

// State
let currentModels = [];
let currentPage = 1;
let pageSize = 20;
let isLoading = false;
let selectedModel = null;
let selectedVersionIndex = 0;
let selectedFileIndex = null;  // null = whichever file Civitai marks primary
// The gallery is a list of pages, as the Model Manager's is, but live: each
// the next page of Civitai's, before the switches filter it, and Load More
// adds the next (model_manager/gallery.py). Nothing is kept on the server;
// nextImagesCursor is where Civitai's next page starts. Its images and pages
// are imageGallery's (shared/gallery.mjs); imageCounts their counts added up,
// for the banner.
const imageGallery = createPagedGallery({
    containerId: 'cb_images', bannerClass: 'cb-nsfw-warning', loadMoreId: 'cb_load_more_btn',
    loadMoreAction: 'civitaiBrowser.loadMoreImages', card: (img, index) => renderImageCard(img, index),
    bannerHtml: () => imagesBannerHtml(), redraw: () => renderImages(),
    afterDraw: (images) => { updateImagesCount(); learnResourceHashes(images); },
});
let imageCounts = null;
// Each fetch of the gallery takes a number; an answer to anything but the
// latest is dropped, so a slow page cannot land over a newer one.
let imagesRequest = 0;
let nextImagesCursor = null;
let isLoadingImages = false;
// The gallery's two switches. Each model opens as the settings say, and a
// switch then lasts while that model is open - as in the Model Manager.
let showAllNsfwImages = false;
let showPromptlessImages = false;

// Card sizing (default values, updated from API)
// The cards' size as the server last gave it, applied when it changes (shared/grid.mjs).
const cardSize = createCardSize({ containerId: 'civitai_browser_app', logTag: 'CivitaiBrowser' });

// After the settings window saved: redo what this tab drew from the settings.
// The page size applies from the next search, and the gallery reads its
// settings each time a model opens.
window.addEventListener('mm-settings-saved', (e) => {
    refreshUiOptions().then(syncSfwOnlyEnabled);
    if ((e.detail?.changed || []).includes('model_manager_civitai_card_size')) {
        // Saved as the server normalises it: "200x280".
        const [width, height] = String(e.detail.settings.model_manager_civitai_card_size.value || '')
            .split('x').map(Number);
        if (width > 0 && height > 0) cardSize.apply(width, height);
    }
});

// The settings window's card preview: this tab's own cards, at a size not yet
// saved. From the results already shown when there are enough, else exactly
// as many models as the preview asks Civitai for.
let cardPreviewModels = [];
async function cardPreview(count) {
    let models = currentModels;
    if (models.length < count) {
        if (cardPreviewModels.length < count) {
            const data = await apiCall({ endpoint: '/model-manager/civitai/models',
                                         params: { limit: count } });
            if (!data.success) throw new Error(data.error || 'Civitai did not answer');
            cardPreviewModels = data.models || [];
        }
        models = cardPreviewModels;
    }
    return models.slice(0, count).map((model, index) => renderCard(model, index)).join('');
}
provide('cardPreview.model_manager_civitai_card_size', cardPreview);

// Cursor-based pagination state
// cursors[N-1] = cursor to fetch page N
// cursors[0] = "" (first page needs no cursor)
// cursors[1] = nextCursor from page 1 (use to fetch page 2)
let cursors = [""];
let hasMorePages = true;

// In-flight streaming search, so a new search can cancel the old one
let activeStream = null;
// While streaming, pagination controls are held back until the page is final
let isStreaming = false;


// Tag state (single tag)
let selectedTag = '';
// Which tag lookup is the latest. Suggestions are asked for on every
// keystroke, so an answer for "ani" can arrive after the one for "anime";
// only the latest may fill the list.
let tagRequest = 0;
let tagSuggestions = [];
let tagSelectedIndex = -1;
let tagInputInitialized = false;


// POST API call helper
async function apiPost(endpoint, data = {}) {
    const formData = new FormData();
    Object.entries(data).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
            formData.append(key, value);
        }
    });
    const response = await fetch(endpoint, {
        method: 'POST',
        body: formData
    });
    return response.json();
}

// Get filter values
function getFilters() {
    const types = document.getElementById('cb_type')?.value || '';
    return {
        query: document.getElementById('cb_search')?.value || '',
        types,
        // Civitai rejects checkpointType on anything but checkpoints.
        checkpoint_type: types === 'Checkpoint'
            ? (document.getElementById('cb_checkpoint_type')?.value || '')
            : '',
        base_models: document.getElementById('cb_base_model')?.value || '',
        sort: document.getElementById('cb_sort')?.value || 'Most Downloaded',
        period: document.getElementById('cb_period')?.value || 'AllTime',
        nsfw: document.getElementById('cb_nsfw')?.checked || false,
        tag: selectedTag,
        require_prompt: document.getElementById('cb_require_prompt')?.checked || false,
        sfw_only: sfwOnlyEnabled(),
        min_size_gb: sizeBound('cb_min_size'),
        max_size_gb: sizeBound('cb_max_size'),
    };
}

/**
 * What a filtered page passed over, for the status line: "checked 40,
 * skipped 12 without usable prompts, 30 outside the size range".
 */
function describeFilterStats(stats) {
    const skipped = [];
    if (stats.sfwFilter) skipped.push(`${stats.unsafe || 0} with NSFW images`);
    if (stats.promptFilter !== false) skipped.push(`${stats.dropped || 0} without usable prompts`);
    if (stats.sizeFilter) skipped.push(`${stats.rejected || 0} outside the size range`);
    if (stats.failed) skipped.push(`${stats.failed} could not be checked`);
    const costly = stats.promptFilter !== false || stats.sfwFilter;
    const checked = costly ? `checked ${stats.checked}, ` : '';
    let text = ` - ${checked}skipped ${skipped.join(', ')}`;
    if (stats.rateLimited) {
        text += '. Civitai is limiting requests, so this page stopped early; '
            + 'wait a moment, then press Next.';
    } else if (stats.budgetReached) {
        text += '. Stopped early to avoid a long wait; press Next to keep looking.';
    }
    return text;
}

// What a filtered search is doing, before it has found anything.
function filteringMessage() {
    if (feelingLucky()) return 'Drawing models at random...';
    if (requirePromptEnabled()) return 'Checking models for usable prompts...';
    if (sfwOnlyEnabled()) return 'Checking models for SFW images...';
    return 'Looking for models in the size range...';
}

/**
 * Is "Only Show Models with SFW images" ticked and in force?
 *
 * It means nothing while NSFW models are included, so it is greyed out then,
 * keeps its tick for when it applies again, and is not sent. A draw does
 * not use it either.
 */
function sfwOnlyEnabled() {
    const nsfw = document.getElementById('cb_nsfw')?.checked || false;
    return !nsfw && !feelingLucky() && (document.getElementById('cb_sfw_only')?.checked || false);
}

// Grey out "Only Show Models with SFW images" while NSFW models are included, saying why,
// and while it is in force, say above the results what it is doing: its
// pages come back short, and without this that reads as something broken.
// Listened for on the page, not on the checkboxes, and redrawn after Gradio
// redraws the tab: see syncSfwOnlyBanner() in model_manager.mjs.
document.addEventListener('change', (event) => {
    if (event.target?.id === 'cb_nsfw' || event.target?.id === 'cb_sfw_only') syncSfwOnlyEnabled();
});
if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(syncSfwOnlyEnabled);

function syncSfwOnlyEnabled() {
    const box = document.getElementById('cb_sfw_only');
    const label = document.getElementById('cb_sfw_only_label');
    if (!box || !label) return;

    if (label.dataset.title === undefined) label.dataset.title = label.title;
    const nsfw = document.getElementById('cb_nsfw')?.checked || false;
    const applies = !nsfw && !feelingLucky();
    box.disabled = !applies;
    label.classList.toggle('filter-disabled', !applies);
    setTitle(label, applies ? label.dataset.title
        : `${feelingLucky() ? NOT_IN_A_DRAW : 'Only applies while Include NSFW models is unticked.'} `
            + label.dataset.title);

    const banner = document.getElementById('cb_sfw_only_banner');
    const text = document.getElementById('cb_sfw_only_banner_text');
    if (banner && text) {
        setText(text, label.dataset.title);
        banner.style.display = sfwOnlyEnabled() ? 'flex' : 'none';
    }
    const note = document.getElementById('cb_sfw_only_banner_model');
    setText(note, nsfwModelNote());
}

// Is the prompt filter currently on?
function requirePromptEnabled() {
    return document.getElementById('cb_require_prompt')?.checked || false;
}

// ------------------------------------------------------- I'm feeling lucky
// Ticked, Search becomes Draw: a page of models drawn at random from those
// Civitai's own filters allow, every one equally likely (#102,
// civitai/random_draw.py). What a draw cannot use is greyed out, keeping
// what it holds for when the box is unticked: the text - Civitai's text
// search ignores the ids a draw asks for - the sort, and the checks made
// here, which cost requests per model.
const NOT_IN_A_DRAW = "Not used while I'm feeling lucky is ticked.";

function feelingLucky() {
    return document.getElementById('cb_lucky')?.checked || false;
}

/** Grey out a control a draw does not use, or bring it back; `holder` carries the look and the tooltip. */
function setAside(holder, controls, aside) {
    if (!holder) return;
    if (holder.dataset.title === undefined) holder.dataset.title = holder.title || '';
    for (const control of controls) {
        if (control && control.disabled !== aside) control.disabled = aside;
    }
    holder.classList.toggle('filter-disabled', aside);
    setTitle(holder, aside ? `${NOT_IN_A_DRAW} ${holder.dataset.title}`.trim() : holder.dataset.title);
}

function syncLucky() {
    const lucky = feelingLucky();
    const byId = (id) => document.getElementById(id);
    const group = (id) => byId(id)?.closest('.filter-group');
    setAside(group('cb_search'), [byId('cb_search')], lucky);
    setAside(group('cb_sort'), [byId('cb_sort')], lucky);
    setAside(group('cb_min_size'), [byId('cb_min_size'), byId('cb_max_size')], lucky);
    setAside(byId('cb_require_prompt')?.closest('label'), [byId('cb_require_prompt')], lucky);
    syncSfwOnlyEnabled();
    const button = byId('cb_search_btn');
    setText(button, lucky ? 'Draw' : 'Search');
    setTitle(button, lucky ? 'Draw a page of models at random from those the filters allow' : '');
}
if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(syncLucky);

// Update status
function updateStatus(message) {
    const status = document.getElementById('cb_status');
    if (status) status.textContent = message;
}

// Search with the prompt or size filter, rendering models as they are found.
// Checking models costs API calls, and a narrow size range can take several
// searches, so a page can take a while to fill - showing each one as it
// qualifies beats staring at a spinner.
async function searchModelsStreaming(page, cursor) {
    // Which images are safe depends on the NSFW prompt words too.
    if (activeStream) activeStream.abort();
    const controller = new AbortController();
    activeStream = controller;

    const filters = getFilters();
    const params = new URLSearchParams();
    Object.entries({ ...filters, cursor: cursor })
        .forEach(([k, v]) => {
            // Sent either way: the endpoint assumes the prompt filter unless told.
            if (k === 'require_prompt') {
                params.append(k, v ? 'true' : 'false');
                return;
            }
            if (v !== undefined && v !== null && v !== '' && v !== false) {
                params.append(k, v);
            }
        });

    currentModels = [];
    currentPage = page;
    isStreaming = true;
    renderGrid();
    closeDetails();
    updateStatus(filteringMessage());

    let finished = false;

    try {
        const response = await fetch(
            '/model-manager/civitai/models/stream?' + params.toString(),
            { signal: controller.signal }
        );
        if (!response.ok) throw new Error('HTTP ' + response.status);

        await readEvents(response, (evt) => {
            if (evt.type === 'meta') {
                if (evt.cardWidth && evt.cardHeight) {
                    cardSize.apply(evt.cardWidth, evt.cardHeight);
                }
                pageSize = evt.pageSize || pageSize;
            } else if (evt.type === 'model') {
                currentModels.push(evt.model);
                renderGrid();
                updateStatus(`Found ${currentModels.length} of ${pageSize}...`);
            } else if (evt.type === 'progress') {
                // Every model looked at was taken or passed over by one filter.
                const seen = evt.found + (evt.dropped || 0) + (evt.unsafe || 0)
                    + (evt.failed || 0) + (evt.rejected || 0);
                const passed = [evt.unsafe ? `${evt.unsafe} with NSFW images` : '',
                                evt.dropped ? `${evt.dropped} without usable prompts` : '',
                                evt.rejected ? `${evt.rejected} outside the size range` : '',
                                evt.failed ? `${evt.failed} could not be checked` : '']
                    .filter(Boolean).join(', ');
                updateStatus(`Looked through ${seen} models, found ${evt.found} of ${pageSize}`
                    + (passed ? ` (${passed})` : ''));
            } else if (evt.type === 'done') {
                finished = true;
                if (evt.nextCursor) {
                    cursors[page] = evt.nextCursor;
                    hasMorePages = true;
                } else {
                    hasMorePages = false;
                }

                const stats = evt.filterStats || {};
                const status = `Showing ${currentModels.length} models (page ${page})`
                    + describeFilterStats(stats);
                isStreaming = false;
                renderGrid();
                updateStatus(status);
            } else if (evt.type === 'error') {
                throw new Error(evt.error);
            }
        });
    } catch (e) {
        if (e.name === 'AbortError') return;        // superseded by a newer search
        console.error('[CivitaiBrowser] Stream error:', e);
        updateStatus(`Error: ${e.message}`);
    } finally {
        if (activeStream === controller) activeStream = null;
        if (!finished) {
            // stream cut short - show whatever arrived rather than nothing
            isStreaming = false;
            renderGrid();
        }
    }
}

/** What a draw is doing, on the status line: it can take a dozen requests, at 0.5 a second without an API key. */
function describeDrawProgress(evt) {
    if (evt.listing) return `Few models match: listing all of them to draw from (${evt.listing.toLocaleString()} so far)...`;
    if (!evt.asked) return 'Drawing models at random...';
    return `Drawing models at random: asked Civitai about ${evt.asked.toLocaleString()} ids, `
        + `found ${Math.min(evt.found, pageSize)} of ${pageSize}...`;
}

/** What a draw came back with, and what it cost. */
function describeDraw(count, draw) {
    let text;
    if (draw.listed && !draw.matches) {
        text = 'No models match these filters.';
    } else if (draw.listed && count >= draw.matches) {
        text = `All ${count.toLocaleString()} models these filters match, in random order`;
    } else if (draw.listed) {
        text = `Drew ${count} models at random from all ${draw.matches.toLocaleString()} these filters match`;
    } else {
        text = `Drew ${count} models at random`
            + (draw.matches ? ` from about ${draw.matches.toLocaleString()} that match` : '')
            + ` - ${draw.asked.toLocaleString()} ids asked in ${draw.requests} `
            + `request${draw.requests === 1 ? '' : 's'}`;
    }
    if (draw.rate_limited) {
        text += '. Civitai is limiting requests, so the draw stopped early; wait a moment, then press Draw again.';
    } else if (draw.stopped) {
        text += `. Stopped after ${draw.requests} requests; press Draw to try again.`;
    }
    return text;
}

/**
 * Draw a page of models at random (I'm feeling lucky), streamed: the status
 * line follows the draw, and the page comes at the end, shuffled. Another
 * Draw or a Search supersedes it.
 */
async function drawModels() {
    if (activeStream) activeStream.abort();
    const controller = new AbortController();
    activeStream = controller;

    // Civitai's own filters, and nothing a draw cannot use.
    const { types, checkpoint_type, base_models, nsfw, tag, period } = getFilters();
    const params = new URLSearchParams();
    Object.entries({ types, checkpoint_type, base_models, nsfw, tag, period }).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '' && v !== false) params.append(k, v);
    });

    currentModels = [];
    currentPage = 1;
    // A draw is one page: nothing comes before or after it.
    cursors = [""];
    hasMorePages = false;
    isStreaming = true;
    renderGrid();
    closeDetails();
    updateStatus('Drawing models at random...');

    let finished = false;
    try {
        const response = await fetch('/model-manager/civitai/models/random?' + params.toString(),
                                     { signal: controller.signal });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        await readEvents(response, (evt) => {
            if (evt.type === 'meta') {
                if (evt.cardWidth && evt.cardHeight) cardSize.apply(evt.cardWidth, evt.cardHeight);
                pageSize = evt.pageSize || pageSize;
            } else if (evt.type === 'progress') {
                updateStatus(describeDrawProgress(evt));
            } else if (evt.type === 'done') {
                finished = true;
                currentModels = evt.models || [];
                isStreaming = false;
                renderGrid();
                updateStatus(describeDraw(currentModels.length, evt.draw || {}));
            } else if (evt.type === 'error') {
                throw new Error(evt.error);
            }
        });
    } catch (e) {
        if (e.name === 'AbortError') return;        // superseded by another draw or a search
        console.error('[CivitaiBrowser] Draw error:', e);
        updateStatus(`Error: ${e.message}`);
    } finally {
        if (activeStream === controller) activeStream = null;
        if (!finished) {
            isStreaming = false;
            renderGrid();
        }
    }
}

// Search models using cursor-based pagination
/**
 * The model, and optionally the version, a targeted query names - or null
 * for an ordinary search.
 *
 * The Model Manager's search takes model:123 / version:456 / hash:ABC, and
 * its "Show in Civitai Browser" button sends "model:123 version:456" here -
 * the version it was showing - so the two tabs read the same syntax. The
 * model is fetched by id; the version picks which of its versions is shown.
 */
function targetedLookup(query) {
    const match = /^\s*model:\s*(\d+)(?:\s+version:\s*(\d+))?\s*$/i.exec(query || '');
    return match ? { modelId: Number(match[1]), versionId: match[2] ? Number(match[2]) : null } : null;
}

/**
 * Show one model, asked for by id rather than searched for.
 *
 * Civitai's search has no way to ask for a known model, so this goes to the
 * model endpoint instead. The result is a page of exactly one, with no
 * cursors - paging past it would be meaningless.
 */
async function showModelById(modelId, versionId = null) {
    // Which images are safe depends on the NSFW prompt words too.
    isLoading = true;
    updateStatus(`Loading model ${modelId}...`);
    try {
        const data = await apiCall({ endpoint: `/model-manager/civitai/models/${modelId}` });
        if (!data.success || !data.model) {
            currentModels = [];
            renderGrid();
            closeDetails();
            updateStatus(data.error === 'Model not found'
                ? `Civitai has no model ${modelId}. It may have been taken down.`
                : `Could not load model ${modelId}: ${data.error || 'unknown error'}`);
            return;
        }

        currentModels = [data.model];
        currentPage = 1;
        cursors = [""];
        hasMorePages = false;
        renderGrid();
        // Versions get deleted on Civitai; the model is still worth showing.
        const versionIndex = versionId === null ? 0
            : (data.model.modelVersions || []).findIndex(v => v.id === versionId);
        updateStatus(versionIndex >= 0
            ? `Showing model ${modelId}`
            : `Version ${versionId} is no longer on Civitai; showing the newest`);
        openModel(0, Math.max(0, versionIndex));
    } catch (e) {
        console.error('[CivitaiBrowser] Targeted lookup failed:', e);
        updateStatus(`Could not load model ${modelId}: ${e.message}`);
    } finally {
        isLoading = false;
    }
}

async function searchModels(page = 1) {
    // Which images are safe depends on the NSFW prompt words too.
    // Ensure page is a valid positive integer
    page = parseInt(page, 10);
    if (isNaN(page) || page < 1) {
        page = 1;
    }

    // Check if we have a cursor for this page
    const cursorIndex = page - 1;
    if (cursorIndex > 0 && !cursors[cursorIndex]) {
        console.warn('[CivitaiBrowser] No cursor for page', page, '- cannot navigate');
        return;
    }

    if (isLoading) return;
    // A draw still coming would land over this search.
    if (activeStream) activeStream.abort();

    // A targeted lookup is not a search: it names the model outright, so the
    // filters, the cursors and the prompt filter all have nothing to say.
    const targeted = targetedLookup(document.getElementById('cb_search')?.value);
    if (targeted !== null) {
        await showModelById(targeted.modelId, targeted.versionId);
        return;
    }

    // A range nothing can be in would spend every search it is allowed on
    // finding that out.
    const { min_size_gb: minSize, max_size_gb: maxSize, sfw_only: sfwOnly } = getFilters();
    if (minSize !== '' && maxSize !== '' && minSize > maxSize) {
        updateStatus('File size: Min is larger than Max.');
        return;
    }

    // A filtered page is filled from as many models as it takes - checked one
    // by one for prompts, or searched through for a size - so stream results
    // in as they are found instead of blocking on the whole page.
    if (requirePromptEnabled() || sfwOnly || minSize !== '' || maxSize !== '') {
        isLoading = true;
        try {
            await searchModelsStreaming(page, cursors[cursorIndex] || "");
        } finally {
            isLoading = false;
        }
        return;
    }

    isLoading = true;

    const filters = getFilters();
    updateStatus('Searching...');

    try {
        const cursor = cursors[cursorIndex] || "";
        const params = {
            ...filters,
            cursor: cursor
        };

        const result = await apiCall({ endpoint: '/model-manager/civitai/models', params });

        if (result.success) {
            // Apply card size from API response
            if (result.cardWidth && result.cardHeight) {
                cardSize.apply(result.cardWidth, result.cardHeight);
            }

            currentModels = result.models || [];
            currentPage = page;
            pageSize = result.pageSize || 20;

            // Store nextCursor for the next page
            if (result.nextCursor) {
                cursors[page] = result.nextCursor;  // cursors[page] = cursor to fetch page+1
                hasMorePages = true;
            } else {
                hasMorePages = false;
            }

            renderGrid();
            closeDetails();

            let status = `Showing ${currentModels.length} models (page ${currentPage})`;
            const stats = result.filterStats;
            if (stats) status += describeFilterStats(stats);
            updateStatus(status);
        } else {
            updateStatus(`Error: ${result.error}`);
        }
    } catch (e) {
        console.error('[CivitaiBrowser] Search error:', e);
        updateStatus(`Error: ${e.message}`);
    } finally {
        isLoading = false;
    }
}

/**
 * The image a card shows for a version: the first of its showcase.
 *
 * With NSFW models not included, Civitai leaves only PG images in the
 * showcase, so that is safe as it comes. Nothing here depends on it staying
 * so: an image above PG-13 is passed over for the first one that is PG or
 * PG-13 - the line drawn everywhere else - and a version with none shows no
 * image rather than an unsafe one.
 */
function cardImage(version) {
    const images = version?.images || [];
    if (document.getElementById('cb_nsfw')?.checked) return images[0];
    return images.find((img) => isImageSafe(img));
}

// Render model grid
function renderGrid() {
    renderSharedGrid({
        gridId: 'cb_grid',
        cards: currentModels.map((model, index) => renderCard(model, index)),
        empty: isStreaming ? filteringMessage() : 'No models found.',
        // Civitai's page count is not known: the pages are the ones a cursor
        // leads to - so far as this search has been - and there is another
        // while Civitai hands back a cursor for it.
        pagination: !isStreaming && (cursors.length > 1 || hasMorePages) ? renderGridPagination({
            current: currentPage, last: cursors.length, hasNext: hasMorePages,
            goTo: 'civitaiBrowser.goToPage', prev: 'civitaiBrowser.prevPage', next: 'civitaiBrowser.nextPage',
        }) : '',
    });
}

/**
 * A Civitai search result as a card: what renderModelCard() is to show. Its
 * image is the first version's, per cardImage() and so per Include NSFW models.
 */
function renderCard(model, index) {
    const firstVersion = model.modelVersions?.[0];
    const image = cardImage(firstVersion);
    const src = image?.url ? cardMediaUrl(image.url, image.type, cardSize.width, image.width) : '';
    return renderModelCard({
        index,
        action: 'civitaiBrowser.openModel',
        name: model.name,
        media: { src, video: isVideoUrl({ url: src, type: image?.type }),
                 original: image?.url ? originalMediaUrl(image.url) : '' },
        classes: [model.owned_locally ? 'owned' : ''],
        overlays: [
            ...(model.owned_locally ? [{ cls: 'cb-owned-badge', text: 'Owned' }] : []),
            // Buzz paywall on the version this card is previewing
            ...(isPaid(firstVersion) ? [{
                cls: 'cb-paid-badge', title: paidAccessLabel(firstVersion),
                text: firstVersion.paid_access.permanent ? 'Paid' : 'Early Access',
            }] : []),
        ],
        badges: [
            { cls: 'type-badge', text: model.type || 'Unknown' },
            ...(firstVersion?.baseModel ? [{ cls: 'base-model', text: firstVersion.baseModel }] : []),
        ],
        stats: [
            // stats.rating no longer exists in the API; thumbs are what Civitai reports now.
            { html: renderThumbs(model.stats?.thumbsUpCount, model.stats?.thumbsDownCount) },
            { text: `↓ ${formatNumber(model.stats?.downloadCount || 0)}`, title: 'Downloads' },
        ],
    });
}

function primaryFile(version) {
    return (version?.files || [])[primaryFileIndex(version)];
}

/** The file currently chosen for download - the picker's, or the primary. */
function chosenFileIndex(version) {
    const files = version?.files || [];
    if (selectedFileIndex !== null && selectedFileIndex >= 0
        && selectedFileIndex < files.length) {
        return selectedFileIndex;
    }
    return primaryFileIndex(version);
}

// Open model detail
async function openModel(index, versionIndex = 0) {
    const model = currentModels[index];
    if (!model) return;

    selectedModel = model;
    selectedVersionIndex = versionIndex;
    selectedFileIndex = null;

    // Highlight selected card
    document.querySelectorAll('#cb_grid .model-card').forEach((card, i) => {
        card.classList.toggle('selected', i === index);
    });

    renderModelDetails();
    // At once, before even the settings are asked: the last model's images
    // stayed up for a second or more, as if the click had done nothing.
    showImagesLoading();

    // The switches start as the settings say - not as the search does:
    // Include NSFW models and Only with usable prompts choose which models
    // are listed, and someone may list them and still not want every image.
    const defaults = await galleryDefaults();
    if (selectedModel !== model) return;   // another model was opened meanwhile
    showAllNsfwImages = !defaults.hideNsfw;
    showPromptlessImages = !defaults.hidePromptless;
    loadImagesFromVersion();
}

// Close details
function closeDetails() {
    const details = document.getElementById('cb_details');
    const images = document.getElementById('cb_images');
    if (details) details.style.display = 'none';
    if (images) images.style.display = 'none';

    document.querySelectorAll('#cb_grid .model-card.selected').forEach(card => {
        card.classList.remove('selected');
    });

    selectedModel = null;
    selectedVersionIndex = 0;
    selectedFileIndex = null;
    imageGallery.images = [];
    imageGallery.pages = [];
    imageCounts = null;
    nextImagesCursor = null;
}

// Get current selected version
function getSelectedVersion() {
    return selectedModel?.modelVersions?.[selectedVersionIndex];
}

// Render version selector pills (like Model Manager)
function renderVersionSelector() {
    const versions = selectedModel?.modelVersions || [];
    if (versions.length <= 1) return '';

    const pills = versions.map((version, index) => {
        const activeClass = index === selectedVersionIndex ? 'active' : '';
        const ownedClass = version.owned_locally ? 'owned' : '';
        const paidClass = isPaid(version) ? 'paid' : '';
        const versionName = version.name || `v${index + 1}`;
        const ownedIndicator = version.owned_locally ? ' ✓' : (isPaid(version) ? ' ⬥' : '');
        const paidNote = paidAccessLabel(version);
        const tooltip = `${versionName}\nBase: ${version.baseModel || 'Unknown'}`
            + `${version.owned_locally ? '\n(Owned)' : ''}${paidNote ? '\n' + paidNote : ''}`;

        return `<button class="mm-version-pill ${activeClass} ${ownedClass} ${paidClass}"
                       data-action="civitaiBrowser.selectVersion" data-index="${index}"
                       title="${escapeHtml(tooltip)}">${escapeHtml(versionName)}${ownedIndicator}</button>`;
    }).join('');

    return `
        <div class="detail-section mm-version-selector">
            <h4>Versions (${versions.length})</h4>
            <div class="mm-version-pills">
                ${pills}
            </div>
        </div>
    `;
}

// Render model details panel (like Model Manager)
function renderModelDetails() {
    const container = document.getElementById('cb_details');
    if (!container || !selectedModel) return;

    const model = selectedModel;
    const versions = model.modelVersions || [];
    const version = getSelectedVersion() || versions[0];
    const isOwned = version?.owned_locally || model.owned_versions?.includes(version?.id);
    const versionFiles = version?.files || [];
    const fileIndex = chosenFileIndex(version);
    const file = versionFiles[fileIndex];

    // Version selector pills
    const versionSelectorHtml = renderVersionSelector();

    // Trained words / Trigger words
    const trainedWords = version?.trainedWords && version.trainedWords.length > 0
        ? `<div class="detail-section">
             <h4>Trigger Words</h4>
             <div class="trigger-words">
               ${version.trainedWords.map(w => `<span class="trigger-word" data-copy="${escapeHtml(w)}" title="Click to copy">${escapeHtml(w)}</span>`).join('')}
             </div>
           </div>`
        : '';

    // Tags
    const tags = model.tags && model.tags.length > 0
        ? `<div class="detail-section">
             <h4>Tags</h4>
             <div class="tag-list">
               ${model.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
             </div>
           </div>`
        : '';

    // Description (with collapsible)
    const description = model.description || '';
    const descriptionHtml = description
        ? `<div class="detail-section">
             <h4>Description</h4>
             <div class="mm-description collapsed" id="cb_description_content">${sanitizeHtml(description)}</div>
             <button class="mm-description-toggle" id="cb_description_toggle" data-action="civitaiBrowser.toggleDescription">
                 Show more
             </button>
           </div>`
        : '';

    // File info
    const fileSize = file?.sizeKB ? formatFileSize(file.sizeKB * 1024) : 'Unknown';
    const fileName = file?.name || 'Unknown';

    // Stats
    const stats = model.stats || {};

    const paidLabel = paidAccessLabel(version);
    const downloadControls = renderDownloadControls({
        controls: DOWNLOAD_CONTROLS, modelId: model.id, version, fileIndex, owned: isOwned });

    // Only offer the jump for models that are actually in the library.
    // Lives on the header row so it stays reachable while scrolling the
    // details panel, rather than only at the very bottom.
    const showInManagerBtn = model.owned_locally
        ? `<button class="mm-btn secondary mm-btn-small header-action" data-action="civitaiBrowser.showInModelManager"${dataAttributes({ modelId: safeId(model.id) })} title="Open this model in the Model Manager tab">Show in Model Manager</button>`
        : '';

    container.innerHTML = `
        <div class="model-details-content">
            <div class="detail-header">
                <h3>${escapeHtml(model.name)}</h3>
                ${showInManagerBtn}
                <button class="close-details" data-action="civitaiBrowser.closeDetails">×</button>
            </div>

            ${versionSelectorHtml}

            <div class="detail-section">
                <h4>Information</h4>
                <table class="detail-table">
                    <tr><td>Model ID</td><td>${model.id}</td></tr>
                    <tr><td>Version ID</td><td>${version?.id || 'Unknown'}</td></tr>
                    <tr><td>Version Name</td><td>${escapeHtml(version?.name || 'Unknown')}</td></tr>
                    <tr><td>Type</td><td>${model.type || 'Unknown'}</td></tr>
                    <tr><td>Base Model</td><td>${version?.baseModel || 'Unknown'}</td></tr>
                    <tr><td>Creator</td><td>${escapeHtml(model.creator?.username || 'Unknown')}</td></tr>
                    ${paidLabel ? `<tr><td>Access</td><td class="cb-paid-cell">${escapeHtml(paidLabel)}</td></tr>` : ''}
                    <tr><td>Published</td><td>${version?.publishedAt ? formatDate(version.publishedAt) : 'Unknown'}</td></tr>
                    <tr><td>Updated</td><td>${version?.updatedAt ? formatDate(version.updatedAt) : 'Unknown'}</td></tr>
                    <tr><td>Rating</td><td>★ ${(stats.rating || 0).toFixed(1)} (${formatNumber(stats.ratingCount || 0)} ratings)</td></tr>
                    <tr><td>Downloads</td><td>${formatNumber(stats.downloadCount || 0)}</td></tr>
                    <tr><td>Favorites</td><td>${formatNumber(stats.favoriteCount || 0)}</td></tr>
                    <tr><td>Comments</td><td>${formatNumber(stats.commentCount || 0)}</td></tr>
                    <tr><td>File</td><td id="cb_file_name">${escapeHtml(fileName)}</td></tr>
                    <tr><td>File Size</td><td id="cb_file_size">${fileSize}</td></tr>
                    <tr><td>Images</td><td id="cb_images_count">${imageCounts ? imageCounts.total : '...'}</td></tr>
                </table>
            </div>

            ${trainedWords}
            ${tags}
            ${descriptionHtml}

            <div class="detail-section detail-actions">
                <a class="mm-btn secondary" href="https://civitai.com/models/${safeId(model.id)}?modelVersionId=${safeId(version?.id)}" target="_blank">View on Civitai</a>
                ${downloadControls}
            </div>
        </div>
    `;

    container.style.display = 'block';

    // Check if description needs toggle
    setTimeout(() => {
        const content = document.getElementById('cb_description_content');
        const toggle = document.getElementById('cb_description_toggle');
        if (content && toggle) {
            if (content.scrollHeight <= 100) {
                toggle.style.display = 'none';
                content.classList.remove('collapsed');
            }
        }
    }, 0);
}

// Toggle description expand/collapse
function toggleDescription() {
    const content = document.getElementById('cb_description_content');
    const toggle = document.getElementById('cb_description_toggle');
    if (content && toggle) {
        const isCollapsed = content.classList.contains('collapsed');
        if (isCollapsed) {
            content.classList.remove('collapsed');
            toggle.textContent = 'Show less';
        } else {
            content.classList.add('collapsed');
            toggle.textContent = 'Show more';
        }
    }
}

// Select version
/**
 * Point the download at a different file of the current version.
 *
 * Updates the two rows and the button in place rather than re-rendering
 * the panel, which would scroll the reader back to the top.
 */
function selectFile(fileIndex) {
    const index = parseInt(fileIndex, 10);
    const version = getSelectedVersion();
    const file = (version?.files || [])[index];
    if (!file) return;

    selectedFileIndex = index;
    showChosenFile(DOWNLOAD_CONTROLS, selectedModel?.id, version, file);
}

function selectVersion(versionIndex) {
    if (versionIndex === selectedVersionIndex) return;
    selectedVersionIndex = versionIndex;
    selectedFileIndex = null;  // a different version has different files

    // Update pills UI
    document.querySelectorAll('.mm-version-pill').forEach((pill, idx) => {
        pill.classList.toggle('active', idx === selectedVersionIndex);
    });

    // Update version-specific info
    renderModelDetails();
    loadImagesFromVersion();
}

/**
 * Fetch page `number` of the selected version's gallery from Civitai, through
 * the two switches: page 1 from the start, any other from where the last
 * one ended.
 *
 * @returns {Promise<object|null>} the answer, or null if a newer fetch or
 *     another version has taken over since
 */
async function fetchImagesPage(number) {
    const version = getSelectedVersion();
    if (!version?.id) return null;
    const request = ++imagesRequest;
    // What it waits on, where its loading shows: page 1's over the gallery -
    // a model opened, a switch changed - Load More's under its button (#132).
    const status = statusSayer((text) => {
        if (request !== imagesRequest) return;
        if (number > 1) imageGallery.say(text);
        else sayGalleryLoading('cb_images', text);
    });
    try {
        const result = await apiCallTelling({
            endpoint: `/model-manager/civitai/versions/${version.id}/images`,
            params: {
                page: number, cursor: number > 1 ? (nextImagesCursor || '') : '',
                hide_nsfw_images: !showAllNsfwImages,
                hide_promptless_images: !showPromptlessImages,
            },
            onStatus: status.say,
        });
        if (request !== imagesRequest || getSelectedVersion() !== version) return null;
        return result;
    } finally {
        status.done();
    }
}

/** Every loaded page's counts added up: what the banner states. */
function addUpPages() {
    const keys = ['count', 'shown', 'hidden_nsfw', 'hidden_promptless', 'hidden_both', 'nsfw_count',
                  'promptless_count', 'promptless_total'];
    const sums = Object.fromEntries(keys.map((key) =>
        [key, imageGallery.pages.reduce((sum, page) => sum + (page[key] || 0), 0)]));
    return { total: sums.count, filtered: sums.shown, hidden_nsfw: sums.hidden_nsfw,
             hidden_promptless: sums.hidden_promptless, hidden_both: sums.hidden_both,
             nsfw_count: sums.nsfw_count,
             // Only when every page says it: a page without it would make it short.
             promptless_total: imageGallery.pages.every((page) => typeof page.promptless_total === 'number')
                 ? sums.promptless_total : undefined,
             promptless_count: sums.promptless_count };
}

/** Take a page's answer: the page itself, and the banner's totals again. */
function takeImagesPage(result, { append }) {
    nextImagesCursor = result.next_cursor || null;
    const taken = imageGallery.take(result, { append });
    imageCounts = addUpPages();
    return taken;
}

// While a model's images load: a bar, from the moment it starts
// (showGalleryLoading, dimGalleryWhileLoading in gallery.mjs).
const showImagesLoading = () => showGalleryLoading('cb_images');
const dimImagesWhileLoading = (on) => dimGalleryWhileLoading('cb_images', on);

// Load images from API (with full metadata)
async function loadImagesFromVersion() {
    // Which images are safe depends on the NSFW prompt words too.
    const version = getSelectedVersion();
    imageGallery.images = [];
    imageGallery.pages = [];
    imageCounts = null;
    nextImagesCursor = null;
    imageGallery.error = '';
    if (!version?.id) {
        renderImages();
        return;
    }
    isLoadingImages = true;

    const container = document.getElementById('cb_images');
    showImagesLoading();

    try {
        const result = await fetchImagesPage(1);
        if (!result) return;
        if (result.success) {
            takeImagesPage(result, { append: false });
            renderImages();
        } else if (container) {
            container.innerHTML = `<div class="mm-images-error">Error: ${escapeHtml(result.error || '')}</div>`;
        }
    } catch (e) {
        console.error('[CivitaiBrowser] Load images error:', e);
        if (container) {
            container.innerHTML = `<div class="mm-images-error">Error loading images</div>`;
        }
    } finally {
        isLoadingImages = false;
    }
}

// Load More: the next page, added to the end of the list.
function loadMoreImages() {
    return imageGallery.more(async (number) => {
        const result = await fetchImagesPage(number);
        if (!result) return;
        if (!result.success) {
            imageGallery.error = `Page ${number} could not be loaded: ${result.error || 'no answer'}`;
            return;
        }
        const { page, images } = takeImagesPage(result, { append: true });
        imageGallery.append(page, images);
    });
}

// Update images count in the details table: every image loaded, filtered or
// not, and a "+" while Civitai has more - it does not say how many.
function updateImagesCount() {
    const countCell = document.getElementById('cb_images_count');
    if (countCell) {
        const last = imageGallery.pages[imageGallery.pages.length - 1];
        countCell.textContent = imageCounts ? `${imageCounts.total}${last?.more ? '+' : ''}` : '...';
    }
}

/**
 * The banner, built in shared/gallery.mjs as the Model Manager's is: what the
 * switches hold back over everything loaded - which adds up with what
 * matches, NSFW counted first as it filters first - and a switch for each on
 * the right. A ticked NSFW switch shows how many NSFW images it lets through,
 * among those the prompt filter lets through.
 */
function imagesBannerHtml() {
    const counts = imageCounts || {};
    return renderFilterBanner({
        matching: counts.filtered || 0,
        total: counts.total || 0,
        onScreen: imageGallery.images.length,
        word: 'loaded',
        bannerClass: 'cb-nsfw-warning',
        labelClass: 'cb-show-all-label',
        both: counts.hidden_both || 0,
        switches: [
            { id: 'cb_show_all_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: showAllNsfwImages, hidden: counts.hidden_nsfw || 0,
              count: counts.nsfw_count || 0,
              action: 'civitaiBrowser.showAllImages', note: nsfwModelNote() },
            { id: 'cb_show_promptless_images', label: 'Show unusable prompts',
              reason: 'unusable prompt',
              showing: showPromptlessImages, hidden: counts.hidden_promptless || 0,
              count: counts.promptless_count || 0, total: counts.promptless_total,
              action: 'civitaiBrowser.showPromptless' },
        ],
    });
}

// Draw the gallery whole: when a version opens, or a switch changes.
function renderImages() {
    const container = document.getElementById('cb_images');
    if (!container) return;

    if (!imageCounts || !imageCounts.total) {
        container.innerHTML = '<div class="mm-images-empty">No images available for this version.</div>';
        container.style.display = 'block';
        updateImagesCount();
        return;
    }

    galleryWidth = galleryImageWidth(container);
    container.innerHTML = `
        <div class="mm-images-header">
            <h4>Example Images</h4>
        </div>
        ${imagesBannerHtml()}
        ${imageGallery.pagesHtml()}
    `;
    container.style.display = 'block';
    setupLazyMedia(container);
    updateImagesCount();
    learnResourceHashes(imageGallery.images);
}

/** A switch changed: the gallery again from page 1, at its first image. */
async function reloadFromFirstPage() {
    dimImagesWhileLoading(true);
    let failed = '';
    try {
        const result = await fetchImagesPage(1);
        if (result === null) return;              // a newer fetch has taken over
        if (!result.success) {
            failed = result.error || 'no answer';
        } else {
            takeImagesPage(result, { append: false });
            dimImagesWhileLoading(false);
            renderImages();
            await scrollToImagesTop('cb_images');
            return;
        }
    } catch (e) {
        console.error('[CivitaiBrowser] Load images error:', e);
        failed = e.message || String(e);
    }
    // It used to fail without a word, the switch looking ignored.
    dimImagesWhileLoading(false);
    document.getElementById('cb_images')?.insertAdjacentHTML('afterbegin',
        `<div class="mm-images-error">The images could not be loaded again: ${escapeHtml(failed)}</div>`);
}

// Toggle show all images checkbox. The server filters, so the gallery is
// fetched again from its first page.
async function toggleShowAllImages(checked) {
    showAllNsfwImages = checked;
    await reloadFromFirstPage();
}

// Show or hide this model's images without a prompt. The search's own filter
// is left as it is.
async function toggleShowPromptless(checked) {
    showPromptlessImages = checked;
    await reloadFromFirstPage();
}

// How wide the gallery draws a card's image, measured as each page is drawn.
let galleryWidth = null;

// A Civitai image's card, as both tabs draw it (shared/image_card.mjs): this
// tab's Show All and Resources - no Send here - and the version its gallery
// is of.
const IMAGE_ACTIONS = { send: null, showAll: 'civitaiBrowser.showImageMeta', resources: 'civitaiBrowser.showResources' };
function renderImageCard(img, index) {
    return sharedImageCard(img, index, { width: galleryWidth, exclude: galleryVersionId(), actions: IMAGE_ACTIONS });
}

// Show All, the same window in both tabs.
const showImageMetaAt = (index) => showImageMeta(imageGallery.images[index]);

// A card's image, or a video's ⤢, opens the viewer on the card as it is -
// its file large, its buttons below, its text beside (shared/viewer.mjs) -
// from data on it, not an inline handler, as every image here opens.
const browserCards = () => Array.from(document.querySelectorAll('#cb_images .model-images-list .mm-image-card'));
document.addEventListener('click', (event) => {
    const target = event.target.closest?.('#cb_images [data-view-index]');
    if (!target) return;
    event.preventDefault();
    const index = Number(target.getAttribute('data-view-index'));
    const at = browserCards().findIndex((card) => Number(card.dataset.index) === index);
    if (at < 0) return;
    openViewer(cardSource({
        cards: browserCards,
        more: () => !!imageGallery.pages[imageGallery.pages.length - 1]?.more,
        loadMore: () => loadMoreImages(),
        videoUrl: viewerVideoUrl,
    }), at);
});



// ------------------------------------------------------------ resources
// The Model Manager's Resources, for these images too: the same dialog, the
// same lookups, the same Download into the library (resources.mjs) - so a
// LoRA an image used can be had without the model it is an example of.

/** The version this gallery shows: its own images do not list it. */
const galleryVersionId = () => getSelectedVersion()?.id ?? null;

/** What an image's Resources button says, or '' for none. */
function resourceButtonLabel(img) {
    const meta = img.meta || {};
    if (!(meta.civitaiResources || []).length && !(meta.resources || []).length) return '';
    return resourcesLabel(img, galleryVersionId());
}

/** Relabel the gallery's Resources buttons from what is known now. */
function updateResourceButtons() {
    document.querySelectorAll('#cb_images [data-resources-index]').forEach((button) => {
        const img = imageGallery.images[Number(button.dataset.resourcesIndex)];
        const label = img ? resourceButtonLabel(img) : '';
        if (label) button.textContent = label;
        else button.remove();
    });
}
window.addEventListener('mm-resource-hashes', updateResourceButtons);

function showResources(index) {
    const img = imageGallery.images[index];
    if (img) showImageResources(img, galleryVersionId());
}

// Start download. The list and its panel are shared with the Model
// Manager: see downloads() in shared/downloads.mjs.
async function startDownload(modelId, versionId, fileId) {
    try {
        updateStatus('Starting download...');
        const result = await downloads().start(modelId, versionId, fileId);
        if (result.success) {
            updateStatus(`Download started: ${result.progress?.file_name || 'Unknown'}`);
        } else {
            updateStatus(`Download error: ${result.error}`);
        }
    } catch (e) {
        console.error('[CivitaiBrowser] Download error:', e);
        updateStatus(`Download error: ${e.message}`);
    }
}

downloads().addPanel('cb');
downloads().onComplete(dl => markVersionOwned(dl.version_id));

// Mark a freshly downloaded version as owned without re-running the
// search. Re-searching would close the details panel the user is looking
// at, and costs a round trip just to learn what we already know.
function markVersionOwned(versionId) {
    let touchedOpenModel = false;

    currentModels.forEach(model => {
        (model.modelVersions || []).forEach(version => {
            if (version.id !== versionId) return;

            version.owned_locally = true;
            model.owned_locally = true;
            if (!Array.isArray(model.owned_versions)) model.owned_versions = [];
            if (!model.owned_versions.includes(versionId)) {
                model.owned_versions.push(versionId);
            }
            if (selectedModel && selectedModel.id === model.id) {
                touchedOpenModel = true;
            }
        });
    });

    renderGrid();
    if (touchedOpenModel) {
        renderModelDetails();
    }
}

// ===== Tag Autocomplete (Single Tag) =====

// Search tags from API
async function searchTags(query) {
    const request = ++tagRequest;
    if (query.length < 3) {
        tagSuggestions = [];
        renderTagDropdown();
        return;
    }

    try {
        const result = await apiCall({ endpoint: '/model-manager/civitai/tags', params: { query, limit: 20 } });
        if (request !== tagRequest) return;     // a newer lookup has been asked for
        if (result.success) {
            tagSuggestions = result.tags || [];
            tagSelectedIndex = -1;
            renderTagDropdown();
        }
    } catch (e) {
        if (request !== tagRequest) return;
        console.error('[CivitaiBrowser] Tag search error:', e);
        tagSuggestions = [];
        renderTagDropdown();
    }
}

// Render tag dropdown
function renderTagDropdown() {
    const dropdown = document.getElementById('cb_tag_dropdown');
    if (!dropdown) return;

    if (tagSuggestions.length === 0) {
        dropdown.classList.remove('show');
        return;
    }

    dropdown.innerHTML = tagSuggestions.map((tag, index) => {
        const selectedClass = index === tagSelectedIndex ? 'selected' : '';
        return `<div class="cb-tag-dropdown-item ${selectedClass}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</div>`;
    }).join('');

    dropdown.classList.add('show');
}

/**
 * Choose a tag, or clear it with ''.
 *
 * A chosen tag is shown as a chip with an x, in place of the box, so it reads
 * as a filter in force rather than as text half typed. Clearing it brings the
 * empty box back, focused, for the next one. Civitai searches by one tag, so
 * there is only ever one chip.
 */
function selectTag(tagName) {
    selectedTag = (tagName || '').trim();
    tagSuggestions = [];
    renderTagDropdown();

    const input = document.getElementById('cb_tag_input');
    const chipBox = document.getElementById('cb_tag_selected');
    const chipName = document.getElementById('cb_tag_chip_name');
    if (input) input.value = '';
    if (chipName) chipName.textContent = selectedTag;
    if (chipBox) chipBox.style.display = selectedTag ? 'flex' : 'none';
    if (input) {
        input.style.display = selectedTag ? 'none' : '';
        if (!selectedTag) input.focus?.();
    }
}

// Text typed but never chosen still counts at Search, as it always has, and
// becomes a chip then, so what the search is filtered by is always on show.
function commitTypedTag() {
    const input = document.getElementById('cb_tag_input');
    if (input && input.style.display !== 'none' && input.value.trim()) {
        selectTag(input.value);
    }
}

// Civitai's own type/base-model lists, fetched once per page load. Until
// they arrive (or if the request fails) the static options in the page
// stand in, so the tab still works offline.
let enumsLoaded = false;
let enumsRequest = null;

function makeOption(value, label) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    return option;
}

/**
 * Refill a <select> with `values`, keeping whatever was selected.
 * The "All" entry from the static markup is kept as the first option.
 *
 * Options are built as nodes rather than markup: a model type is whatever
 * Civitai says it is, and escapeHtml() does not escape quotes, so pasting
 * one into a value="" attribute would be a way out of it.
 */
function fillSelect(selectId, values, labelFor) {
    const select = document.getElementById(selectId);
    if (!select || !values.length) return false;

    const previous = select.value;
    const allOption = select.querySelector('option[value=""]');

    select.innerHTML = '';
    select.appendChild(allOption || makeOption('', 'All'));
    for (const value of values) {
        select.appendChild(makeOption(value, labelFor ? labelFor(value) : value));
    }

    // Keep the user's choice if Civitai still offers it.
    select.value = previous;
    if (select.selectedIndex === -1) select.value = '';
    return true;
}

// Civitai's raw enum names, where they are not what the UI should say.
const TYPE_LABELS = {
    TextualInversion: 'Embedding',
    LORA: 'LoRA',
    Controlnet: 'ControlNet',
};

// Asked for once per page load and reused. The retry below is for the
// dropdowns not existing yet, not for a failed request, so it must not
// fire a fresh call every time it ticks.
function fetchEnums() {
    if (!enumsRequest) {
        enumsRequest = apiCall({ endpoint: '/model-manager/civitai/enums' })
            .catch(error => {
                console.warn('[CivitaiBrowser] Could not reach the enums endpoint, '
                             + 'keeping the static options', error);
                return null;
            });
    }
    return enumsRequest;
}

async function loadEnums() {
    if (enumsLoaded) return true;

    const result = await fetchEnums();
    if (!result || !result.success) {
        return false;  // the options already in the page stand in
    }

    // Both selects have to exist - Gradio builds the tab lazily.
    const typesFilled = fillSelect('cb_type', result.model_types || [],
                                   value => TYPE_LABELS[value] || value);
    const baseFilled = fillSelect('cb_base_model', sortBaseModels(result.base_models || []));
    if (!typesFilled || !baseFilled) return false;

    enumsLoaded = true;
    syncCheckpointType('cb');
    console.log(`[CivitaiBrowser] Loaded ${result.model_types.length} model types, `
                + `${result.base_models.length} base models from Civitai`);
    return true;
}

function initTagInput() {
    const input = document.getElementById('cb_tag_input');
    const dropdown = document.getElementById('cb_tag_dropdown');

    if (!input || tagInputInitialized) return;
    tagInputInitialized = true;

    console.log('[CivitaiBrowser] Tag input initialized');

    // Suggestions on every keystroke. There was a one-second wait before
    // asking, which made the box feel dead; searchTags() drops any answer
    // that a later keystroke has overtaken.
    input.addEventListener('input', (e) => {
        const query = e.target.value.trim();
        selectedTag = query; // Update selected tag as user types
        searchTags(query);
    });

    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (tagSuggestions.length > 0) {
                tagSelectedIndex = Math.min(tagSelectedIndex + 1, tagSuggestions.length - 1);
                renderTagDropdown();
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (tagSuggestions.length > 0) {
                tagSelectedIndex = Math.max(tagSelectedIndex - 1, 0);
                renderTagDropdown();
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (tagSelectedIndex >= 0 && tagSuggestions[tagSelectedIndex]) {
                selectTag(tagSuggestions[tagSelectedIndex]);
            } else if (input.value.trim()) {
                // Nothing highlighted: what was typed is the tag.
                selectTag(input.value);
            } else {
                tagSuggestions = [];
                renderTagDropdown();
            }
        }
        // Escape is the page's listener's (init): it closes the suggestions,
        // or else the open model. Emptied here first, it found none showing
        // and closed both (#127).
    });

    document.getElementById('cb_tag_chip_remove')?.addEventListener('click', () => selectTag(''));

    // Click on dropdown item
    if (dropdown) {
        dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.cb-tag-dropdown-item');
            if (item) {
                selectTag(item.dataset.tag);
            }
        });
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.cb-tag-container')) {
            tagSuggestions = [];
            renderTagDropdown();
        }
    });
}

// Initialize (with guard against multiple initializations)
let isInitialized = false;
function init() {
    // Same warning as the Model Manager tab; the shared helper waits for the
    // answer and the markup in whichever order they turn up.
    showApiKeyBanner('cb_api_key_warning');
    showNotes('civitai_browser', 'cb_notes');

    if (isInitialized) {
        console.log('[CivitaiBrowser] Already initialized, skipping');
        return;
    }
    isInitialized = true;
    console.log('[CivitaiBrowser] Initializing...');

    const searchInput = document.getElementById('cb_search');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchModels(1);
        });
    }

    const typeSelect = document.getElementById('cb_type');
    if (typeSelect) {
        typeSelect.addEventListener('change', () => syncCheckpointType('cb'));
    }
    syncCheckpointType('cb');

    syncSfwOnlyEnabled();
    loadNsfwDetection().then(syncSfwOnlyEnabled);
    syncLucky();

    const saveBtn = document.getElementById('cb_save_search_btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', (e) => {
            e.preventDefault();
            saveCbSearch();
        });
        saveBtn.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            clearCbSearch();
        });
    }
    prepareSavedSearch();

    // Initialize tag input (try now and also watch for dynamic loading)
    initTagInput();
    loadEnums();

    // Retry initialization for dynamically loaded elements (Gradio tabs)
    const initRetry = setInterval(() => {
        if (!tagInputInitialized) {
            initTagInput();
        }
        if (!enumsLoaded) {
            loadEnums();
        }
        if (tagInputInitialized && enumsLoaded) {
            clearInterval(initRetry);
        }
    }, 500);

    // Stop retrying after 10 seconds
    setTimeout(() => clearInterval(initRetry), 10000);

    // Esc closes the tag suggestions, then the open model - this tab's, while
    // it is the one showing and nothing is open over it. A dialog or a viewer
    // closes itself (closeOnEscape); this used to close the first modal on
    // the page whatever tab it was, and the open model with any Escape.
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || dialogShowing() || viewerIsOpen()) return;
        if (document.getElementById('cb_grid')?.offsetParent === null) return;
        if (tagSuggestions.length) {
            tagSuggestions = [];
            renderTagDropdown();
            return;
        }
        closeDetails();
    });

    console.log('[CivitaiBrowser] Ready');
}

// ------------------------------------------------------------- Save Search
// One saved search, in the database (savedSearch in filters.mjs): its filters
// fill the bar, and it runs the first time this tab is shown - not when the
// page loads, when every tab loads at once, which would ask Civitai whether
// or not the tab is ever looked at. A search of the reader's own, or one the
// Model Manager's "Show in Civitai Browser" brings, comes first and it stands
// aside.
let savedSearchDone = false;

/** The filters as the bar shows them, as Save Search keeps them - the boxes, not what is sent. */
function currentSearch() {
    const value = (id) => document.getElementById(id)?.value || '';
    const ticked = (id) => document.getElementById(id)?.checked || false;
    return {
        query: value('cb_search'), types: value('cb_type'), checkpoint_type: value('cb_checkpoint_type'),
        base_models: value('cb_base_model'), sort: value('cb_sort'), period: value('cb_period'),
        nsfw: ticked('cb_nsfw'), tag: selectedTag, require_prompt: ticked('cb_require_prompt'),
        sfw_only: ticked('cb_sfw_only'), min_size: value('cb_min_size'), max_size: value('cb_max_size'),
    };
}

function applySearch(filters) {
    const set = (id, key) => {
        const element = document.getElementById(id);
        if (element && Object.prototype.hasOwnProperty.call(filters, key)) element.value = filters[key] ?? '';
    };
    const tick = (id, key) => {
        const element = document.getElementById(id);
        if (element && Object.prototype.hasOwnProperty.call(filters, key)) element.checked = Boolean(filters[key]);
    };
    set('cb_search', 'query');
    set('cb_type', 'types');
    set('cb_checkpoint_type', 'checkpoint_type');
    set('cb_base_model', 'base_models');
    set('cb_sort', 'sort');
    set('cb_period', 'period');
    tick('cb_nsfw', 'nsfw');
    tick('cb_require_prompt', 'require_prompt');
    tick('cb_sfw_only', 'sfw_only');
    set('cb_min_size', 'min_size');
    set('cb_max_size', 'max_size');
    if (Object.prototype.hasOwnProperty.call(filters, 'tag')) selectTag(filters.tag || '');
    syncCheckpointType('cb');
    syncSfwOnlyEnabled();
}

async function saveCbSearch() {
    commitTypedTag();
    if (!await saveSearch('civitai_browser', currentSearch())) {
        updateStatus('Could not save the search: the server did not keep it.');
        return;
    }
    flashSaveSearch('cb_save_search_btn', '✓ Saved');
}

async function clearCbSearch() {
    if (!await saveSearch('civitai_browser', null)) {
        updateStatus('Could not clear the saved search: the server did not answer.');
        return;
    }
    flashSaveSearch('cb_save_search_btn', '✗ Cleared');
}

function runSavedSearch() {
    if (savedSearchDone) return;
    savedSearchDone = true;
    search();
}

/**
 * Fill the bar from the saved search - once Civitai's lists are in, or a
 * type or base model not in the page's first list would not take - and run
 * it when the tab is first shown.
 */
async function prepareSavedSearch() {
    const filters = await savedSearch('civitai_browser');
    if (!filters || savedSearchDone) return;
    await loadEnums();
    if (savedSearchDone) return;
    applySearch(filters);
    if (tabShowing('civitaiBrowser')) {
        runSavedSearch();
        return;
    }
    document.addEventListener('click', (event) => {
        if (tabButton('civitaiBrowser')?.contains(event.target)) runSavedSearch();
    });
}

// Expose functions to window for inline handlers
function search() {
    savedSearchDone = true;          // the reader's own search: the saved one stands aside
    initTagInput();
    loadEnums();
    commitTypedTag();
    if (feelingLucky()) {
        drawModels();
        return;
    }
    // A search starts at page 1 with only the pages it has been to: a
    // filtered page's cursor holds what the filters found then, not now.
    cursors = [""];
    hasMorePages = true;
    searchModels(1);
}
function prevPage() {
    if (currentPage > 1) {
        searchModels(currentPage - 1);
    }
}
function nextPage() {
    // Can go next if there are more pages AND we have a cursor for it
    if (hasMorePages && cursors[currentPage]) {
        searchModels(currentPage + 1);
    }
}
function goToPage(page) {
    // Can navigate to any page we have a cursor for
    if (page >= 1 && page <= cursors.length && page !== currentPage) {
        searchModels(page);
    }
}
// Show a model here, asked for from another tab: this tab first, once it
// shows - the grid measures itself, and a hidden tab measures nothing - and
// a search of its own, so the saved search stands aside. The mirror of the
// Model Manager's modelManager.showModel.
async function showModel(query) {
    savedSearchDone = true;
    await showTab('civitaiBrowser');
    const search = document.getElementById('cb_search');
    if (search) search.value = query;

    // A targeted lookup ignores them, but leaving them set would be confusing
    // the moment the next search is run.
    const nsfw = document.getElementById('cb_nsfw');
    if (nsfw) nsfw.checked = true;
    syncSfwOnlyEnabled();
    const requirePrompt = document.getElementById('cb_require_prompt');
    if (requirePrompt) requirePrompt.checked = false;
    // The query goes in the search box, which a draw greys out.
    const lucky = document.getElementById('cb_lucky');
    if (lucky) lucky.checked = false;
    syncLucky();

    await searchModels(1);
}
provide('civitaiBrowser.showModel', showModel);

// Open this model over in the Model Manager tab, which shows itself.
function showInModelManager(modelId) {
    if (!ready('modelManager.showModel')) {
        updateStatus('Model Manager tab has not initialised yet - open it once and try again.');
        return;
    }
    call('modelManager.showModel', 'model:' + modelId);
}


// ---------------------------------------------------------------- markup
// What this tab's markup does, by name: a card, a button or a field says it
// in data-action, and carries what it needs in data-* (shared/calls.mjs, #95).
provide('civitaiBrowser.search', () => search());
provide('civitaiBrowser.feelingLucky', () => syncLucky());
provide('civitaiBrowser.openModel', ({ index }) => openModel(Number(index)));
provide('civitaiBrowser.goToPage', ({ page }) => goToPage(Number(page)));
provide('civitaiBrowser.prevPage', () => prevPage());
provide('civitaiBrowser.nextPage', () => nextPage());
provide('civitaiBrowser.showAllImages', (data, box) => toggleShowAllImages(box.checked));
provide('civitaiBrowser.showPromptless', (data, box) => toggleShowPromptless(box.checked));
provide('civitaiBrowser.loadMoreImages', () => loadMoreImages());
provide('civitaiBrowser.download', ({ modelId, versionId, fileId }) =>
    startDownload(safeId(modelId), safeId(versionId), safeId(fileId)));
provide('civitaiBrowser.selectFile', (data, picker) => selectFile(picker.value));
provide('civitaiBrowser.showImageMeta', ({ index }) => showImageMetaAt(Number(index)));
provide('civitaiBrowser.showResources', ({ index }) => showResources(Number(index)));
provide('civitaiBrowser.selectVersion', ({ index }) => selectVersion(Number(index)));
provide('civitaiBrowser.toggleDescription', () => toggleDescription());
provide('civitaiBrowser.showInModelManager', ({ modelId }) => showInModelManager(safeId(modelId)));
provide('civitaiBrowser.closeDetails', () => closeDetails());

// Initialize when ready
onReady(init);
