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
// import.meta.url carries this script's own version, so the shared module is
// asked for with the same one. A dynamic import is the only way to build that
// URL at runtime, which is why this is not a plain import statement.
const sharedModule = new URL('./shared/common.mjs', import.meta.url);
sharedModule.search = new URL(import.meta.url).search;

const {
    onReady,
    showApiKeyBanner,
    apiCall,
    escapeHtml,
    safeId,
    sanitizeHtml,
    formatNumber,
    renderThumbs,
    nsfwImageLevel,
    isImageSafe,
    nsfwBadgeLabel,
    isVideoUrl,
    sortBaseModels,
    cardMediaUrl,
    getImagePageCount,
    downloadedImagesNote,
    setupLazyMedia,
    renderResource,
    renderFilterBanner,
    balanceGridRows,
    IMAGE_PAGE_SIZE,
    applyCardSize: sharedApplyCardSize,
    renderImagePagination: sharedImagePagination,
    paidAccessLabel,
    isPaid,
    primaryFileIndex,
    renderDownloadControls,
    showChosenFile,
    downloads,
    formatBytes: formatFileSize,
    formatDay: formatDate,
    loadNsfwDetection,
    nsfwModelNote,
    galleryDefaults,
    refreshUiOptions,
    renderModelCard,
    renderGridPagination,
    renderModelGrid: renderSharedGrid,
} = await import(sharedModule.href);

// The settings window behind the gear in the header, asked for with this
// script's version as the shared module is.
const settingsModule = new URL('./shared/settings.mjs', import.meta.url);
settingsModule.search = sharedModule.search;
await import(settingsModule.href);

// State
let currentModels = [];
let currentPage = 1;
let pageSize = 20;
let isLoading = false;
let selectedModel = null;
let selectedVersionIndex = 0;
let selectedFileIndex = null;  // null = whichever file Civitai marks primary
// The gallery is fetched a page at a time, filtered on the server; it used to
// arrive whole and be filtered and sliced here. currentImages is the page on
// show, imagesOffset where it starts among the images the switches let
// through, and imageCounts the counts the banner states, as the server gives
// them (ImagesOps.get_image_counts() says what each means).
let currentImages = [];
let currentImagePage = 1;
let imagesOffset = 0;
let imageCounts = null;
// Each fetch of the gallery takes a number; an answer to anything but the
// latest is dropped, so a slow page cannot land over a newer one.
let imagesRequest = 0;
// What the last Load More brought, beside the button, until the gallery is
// next loaded some other way.
let downloadNote = '';
let nextImagesCursor = null;
let isLoadingImages = false;
// The gallery's two switches. Each model opens as the settings say, and a
// switch then lasts while that model is open - as in the Model Manager.
let showAllNsfwImages = false;
let showPromptlessImages = false;

// Card sizing (default values, updated from API)
let cardWidth = 200;
let cardHeight = 280;

// Apply card size from API response
function applyCardSize(width, height) {
    if (width && height && (width !== cardWidth || height !== cardHeight)) {
        cardWidth = width;
        cardHeight = height;
        sharedApplyCardSize({
            width, height,
            containerId: 'civitai_browser_app',
            logTag: 'CivitaiBrowser',
        });
    }
}

// After the settings window saved: redo what this tab drew from the settings.
// The page size applies from the next search, and the gallery reads its
// settings each time a model opens.
window.addEventListener('mm-settings-saved', (e) => {
    refreshUiOptions().then(syncSfwOnlyEnabled);
    if ((e.detail?.changed || []).includes('model_manager_civitai_card_size')) {
        // Saved as the server normalises it: "200x280".
        const [width, height] = String(e.detail.settings.model_manager_civitai_card_size.value || '')
            .split('x').map(Number);
        if (width > 0 && height > 0) applyCardSize(width, height);
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
(window.mmCardPreviews ||= {}).model_manager_civitai_card_size = cardPreview;

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

const IMAGE_PLACEHOLDER_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200'%3E%3Crect fill='%23222933' width='320' height='200'/%3E%3Cg fill='%236b7280'%3E%3Cpath d='M130 78h60v44h-60z'/%3E%3Cpath d='M92 132l34-30 28 24 18-14 56 44H92z'/%3E%3Ccircle cx='208' cy='82' r='10'/%3E%3C/g%3E%3Ctext x='160' y='176' text-anchor='middle' fill='%239ca3af' font-size='14'%3EImage unavailable%3C/text%3E%3C/svg%3E";

// Calculate effective NSFW level using same algorithm as Python backend
// NSFW levels: 1=PG, 2=PG-13, 4=R, 8=X, 16=XXX, 32=Blocked, 64=Unknown
function renderImagePagination(totalPages, position = 'bottom') {
    return sharedImagePagination({
        currentPage: currentImagePage, totalPages, position, prefix: 'cb',
    });
}

function scrollToBrowserImagesTop() {
    return new Promise((resolve) => {
        const container = document.getElementById('cb_images');
        if (!container) {
            resolve();
            return;
        }

        const list = container.querySelector('.model-images-list') || container;
        const targetY = Math.max(0, window.scrollY + list.getBoundingClientRect().top - 12);

        if (Math.abs(window.scrollY - targetY) < 4) {
            resolve();
            return;
        }

        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            window.removeEventListener('scroll', onScroll);
            resolve();
        };

        const onScroll = () => {
            if (Math.abs(window.scrollY - targetY) < 4) {
                finish();
            }
        };

        window.addEventListener('scroll', onScroll, { passive: true });
        window.scrollTo({ top: targetY, behavior: 'smooth' });
        setTimeout(finish, 500);
    });
}

// Wait for DOM

// API call helper

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

// A size box's value in GB, or '' when it is empty or not a positive number -
// which apiCall and the stream both leave out of the request.
function sizeBound(id) {
    const value = parseFloat(document.getElementById(id)?.value);
    return Number.isFinite(value) && value > 0 ? value : '';
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
    if (requirePromptEnabled()) return 'Checking models for usable prompts...';
    if (sfwOnlyEnabled()) return 'Checking models for SFW images...';
    return 'Looking for models in the size range...';
}

/**
 * Is "Only Show Models with SFW images" ticked and in force?
 *
 * It means nothing while NSFW models are included, so it is greyed out then,
 * keeps its tick for when it applies again, and is not sent.
 */
function sfwOnlyEnabled() {
    const nsfw = document.getElementById('cb_nsfw')?.checked || false;
    return !nsfw && (document.getElementById('cb_sfw_only')?.checked || false);
}

// Grey out "Only Show Models with SFW images" while NSFW models are included, saying why,
// and while it is in force, say above the results what it is doing: its
// pages come back short, and without this that reads as something broken.
function syncSfwOnlyEnabled() {
    const box = document.getElementById('cb_sfw_only');
    const label = document.getElementById('cb_sfw_only_label');
    if (!box || !label) return;

    if (label.dataset.title === undefined) label.dataset.title = label.title;
    const applies = !(document.getElementById('cb_nsfw')?.checked || false);
    box.disabled = !applies;
    label.classList.toggle('cb-filter-disabled', !applies);
    label.title = applies
        ? label.dataset.title
        : 'Only applies while Include NSFW models is unticked. ' + label.dataset.title;

    const banner = document.getElementById('cb_sfw_only_banner');
    const text = document.getElementById('cb_sfw_only_banner_text');
    if (banner && text) {
        text.textContent = label.dataset.title;
        banner.style.display = sfwOnlyEnabled() ? 'flex' : 'none';
    }
    const note = document.getElementById('cb_sfw_only_banner_model');
    if (note) note.textContent = nsfwModelNote();
}

// Is the prompt filter currently on?
function requirePromptEnabled() {
    return document.getElementById('cb_require_prompt')?.checked || false;
}

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

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();          // keep any partial line

            for (const line of lines) {
                if (!line.trim()) continue;
                let evt;
                try {
                    evt = JSON.parse(line);
                } catch (e) {
                    console.warn('[CivitaiBrowser] Bad stream line:', line);
                    continue;
                }

                if (evt.type === 'meta') {
                    if (evt.cardWidth && evt.cardHeight) {
                        applyCardSize(evt.cardWidth, evt.cardHeight);
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
            }
        }
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
                applyCardSize(result.cardWidth, result.cardHeight);
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
            goTo: 'cbGoToPage', prev: 'cbPrevPage', next: 'cbNextPage',
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
    const src = image?.url ? cardMediaUrl(image.url, image.type) : '';
    return renderModelCard({
        index,
        onclick: `window.cbOpenModel(${index})`,
        name: model.name,
        media: { src, video: isVideoUrl({ url: src, type: image?.type }) },
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
    currentImages = [];
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
                       onclick="window.cbSelectVersion(${index})"
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
             <button class="mm-description-toggle" id="cb_description_toggle" onclick="window.cbToggleDescription()">
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
        prefix: 'cb', modelId: model.id, version, fileIndex, owned: isOwned });

    // Only offer the jump for models that are actually in the library.
    // Lives on the header row so it stays reachable while scrolling the
    // details panel, rather than only at the very bottom.
    const showInManagerBtn = model.owned_locally
        ? `<button class="mm-btn secondary mm-btn-small header-action" onclick="window.cbShowInModelManager(${safeId(model.id)})" title="Open this model in the Model Manager tab">Show in Model Manager</button>`
        : '';

    container.innerHTML = `
        <div class="model-details-content">
            <div class="detail-header">
                <h3>${escapeHtml(model.name)}</h3>
                ${showInManagerBtn}
                <button class="close-details" onclick="window.cbCloseDetails()">×</button>
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
window.cbToggleDescription = function() {
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
};

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
    showChosenFile('cb', selectedModel?.id, version, file);
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
 * Fetch a page of the selected version's gallery, through the two switches.
 * Only opening a version asks the server to look up missing prompts on
 * Civitai; a page turn or a switch only reads what is cached.
 *
 * @returns {Promise<object|null>} the answer, or null if a newer fetch or
 *     another version has taken over since
 */
async function fetchImagesPage(offset, { opening = false } = {}) {
    const version = getSelectedVersion();
    if (!version?.id) return null;
    const request = ++imagesRequest;
    const result = await apiCall({
        endpoint: `/model-manager/civitai/versions/${version.id}/images`,
        params: {
            model_id: selectedModel.id, offset, limit: IMAGE_PAGE_SIZE,
            hide_nsfw_images: !showAllNsfwImages,
            hide_promptless_images: !showPromptlessImages,
            backfill: opening,
        },
    });
    if (request !== imagesRequest || getSelectedVersion() !== version) return null;
    if (result.success) {
        currentImages = result.images || [];
        imageCounts = result.images_state || null;
        imagesOffset = imageCounts?.offset || 0;
        currentImagePage = Math.floor(imagesOffset / IMAGE_PAGE_SIZE) + 1;
        nextImagesCursor = result.next_cursor || null;
    }
    return result;
}

// Load images from API (with full metadata)
async function loadImagesFromVersion() {
    // Which images are safe depends on the NSFW prompt words too.
    const version = getSelectedVersion();
    if (!version?.id) {
        currentImages = [];
        imageCounts = null;
        nextImagesCursor = null;
        renderImages();
        return;
    }

    // Reset state
    currentImages = [];
    imageCounts = null;
    downloadNote = '';
    currentImagePage = 1;
    imagesOffset = 0;
    nextImagesCursor = null;
    isLoadingImages = true;

    const container = document.getElementById('cb_images');
    if (container) {
        container.innerHTML = '<div class="mm-images-loading">Loading images...</div>';
        container.style.display = 'block';
    }

    try {
        const result = await fetchImagesPage(0, { opening: true });
        if (!result) return;
        if (result.success) {
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

/** Fetch and show one page of the gallery. */
async function showImagePage(page) {
    downloadNote = '';
    const totalPages = getImagePageCount(imageCounts?.filtered || 0);
    const target = Math.min(Math.max(1, page), totalPages);
    try {
        const result = await fetchImagesPage((target - 1) * IMAGE_PAGE_SIZE);
        if (result?.success) renderImages();
    } catch (e) {
        console.error('[CivitaiBrowser] Load images error:', e);
    }
}

// Load more images from API (server tracks cursor)
async function loadMoreImages() {
    const version = getSelectedVersion();
    if (!version?.id || isLoadingImages || !nextImagesCursor) return;

    isLoadingImages = true;

    const loadMoreBtn = document.getElementById('cb_load_more_btn');
    if (loadMoreBtn) {
        loadMoreBtn.disabled = true;
        loadMoreBtn.textContent = 'Loading...';
    }

    try {
        // POST to load-more endpoint (server uses cached cursor)
        const result = await apiPost(`/model-manager/civitai/versions/${version.id}/images/load-more`, {
            model_id: selectedModel.id
        });

        if (result.success) {
            // The answer holds what Civitai sent, filtered or not, so the
            // page is read again from the server rather than added to. A new
            // page means the new images are on it: go there.
            const before = { ...imageCounts };
            const oldPages = getImagePageCount(imageCounts?.filtered || 0);
            const page = await fetchImagesPage(imagesOffset);
            if (!page) return;   // another version, or a newer fetch, took over
            if (page.success) {
                const newPages = getImagePageCount(imageCounts?.filtered || 0);
                if (newPages > oldPages) {
                    await scrollToBrowserImagesTop();
                    await showImagePage(newPages);
                }
                downloadNote = downloadedImagesNote(before, imageCounts || before, result.message);
            } else {
                nextImagesCursor = result.next_cursor || null;
            }
            renderImages();
        } else {
            // Reset button on error
            if (loadMoreBtn) {
                loadMoreBtn.disabled = false;
                loadMoreBtn.textContent = 'Load More Images';
            }
        }
    } catch (e) {
        console.error('[CivitaiBrowser] Load more error:', e);
        if (loadMoreBtn) {
            loadMoreBtn.disabled = false;
            loadMoreBtn.textContent = 'Load More Images';
        }
    } finally {
        isLoadingImages = false;
    }
}

// Update images count in the details table: every image cached, filtered or not
function updateImagesCount() {
    const countCell = document.getElementById('cb_images_count');
    if (countCell) {
        countCell.textContent = imageCounts ? imageCounts.total : '...';
    }
}

// Render images - EXACTLY like Model Manager
function renderImages() {
    const container = document.getElementById('cb_images');
    if (!container) return;

    const counts = imageCounts || { total: 0, filtered: 0, hidden_nsfw: 0,
                                    hidden_promptless: 0, nsfw_count: 0, promptless_count: 0 };
    if (counts.total === 0) {
        container.innerHTML = '<div class="mm-images-empty">No images available for this version.</div>';
        container.style.display = 'block';
        updateImagesCount();
        return;
    }

    // The server filters, NSFW first and then the prompt filter (hiding
    // images with no prompt worth reading, by the Model Manager's rule), and
    // pages what is left, so page numbers count only what is shown. What each
    // filter holds back, and each switch's count, come with the page.
    const shown = counts.filtered;
    const hiddenCount = counts.hidden_nsfw;
    const promptHiddenCount = counts.hidden_promptless;
    const totalPages = getImagePageCount(shown);
    currentImagePage = Math.min(Math.max(1, currentImagePage), totalPages);
    const pageStart = imagesOffset;
    const pageEnd = imagesOffset + currentImages.length;

    // One banner for both filters, built in shared/common.mjs as the Model
    // Manager's is: what they are holding back - which adds up with what is
    // shown, NSFW counted first as it filters first - and a switch for each on
    // the right. A ticked NSFW switch shows how many NSFW images it lets
    // through, among those the prompt filter lets through.
    const bannerOptions = {
        shown,
        total: counts.total,
        bannerClass: 'cb-nsfw-warning',
        labelClass: 'cb-show-all-label',
        switches: [
            { id: 'cb_show_all_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: showAllNsfwImages, hidden: hiddenCount,
              count: counts.nsfw_count,
              onchange: 'window.cbToggleShowAllImages(this.checked)', note: nsfwModelNote() },
            { id: 'cb_show_promptless_images', label: 'Show unusable prompts',
              reason: 'unusable prompt',
              showing: showPromptlessImages, hidden: promptHiddenCount,
              count: counts.promptless_count,
              onchange: 'window.cbToggleShowPromptless(this.checked)' },
        ],
    };
    const filterBannerHtml = renderFilterBanner(bannerOptions);

    // The same sentence again under a long list, without a second set of
    // switches - they would share ids, and one set is enough.
    const filterFooterHtml = (hiddenCount + promptHiddenCount) > 0
        ? renderFilterBanner({ ...bannerOptions, withSwitches: false })
        : '';

    const imageCards = currentImages.map((img, index) => renderImageCard(img, index)).join('');

    // Only show "Load More" button if there's a cursor (more images available)
    const loadMoreHtml = currentImagePage === totalPages && nextImagesCursor
        ? `<div class="mm-load-more">
            <button class="mm-btn secondary" id="cb_load_more_btn" onclick="window.cbLoadMoreImages()">
                Load More Images
            </button>
            <span class="mm-load-more-info">${escapeHtml(downloadNote) || `${counts.total} images loaded`}</span>
           </div>`
        : (currentImagePage === totalPages ? `<div class="mm-load-more">
            <span class="mm-load-more-info">${downloadNote ? escapeHtml(downloadNote) : `${counts.total} images (all loaded)`}</span>
           </div>` : '');

    container.innerHTML = `
        <div class="mm-images-header">
            <h4>Example Images</h4>
            <span class="mm-images-count">${shown > 0 ? `${pageStart + 1}-${pageEnd} of ${shown}` : '0'}${(hiddenCount + promptHiddenCount) > 0 ? ` (${hiddenCount + promptHiddenCount} hidden)` : ''} images (Page ${currentImagePage}/${totalPages})</span>
        </div>
        ${filterBannerHtml}
        ${renderImagePagination(totalPages, 'top')}
        <div class="model-images-list">${imageCards}</div>
        ${filterFooterHtml}
        ${loadMoreHtml}
        ${renderImagePagination(totalPages, 'bottom')}
    `;

    container.style.display = 'block';
    setupLazyMedia(container);

    // Update the images count in the details table
    updateImagesCount();
}

// Toggle show all images checkbox. The server filters, so the gallery is
// fetched again from its first page.
window.cbToggleShowAllImages = async function(checked) {
    showAllNsfwImages = checked;
    await showImagePage(1);
};

// Show or hide this model's images without a prompt. The search's own filter
// is left as it is.
window.cbToggleShowPromptless = async function(checked) {
    showPromptlessImages = checked;
    await showImagePage(1);
};

window.cbFirstImagePage = async function() {
    if (currentImagePage === 1) return;
    await showImagePage(1);
};

window.cbLastImagePage = async function() {
    const totalPages = getImagePageCount(imageCounts?.filtered || 0);
    if (currentImagePage === totalPages) return;
    await showImagePage(totalPages);
};

window.cbPrevImagePage = async function() {
    if (currentImagePage <= 1) return;
    await showImagePage(currentImagePage - 1);
};

window.cbNextImagePage = async function() {
    const totalPages = getImagePageCount(imageCounts?.filtered || 0);
    if (currentImagePage >= totalPages) return;
    await showImagePage(currentImagePage + 1);
};

window.cbGoToImagePage = async function(page) {
    const totalPages = getImagePageCount(imageCounts?.filtered || 0);
    if (page < 1 || page > totalPages || page === currentImagePage) return;

    await scrollToBrowserImagesTop();
    await showImagePage(page);
};

// Helper to detect video URLs

// Render single image card - EXACTLY like Model Manager
function renderImageCard(img, index) {
    const src = img.url || '';

    // Detect media type from URL or type field
    const isVideo = isVideoUrl({ url: src, type: img.type });

    const meta = img.meta || {};
    const prompt = meta.prompt || '';
    const negPrompt = meta.negativePrompt || '';
    const resources = meta.resources || [];
    const civitaiResources = meta.civitaiResources || [];

    // Split sampler if it contains scheduler
    let displaySampler = meta.sampler;
    let displayScheduler = meta['Schedule type'];

    if (!displayScheduler && displaySampler) {
        const split = splitSamplerScheduler(displaySampler);
        displaySampler = split.sampler;
        displayScheduler = split.scheduler;
    }

    // Get size
    let sizeStr = meta.Size;
    if (!sizeStr && img.width && img.height) {
        sizeStr = `${img.width}x${img.height}`;
    }
    if (!sizeStr && meta.width && meta.height) {
        sizeStr = `${meta.width}x${meta.height}`;
    }

    // Build generation params string
    const genParams = [];
    if (meta.steps) genParams.push(`Steps: ${meta.steps}`);
    if (displaySampler) genParams.push(`Sampler: ${displaySampler}`);
    if (displayScheduler) genParams.push(`Scheduler: ${displayScheduler}`);
    if (meta.cfgScale) genParams.push(`CFG: ${meta.cfgScale}`);
    if (meta.seed) genParams.push(`Seed: ${meta.seed}`);
    if (meta.VAE) genParams.push(`VAE: ${meta.VAE}`);
    if (meta['Clip skip']) genParams.push(`Clip Skip: ${meta['Clip skip']}`);
    if (meta['Denoising strength']) genParams.push(`Denoise: ${meta['Denoising strength']}`);
    if (sizeStr) genParams.push(`Size: ${sizeStr}`);

    // Hires info
    const hiresParams = [];
    if (meta['Hires upscaler']) hiresParams.push(`Upscaler: ${meta['Hires upscaler']}`);
    if (meta['Hires upscale']) hiresParams.push(`Scale: ${meta['Hires upscale']}`);
    if (meta['Hires steps']) hiresParams.push(`Steps: ${meta['Hires steps']}`);

    // ADetailer info
    const adetailerParams = [];
    if (meta['ADetailer model']) adetailerParams.push(`Model: ${meta['ADetailer model']}`);
    if (meta['ADetailer confidence']) adetailerParams.push(`Conf: ${meta['ADetailer confidence']}`);
    if (meta['ADetailer dilate erode']) adetailerParams.push(`Dilate: ${meta['ADetailer dilate erode']}`);
    if (meta['ADetailer mask blur']) adetailerParams.push(`Blur: ${meta['ADetailer mask blur']}`);
    if (meta['ADetailer denoising strength']) adetailerParams.push(`Denoise: ${meta['ADetailer denoising strength']}`);

    // Image ID
    const imageIdHtml = img.id
        ? `<div class="mm-image-id">
             <span class="mm-resources-label">Image ID:</span>
             <span>${img.id}</span>
           </div>`
        : '';

    // Resources (LoRAs, etc)
    const resourcesHtml = resources.length > 0
        ? `<div class="mm-image-resources">
             <span class="mm-resources-label">Resources:</span>
             ${resources.map(r => renderResource(r)).join('')}
           </div>`
        : '';

    // Prompt (truncated)
    const promptShort = prompt.length > 300 ? prompt.substring(0, 300) + '...' : prompt;
    const promptHtml = prompt
        ? `<div class="mm-image-prompt">
             <span class="mm-prompt-label">Prompt:</span>
             <span class="mm-prompt-text" title="${escapeHtml(prompt)}">${escapeHtml(promptShort)}</span>
           </div>`
        : '';

    // Negative prompt (truncated)
    const negPromptShort = negPrompt.length > 150 ? negPrompt.substring(0, 150) + '...' : negPrompt;
    const negPromptHtml = negPrompt
        ? `<div class="mm-image-neg-prompt">
             <span class="mm-prompt-label">Negative:</span>
             <span class="mm-prompt-text" title="${escapeHtml(negPrompt)}">${escapeHtml(negPromptShort)}</span>
           </div>`
        : '';

    // Generation params
    const genParamsHtml = genParams.length > 0
        ? `<div class="mm-image-params">${genParams.join(' | ')}</div>`
        : '';

    // Hires params
    const hiresHtml = hiresParams.length > 0
        ? `<div class="mm-image-hires">Hires: ${hiresParams.join(', ')}</div>`
        : '';

    // ADetailer params
    const adetailerHtml = adetailerParams.length > 0
        ? `<div class="mm-image-adetailer">ADetailer: ${adetailerParams.join(', ')}</div>`
        : '';

    // NSFW indicator
    const nsfwLevel = nsfwBadgeLabel(img, img.nsfw || img.nsfwLevel || '');
    const nsfwClass = nsfwLevel && nsfwLevel !== 'None' && nsfwLevel !== 'Soft'
        ? 'mm-nsfw-indicator'
        : '';

    // Render media element (image or video)
    const mediaHtml = isVideo
        ? `<video data-src="${escapeHtml(src)}" class="mm-lazy-media" preload="none" controls loop muted
                  onclick="event.stopPropagation()"
                  title="Click to play"></video>`
        : `<img data-src="${escapeHtml(src || IMAGE_PLACEHOLDER_SVG)}" class="mm-lazy-media" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Example image" loading="lazy"
                onerror="this.onerror=null; this.src='${IMAGE_PLACEHOLDER_SVG}'"
                ${src ? `data-open-url="${escapeHtml(src)}"` : ''}
                title="Click to view full size">`;

    return `
        <div class="mm-image-card" data-index="${index}">
            <div class="mm-image-left">
                ${mediaHtml}
                ${nsfwClass ? `<span class="mm-nsfw-badge">${escapeHtml(String(nsfwLevel))}</span>` : ''}
            </div>
            <div class="mm-image-right">
                ${imageIdHtml}
                ${resourcesHtml}
                ${promptHtml}
                ${negPromptHtml}
                ${genParamsHtml}
                ${hiresHtml}
                ${adetailerHtml}
                <div class="mm-image-actions">
                    <button class="mm-btn secondary" data-copy="${escapeHtml(prompt)}">
                        Copy Prompt
                    </button>
                    <button class="mm-btn secondary" onclick="window.cbShowImageMeta(${index})">
                        Show All
                    </button>
                    ${img.id ? `<a class="mm-btn secondary" href="https://civitai.com/images/${safeId(img.id)}" target="_blank">View on Civitai</a>` : ''}
                    ${(civitaiResources.length > 0 || resources.length > 0) ? `<button class="mm-btn secondary" onclick="window.cbShowResources(${index})">Resources (${civitaiResources.length + resources.length})</button>` : ''}
                </div>
            </div>
        </div>
    `;
}

// Render a single resource (LoRA, VAE, etc)

// Split sampler/scheduler if combined
function splitSamplerScheduler(sampler) {
    if (!sampler) return { sampler: '', scheduler: '' };

    const schedulers = ['Karras', 'Exponential', 'SGM Uniform', 'Simple', 'Normal', 'Beta'];
    for (const sched of schedulers) {
        if (sampler.includes(sched)) {
            return {
                sampler: sampler.replace(sched, '').trim(),
                scheduler: sched
            };
        }
    }
    return { sampler, scheduler: '' };
}

// Show image metadata modal
window.cbShowImageMeta = function(index) {
    const img = currentImages[index];
    if (!img) return;

    const meta = img.meta || {};
    const metaStr = JSON.stringify(meta, null, 2);

    // Create modal
    const modal = document.createElement('div');
    modal.className = 'mm-modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `
        <div class="mm-modal">
            <div class="mm-modal-header">
                <h3>Image Metadata</h3>
                <button class="mm-modal-close" onclick="this.closest('.mm-modal-overlay').remove()">×</button>
            </div>
            <div class="mm-modal-body">
                <pre class="mm-meta-content">${escapeHtml(metaStr)}</pre>
            </div>
            <div class="mm-modal-footer">
                <button class="mm-btn secondary" data-copy="${escapeHtml(metaStr)}">Copy JSON</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
};

// Show resources modal
window.cbShowResources = function(index) {
    const img = currentImages[index];
    if (!img) return;

    const meta = img.meta || {};
    const resources = meta.resources || [];
    const civitaiResources = meta.civitaiResources || [];
    const allResources = [...resources, ...civitaiResources];

    const resourcesHtml = allResources.map(r => `
        <div class="mm-resource-item">
            <span class="mm-resource-type-label">${escapeHtml(r.type || 'Unknown')}</span>
            <span class="mm-resource-name-label">${escapeHtml(r.name || 'Unknown')}</span>
            ${r.weight !== undefined ? `<span class="mm-resource-weight">Weight: ${escapeHtml(String(r.weight))}</span>` : ''}
            ${r.modelVersionId ? `<a class="mm-btn secondary small" href="https://civitai.com/models/${safeId(r.modelId)}?modelVersionId=${safeId(r.modelVersionId)}" target="_blank">View</a>` : ''}
        </div>
    `).join('');

    // Create modal
    const modal = document.createElement('div');
    modal.className = 'mm-modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `
        <div class="mm-modal">
            <div class="mm-modal-header">
                <h3>Resources (${allResources.length})</h3>
                <button class="mm-modal-close" onclick="this.closest('.mm-modal-overlay').remove()">×</button>
            </div>
            <div class="mm-modal-body">
                <div class="mm-resources-list">${resourcesHtml || '<p>No resources found</p>'}</div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
};

// Start download. The list and its panel are shared with the Model
// Manager: see downloads() in shared/common.mjs.
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
    syncCheckpointTypeEnabled();
    console.log(`[CivitaiBrowser] Loaded ${result.model_types.length} model types, `
                + `${result.base_models.length} base models from Civitai`);
    return true;
}

// Initialize tag input
// Trained/Merge only applies to checkpoints, so grey it out otherwise
// rather than letting it silently do nothing.
function syncCheckpointTypeEnabled() {
    const typeSelect = document.getElementById('cb_type');
    const checkpointType = document.getElementById('cb_checkpoint_type');
    if (!typeSelect || !checkpointType) return;

    const applies = typeSelect.value === 'Checkpoint';
    checkpointType.disabled = !applies;
    checkpointType.title = applies
        ? 'Show only trained checkpoints or only merges'
        : 'Only applies when Type is Checkpoint';
    checkpointType.closest('.filter-group')?.classList.toggle('cb-filter-disabled', !applies);
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
        } else if (e.key === 'Escape') {
            tagSuggestions = [];
            renderTagDropdown();
        }
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
        typeSelect.addEventListener('change', syncCheckpointTypeEnabled);
    }
    syncCheckpointTypeEnabled();

    document.getElementById('cb_nsfw')?.addEventListener('change', syncSfwOnlyEnabled);
    document.getElementById('cb_sfw_only')?.addEventListener('change', syncSfwOnlyEnabled);
    syncSfwOnlyEnabled();
    loadNsfwDetection().then(syncSfwOnlyEnabled);

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

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            // Close tag dropdown first
            tagSuggestions = [];
            renderTagDropdown();

            // Close any open modals
            const modal = document.querySelector('.mm-modal-overlay');
            if (modal) {
                modal.remove();
            } else {
                closeDetails();
            }
        }
    });

    console.log('[CivitaiBrowser] Ready');
}

// Expose functions to window for inline handlers
window.cbSearch = function() {
    initTagInput();
    loadEnums();
    commitTypedTag();
    // A search starts at page 1 with only the pages it has been to: a
    // filtered page's cursor holds what the filters found then, not now.
    cursors = [""];
    hasMorePages = true;
    searchModels(1);
};
window.cbPrevPage = function() {
    if (currentPage > 1) {
        searchModels(currentPage - 1);
    }
};
window.cbNextPage = function() {
    // Can go next if there are more pages AND we have a cursor for it
    if (hasMorePages && cursors[currentPage]) {
        searchModels(currentPage + 1);
    }
};
window.cbGoToPage = function(page) {
    // Can navigate to any page we have a cursor for
    if (page >= 1 && page <= cursors.length && page !== currentPage) {
        searchModels(page);
    }
};
window.cbOpenModel = openModel;
window.cbCloseDetails = closeDetails;
window.cbSelectVersion = selectVersion;
window.cbSelectFile = selectFile;
// Show a model here, asked for from the Model Manager tab. The mirror of
// cbShowInModelManager() below, and of mmShowModel() over there.
window.cbShowModel = async function(query) {
    const search = document.getElementById('cb_search');
    if (search) search.value = query;

    // A targeted lookup ignores them, but leaving them set would be confusing
    // the moment the next search is run.
    const nsfw = document.getElementById('cb_nsfw');
    if (nsfw) nsfw.checked = true;
    syncSfwOnlyEnabled();
    const requirePrompt = document.getElementById('cb_require_prompt');
    if (requirePrompt) requirePrompt.checked = false;

    await searchModels(1);
};

// Open this model over in the Model Manager tab
window.cbShowInModelManager = function(modelId) {
    if (typeof window.mmShowModel !== 'function') {
        updateStatus('Model Manager tab has not initialised yet - open it once and try again.');
        return;
    }

    const root = (typeof gradioApp === 'function') ? gradioApp() : document;
    const tabs = root.querySelector('#tabs');
    const tabButton = tabs && Array.from(tabs.querySelectorAll('button'))
        .find(b => b.textContent.trim() === 'Model Manager');

    if (tabButton) {
        tabButton.click();
    } else {
        console.warn('[CivitaiBrowser] Could not find the Model Manager tab button');
    }

    // The grid sizes itself from the viewport, so let the tab become
    // visible before loading - measuring a hidden tab gives nonsense
    setTimeout(() => window.mmShowModel('model:' + modelId), 100);
};

window.cbDownload = startDownload;
window.cbLoadMoreImages = loadMoreImages;

// Initialize when ready
onReady(init);
