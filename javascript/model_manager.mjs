/**
 * Model Manager JavaScript
 * Handles API calls, grid rendering, and UI interactions.
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
// one URL and runs once, not once per tab. Without an answer, this script's
// own version, as before. A dynamic import is the only way to build that URL
// at runtime, which is why this is not a plain import statement.
window.mmSharedVersion ||= fetch('/model-manager/asset-version', { cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((body) => (/^\d+$/.test(String(body?.version ?? '')) ? `?v=${body.version}` : null))
    .catch(() => null);
const sharedVersion = (await window.mmSharedVersion) || new URL(import.meta.url).search;
const shared = (name) => import(new URL(`./shared/${name}${sharedVersion}`, import.meta.url).href);

// Asked for all at once, then taken one by one below. Awaited in turn, each
// module waited a round trip of its own before the next was asked for. An
// import of a URL already asked for is the same module, so the awaits find
// them on their way. A failure still stops the tab at its await; the catch
// here only keeps it from being reported twice.
const SHARED_MODULES = ['core.mjs', 'calls.mjs', 'tabs.mjs', 'ui_options.mjs', 'notes.mjs', 'filters.mjs',
    'gallery.mjs', 'grid.mjs', 'media.mjs', 'nsfw.mjs', 'chips.mjs', 'wan.mjs', 'your_generations.mjs',
    'downloads.mjs', 'image_card.mjs', 'resources.mjs', 'samplers.mjs', 'send.mjs', 'update_notice.mjs',
    'viewer.mjs', 'settings.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const {
    onReady, apiCall, escapeHtml, safeId, sanitizeHtml, formatNumber, formatBytes, formatDay, setText, TIMING,
} = await shared('core.mjs');
const { provide, ready, call } = await shared('calls.mjs');
const { showTab } = await shared('tabs.mjs');
const {
    showApiKeyBanner, generationsEnabled, loadNsfwDetection, nsfwModelNote, refreshUiOptions,
} = await shared('ui_options.mjs');
const { showNotes } = await shared('notes.mjs');
const { savedSearch, saveSearch, sortBaseModels, sizeBound } = await shared('filters.mjs');
const {
    showGalleryLoading, dimGalleryWhileLoading, pageSeparator, pageNoteHtml, renderFilterBanner,
    createPagedGallery,
} = await shared('gallery.mjs');
const {
    renderThumbs, balanceGridRows, applyCardSize: sharedApplyCardSize, renderModelCard, renderGridPagination,
    renderModelGrid: renderSharedGrid,
} = await shared('grid.mjs');
const {
    isVideoUrl, cardMediaUrl, originalMediaUrl, viewerVideoUrl, mediaFallback, IMAGE_PLACEHOLDER_SVG,
    galleryImageWidth, setupLazyMedia,
} = await shared('media.mjs');
const { nsfwBadgeLabel } = await shared('nsfw.mjs');
const {
    selectBarHtml, bulkDeleteQuestion, deleteManyGenerations, bulkDeleteReport, ratingRowHtml,
} = await shared('your_generations.mjs');
const {
    paidAccessLabel, isPaid, primaryFileIndex, renderDownloadControls, showChosenFile, downloads,
} = await shared('downloads.mjs');
const { renderImageCard: sharedImageCard, showImageMeta, imageTextHtml } = await shared('image_card.mjs');
const { showImageResources, resourceButtonLabel, learnResourceHashes } = await shared('resources.mjs');
const { sendInfotext, sendTab, sendGalleryImage } = await shared('send.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The image viewer every gallery opens.
const {
    openViewer, closeViewer, showImage, viewerIndex, askToDelete, cardSource, viewerPageScroll,
} = await shared('viewer.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// The download controls' ids, and the window functions they call
// (renderDownloadControls in shared/downloads.mjs).
const DOWNLOAD_CONTROLS = { prefix: 'mm', download: 'mmDownload', selectFile: 'mmSelectFile' };

// State
let currentModels = [];
let selectedModelIndex = null;
let isLoading = false;

// Version grouping state
let currentVersions = [];  // All versions for currently selected model
let selectedVersionIndex = 0;  // Currently selected version within the group
// Every version Civitai lists for the model, local or not, as last recorded -
// each with `local`. currentVersions stays the local ones: everything that
// sends, deletes or shows a gallery works on a file.
let civitaiVersions = [];
let versionsSyncedAt = null;   // when Civitai listed them; null when read from sidecars
let pillEntries = [];          // the version pills, in order: see versionPills()
let remoteVersionId = null;    // the version shown, when it is not in the library
let remoteFileIndex = null;    // its file picked for download; null = the primary
let modelDescription = '';     // the open model's, for a version with no gallery to load

// Pagination state
let currentPage = 1;
let totalPages = 1;
let totalModels = 0;
let pageSize = 0;  // the server's, from the Models per page setting

// Card sizing (default values, updated from API)
let cardWidth = 200;
let cardHeight = 280;

// Track if preview_least_nsfw checkbox has been initialized from setting
let previewLeastNsfwInitialized = false;
let previewLeastNsfwUserTouched = false;
let filterDefaultsPromise = null;

// Apply card size from API response
function applyCardSize(width, height) {
    if (width && height && (width !== cardWidth || height !== cardHeight)) {
        cardWidth = width;
        cardHeight = height;
        sharedApplyCardSize({
            width, height,
            containerId: 'model_manager_app',
            logTag: 'ModelManager',
        });
    }
}


// Sync state
let isSyncing = false;
let syncPollInterval = null;

// Scan state
let isScanning = false;
let scanPollInterval = null;

// Image gallery state
let currentVersionId = null;
let currentModelPath = null;
// Whether the gallery is hiding images with no prompt worth reading. Filtered
// in SQL, like the NSFW one, so the counts come from the same place the images
// do rather than from whatever happens to be loaded.
let hidePromptlessImages = true;
let hidePromptlessInitialised = false;
// What each gallery switch is acting on right now: how many images it hides,
// or while it is ticked, how many it is showing - counted among the images the
// other switch lets through. The banner and the switch both state this one
// number, so they cannot disagree. It comes from the server, because the
// filtering happens there and a hidden image never reaches the page.
let nsfwImageCount = 0;
let promptlessImageCount = 0;
// The images the prompt filter alone is hiding right now - the other half of
// the banner's "hidden due to" split - and those both filters hide, counted in
// neither, so each switch's number stays put when it is flipped.
let hiddenPromptlessCount = 0;
let hiddenByBothCount = 0;
// Every image with an unusable prompt: the number on the prompt switch.
let promptlessImageTotal = null;
// The gallery is a list of pages, each a slice of what is stored, in gallery
// order, before the switches filter it - see model_manager/gallery.py. Load
// more adds the next. Its images and pages are imageGallery's (shared/gallery.mjs).
const imageGallery = createPagedGallery({
    containerId: 'mm_images', bannerClass: 'mm-nsfw-warning', loadMoreId: 'mm_load_more_btn',
    loadMoreCall: 'mmLoadMoreImages', card: (img, index) => renderImageCard(img, index),
    bannerHtml: () => imagesBannerHtml(), showing: () => galleryTab === 'civitai',
    redraw: () => renderModelImages(), afterDraw: () => refreshResourceButtons(),
});
let filteredImageCount = 0;
// Each fetch of the gallery takes a number; an answer to anything but the
// latest is dropped, so a slow page cannot land over a newer one.
let imagesRequest = 0;

// The gallery's two tabs: the version's example images from Civitai, and your
// own generations with the model. Each model opens on Civitai's. The
// generations are a page of cards, one per generation, fetched when the tab
// is first opened - see model_manager/api/generations.py.
let galleryTab = 'civitai';
let generationsCount = 0;       // for the tab's label, from the details
let generationCards = [];       // the cards drawn, every page's in turn
let generationPages = [];       // each page loaded: its number, first card, counts
let generationsState = null;    // the server's totals; null until the tab loads
let loadingGenerationPage = false;
let generationPageError = '';   // why the last page asked for did not come
let generationsRequest = 0;

// NSFW image filtering state
let hideNsfwImages = true;  // Default to hide, will be set from setting on first load
let hideNsfwImagesInitialized = false;
let totalImageCount = 0;
let hiddenImageCount = 0;

function scrollToModelImagesTop() {
    return new Promise((resolve) => {
        const container = document.getElementById('mm_images');
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

// NSFW level order for "use max" mode
const NSFW_LEVEL_ORDER = ['PG', 'PG-13', 'R', 'X', 'XXX', 'Blocked', 'Unknown'];

// Get current filter values
/**
 * Trained or merged is a question only checkpoints answer.
 *
 * Disabled rather than hidden, so the filter bar keeps its shape and the
 * control explains itself when it cannot be used.
 */
function syncCheckpointTypeEnabled() {
    const typeSelect = document.getElementById('mm_type');
    const checkpointType = document.getElementById('mm_checkpoint_type');
    if (!typeSelect || !checkpointType) return;

    const applies = typeSelect.value === 'Checkpoint';
    checkpointType.disabled = !applies;
    checkpointType.title = applies
        ? 'Show only trained checkpoints, or only merges'
        : 'Only applies when Type is Checkpoint';
    checkpointType.closest('.filter-group')?.classList.toggle('mm-filter-disabled', !applies);
}

// The checkbox asks to SHOW NSFW in the preview; the API asks for the LEAST
// NSFW image to be used as the preview. Those are opposites, and the backend
// name stays as it is because it describes which stored column is read
// (preview_url_least_nsfw or preview_url_recent). Converting in these two
// places means the inversion cannot be applied to some call sites and not
// others - which is the only way a filter like this goes wrong.
function previewLeastNsfwFromCheckbox() {
    const checkbox = document.getElementById('mm_preview_show_nsfw');
    return checkbox ? !checkbox.checked : null;
}

function setPreviewCheckboxFrom(previewLeastNsfw) {
    const checkbox = document.getElementById('mm_preview_show_nsfw');
    if (checkbox) checkbox.checked = !previewLeastNsfw;
    return Boolean(checkbox);
}

// After the settings window saved: redo what this tab drew from the settings.
// The grid's page size, card size and thumbnails come with the grid, so it is
// asked for again; the gallery reads its settings each time a model opens.
const GRID_SETTINGS = ['model_manager_page_size', 'model_manager_card_size',
                       'model_manager_preview_least_nsfw'];
window.addEventListener('mm-settings-saved', (e) => {
    const changed = e.detail?.changed || [];
    refreshUiOptions();
    if (changed.includes('model_manager_preview_least_nsfw')) {
        setPreviewCheckboxFrom(e.detail.settings.model_manager_preview_least_nsfw.value);
        previewLeastNsfwInitialized = true;
        previewLeastNsfwUserTouched = false;
    }
    if (currentModels.length && GRID_SETTINGS.some((key) => changed.includes(key))) {
        loadModels(changed.includes('model_manager_page_size') ? 1 : currentPage);
    }
});

// The settings window's card preview: this tab's own cards, at a size not yet
// saved. From the page already loaded when it has enough, else exactly as
// many as the preview asks for.
let cardPreviewModels = [];
async function cardPreview(count) {
    let models = currentModels;
    if (models.length < count) {
        if (cardPreviewModels.length < count) {
            const data = await apiCall({ endpoint: '/model-manager/models',
                                         params: { page: 1, page_size: count } });
            if (!data.success) throw new Error(data.error || 'the library did not answer');
            cardPreviewModels = data.models || [];
        }
        models = cardPreviewModels;
    }
    return models.slice(0, count).map((model, index) => mmCard(model, index)).join('');
}
provide('cardPreview.model_manager_card_size', cardPreview);

function getFilters() {
    const useMax = document.getElementById('mm_nsfw_use_max')?.checked || false;
    const checkboxes = document.querySelectorAll('#mm_nsfw_panel input[type="checkbox"][value]');
    const selectedLevels = [];

    checkboxes.forEach(cb => {
        if (cb.checked) selectedLevels.push(cb.value);
    });

    let nsfwFilter = {};
    if (useMax && selectedLevels.length > 0) {
        // Max mode: get highest selected level (NSFW_LEVEL_ORDER is pre-sorted)
        const maxLevel = NSFW_LEVEL_ORDER.filter(level => selectedLevels.includes(level)).pop();
        if (maxLevel) {
            nsfwFilter.nsfw_levels = maxLevel;
            nsfwFilter.nsfw_mode = 'max';
        }
    } else if (selectedLevels.length > 0) {
        // Contains mode: send all selected levels
        nsfwFilter.nsfw_levels = selectedLevels.join(',');
        nsfwFilter.nsfw_mode = 'contains';
    }

    console.log('[ModelManager] NSFW mode:', nsfwFilter.nsfw_mode, 'levels:', nsfwFilter.nsfw_levels);

    // Handle is_bookmarked filter
    const bookmarkedVal = document.getElementById('mm_is_bookmarked')?.value || '';
    const bookmarkedFilter = bookmarkedVal === 'true' ? { is_bookmarked: true } : {};

    // Handle the NSFW preview checkbox
    const previewLeastNsfwCheckbox = document.getElementById('mm_preview_show_nsfw');
    const shouldSendPreviewFilter = previewLeastNsfwCheckbox && (previewLeastNsfwInitialized || previewLeastNsfwUserTouched);
    const previewLeastNsfwFilter = shouldSendPreviewFilter
        ? { preview_least_nsfw: previewLeastNsfwFromCheckbox() }
        : {};

    // Handle license filters
    // Commercial use is now multi-select checkboxes - only filter if not all selected
    const commercialCheckboxes = document.querySelectorAll('#mm_commercial_panel input[type="checkbox"][value]');
    const selectedCommercial = [];
    commercialCheckboxes.forEach(cb => {
        if (cb.checked) selectedCommercial.push(cb.value);
    });
    // Don't filter if all 5 selected or none selected
    const commercialFilter = (selectedCommercial.length > 0 && selectedCommercial.length < 5)
        ? { commercial_use: selectedCommercial.join(',') }
        : {};

    // Allow Derivatives: both checked = no filter, one checked = filter for that value
    // Licence filters are four-valued: '' asks nothing, 'unknown' asks for
    // the models with no Civitai data, which have no licence to read.
    // Only checkpoints have one, and the control is disabled otherwise, so
    // reading it while it is disabled would send a filter the user cannot see.
    const checkpointTypeEl = document.getElementById('mm_checkpoint_type');
    const checkpointTypeFilter = (checkpointTypeEl && !checkpointTypeEl.disabled
                                  && checkpointTypeEl.value)
        ? { checkpoint_type: checkpointTypeEl.value }
        : {};

    const derivatives = document.getElementById('mm_allow_derivatives')?.value || '';
    const derivativesFilter = derivatives ? { allow_derivatives: derivatives } : {};

    const diffLicense = document.getElementById('mm_allow_different_license')?.value || '';
    const diffLicenseFilter = diffLicense ? { allow_different_license: diffLicense } : {};

    const sfwOnlyFilter = document.getElementById('mm_sfw_only')?.checked
        ? { sfw_only: true }
        : {};

    const filters = {
        search: document.getElementById('mm_search')?.value || '',
        type: document.getElementById('mm_type')?.value || '',
        base_model: document.getElementById('mm_base_model')?.value || '',
        ...nsfwFilter,
        ...sfwOnlyFilter,
        has_civitai: document.getElementById('mm_civitai')?.value || '',
        ...bookmarkedFilter,
        min_versions: document.getElementById('mm_min_versions')?.value || '',
        min_size_gb: sizeBound('mm_min_size'),
        max_size_gb: sizeBound('mm_max_size'),
        ...previewLeastNsfwFilter,
        ...checkpointTypeFilter,
        ...commercialFilter,
        ...derivativesFilter,
        ...diffLicenseFilter,
        sort_by: document.getElementById('mm_sort_by')?.value || 'name',
        sort_order: document.getElementById('mm_sort_order')?.value || 'asc',
    };
    console.log('[ModelManager] Filters:', filters);
    return filters;
}

// Toggle NSFW dropdown
window.mmToggleNsfwDropdown = function() {
    const panel = document.getElementById('mm_nsfw_panel');
    if (panel) panel.classList.toggle('open');
};

// Toggle Commercial Use dropdown
window.mmToggleCommercialDropdown = function() {
    const panel = document.getElementById('mm_commercial_panel');
    if (panel) panel.classList.toggle('open');
};

// Update NSFW display text
function updateNsfwDisplay() {
    const display = document.getElementById('mm_nsfw_display');
    const useMax = document.getElementById('mm_nsfw_use_max')?.checked || false;
    const checkboxes = document.querySelectorAll('#mm_nsfw_panel input[type="checkbox"][value]');
    const selected = [];

    checkboxes.forEach(cb => {
        if (cb.checked) selected.push(cb.value);
    });

    if (useMax && selected.length > 0) {
        // Find highest level
        let maxIndex = -1;
        selected.forEach(level => {
            const idx = NSFW_LEVEL_ORDER.indexOf(level);
            if (idx > maxIndex) maxIndex = idx;
        });
        display.textContent = maxIndex >= 0 ? `Max: ${NSFW_LEVEL_ORDER[maxIndex]}` : 'None';
    } else {
        display.textContent = selected.length > 0 ? selected.join(', ') : 'None';
    }
}

// Update Commercial Use display text
function updateCommercialDisplay() {
    const display = document.getElementById('mm_commercial_display');
    const checkboxes = document.querySelectorAll('#mm_commercial_panel input[type="checkbox"][value]');
    const selected = [];

    checkboxes.forEach(cb => {
        if (cb.checked) selected.push(cb.value);
    });

    // Show "All" if all 5 options are selected or none selected
    if (selected.length === 5 || selected.length === 0) {
        display.textContent = 'All';
    } else {
        display.textContent = selected.join(', ');
    }
}

// Setup Commercial Use controls
function setupCommercialControls() {
    const checkboxes = document.querySelectorAll('#mm_commercial_panel input[type="checkbox"][value]');

    checkboxes.forEach(cb => {
        cb.addEventListener('change', updateCommercialDisplay);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const dropdown = document.getElementById('mm_commercial_dropdown');
        const panel = document.getElementById('mm_commercial_panel');
        if (dropdown && panel && !dropdown.contains(e.target)) {
            panel.classList.remove('open');
        }
    });
}

// Handle "Use max" checkbox toggle and level selection
function setupNsfwControls() {
    const useMaxCb = document.getElementById('mm_nsfw_use_max');
    const levelCheckboxes = document.querySelectorAll('#mm_nsfw_panel input[type="checkbox"][value]');

    if (!useMaxCb) return;

    // When "Use max" changes, update display
    useMaxCb.addEventListener('change', updateNsfwDisplay);

    // When a level checkbox changes
    levelCheckboxes.forEach(cb => {
        cb.addEventListener('change', (e) => {
            const useMax = useMaxCb.checked;

            if (useMax) {
                // In max mode: clicking a level always sets it as max
                const clickedLevel = e.target.value;
                const clickedIndex = NSFW_LEVEL_ORDER.indexOf(clickedLevel);

                // Use setTimeout to override after the default toggle
                setTimeout(() => {
                    levelCheckboxes.forEach(otherCb => {
                        const otherIndex = NSFW_LEVEL_ORDER.indexOf(otherCb.value);
                        otherCb.checked = otherIndex <= clickedIndex;
                    });
                    updateNsfwDisplay();
                }, 0);
            } else {
                updateNsfwDisplay();
            }
        });
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const dropdown = document.getElementById('mm_nsfw_dropdown');
        const panel = document.getElementById('mm_nsfw_panel');
        if (dropdown && panel && !dropdown.contains(e.target)) {
            panel.classList.remove('open');
        }
    });
}

// Set status message
function setStatus(message, isError = false) {
    const statusEl = document.getElementById('mm_status');
    if (statusEl) {
        statusEl.textContent = message;
        statusEl.className = 'model-manager-status' + (isError ? ' error' : '');
    }
}

// Load models from API
async function loadModels(page = 1) {
    if (isLoading) return;

    isLoading = true;
    setStatus('Loading models...');

    const loadBtn = document.getElementById('mm_load_btn');
    if (loadBtn) loadBtn.disabled = true;

    try {
        // The preview checkbox's default has to be in place before the
        // first load reads it, and the saved search's filters.
        await ensureFilterDefaults();
        await savedFiltersReady;

        // No page_size: the server uses the Models per page setting.
        const filters = getFilters();
        filters.page = page;
        filters.pinned = gridTab === 'pinned';
        const data = await apiCall({ endpoint: '/model-manager/models', params: filters });

        if (data.success) {
            // Apply card size from API response
            if (data.card_width && data.card_height) {
                applyCardSize(data.card_width, data.card_height);
            }

            // Initialize preview_least_nsfw checkbox from setting on first load
            if (!previewLeastNsfwInitialized && data.preview_least_nsfw_setting !== undefined) {
                if (setPreviewCheckboxFrom(data.preview_least_nsfw_setting)) {
                    console.log(`[ModelManager] Initialized NSFW preview checkbox from setting `
                        + `preview_least_nsfw=${data.preview_least_nsfw_setting}`);
                }
                previewLeastNsfwInitialized = true;
            }

            currentModels = data.models;
            currentPage = data.page || 1;
            pageSize = data.page_size || data.models.length || 1;
            totalModels = data.total || 0;
            totalPages = Math.max(1, Math.ceil(totalModels / pageSize));

            gridTabCounts = data.tab_counts || null;
            gridLoaded = true;
            updateGridTabs();
            renderModelGrid(data.models);
            updatePaginationStatus();
        } else {
            setStatus('Error: ' + (data.error || 'Unknown error'), true);
        }
    } catch (error) {
        console.error('[ModelManager] Load error:', error);
        setStatus('Error loading models: ' + error.message, true);
    } finally {
        isLoading = false;
        if (loadBtn) loadBtn.disabled = false;
    }
}

async function ensureFilterDefaults() {
    if (filterDefaultsPromise) {
        await filterDefaultsPromise;
        return;
    }

    filterDefaultsPromise = (async () => {
        try {
            const data = await apiCall({ endpoint: '/model-manager/filter-defaults' });
            if (data.success) {
                if (data.card_width && data.card_height) {
                    applyCardSize(Number(data.card_width), Number(data.card_height));
                }

                if (!previewLeastNsfwInitialized && !previewLeastNsfwUserTouched && data.preview_least_nsfw !== undefined) {
                    if (setPreviewCheckboxFrom(data.preview_least_nsfw)) {
                        previewLeastNsfwInitialized = true;
                        console.log(`[ModelManager] Initialized NSFW preview default: `
                            + `preview_least_nsfw=${Boolean(data.preview_least_nsfw)}`);
                    }
                }
            }
        } catch (e) {
            console.warn('[ModelManager] Failed to load filter defaults:', e);
        }
    })();

    await filterDefaultsPromise;
}

// Update status with pagination info
function updatePaginationStatus() {
    const start = (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, totalModels);
    setStatus(`Showing ${start}-${end} of ${totalModels} models (Page ${currentPage}/${totalPages})`);
}

// Navigate to previous page
window.mmPrevPage = function() {
    if (currentPage > 1 && !isLoading) {
        loadModels(currentPage - 1);
    }
};

// Navigate to next page
window.mmNextPage = function() {
    if (currentPage < totalPages && !isLoading) {
        loadModels(currentPage + 1);
    }
};

// Navigate to specific page
window.mmGoToPage = function(page) {
    if (page >= 1 && page <= totalPages && page !== currentPage && !isLoading) {
        loadModels(page);
    }
};

// NSFW level -> the card's class, by the integer bitmask (1=PG, 2=PG-13,
// 4=R, 8=X, 16=XXX); PG has none.
function nsfwCardClass(level) {
    if (level >= 16) return 'nsfw-xxx';
    if (level >= 8) return 'nsfw-x';
    if (level >= 4) return 'nsfw-r';
    if (level >= 2) return 'nsfw-pg13';
    return '';
}

/**
 * A library model as a card: what renderModelCard() is to show. The preview
 * was chosen by the server, by the card thumbnail setting.
 */
function mmCard(model, index) {
    const src = cardMediaUrl(model.preview_url, null, cardWidth);
    const versions = model.local_version_count || 1;
    return renderModelCard({
        index,
        onclick: `window.mmSelectModel(${index})`,
        name: model.display_name,
        media: { src, video: isVideoUrl({ url: src }), original: originalMediaUrl(model.preview_url) },
        classes: [model.has_civitai_data ? 'has-civitai' : 'no-civitai', nsfwCardClass(model.nsfw_level || 1)],
        data: { 'model-id': model.civitai_model_id || '' },
        overlays: [
            ...(model.has_civitai_data ? [] : [{ cls: 'no-data-overlay', text: 'No Civitai Data' }]),
            ...(model.is_bookmarked ? [{ cls: 'mm-bookmark-indicator', text: '★', title: 'Bookmarked' }] : []),
            pinButton(model, index, 'mm-pin-btn'),
        ],
        badges: [
            { cls: 'type-badge', text: model.model_type || 'Unknown' },
            ...(model.base_model ? [{ cls: 'base-model', text: model.base_model }] : []),
            // Only when several versions are on disk.
            ...(versions > 1 ? [{ cls: 'versions-badge', text: `v${versions}`, title: `${versions} local versions` }] : []),
        ],
        stats: [
            { text: formatFileSize(model.file_size) },
            // Civitai retired star ratings; thumbs are what it reports now.
            { html: renderThumbs(model.thumbs_up, model.thumbs_down) },
            ...(model.download_count > 0 ? [{ text: `↓ ${formatNumber(model.download_count)}`, title: 'Downloads' }] : []),
        ],
    });
}

// ---------------------------------------------------------------- grid tabs
// The grid's two tabs: the pinned models, and the rest. The page opens on
// Unpinned; the search and filters apply to both, and each tab says how many
// match them. A card pinned or unpinned stays where it is until the grid
// loads again, as pinning always has; the counts follow at once. A tab
// changes what the loaded grid shows: before Load Models it loads nothing.
let gridTab = 'others';
// Filled from the saved search, once bindElements() has asked for it.
let savedFiltersReady = Promise.resolve(false);
let gridTabCounts = null;
let gridLoaded = false;

function updateGridTabs() {
    document.querySelectorAll('#mm_grid_tabs [data-grid-tab]').forEach((tab) => {
        const which = tab.dataset.gridTab;
        tab.classList.toggle('active', which === gridTab);
        tab.setAttribute('aria-selected', String(which === gridTab));
        const count = tab.querySelector('[data-grid-count]');
        if (count) count.textContent = gridTabCounts ? `(${Number(gridTabCounts[which] ?? 0).toLocaleString()})` : '';
    });
}

document.addEventListener('click', (event) => {
    const tab = event.target.closest?.('#mm_grid_tabs [data-grid-tab]');
    if (!tab || tab.dataset.gridTab === gridTab || isLoading) return;
    gridTab = tab.dataset.gridTab;
    updateGridTabs();
    if (gridLoaded) loadModels(1);
});

// Render model grid
function renderModelGrid(models) {
    renderSharedGrid({
        gridId: 'mm_grid',
        cards: (models || []).map((model, index) => mmCard(model, index)),
        empty: gridTab === 'pinned'
            ? 'No pinned models match your filters. Pin a model with the 📌 on its card to keep it in this tab.'
            : 'No models found matching your filters.',
        // The library's page count is known: the server gives the total.
        pagination: totalPages > 1 ? renderGridPagination({
            current: currentPage, last: totalPages, hasNext: currentPage < totalPages,
            goTo: 'mmGoToPage', prev: 'mmPrevPage', next: 'mmNextPage',
        }) : '',
    });
}

// Select a model
window.mmSelectModel = async function(index) {
    selectedModelIndex = index;
    const model = currentModels[index];
    if (!model) return;

    // Reset image state
    imageGallery.images = [];
    currentVersionId = null;
    currentModelPath = model.file_path;
    imageGallery.pages = [];
    filteredImageCount = 0;
    resetGenerations();
    // Each model's gallery starts from the settings; its switches then last
    // while this model is open - as in the Civitai Browser.
    hideNsfwImagesInitialized = false;
    hidePromptlessInitialised = false;
    // At once: the last model's gallery stayed up while this one's versions
    // and details were asked for, as if the click had done nothing.
    showGalleryLoading('mm_images');

    // Reset version state
    currentVersions = [];
    selectedVersionIndex = 0;
    civitaiVersions = [];
    versionsSyncedAt = null;
    remoteVersionId = null;
    remoteFileIndex = null;
    modelDescription = '';

    // Highlight selected card
    document.querySelectorAll('.model-card').forEach(card => card.classList.remove('selected'));
    const selectedCard = document.querySelector(`.model-card[data-index="${index}"]`);
    if (selectedCard) selectedCard.classList.add('selected');

    // The model's versions: the local ones when there are several, and every
    // one Civitai lists. Neither asks Civitai.
    if (model.model_id) {
        try {
            const versionsData = await apiCall({ endpoint: '/model-manager/models/versions', params: { model_id: model.model_id } });
            if (selectedModelIndex !== index) return;  // another model was opened meanwhile
            if (versionsData.success && versionsData.versions) {
                if (versionsData.versions.length > 1) {
                    currentVersions = versionsData.versions;
                    // Find current version in list (it should be there since it's the latest)
                    selectedVersionIndex = currentVersions.findIndex(v => v.file_path === model.file_path);
                    if (selectedVersionIndex < 0) selectedVersionIndex = 0;
                }
                civitaiVersions = versionsData.civitai_versions || [];
                versionsSyncedAt = versionsData.versions_synced_at || null;
                console.log(`[ModelManager] Loaded ${versionsData.versions.length} local and ${civitaiVersions.length} listed versions for model ${model.model_id}`);
            }
        } catch (error) {
            console.error('[ModelManager] Failed to load versions:', error);
        }
    }

    // Show basic details immediately (with version selector if applicable)
    renderModelDetails(model);

    // Load full details for the selected version
    await loadVersionDetails(model.file_path);
};

// Load details for a specific version
async function loadVersionDetails(filePath) {
    try {
        // Until the first answer, neither is sent: the server then goes by
        // the settings and says what it chose. Sending the defaults here
        // meant the settings were never read at all.
        const params = {
            path: filePath,
            hide_nsfw_images: hideNsfwImagesInitialized ? hideNsfwImages : undefined,
            hide_promptless_images: hidePromptlessInitialised ? hidePromptlessImages : undefined,
        };
        const request = ++imagesRequest;
        const data = await apiCall({ endpoint: '/model-manager/models/details', params });
        if (request !== imagesRequest) return;  // superseded by a newer load
        if (data.success && data.model) {
            // Store version ID for load-more
            if (data.model.civitai_version) {
                currentVersionId = data.model.civitai_version.id;
            }

            // Update description if available
            if (data.model.civitai_model?.description) {
                modelDescription = data.model.civitai_model.description;
                updateDescription(data.model.civitai_model.description);
            }

            // The gallery's totals now, its first page after: page 1 may be
            // fetched from Civitai, and the details do not wait for it.
            imageGallery.images = [];
            imageGallery.pages = [];
            const imagesState = data.model.images_state || {};
            applyImagesState(imagesState);
            generationsCount = data.model.generations_count || 0;

            if (!hidePromptlessInitialised && imagesState.hide_promptless_images !== undefined) {
                hidePromptlessImages = imagesState.hide_promptless_images;
                hidePromptlessInitialised = true;
            }

            // Initialize hideNsfwImages from setting on first load
            if (!hideNsfwImagesInitialized && imagesState.hide_nsfw_images !== undefined) {
                hideNsfwImages = imagesState.hide_nsfw_images;
                hideNsfwImagesInitialized = true;
                console.log(`[ModelManager] Initialized hideNsfwImages: ${hideNsfwImages}`);
            }

            updateImagesCountCell();
            await loadGalleryPage(1);
        } else {
            sayGalleryFailed(data.error || 'the model\'s details did not come');
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load model details:', error);
        updateImagesCountCell();  // Update even on error to show "None"
        sayGalleryFailed(error.message);
    }
}

/**
 * Take the gallery's state from the server's images_state: what Civitai has
 * left, the counts the banner states, and where the loaded images start. Every
 * page carries it, so the counts are always those of the images drawn.
 */
function applyImagesState(state) {
    currentVersionId = state.version_id || null;
    totalImageCount = state.total_count || 0;
    filteredImageCount = state.filtered_count || 0;
    hiddenImageCount = state.hidden_nsfw ?? state.hidden_count ?? 0;
    hiddenPromptlessCount = state.hidden_promptless || 0;
    hiddenByBothCount = state.hidden_both || 0;
    nsfwImageCount = state.nsfw_count || 0;
    promptlessImageCount = state.promptless_count || 0;
    promptlessImageTotal = state.promptless_total ?? null;
}

/**
 * Fetch page `number` of the open version's gallery, through its two
 * switches, and draw it: added to the list after the pages loaded - Load
 * more - or as the first, replacing them. The server fills a page the
 * library cannot from Civitai first, so this can wait on Civitai.
 *
 * @returns {Promise<boolean>} whether the page arrived and was drawn
 */
async function loadGalleryPage(number, { append = false } = {}) {
    const versionId = currentVersionId;
    if (!versionId) {
        renderModelImages();
        return false;
    }
    const request = ++imagesRequest;
    try {
        const data = await apiCall({ endpoint: '/model-manager/images/gallery-page', params: {
            version_id: versionId, page: number,
            hide_nsfw_images: hideNsfwImages, hide_promptless_images: hidePromptlessImages,
        } });
        if (request !== imagesRequest || versionId !== currentVersionId) return false;
        if (!data.success) {
            console.error('[ModelManager] Failed to load images:', data.error);
            if (append) imageGallery.error = `Page ${number} could not be loaded: ${data.error || 'no answer'}`;
            else sayGalleryFailed(data.error || 'no answer');
            return false;
        }
        imageGallery.error = '';
        applyImagesState(data.images_state || {});
        const { page, images } = imageGallery.take(data, { append, number });
        if (append) imageGallery.append(page, images);
        else renderModelImages();
        updateImagesCountCell();
        return true;
    } catch (error) {
        console.error('[ModelManager] Failed to load images:', error);
        if (append) imageGallery.error = `Page ${number} could not be loaded: ${error.message}`;
        else sayGalleryFailed(error.message);
        return false;
    }
}

/** A first page that did not come: said in the gallery - it used to be the console's alone. */
function sayGalleryFailed(why) {
    dimGalleryWhileLoading('mm_images', false);
    const container = document.getElementById('mm_images');
    container?.querySelector(':scope > .mm-loading-bar')?.remove();
    container?.querySelector(':scope > .mm-images-loading')?.remove();
    container?.insertAdjacentHTML('afterbegin',
        `<div class="mm-images-error">The images could not be loaded: ${escapeHtml(why)}</div>`);
}

/**
 * A gallery switch changed: the version's details and first page again,
 * the images meanwhile dimmed under the bar - it used to show nothing until
 * they came.
 */
async function reloadGalleryForSwitch() {
    if (!currentModelPath) return;
    dimGalleryWhileLoading('mm_images', true);
    try {
        await loadVersionDetails(currentModelPath);
        await scrollToModelImagesTop();
        if (galleryTab === 'generations') await loadGenerationsPage(1);
    } finally {
        dimGalleryWhileLoading('mm_images', false);
    }
}

// The no-prompt switch. It reads "Show images without prompts", as the Civitai
// Browser's does, while the server is still asked whether to *hide* them -
// hide_promptless_images. This is the one place the two meet. It reloads,
// because the filtering is done in SQL: the hidden images are not in the page
// to be revealed.
window.mmToggleShowPromptless = async function(showPromptless) {
    hidePromptlessImages = !showPromptless;
    hidePromptlessInitialised = true;
    await reloadGalleryForSwitch();
};

// The gallery's NSFW switch. It reads "Show NSFW", as every other NSFW switch
// in both tabs does, while the server is still asked whether to *hide* them -
// hide_nsfw_images, and hideNsfwImages here. This is the one place the two
// meet, so the inversion is done here and nowhere else.
window.mmToggleShowNsfwImages = async function(showNsfw) {
    hideNsfwImages = !showNsfw;
    hideNsfwImagesInitialized = true;
    await reloadGalleryForSwitch();
};

// Update the images count cell in the Information table
function updateImagesCountCell() {
    const cell = document.getElementById('mm_images_count_cell');
    if (!cell) return;

    // The images the switches let through, loaded or not.
    cell.textContent = filteredImageCount > 0 ? `${filteredImageCount}` : 'None';
}

// Switch to a different version within the same model group
window.mmSelectVersion = async function(versionIndex) {
    if (versionIndex < 0 || versionIndex >= currentVersions.length) return;
    if (versionIndex === selectedVersionIndex) return;

    selectedVersionIndex = versionIndex;
    const version = currentVersions[versionIndex];
    currentModelPath = version.file_path;

    // Reset image state
    imageGallery.images = [];
    currentVersionId = null;
    imageGallery.pages = [];
    filteredImageCount = 0;
    resetGenerations();

    // Update version selector UI
    updateVersionSelectorUI();

    // Update version-specific info in details panel
    updateVersionInfo(version);

    // Load details for new version - its gallery saying so meanwhile.
    if (document.getElementById('mm_images')?.style.display !== 'none') showGalleryLoading('mm_images');
    await loadVersionDetails(version.file_path);
};

// Update version selector pills UI
function updateVersionSelectorUI() {
    document.querySelectorAll('#mm_details .mm-version-pill').forEach((pill) => {
        const entry = pillEntries[Number(pill.dataset.pill)];
        pill.classList.toggle('active', !!entry && isShownPill(entry));
    });
}

/**
 * The Type row: what the file is, read from it. Where Civitai lists it as
 * something else - a VAE shared as a "Checkpoint" - that is said too, so a
 * model that moved under the Type filter explains itself. A file not read
 * yet shows Civitai's type alone, as the filter uses it.
 */
function typeText(entry, civitaiType) {
    const own = entry.file_type;
    if (!own) return escapeHtml(civitaiType || entry.model_type || 'Unknown');
    const listed = civitaiType && civitaiType !== own
        ? ` <span class="mm-type-civitai">(listed on Civitai as ${escapeHtml(civitaiType)})</span>` : '';
    return escapeHtml(own) + listed;
}

/** What decided the file's type, as the Type row's tooltip. */
function typeTitle(entry) {
    return entry.identified_by ? ` title="${escapeHtml('Read from the file: ' + entry.identified_by)}"` : '';
}

// Update version-specific info in details panel
function updateVersionInfo(version) {
    // Update file path
    const pathCell = document.querySelector('.file-path-cell');
    if (pathCell) {
        pathCell.textContent = shortenFilePath(version.file_path);
    }

    // Update file size, modified date, published date
    document.querySelectorAll('.detail-table tr').forEach(row => {
        const label = row.querySelector('td:first-child');
        const value = row.querySelector('td:last-child');
        if (!label || !value) return;

        if (label.textContent === 'File Size') {
            value.textContent = formatFileSize(version.file_size);
        } else if (label.textContent === 'Modified') {
            value.textContent = formatDate(version.file_modified);
        } else if (label.textContent === 'Published' && version.published_at) {
            value.textContent = formatDate(version.published_at);
        }
    });

    // The Show in Civitai Browser row beside it sends this id.
    const idCell = document.querySelector('.mm-version-id-cell');
    if (idCell && version.id) idCell.textContent = version.id;

    // One Civitai model can hold a VAE version and a text encoder version.
    const typeCell = document.querySelector('.mm-type-cell');
    if (typeCell) {
        const model = currentModels[selectedModelIndex] || {};
        typeCell.innerHTML = typeText(version, model.civitai_type);
        if (version.identified_by) typeCell.title = 'Read from the file: ' + version.identified_by;
        else typeCell.removeAttribute('title');
    }

    // Update trigger words if different
    const triggerSection = document.querySelector('.trigger-words');
    if (triggerSection && version.trained_words && version.trained_words.length > 0) {
        triggerSection.innerHTML = version.trained_words.map(w =>
            `<span class="trigger-word" data-copy="${escapeHtml(w)}" title="Click to copy">${escapeHtml(w)}</span>`
        ).join('');
    }

    // Reset images count to loading state
    const imagesCell = document.getElementById('mm_images_count_cell');
    if (imagesCell) {
        imagesCell.textContent = 'Loading...';
    }
}

// NSFW level bitmask to string mapping
const NSFW_LEVEL_BITS = {
    1: 'PG',
    2: 'PG-13',
    4: 'R',
    8: 'X',
    16: 'XXX',
    32: 'Blocked',
    64: 'Unknown'
};

// Format NSFW level (now an integer bitmask) - returns highest set bit only
function formatNsfwLevels(level) {
    if (!level || typeof level !== 'number') return 'Unknown';

    // Find highest set bit
    const bitOrder = [64, 32, 16, 8, 4, 2, 1];
    for (const bit of bitOrder) {
        if (level & bit) {
            return NSFW_LEVEL_BITS[bit] || 'Unknown';
        }
    }
    return 'Unknown';
}

// Expand NSFW level bitmask to comma-separated labels (e.g., 5 -> "PG, R")
function expandNsfwLevel(level) {
    if (!level || typeof level !== 'number') return 'Unknown';

    const labels = [];
    const bitOrder = [1, 2, 4, 8, 16, 32, 64];  // Low to high
    for (const bit of bitOrder) {
        if (level & bit) {
            labels.push(NSFW_LEVEL_BITS[bit]);
        }
    }
    return labels.length > 0 ? labels.join(', ') : 'Unknown';
}

// Shorten file path - remove everything before \models or /models
function shortenFilePath(path) {
    if (!path) return '';
    const match = path.match(/[\\\/]models[\\\/].*/i);
    return match ? match[0] : path;
}

/**
 * The version pills: every version Civitai lists, in Civitai's order, with
 * the local ones marked; then any local version it does not list. With no
 * list recorded, the local versions alone, as before there was one.
 *
 * `local` is the version's index in currentVersions - or 0 for a model with
 * one local version, which is the grid's entry itself - and null for one not
 * in the library.
 */
function versionPills() {
    const model = currentModels[selectedModelIndex] || {};
    const locals = currentVersions.length ? currentVersions : [model];
    const entries = civitaiVersions.map((version) => {
        const local = locals.findIndex((l) => l.id != null && l.id === version.id);
        return { id: version.id, local: local >= 0 ? local : null, version };
    });
    locals.forEach((l, i) => {
        if (!entries.some((e) => e.local === i)) entries.push({ id: l.id, local: i, version: null });
    });
    return entries;
}

function isShownPill(entry) {
    if (remoteVersionId !== null) return entry.local === null && entry.id === remoteVersionId;
    return entry.local === (currentVersions.length ? selectedVersionIndex : 0);
}

/** "As Civitai listed them on ...": the list is only as fresh as the last sync. */
function renderVersionsNote() {
    if (!civitaiVersions.length) return '';
    const as = versionsSyncedAt
        ? `Versions as Civitai listed them on ${formatDay(versionsSyncedAt)}`
        : 'Versions as the model\'s files list them';
    return `<div class="mm-versions-note">${as}; this may not be up to date. `
        + 'Sync metadata with Civitai to get the latest.</div>';
}

// Render version selector pills
function renderVersionSelector() {
    pillEntries = versionPills();
    if (pillEntries.length <= 1) return '';

    const model = currentModels[selectedModelIndex] || {};
    const locals = currentVersions.length ? currentVersions : [model];
    const anyRemote = pillEntries.some((e) => e.local === null);

    const pills = pillEntries.map((entry, index) => {
        const activeClass = isShownPill(entry) ? 'active' : '';
        if (entry.local === null) {
            const version = entry.version;
            const versionName = version.name || `v${index + 1}`;
            const paidNote = paidAccessLabel(version);
            const tooltip = `${versionName}\nBase: ${version.baseModel || 'Unknown'}\nNot downloaded`
                + `${paidNote ? '\n' + paidNote : ''}`;
            return `<button class="mm-version-pill ${activeClass} ${isPaid(version) ? 'paid' : ''}" data-pill="${index}"
                           onclick="window.mmSelectPill(${index})"
                           title="${escapeHtml(tooltip)}">${escapeHtml(versionName)}${isPaid(version) ? ' ⬥' : ''}</button>`;
        }
        const version = locals[entry.local];
        const versionName = version.version_name || `v${index + 1}`;
        const fileName = version.file_name ? version.file_name.replace(/\.(safetensors|sft|gguf|ckpt|pt|pth|bin)$/i, '') : '';
        const displayName = version.version_name ? versionName : fileName;
        const tooltip = `${versionName}\n${version.file_name}\n${formatFileSize(version.file_size)}`;
        // Only worth marking when some are not downloaded.
        const owned = anyRemote ? ' owned' : '';

        return `<button class="mm-version-pill ${activeClass}${owned}" data-pill="${index}"
                       onclick="window.mmSelectPill(${index})"
                       title="${escapeHtml(tooltip)}">${escapeHtml(displayName)}${anyRemote ? ' ✓' : ''}</button>`;
    }).join('');

    const heading = anyRemote
        ? `Versions (${pillEntries.length}, ${locals.length} downloaded)`
        : `Local Versions (${pillEntries.length})`;

    return `
        <div class="detail-section mm-version-selector">
            <h4>${heading}</h4>
            <div class="mm-version-pills">
                ${pills}
            </div>
            ${renderVersionsNote()}
        </div>
    `;
}

/**
 * A pill was clicked. A local version is shown as it always was; one not in
 * the library is shown as the Civitai Browser shows it, with a Download.
 */
window.mmSelectPill = async function(index) {
    const entry = pillEntries[index];
    if (!entry) return;
    if (entry.local === null) {
        if (remoteVersionId === entry.id) return;
        remoteVersionId = entry.id;
        remoteFileIndex = null;
        renderRemoteVersion();
        return;
    }
    if (remoteVersionId !== null) {
        // The remote view replaced the panel and hid the gallery: draw the
        // local one again, then select the version in it.
        remoteVersionId = null;
        const model = currentModels[selectedModelIndex];
        if (!currentVersions.length) {
            currentModelPath = model.file_path;
            resetImageState();
            renderModelDetails(model);
            await loadVersionDetails(model.file_path);
            return;
        }
        const wanted = entry.local;
        selectedVersionIndex = currentVersions.findIndex((v) => v.file_path === model.file_path);
        renderModelDetails(model);
        if (wanted === selectedVersionIndex) {
            currentModelPath = model.file_path;
            resetImageState();
            await loadVersionDetails(model.file_path);
            return;
        }
        await window.mmSelectVersion(wanted);
        return;
    }
    await window.mmSelectVersion(entry.local);
};

function resetImageState() {
    imageGallery.images = [];
    currentVersionId = null;
    imageGallery.pages = [];
    filteredImageCount = 0;
}

/**
 * The pin: a card pinned comes first in the grid whenever it matches the
 * filters. On the card's corner, and beside the bookmark in its details, as
 * { cls, text, title, onclick } - an overlay of renderModelCard().
 */
function pinButton(model, index, cls) {
    const pinned = !!model?.is_pinned;
    return { cls: `${cls}${pinned ? ' pinned' : ''}`, text: '📌', onclick: `window.mmTogglePin(${Number(index)})`,
             title: pinned ? 'Pinned: first whenever it matches the filters. Click to unpin.'
                           : 'Pin: show first whenever it matches the filters' };
}

/** The header's buttons: the same for any version, but deleting needs a file. */
function renderDetailHeader(model, { deletable = true } = {}) {
    const modelId = model.model_id || model.civitai_model_id;
    const isBookmarked = model.is_bookmarked || false;
    const bookmarkBtn = modelId
        ? `<button class="mm-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" onclick="window.mmToggleBookmark(${safeId(modelId)})" title="${isBookmarked ? 'Remove bookmark' : 'Bookmark this model'}">${isBookmarked ? '★' : '☆'}</button>`
        : '';
    // The card's pin: the grid's model, whichever version the panel shows.
    const pin = pinButton(currentModels[selectedModelIndex], selectedModelIndex, 'mm-bookmark-btn mm-pin-toggle');
    const pinBtn = currentModels[selectedModelIndex]
        ? `<button class="${pin.cls}" onclick="${pin.onclick}" title="${escapeHtml(pin.title)}">${pin.text}</button>` : '';

    // Deleting sits with the other actions on the model, in the header. With
    // several versions, the one shown and all of them are separate choices.
    const deleteButton = (scope, label, title) =>
        `<button class="mm-btn danger mm-btn-small header-action" onclick="window.mmDeleteModel('${scope}')" title="${title}">${label}</button>`;
    const deleteButtons = !deletable ? ''
        : currentVersions.length > 1
        ? deleteButton('version', 'Delete Current Model Version', 'Delete the version shown here, and its files')
          + deleteButton('all', 'Delete All Model Versions', `Delete all ${currentVersions.length} versions of this model, and their files`)
        : deleteButton('version', 'Delete Model', 'Delete this model, and its files');

    return `
            <div class="detail-header">
                <h3>${escapeHtml(model.display_name)}</h3>
                ${bookmarkBtn}
                ${pinBtn}
                ${modelId ? `<button class="mm-btn primary mm-btn-small header-action" onclick="window.mmForceSyncModel()" title="Force sync this model">Sync</button>` : ''}
                ${deleteButtons}
                <button class="close-details" onclick="window.mmCloseDetails()">×</button>
            </div>`;
}

/**
 * A version not in the library, as the Civitai Browser shows one: what it is
 * and a Download, from what was recorded at the last sync. It has no gallery
 * here - that is fetched for a file - so the one below is hidden.
 */
function renderRemoteVersion() {
    const container = document.getElementById('mm_details');
    const model = currentModels[selectedModelIndex];
    const version = civitaiVersions.find((v) => v.id === remoteVersionId);
    if (!container || !model || !version) return;

    const modelId = model.model_id;
    const files = version.files || [];
    const fileIndex = remoteFileIndex !== null && remoteFileIndex < files.length
        ? remoteFileIndex : primaryFileIndex(version);
    const file = files[fileIndex];
    const paidLabel = paidAccessLabel(version);
    const votes = (model.thumbs_up || 0) + (model.thumbs_down || 0);

    const trainedWords = version.trainedWords && version.trainedWords.length > 0
        ? `<div class="detail-section">
             <h4>Trigger Words</h4>
             <div class="trigger-words">
               ${version.trainedWords.map(w => `<span class="trigger-word" data-copy="${escapeHtml(w)}" title="Click to copy">${escapeHtml(w)}</span>`).join('')}
             </div>
           </div>`
        : '';
    const tags = model.tags && model.tags.length > 0
        ? `<div class="detail-section">
             <h4>Tags</h4>
             <div class="tag-list">
               ${model.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
             </div>
           </div>`
        : '';
    const descriptionHtml = modelDescription
        ? `<div class="detail-section">
             <h4>Description</h4>
             <div class="mm-description">${sanitizeHtml(modelDescription)}</div>
           </div>`
        : '';

    container.innerHTML = `
        <div class="model-details-content">
            ${renderDetailHeader(model, { deletable: false })}

            ${renderVersionSelector()}

            <div class="detail-section">
                <h4>Information</h4>
                <table class="detail-table">
                    ${showInCivitaiRow()}
                    <tr><td>Model ID</td><td>${safeId(modelId)}</td></tr>
                    <tr><td>Version ID</td><td>${safeId(version.id)}</td></tr>
                    <tr><td>Version Name</td><td>${escapeHtml(version.name || 'Unknown')}</td></tr>
                    <tr><td>Type</td><td>${escapeHtml(model.civitai_type || 'Unknown')}</td></tr>
                    <tr><td>Base Model</td><td>${escapeHtml(version.baseModel || 'Unknown')}</td></tr>
                    <tr><td>Creator</td><td>${escapeHtml(model.creator || 'Unknown')}</td></tr>
                    ${paidLabel ? `<tr><td>Access</td><td class="mm-paid-cell">${escapeHtml(paidLabel)}</td></tr>` : ''}
                    <tr><td>Published</td><td>${formatDay(version.publishedAt)}</td></tr>
                    <tr><td>Updated</td><td>${formatDay(version.updatedAt)}</td></tr>
                    <tr><td>Rating</td><td>★ ${(model.rating || 0).toFixed(1)} (${formatNumber(votes)} ratings)</td></tr>
                    <tr><td>Downloads</td><td>${formatNumber(model.download_count || 0)}</td></tr>
                    <tr><td>File</td><td id="mm_file_name">${escapeHtml(file?.name || 'Unknown')}</td></tr>
                    <tr><td>File Size</td><td id="mm_file_size">${file?.sizeKB ? formatBytes(file.sizeKB * 1024) : 'Unknown'}</td></tr>
                </table>
            </div>

            ${trainedWords}
            ${tags}
            ${descriptionHtml}

            <div class="detail-section detail-actions">
                <a class="mm-btn secondary" href="https://civitai.com/models/${safeId(modelId)}?modelVersionId=${safeId(version.id)}" target="_blank">View on Civitai</a>
                ${renderDownloadControls({ controls: DOWNLOAD_CONTROLS, modelId, version, fileIndex, owned: false })}
            </div>
            <div class="mm-versions-note">Not downloaded, so there are no example images here yet.
                Show in Civitai Browser has them.</div>
        </div>
    `;
    container.style.display = 'block';

    const images = document.getElementById('mm_images');
    if (images) images.style.display = 'none';
}

window.mmSelectFile = function(fileIndex) {
    const index = parseInt(fileIndex, 10);
    const version = civitaiVersions.find((v) => v.id === remoteVersionId);
    const file = (version?.files || [])[index];
    if (!file) return;
    remoteFileIndex = index;
    showChosenFile(DOWNLOAD_CONTROLS, currentModels[selectedModelIndex]?.model_id, version, file);
};

// The list and its panel are shared with the Civitai Browser: see
// downloads() in shared/downloads.mjs.
window.mmDownload = async function(modelId, versionId, fileId) {
    try {
        setStatus('Starting download...');
        const result = await downloads().start(modelId, versionId, fileId);
        if (result.success) setStatus(`Download started: ${result.progress?.file_name || 'Unknown'}`);
        else setStatus(`Download error: ${result.error}`, true);
    } catch (e) {
        console.error('[ModelManager] Download error:', e);
        setStatus(`Download error: ${e.message}`, true);
    }
};

/**
 * A version of the open model has reached the library: it is local now. If
 * it is the one shown, show it as a local version, gallery and all;
 * otherwise mark its pill.
 */
async function versionDownloaded(dl) {
    const model = currentModels[selectedModelIndex];
    if (!model || !model.model_id || !civitaiVersions.some((v) => v.id === dl.version_id)) return;
    const index = selectedModelIndex;
    let data;
    try {
        data = await apiCall({ endpoint: '/model-manager/models/versions', params: { model_id: model.model_id } });
    } catch (error) {
        console.error('[ModelManager] Failed to reload versions:', error);
        return;
    }
    if (selectedModelIndex !== index || !data.success) return;

    const shown = remoteVersionId;
    const previous = shownVersion(model);
    currentVersions = (data.versions || []).length > 1 ? data.versions : [];
    civitaiVersions = data.civitai_versions || [];
    versionsSyncedAt = data.versions_synced_at || null;
    model.local_version_count = (data.versions || []).length;

    if (shown === dl.version_id) {
        const arrived = currentVersions.findIndex((v) => v.id === dl.version_id);
        remoteVersionId = null;
        selectedVersionIndex = -1;   // so that mmSelectVersion does not think it is shown
        renderModelDetails(model);
        if (arrived >= 0) {
            await window.mmSelectVersion(arrived);
        } else {
            currentModelPath = model.file_path;
            resetImageState();
            await loadVersionDetails(model.file_path);
        }
        return;
    }
    // Keep showing what was shown, with the pills brought up to date - and
    // the header, whose delete buttons count the local versions.
    selectedVersionIndex = Math.max(0, currentVersions.findIndex((v) => v.file_path === previous.file_path));
    const header = document.querySelector('#mm_details .detail-header');
    if (header) header.outerHTML = renderDetailHeader(model, { deletable: remoteVersionId === null });
    const selector = document.querySelector('#mm_details .mm-version-selector');
    const fresh = renderVersionSelector();
    if (selector) selector.outerHTML = fresh;
}

downloads().addPanel('mm');
downloads().onComplete(versionDownloaded);

// Render model details panel
function renderModelDetails(model, fullDetails = null) {
    const container = document.getElementById('mm_details');
    if (!container) return;

    const trainedWords = model.trained_words && model.trained_words.length > 0
        ? `<div class="detail-section">
             <h4>Trigger Words</h4>
             <div class="trigger-words">
               ${model.trained_words.map(w => `<span class="trigger-word" data-copy="${escapeHtml(w)}" title="Click to copy">${escapeHtml(w)}</span>`).join('')}
             </div>
           </div>`
        : '';

    const tags = model.tags && model.tags.length > 0
        ? `<div class="detail-section">
             <h4>Tags</h4>
             <div class="tag-list">
               ${model.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
             </div>
           </div>`
        : '';

    // Use model_id for Civitai link (the parent model ID)
    const modelId = model.model_id || model.civitai_model_id;
    const civitaiLink = modelId
        ? `<a class="action-btn secondary" href="https://civitai.com/models/${safeId(modelId)}" target="_blank">View on Civitai</a>`
        : '';

    // Get description from full details if available
    const description = fullDetails?.civitai_model?.description || '';
    const descriptionHtml = description
        ? `<div class="detail-section">
             <h4>Description</h4>
             <div class="mm-description">${sanitizeHtml(description)}</div>
           </div>`
        : '<div class="detail-section" id="mm_description_placeholder"></div>';

    // Version selector (only if multiple versions)
    const versionSelectorHtml = renderVersionSelector();

    container.innerHTML = `
        <div class="model-details-content">
            ${renderDetailHeader(model)}

            ${versionSelectorHtml}

            <div class="detail-section">
                <h4>Information</h4>
                <table class="detail-table">
                    ${modelId ? showInCivitaiRow() : ''}
                    ${modelId ? `<tr><td>Model ID</td><td>${modelId}</td></tr>` : ''}
                    ${model.id ? `<tr><td>Version ID</td><td class="mm-version-id-cell">${model.id}</td></tr>` : ''}
                    <tr><td>Type</td><td class="mm-type-cell"${typeTitle(model)}>${typeText(model, model.civitai_type)}</td></tr>
                    <tr><td>Base Model</td><td>${model.base_model || 'Unknown'}</td></tr>
                    <tr><td rowspan="3" class="nsfw-label-cell">NSFW Level</td><td>Model: ${expandNsfwLevel(model.civitai_model?.nsfw_level)}</td></tr>
                    <tr><td>Version: ${expandNsfwLevel(model.nsfw_level)}</td></tr>
                    <tr><td>Highest Image: ${expandNsfwLevel(model.max_image_nsfw)}</td></tr>
                    <tr><td>File Size</td><td>${formatFileSize(model.file_size)}</td></tr>
                    <tr><td>Modified</td><td>${formatDate(model.file_modified)}</td></tr>
                    ${model.published_at ? `<tr><td>Published</td><td>${formatDate(model.published_at)}</td></tr>` : ''}
                    ${model.creator ? `<tr><td>Creator</td><td>${escapeHtml(model.creator)}</td></tr>` : ''}
                    ${model.rating > 0 ? `<tr><td>Rating</td><td>★ ${model.rating.toFixed(1)} (${formatNumber(model.download_count)} downloads)</td></tr>` : ''}
                    ${model.civitai_model ? `
                    <tr><td rowspan="3" class="license-label-cell">License</td><td>Commercial: ${formatCommercialUse(model.civitai_model.allow_commercial_use)}</td></tr>
                    <tr><td>Derivatives: ${model.civitai_model.allow_derivatives ? 'Yes' : 'No'}</td></tr>
                    <tr><td>Different License: ${model.civitai_model.allow_different_license ? 'Yes' : 'No'}</td></tr>
                    ` : ''}
                    <tr><td>File</td><td class="file-path-cell">${escapeHtml(shortenFilePath(model.file_path))}</td></tr>
                    <tr id="mm_images_count_row"><td>Images</td><td id="mm_images_count_cell">Loading...</td></tr>
                </table>
            </div>

            ${trainedWords}
            ${tags}
            ${descriptionHtml}

            <div class="detail-section detail-actions">
                ${civitaiLink}
                <button class="action-btn secondary" onclick="window.mmResyncImages()">Resync Images</button>
            </div>
        </div>
    `;

    container.style.display = 'block';
}

// Update description section after full details load
function updateDescription(description) {
    const placeholder = document.getElementById('mm_description_placeholder');
    if (placeholder && description) {
        placeholder.outerHTML = `
            <div class="detail-section">
                <h4>Description</h4>
                <div class="mm-description collapsed" id="mm_description_content">${sanitizeHtml(description)}</div>
                <button class="mm-description-toggle" id="mm_description_toggle" onclick="window.mmToggleDescription()">
                    Show more
                </button>
            </div>
        `;
        // Check if content is short enough to not need toggle
        setTimeout(() => {
            const content = document.getElementById('mm_description_content');
            const toggle = document.getElementById('mm_description_toggle');
            if (content && toggle) {
                // If content height is less than collapsed max-height, hide toggle
                if (content.scrollHeight <= 48) {
                    toggle.style.display = 'none';
                    content.classList.remove('collapsed');
                }
            }
        }, 0);
    }
}

// Toggle description expand/collapse
window.mmToggleDescription = function() {
    const content = document.getElementById('mm_description_content');
    const toggle = document.getElementById('mm_description_toggle');
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

// Resync images for current version
window.mmResyncImages = async function() {
    if (!currentVersionId) {
        setStatus('No version selected or version has no Civitai data', true);
        return;
    }

    try {
        setStatus('Resyncing images...');

        const response = await fetch('/model-manager/images/resync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `version_id=${currentVersionId}`
        });

        const data = await response.json();

        if (data.success) {
            setStatus(`Resynced ${data.fetched_count} images`);
            // The gallery again from its first page, through the switches:
            // the answer holds every image fetched, filtered or not.
            await loadGalleryPage(1);
        } else {
            setStatus('Resync failed: ' + (data.error || 'Unknown error'), true);
        }
    } catch (error) {
        console.error('[ModelManager] Resync error:', error);
        setStatus('Resync error: ' + error.message, true);
    }
};

// Show sync loading overlay
function showSyncOverlay(message) {
    // Remove existing overlay if any
    hideSyncOverlay();

    const overlay = document.createElement('div');
    overlay.className = 'mm-sync-overlay';
    overlay.id = 'mm_sync_overlay';
    overlay.innerHTML = `
        <div class="mm-sync-popup">
            <div class="mm-sync-spinner"></div>
            <div class="mm-sync-status">${escapeHtml(message)}</div>
        </div>
    `;
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
}

function updateSyncOverlay(message) {
    const status = document.querySelector('#mm_sync_overlay .mm-sync-status');
    if (status) {
        status.textContent = message;
    }
}

function hideSyncOverlay() {
    const overlay = document.getElementById('mm_sync_overlay');
    if (overlay) {
        overlay.remove();
    }
    document.body.style.overflow = '';
}

// Force sync model and all versions
window.mmForceSyncModel = async function() {
    const model = currentModels[selectedModelIndex];
    if (!model) {
        setStatus('No model selected', true);
        return;
    }

    const modelId = model.model_id || model.civitai_model_id;
    if (!modelId) {
        setStatus('Model has no Civitai ID - cannot sync', true);
        return;
    }

    try {
        showSyncOverlay('Syncing model data...');

        const response = await fetch('/model-manager/models/force-sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `model_id=${modelId}`
        });

        const data = await response.json();

        if (data.success) {
            const synced = data.synced_count || 0;
            const total = data.total_versions || 0;
            setStatus(`Synced ${synced}/${total} versions successfully`);
            // Reload the current model to show updated data
            if (selectedModelIndex >= 0) {
                window.mmSelectModel(selectedModelIndex);
            }
        } else {
            setStatus('Sync failed: ' + (data.error || 'Unknown error'), true);
        }
    } catch (error) {
        console.error('[ModelManager] Force sync error:', error);
        setStatus('Force sync error: ' + error.message, true);
    } finally {
        hideSyncOverlay();
    }
};

/**
 * Pin the grid's card `index`, or unpin it: a Civitai model by its id, a file
 * Civitai does not know by its path. The card stays where it is until the
 * grid loads again - moving it now would take it from under the pointer.
 */
window.mmTogglePin = async function(index) {
    const model = currentModels[index];
    if (!model) return;
    const pinned = !model.is_pinned;
    const form = new URLSearchParams({ pinned: String(pinned) });
    if (model.model_id) form.set('model_id', model.model_id);
    else form.set('file_path', model.file_path);
    try {
        const response = await fetch('/model-manager/pin', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form });
        const data = await response.json();
        if (!data.success) {
            setStatus('Pin failed: ' + (data.error || 'Unknown error'), true);
            return;
        }
    } catch (error) {
        setStatus('Pin error: ' + error.message, true);
        return;
    }
    model.is_pinned = pinned;
    if (gridTabCounts) {
        gridTabCounts.pinned += pinned ? 1 : -1;
        gridTabCounts.others += pinned ? -1 : 1;
        updateGridTabs();
    }
    const redraw = (button, cls) => {
        if (!button) return;
        const fresh = pinButton(model, index, cls);
        button.className = fresh.cls;
        button.title = fresh.title;
    };
    redraw(document.querySelector(`#mm_grid .model-card[data-index="${Number(index)}"] .mm-pin-btn`), 'mm-pin-btn');
    if (index === selectedModelIndex) {
        redraw(document.querySelector('#mm_details .mm-pin-toggle'), 'mm-bookmark-btn mm-pin-toggle');
    }
    setStatus(pinned ? 'Pinned: it comes first whenever it matches the filters, from the next load'
                     : 'Unpinned');
};

// Toggle bookmark status for a model
window.mmToggleBookmark = async function(modelId) {
    if (!modelId) {
        setStatus('Cannot bookmark: No Civitai model ID', true);
        return;
    }

    const model = currentModels[selectedModelIndex];
    if (!model) return;

    const currentState = model.is_bookmarked || false;
    const newState = !currentState;

    try {
        const response = await fetch('/model-manager/bookmark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `model_id=${modelId}&bookmarked=${newState}`
        });

        const data = await response.json();

        if (data.success) {
            // Update model in memory
            model.is_bookmarked = newState;

            // Update bookmark button in details panel
            const bookmarkBtn = document.querySelector('.mm-bookmark-btn');
            if (bookmarkBtn) {
                bookmarkBtn.classList.toggle('bookmarked', newState);
                bookmarkBtn.textContent = newState ? '★' : '☆';
                bookmarkBtn.title = newState ? 'Remove bookmark' : 'Bookmark this model';
            }

            // Update card indicator
            const card = document.querySelector(`.model-card[data-model-id="${modelId}"]`);
            if (card) {
                let indicator = card.querySelector('.mm-bookmark-indicator');
                if (newState && !indicator) {
                    const imageDiv = card.querySelector('.model-card-image');
                    if (imageDiv) {
                        indicator = document.createElement('div');
                        indicator.className = 'mm-bookmark-indicator';
                        indicator.title = 'Bookmarked';
                        indicator.textContent = '★';
                        imageDiv.appendChild(indicator);
                    }
                } else if (!newState && indicator) {
                    indicator.remove();
                }
            }

            setStatus(newState ? 'Model bookmarked' : 'Bookmark removed');
        } else {
            setStatus('Bookmark failed: ' + (data.error || 'Unknown error'), true);
        }
    } catch (error) {
        console.error('[ModelManager] Bookmark error:', error);
        setStatus('Bookmark error: ' + error.message, true);
    }
};

// Delete a model's files, and it from the library: the version shown, or
// ('all') every version of it here. The version shown, not the grid card's -
// deleting used to take the card's row, which after picking another version
// in the details panel was a different file from the one on screen.
window.mmDeleteModel = async function(scope = 'version') {
    const model = currentModels[selectedModelIndex];
    if (!model) return;

    const all = scope === 'all' && currentVersions.length > 1;
    const targets = all ? currentVersions.slice() : [shownVersion(model)];
    const name = (v) => v.version_name || v.file_name || 'this version';
    const what = all
        ? `all ${targets.length} versions of "${model.display_name}":\n`
          + targets.map((v) => `• ${name(v)} (${v.file_name})`).join('\n')
        : currentVersions.length > 1
            ? `version "${name(targets[0])}" of "${model.display_name}" (${targets[0].file_name})`
            : `"${model.display_name}"`;

    const confirmed = confirm(
        `Are you sure you want to delete ${what}?\n\n` +
        `This will delete, for ${all ? 'each' : 'it'}:\n` +
        `• The model file\n` +
        `• All metadata files (.civitai.info, .preview.png, etc.)\n` +
        `• The containing folder if it's named after the model and becomes empty\n\n` +
        `This action cannot be undone.`
    );
    if (!confirmed) return;

    setStatus(all ? `Deleting ${targets.length} versions...` : 'Deleting model...');
    const failed = [];
    for (const version of targets) {
        try {
            const response = await fetch('/model-manager/models/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `path=${encodeURIComponent(version.file_path)}`
            });
            const data = await response.json();
            if (!data.success) failed.push(`${name(version)}: ${data.error || 'Unknown error'}`);
        } catch (error) {
            console.error('[ModelManager] Delete error:', error);
            failed.push(`${name(version)}: ${error.message}`);
        }
    }

    const deletedName = currentVersions.length > 1 && !all ? ` (${name(targets[0])})` : '';
    // The grid reloads first: its own status line would otherwise replace
    // this one, and a failure would go unsaid.
    if (failed.length < targets.length) {
        window.mmCloseDetails();
        await loadModels(currentPage);
    }
    if (failed.length) {
        setStatus(`Delete failed for ${failed.join('; ')}`, true);
    } else {
        setStatus(all ? `Deleted all ${targets.length} versions of ${model.display_name}`
                      : `Deleted: ${model.display_name}${deletedName}`);
    }
};


// Render model images - new list layout
function renderModelImages() {
    const container = document.getElementById('mm_images');
    if (!container) return;
    if (galleryTab === 'generations') {
        renderGenerations();
        return;
    }

    // No page loaded, or nothing stored and none to fetch: nothing to list.
    if (!imageGallery.pages.length || (!totalImageCount && !imageGallery.pages[0].count)) {
        if (!totalImageCount && generationsCount > 0) {
            // No example images, but your own generations: the tabs still
            // show, or there would be no way to them.
            container.innerHTML = `
                ${imagesHeaderHtml()}
                <div class="model-images-list"><p class="mm-no-images">No example images from Civitai.</p></div>
            `;
            container.style.display = 'block';
            return;
        }
        container.style.display = 'none';
        return;
    }

    galleryWidth = galleryImageWidth(container);
    container.innerHTML = `
        ${imagesHeaderHtml()}
        ${imagesBannerHtml()}
        ${imageGallery.pagesHtml()}
    `;
    container.style.display = 'block';
    setupLazyMedia(container);
    refreshResourceButtons();
}

/**
 * One banner for both filters, over every stored image: what they are holding
 * back, which adds up with what matches them to the total, and a switch for
 * each on the right. The server splits the hidden images between the filters
 * so that none is counted twice - NSFW first, as it filters - and reports
 * what each switch would show once ticked. Built in shared/gallery.mjs, as the
 * Civitai Browser's is.
 */
function imagesBannerHtml() {
    return renderFilterBanner({
        matching: filteredImageCount,
        total: totalImageCount,
        onScreen: imageGallery.images.length,
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        both: hiddenByBothCount,
        switches: [
            { id: 'mm_show_nsfw_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: !hideNsfwImages, hidden: hiddenImageCount, count: nsfwImageCount,
              onchange: 'window.mmToggleShowNsfwImages(this.checked)', note: nsfwModelNote() },
            { id: 'mm_show_promptless_images', label: 'Show unusable prompts',
              reason: 'unusable prompt',
              showing: !hidePromptlessImages, hidden: hiddenPromptlessCount,
              count: promptlessImageCount, total: promptlessImageTotal ?? undefined,
              onchange: 'window.mmToggleShowPromptless(this.checked)' },
        ],
    });
}

/**
 * The gallery's header: its two tabs, which are its title, and on the right
 * what the tab showing is counting - with, on your generations, a Refresh for
 * images made since the tab was drawn.
 */
function imagesHeaderHtml(countText = '') {
    const refresh = galleryTab === 'generations'
        ? `<label class="mm-rate-switch" title="Rate each image's NSFW level: a row of levels on every card">
               <input type="checkbox" id="mm_rate_generations" ${rateGenerations ? 'checked' : ''}
                      onchange="window.mmSetRatingGenerations(this.checked)"> Rate</label>
           <label class="mm-rate-switch" title="Tick generations, then delete them all at once. A tick is the whole generation">
               <input type="checkbox" id="mm_select_generations" ${selectingGenerations ? 'checked' : ''}
                      onchange="window.mmSetSelectingGenerations(this.checked)"> Select</label>
           ${selectingGenerations ? `<span class="mm-select-bar">${selectBarHtml(pickedSummary().images, {
               all: 'window.mmSelectAllGenerations()', clear: 'window.mmClearGenerationPicks()',
               delete: 'window.mmDeletePickedGenerations()' })}</span>` : ''}
           <button class="mm-btn secondary mm-refresh-generations" onclick="window.mmRefreshGenerations()"
                   title="Show images generated since this was drawn">Refresh</button>`
        : '';
    const tab = (key, label) => `
        <button class="mm-gallery-tab ${galleryTab === key ? 'active' : ''}" role="tab"
                aria-selected="${galleryTab === key}" onclick="window.mmShowGalleryTab('${key}')">${label}</button>`;
    return `
        <div class="mm-images-header">
            <div class="mm-gallery-tabs" role="tablist">
                ${tab('civitai', 'Civitai images')}
                ${generationsEnabled() ? tab('generations', 'Your generations' + ` (${generationsCount})`) : ''}
            </div>
            <div class="mm-images-header-right">
                ${refresh}
                <span class="mm-images-count">${countText}</span>
            </div>
        </div>`;
}

/** Forget the open model's generations: another model, or version, is opening. */
function resetGenerations() {
    clearPickedGenerations();
    galleryTab = 'civitai';
    generationsCount = 0;
    generationCards = [];
    generationPages = [];
    generationsState = null;
    generationPageError = '';
    generationsRequest += 1;
}

window.mmShowGalleryTab = async function(tab) {
    if (tab === galleryTab) return;
    galleryTab = tab;
    if (tab === 'generations') {
        // Drawn from what is loaded, or "Loading...", then fetched again:
        // opening the tab shows what was generated since it was last open.
        renderGenerations();
        await refreshGenerations();
        return;
    }
    renderModelImages();
};

// "Your generations" turned off or on: the gallery's tab goes or comes back at
// once - off while it shows, to the Civitai images.
window.addEventListener('mm-generations-enabled', (event) => {
    if (!document.querySelector('#mm_images .mm-images-header')) return;
    if (!event.detail.enabled && galleryTab === 'generations') {
        window.mmShowGalleryTab('civitai');
        return;
    }
    if (galleryTab === 'generations') renderGenerations();
    else renderModelImages();
});

// "Rate" on your generations: a row of NSFW levels on each card and on each
// image "Show images" shows. Not remembered.
let rateGenerations = false;

window.mmSetRatingGenerations = function(checked) {
    rateGenerations = !!checked;
    if (rateGenerations) selectingGenerations = false;
    clearPickedGenerations();
    renderGenerations();
};

// "Select" on your generations, as in the Generations tab: a tick on each
// card - its generation whole, as its Delete - and one Delete for all. The
// ticks by generation id, the last for shift-click. Not remembered.
let selectingGenerations = false;
const pickedGenerations = new Set();
let lastPickedCard = -1;

function clearPickedGenerations() {
    pickedGenerations.clear();
    lastPickedCard = -1;
}

function pickedSummary() {
    const out = { images: 0, hidden: 0, ids: [] };
    for (const card of generationCards) {
        if (!pickedGenerations.has(card.id)) continue;
        const all = card.image_count || card.matching_count || 1;
        out.images += all;
        out.hidden += Math.max(0, all - (card.matching_count || all));
        out.ids.push(card.id);
    }
    return out;
}

function updateGenerationSelectBar() {
    const bar = document.querySelector('#mm_images .mm-select-bar');
    if (!bar) return;
    bar.innerHTML = selectBarHtml(pickedSummary().images, { all: 'window.mmSelectAllGenerations()',
        clear: 'window.mmClearGenerationPicks()', delete: 'window.mmDeletePickedGenerations()' });
}

function showGenerationTicks() {
    document.querySelectorAll('#mm_images [data-mm-pick]').forEach((box) => {
        box.checked = pickedGenerations.has(Number(box.dataset.mmPick));
    });
    updateGenerationSelectBar();
}

window.mmSetSelectingGenerations = function(checked) {
    selectingGenerations = !!checked;
    if (selectingGenerations) rateGenerations = false;
    clearPickedGenerations();
    renderGenerations();
};

document.addEventListener('click', (event) => {
    const box = event.target.closest?.('#mm_images [data-mm-pick]');
    if (!box) return;
    const index = generationCards.findIndex((card) => card.id === Number(box.dataset.mmPick));
    if (index < 0) return;
    const range = event.shiftKey && lastPickedCard >= 0
        ? [Math.min(lastPickedCard, index), Math.max(lastPickedCard, index)] : [index, index];
    for (let i = range[0]; i <= range[1]; i++) {
        if (box.checked) pickedGenerations.add(generationCards[i].id);
        else pickedGenerations.delete(generationCards[i].id);
    }
    lastPickedCard = index;
    showGenerationTicks();
});

// Selecting, a click on a card's images ticks the card rather than opening
// the viewer - caught on the way down, before the image's own click.
document.addEventListener('click', (event) => {
    if (!selectingGenerations) return;
    const card = event.target.closest?.('#mm_images .mm-generation-card');
    if (!card || event.target.closest('[data-mm-pick]')) return;
    if (!event.target.closest('.mm-image-left, [data-view-generation-image]')) return;
    const box = card.querySelector('[data-mm-pick]');
    if (!box) return;
    event.stopPropagation();
    event.preventDefault();
    box.checked = !box.checked;
    box.dispatchEvent(Object.assign(new Event('click', { bubbles: true }), { shiftKey: event.shiftKey }));
}, true);

window.mmSelectAllGenerations = function() {
    generationCards.forEach((card) => pickedGenerations.add(card.id));
    showGenerationTicks();
};

window.mmClearGenerationPicks = function() {
    clearPickedGenerations();
    showGenerationTicks();
};

window.mmDeletePickedGenerations = async function() {
    const picked = pickedSummary();
    if (!picked.images) return;
    const answer = await askToDelete(bulkDeleteQuestion(picked.images, picked.ids.length, picked.hidden),
                                     picked.images);
    if (!answer) return;
    const data = await deleteManyGenerations({ generationIds: picked.ids, withFiles: answer.withFiles });
    if (!data.success) {
        setStatus('Delete failed: ' + (data.error || 'no answer'), true);
        return;
    }
    picked.ids.forEach((id) => removeGenerationCard(id));
    clearPickedGenerations();
    await refreshGenerationTotals();
    renderGenerations();
    setStatus(bulkDeleteReport(data, answer.withFiles), (data.failed || []).length > 0);
};

/**
 * Rate a card - its image, or every image of it this gallery shows, through
 * both switches - or, with `imageId`, one image "Show images" shows. Your
 * rating again clears it. What the switches now hide leaves at once.
 */
window.mmRateGeneration = async function(id, value, imageId = null) {
    const { card } = drawnGeneration(id);
    if (!card) return;
    const image = imageId !== null ? (card.all || card.images || []).find((i) => Number(i.id) === Number(imageId))
        : card.matching_count <= 1 ? card.images?.[0] : null;
    const mine = image ? image.user_level : card.user_level;
    const fields = { level: mine === value ? '' : value, hide_nsfw_images: hideNsfwImages,
                     hide_promptless_images: hidePromptlessImages };
    if (image) fields.image_id = image.id;
    else Object.assign(fields, { path: currentModelPath, generation: card.id });
    let answer;
    try {
        const response = await fetch('/model-manager/generations/rate', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(Object.entries(fields).map(([k, v]) => [k, String(v)])).toString(),
        });
        answer = await response.json();
    } catch (error) {
        answer = { success: false, error: error.message };
    }
    if (!answer?.success) {
        setStatus('Could not rate: ' + (answer?.error || 'no answer'), true);
        return;
    }
    if (!image) {
        // Every image of the card may have changed: the list again, where it was.
        const y = window.scrollY || document.documentElement.scrollTop || 0;
        await refreshGenerations();
        window.scrollTo?.(0, y);
        return;
    }
    Object.assign(image, answer.image || {});
    if (answer.visible === false) {
        for (const key of ['images', 'all']) {
            if (card[key]) card[key] = card[key].filter((i) => Number(i.id) !== Number(image.id));
        }
        card.matching_count = Math.max(0, (card.matching_count || 1) - 1);
        if (!card.matching_count || !(card.images || []).length) {
            removeGenerationCard(card.id);
            await refreshGenerationTotals();
            return;
        }
    } else if (card.matching_count <= 1) {
        card.level = image.mm_level;
        card.user_level = image.user_level;
    }
    redrawGenerationCard(card.id);
    await refreshGenerationTotals();
};

/** Fetch the generations again, from page 1. */
function refreshGenerations() {
    return loadGenerationsPage(1);
}

window.mmRefreshGenerations = refreshGenerations;

/**
 * Fetch page `number` of the open model's generations, through the gallery's
 * two switches, and draw it: added after the pages loaded - Load More - or
 * as the first, replacing them.
 *
 * @returns {Promise<boolean>} whether the page arrived and was drawn
 */
async function loadGenerationsPage(number, { append = false } = {}) {
    const path = currentModelPath;
    if (!path) return false;
    const request = ++generationsRequest;
    try {
        const data = await apiCall({ endpoint: '/model-manager/generations/page', params: {
            path, page: number,
            hide_nsfw_images: hideNsfwImages, hide_promptless_images: hidePromptlessImages,
        } });
        if (request !== generationsRequest || path !== currentModelPath) return false;
        if (!data.success) {
            console.error('[ModelManager] Failed to load your generations:', data.error);
            if (append) generationPageError = `Page ${number} could not be loaded: ${data.error || 'no answer'}`;
            return false;
        }
        generationPageError = '';
        generationsState = data.state || null;
        if (typeof generationsState?.stored_generations === 'number') {
            generationsCount = generationsState.stored_generations;
        }
        const cards = data.generations || [];
        const page = { ...(data.page || { number }), first: append ? generationCards.length : 0,
                       cards: cards.length };
        if (append) {
            generationCards = generationCards.concat(cards);
            generationPages.push(page);
            if (galleryTab === 'generations') appendGenerationPage(page, cards);
        } else {
            generationCards = cards;
            generationPages = [page];
            if (galleryTab === 'generations') renderGenerations();
        }
        return true;
    } catch (error) {
        console.error('[ModelManager] Failed to load your generations:', error);
        if (append) generationPageError = `Page ${number} could not be loaded: ${error.message}`;
        return false;
    }
}

window.mmShowMoreGenerations = async function() {
    const last = generationPages[generationPages.length - 1];
    if (loadingGenerationPage || !last || !last.more) return;
    loadingGenerationPage = true;
    refreshGenerationsChrome();
    try {
        await loadGenerationsPage(last.number + 1, { append: true });
    } finally {
        loadingGenerationPage = false;
        refreshGenerationsChrome();
    }
};

/** How many images the generation cards draw now: previews, or all of one. */
function drawnGenerationImages() {
    return generationCards.reduce((n, card) => n + (card.all || card.images || []).length, 0);
}

/** The "Your generations" tab: a banner, and its pages of cards. */
function renderGenerations() {
    const container = document.getElementById('mm_images');
    if (!container) return;
    const state = generationsState;
    container.style.display = 'block';
    if (!state) {
        container.innerHTML = `${imagesHeaderHtml()}
            <div class="mm-images-loading">Loading your generations...</div>`;
        return;
    }
    if (!state.total) {
        container.innerHTML = `${imagesHeaderHtml()}${generationsBannerHtml()}
            <div class="model-images-list"><p class="mm-no-images">No generations with this model yet. Images you generate with it from now on appear here.</p></div>`;
        return;
    }

    container.innerHTML = `
        ${imagesHeaderHtml()}
        ${generationsBannerHtml()}
        <div class="model-images-list">${generationPages.map((page) =>
            generationPageHtml(page, generationCards.slice(page.first, page.first + page.cards))).join('')}</div>
        <div class="mm-images-footer">${generationsFooterHtml()}</div>
    `;
    setupLazyMedia(container);
    refreshResourceButtons();
}

/**
 * Add a page of generations to the end of the list - Load More - and leave
 * the cards already drawn alone, as imageGallery.append() does for the Civitai
 * images; only the banner and the foot are drawn again.
 */
function appendGenerationPage(page, cards) {
    const container = document.getElementById('mm_images');
    const list = container?.querySelector('.model-images-list');
    if (!list || galleryTab !== 'generations' || !list.querySelector('.mm-page-note')) {
        renderGenerations();
        return;
    }
    list.insertAdjacentHTML('beforeend', generationPageHtml(page, cards));
    refreshGenerationsChrome();
    setupLazyMedia(list);
    refreshResourceButtons();
}

/**
 * A drawn generation, by its id: its card, and its place among those drawn.
 * The cards' buttons name a generation by id, not by place: a card taken out
 * in place would leave every later card's buttons naming the one after it.
 */
function drawnGeneration(id) {
    const index = generationCards.findIndex((card) => Number(card.id) === Number(id));
    return { card: generationCards[index], index };
}

/** Draw one generation's card again - its images shown or hidden - and nothing else. */
function redrawGenerationCard(id) {
    const container = document.getElementById('mm_images');
    const { card, index } = drawnGeneration(id);
    const drawn = container?.querySelector(`.mm-generation-card[data-generation="${card?.id}"]`);
    if (!drawn) {
        renderGenerations();
        return;
    }
    drawn.outerHTML = renderGenerationCard(card, index);
    refreshGenerationsChrome();
    setupLazyMedia(container);
}

/**
 * Take a deleted generation's card out where it is, and nothing else: the
 * list used to be loaded again from page 1, and the reader lost their place.
 * Its page's note is not counted again until the next load.
 */
function removeGenerationCard(id) {
    const { index } = drawnGeneration(id);
    if (index < 0) return;
    generationCards.splice(index, 1);
    for (const page of generationPages) {
        if (index >= page.first && index < page.first + page.cards) page.cards -= 1;
        else if (page.first > index) page.first -= 1;
    }
    document.querySelector(`#mm_images .mm-generation-card[data-generation="${Number(id)}"]`)?.remove();
    generationsCount = Math.max(0, generationsCount - 1);
}

/** The gallery's totals afresh - the banner's, the tab's label - leaving the cards as they are. */
async function refreshGenerationTotals() {
    const path = currentModelPath;
    try {
        const data = await apiCall({ endpoint: '/model-manager/generations/page', params: {
            path, page: 1,
            hide_nsfw_images: hideNsfwImages, hide_promptless_images: hidePromptlessImages,
        } });
        if (!data.success || path !== currentModelPath) return;
        generationsState = data.state || generationsState;
        if (typeof generationsState?.stored_generations === 'number') {
            generationsCount = generationsState.stored_generations;
        }
    } catch (error) {
        console.error('[ModelManager] Failed to count your generations:', error);
    }
    refreshGenerationsChrome();
    const label = document.querySelectorAll('#mm_images .mm-gallery-tab')[1];
    if (label) label.textContent = 'Your generations' + ` (${generationsCount})`;
}

/** Draw again what sums the generations up - banner, foot - and not the cards. */
function refreshGenerationsChrome() {
    const container = document.getElementById('mm_images');
    if (!container || galleryTab !== 'generations' || !generationsState) return;
    const banner = container.querySelector('.mm-nsfw-warning');
    if (banner) banner.outerHTML = generationsBannerHtml();
    const footer = container.querySelector('.mm-images-footer');
    if (footer) footer.innerHTML = generationsFooterHtml();
}

/** The generations' banner: the Civitai images' switches, over your images' counts. */
function generationsBannerHtml() {
    const state = generationsState;
    return renderFilterBanner({
        matching: state.filtered,
        total: state.total,
        onScreen: drawnGenerationImages(),
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        both: state.hidden_both || 0,
        switches: [
            { id: 'mm_show_nsfw_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: !hideNsfwImages, hidden: state.hidden_nsfw, count: state.nsfw_count,
              onchange: 'window.mmToggleShowNsfwImages(this.checked)', note: nsfwModelNote() },
            { id: 'mm_show_promptless_images', label: 'Show unusable prompts',
              reason: 'unusable prompt',
              showing: !hidePromptlessImages, hidden: state.hidden_promptless,
              count: state.promptless_count, total: state.promptless_total ?? undefined,
              onchange: 'window.mmToggleShowPromptless(this.checked)' },
        ],
    });
}

/**
 * One page of generations: its separator, after the first, its cards, and
 * its note of what its images were - nothing here comes from Civitai, so the
 * last page says no more than what it held.
 */
function generationPageHtml(page, cards) {
    const html = cards.map((card, i) => renderGenerationCard(card, page.first + i)).join('');
    return (page.number > 1 ? pageSeparator(page.number) : '') + html + pageNoteHtml(page, { end: '' });
}

/** The foot: why a page did not come, and Load More while there is a next. */
function generationsFooterHtml() {
    const last = generationPages[generationPages.length - 1];
    const error = generationPageError
        ? `<div class="mm-page-note">${escapeHtml(generationPageError)}</div>` : '';
    if (!last || !last.more) return error;
    return `${error}<div class="mm-load-more">
             <button class="mm-btn secondary" id="mm_show_more_generations_btn" onclick="window.mmShowMoreGenerations()"
                     ${loadingGenerationPage ? 'disabled' : ''}>
               ${loadingGenerationPage ? 'Loading...' : 'Load More Generations'}
             </button>
           </div>`;
}

/** One generated image: opens full size in a new tab, or says its file is gone. */
function generationImageHtml(img) {
    const url = new URL(img.url, window.location.origin).href;
    const level = nsfwBadgeLabel(img, 'Unknown');
    const badge = level !== 'PG' && level !== 'Unknown' && level !== 'None'
        ? `<span class="mm-nsfw-badge">${escapeHtml(level)}</span>` : '';
    const image = img.exists
        ? `<img data-src="${escapeHtml(url)}" class="mm-lazy-media" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Generated image" loading="lazy"
                ${mediaFallback('', IMAGE_PLACEHOLDER_SVG)}
                data-view-generation-image="${Number(img.id)}" title="Click to view">`
        : `<img src="${IMAGE_PLACEHOLDER_SVG}" alt="Image unavailable"
                title="Image unavailable: its file is no longer where it was saved">`;
    return `<div class="mm-generation-tile">${image}${badge}</div>`;
}

// ------------------------------------------------------------- the viewer
// A card's image opens the shared viewer (shared/viewer.mjs). On the Civitai
// images, it shows the card's own buttons and text (cardSource); on your
// generations, the images the cards show, each with its own Send, Resources,
// Delete and rating.

/** The Civitai images' cards, in the order drawn. */
function civitaiCards() {
    return Array.from(document.querySelectorAll('#mm_images .model-images-list .mm-image-card:not(.mm-generation-card)'));
}

function viewCivitaiImage(index) {
    const cards = civitaiCards();
    const at = cards.findIndex((card) => Number(card.dataset.index) === index);
    if (at < 0) return;
    openViewer(cardSource({
        cards: civitaiCards,
        more: () => !!imageGallery.pages[imageGallery.pages.length - 1]?.more,
        loadMore: () => window.mmLoadMoreImages(),
        videoUrl: viewerVideoUrl,
    }), at);
}

/** Your generations' images the cards show, in order: a card's four, or all once "Show images". */
function generationViewerImages() {
    return generationCards.flatMap((card) => (card.all || card.images || []).map((image) => ({ card, image })));
}

const generationViewerSource = {
    count: () => generationViewerImages().length,
    media: (index) => {
        const { image } = generationViewerImages()[index] || {};
        return { url: image?.exists ? new URL(image.url, window.location.origin).href : IMAGE_PLACEHOLDER_SVG,
                 video: false };
    },
    buttons: (index) => {
        const { card, image } = generationViewerImages()[index] || {};
        if (!image) return '';
        const label = resourceButtonLabel({ meta: image.meta || {} }, currentVersionId);
        return `${ratingRowHtml(image, 'window.mmRateInViewer(%)')}
            <button type="button" class="mm-btn primary mm-btn-small" data-gen-send>Send to ${sendTab(card)}</button>
            ${label ? `<button type="button" class="mm-btn secondary mm-btn-small" data-gen-resources>${label}</button>` : ''}
            <button type="button" class="mm-btn secondary mm-btn-small" data-gen-delete>Delete</button>`;
    },
    details: (index) => {
        const { card, image } = generationViewerImages()[index] || {};
        if (!image) return '';
        const when = card.created_at
            ? new Date(card.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
        const url = new URL(image.url, window.location.origin).href;
        return `<div class="mm-generation-when">${escapeHtml([when, card.mode].filter(Boolean).join(' · '))}</div>
            ${imageTextHtml(image)}
            <div class="mm-dialog-buttons">
                ${image.infotext ? `<button type="button" class="mm-btn secondary mm-btn-small"
                    data-copy="${escapeHtml(image.infotext)}">Copy infotext</button>` : ''}
                ${image.exists ? `<a class="mm-btn secondary mm-btn-small" href="${escapeHtml(url)}" target="_blank"
                    rel="noopener">Open full size</a>` : ''}
            </div>`;
    },
    where: (index) => {
        const { card, image } = generationViewerImages()[index] || {};
        if (!card) return '';
        const shown = (card.all || card.images || []);
        const count = card.matching_count || shown.length;
        const at = shown.indexOf(image) + 1;
        if (count <= 1) return '';
        return shown.length < count ? `${at} of the ${shown.length} shown · ${count} in this generation`
            : `${at} of ${count} in this generation`;
    },
    more: () => !!generationPages[generationPages.length - 1]?.more,
    loadMore: () => window.mmShowMoreGenerations(),
    onClick: (event, index) => {
        const { card, image } = generationViewerImages()[index] || {};
        if (!image) return false;
        if (event.target.closest?.('[data-gen-send]')) {
            rememberScrollPosition(`#mm_images [data-view-generation-image="${Number(image.id)}"]`);
            closeViewer();
            sendInfotext({ infotext: image.infotext, mode: card.mode, meta: image.meta, generationId: card.id });
            return true;
        }
        if (event.target.closest?.('[data-gen-resources]')) {
            showImageResources(image, currentVersionId);
            return true;
        }
        if (event.target.closest?.('[data-gen-delete]')) {
            deleteGenerationImage(card, image);
            return true;
        }
        return false;
    },
};

function viewGenerationImage(imageId) {
    const at = generationViewerImages().findIndex(({ image }) => Number(image.id) === imageId);
    if (at >= 0) openViewer(generationViewerSource, at);
}

/** Rate the image the viewer shows; one the switches now hide leaves, and the next shows in its place. */
window.mmRateInViewer = async function(value) {
    const index = viewerIndex();
    const { card, image } = generationViewerImages()[index] || {};
    if (!image) return;
    await window.mmRateGeneration(card.id, value, image.id);
    if (viewerIndex() === index) showImage(index);
};

/** Delete one image of a generation, from the viewer: asked first, and whether its file goes too. */
async function deleteGenerationImage(card, image) {
    const index = viewerIndex();
    const answer = await askToDelete('Delete this image?', 1);
    if (!answer) return;
    try {
        const response = await fetch(`/model-manager/generations/images/${Number(image.id)}/delete`, {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `delete_files=${answer.withFiles}`,
        });
        const data = await response.json();
        if (!data.success) {
            setStatus('Delete failed: ' + (data.error || 'unknown error'), true);
            return;
        }
    } catch (error) {
        setStatus('Delete failed: ' + error.message, true);
        return;
    }
    for (const key of ['images', 'all']) {
        if (card[key]) card[key] = card[key].filter((i) => Number(i.id) !== Number(image.id));
    }
    card.matching_count = Math.max(0, (card.matching_count || 1) - 1);
    card.image_count = Math.max(0, (card.image_count || 1) - 1);
    if (!(card.all || card.images || []).length) removeGenerationCard(card.id);
    else redrawGenerationCard(card.id);
    await refreshGenerationTotals();
    if (viewerIndex() === index) showImage(index);
}

// A card's image, or a video's ⤢, opens the viewer: from data on it, not an
// inline handler, as every image here opens.
document.addEventListener('click', (event) => {
    const civitai = event.target.closest?.('#mm_images [data-view-index]');
    if (civitai) {
        event.preventDefault();
        viewCivitaiImage(Number(civitai.getAttribute('data-view-index')));
        return;
    }
    const own = event.target.closest?.('#mm_images [data-view-generation-image]');
    // Selecting, a click ticks the card instead (the listener beside Select).
    if (own && !selectingGenerations) {
        event.preventDefault();
        viewGenerationImage(Number(own.getAttribute('data-view-generation-image')));
    }
});

/** A card for one generation: its images on the left, its settings on the right. */
function renderGenerationCard(card, index) {
    const images = card.all || card.images || [];
    const first = (card.images || [])[0] || {};
    const prompt = first.meta?.prompt || '';
    const when = card.created_at
        ? new Date(card.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
        : '';
    const count = card.image_count || images.length;
    const imagesText = card.matching_count < count
        ? `${card.matching_count} of ${count} images here`
        : `${count} ${count === 1 ? 'image' : 'images'}`;
    const preview = (card.images || []);
    const moreThanShown = card.matching_count > preview.length;
    const resourcesLabel = resourceButtonLabel(generationResourcesImage(card), currentVersionId);
    return `
        <div class="mm-image-card mm-generation-card" data-generation="${card.id}">
            <div class="mm-image-left">
                ${selectingGenerations ? `<label class="mm-select-tick" title="Select">
                    <input type="checkbox" data-mm-pick="${Number(card.id)}" ${pickedGenerations.has(card.id) ? 'checked' : ''}></label>` : ''}
                <div class="mm-generation-preview mm-generation-preview-${Math.min(preview.length, 4)}">
                    ${preview.map(generationImageHtml).join('')}
                </div>
                ${rateGenerations ? ratingRowHtml(card.matching_count <= 1 ? first : card,
                                                  `window.mmRateGeneration(${Number(card.id)}, %)`) : ''}
            </div>
            <div class="mm-image-right">
                <div class="mm-generation-when">${escapeHtml([when, card.mode, imagesText].filter(Boolean).join(' · '))}</div>
                ${imageTextHtml(first)}
                <div class="mm-image-actions">
                    <button class="mm-btn primary mm-send-btn" onclick="window.mmSendGeneration(${Number(card.id)})">
                        Send to ${sendTab(card)}
                    </button>
                    <button class="mm-btn secondary" data-copy="${escapeHtml(prompt)}">Copy Prompt</button>
                    ${resourcesLabel ? `<button class="mm-btn secondary" data-resources-generation="${Number(card.id)}"
                        onclick="window.mmShowGenerationResources(${Number(card.id)})">${resourcesLabel}</button>` : ''}
                    ${moreThanShown || card.all ? `<button class="mm-btn secondary" onclick="window.mmShowAllGeneration(${Number(card.id)})">
                        ${card.all ? 'Hide images' : 'Show images'} (${card.matching_count})</button>` : ''}
                    <span class="mm-generation-delete">
                        <button class="mm-btn secondary" onclick="window.mmDeleteGeneration(${Number(card.id)})">Delete</button>
                        <label title="Also delete the image files from disk; off, only the record goes">
                            <input type="checkbox" id="mm_generation_delete_files_${card.id}"> also delete image files
                        </label>
                    </span>
                </div>
                ${card.all ? `<div class="mm-generation-all">${card.all.map((img) => rateGenerations
                    ? `<div class="mm-generation-rated">${generationImageHtml(img)}${ratingRowHtml(img,
                        `window.mmRateGeneration(${Number(card.id)}, %, ${Number(img.id)})`)}</div>`
                    : generationImageHtml(img)).join('')}</div>` : ''}
            </div>
        </div>`;
}

/**
 * Send a generation back to the tab it was made in: Forge set up as it was
 * made with (sendInfotext), then its own infotext, pasted as Forge's PNG
 * Info sends one, and the scheduler and hires fix as every send sets them.
 * An img2img generation's source image is not kept, so img2img gets its
 * settings and a word to add an image.
 */
window.mmSendGeneration = async function(id) {
    const { card } = drawnGeneration(id);
    const first = card?.images?.[0];
    const infotext = card?.infotext || first?.infotext;
    if (!infotext) {
        console.error('[ModelManager] No infotext to send for generation', card?.id);
        return;
    }
    rememberScrollPosition(`#mm_images .mm-generation-card[data-generation="${Number(card.id)}"]`);
    if (await sendInfotext({ infotext, mode: card.mode, meta: first?.meta, generationId: card.id })) {
        console.log(`[ModelManager] Sent generation ${card.id} to ${sendTab(card)}`);
    }
};

/** Show every image of a generation this gallery has, in the card; or hide them again. */
window.mmShowAllGeneration = async function(id) {
    const { card } = drawnGeneration(id);
    if (!card) return;
    if (card.all) {
        card.all = null;
        redrawGenerationCard(id);
        return;
    }
    try {
        const data = await apiCall({ endpoint: `/model-manager/generations/${card.id}/images`, params: {
            path: currentModelPath,
            hide_nsfw_images: hideNsfwImages, hide_promptless_images: hidePromptlessImages,
        } });
        if (data.success) {
            card.all = data.images || [];
            redrawGenerationCard(id);
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load a generation\'s images:', error);
    }
};

/** Delete a generation's record, and its image files when the box beside Delete is ticked. */
window.mmDeleteGeneration = async function(id) {
    const { card } = drawnGeneration(id);
    if (!card) return;
    const withFiles = !!document.getElementById(`mm_generation_delete_files_${card.id}`)?.checked;
    const n = card.image_count || 1;
    const confirmed = confirm(withFiles
        ? `Delete this generation and its ${n} image file${n === 1 ? '' : 's'}?\n\n`
          + 'The image files are deleted from disk. This cannot be undone.'
        : 'Delete this generation\'s record?\n\n'
          + `Its ${n} image file${n === 1 ? ' stays' : 's stay'} on disk; only the record goes, `
          + 'from this gallery and from those of the other models it used.');
    if (!confirmed) return;
    try {
        const response = await fetch(`/model-manager/generations/${card.id}/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `delete_files=${withFiles}`,
        });
        const data = await response.json();
        if (!data.success) {
            setStatus('Delete failed: ' + (data.error || 'unknown error'), true);
            return;
        }
        const failed = data.failed || [];
        setStatus(withFiles
            ? `Deleted the generation and ${data.deleted_files} image file${data.deleted_files === 1 ? '' : 's'}`
              + (failed.length ? `; ${failed.length} could not be deleted` : '')
            : 'Deleted the generation\'s record; its image files are still on disk', failed.length > 0);
        removeGenerationCard(card.id);
        await refreshGenerationTotals();
    } catch (error) {
        setStatus('Delete failed: ' + error.message, true);
    }
};


// How wide the gallery draws a card's image, measured as each list is drawn.
let galleryWidth = null;

// A Civitai image's card, as both tabs draw it (shared/image_card.mjs): this
// tab's Send, Show All and Resources, and the version its gallery is of.
const IMAGE_ACTIONS = { send: 'mmSendToTxt2img', showAll: 'mmShowImageMeta', resources: 'mmShowResources' };
function renderImageCard(img, index) {
    return sharedImageCard(img, index, { width: galleryWidth, exclude: currentVersionId, actions: IMAGE_ACTIONS });
}

// Show All, the same window in both tabs.
window.mmShowImageMeta = (imageIndex) => showImageMeta(imageGallery.images[imageIndex]);


/** Relabel the gallery's Resources buttons from what is known now - your generations' too. */
function updateResourceButtons() {
    document.querySelectorAll('#mm_images [data-resources-index]').forEach((button) => {
        const img = imageGallery.images[Number(button.dataset.resourcesIndex)];
        const label = img ? resourceButtonLabel(img, currentVersionId) : '';
        if (label) button.textContent = label;
        else button.remove();
    });
    document.querySelectorAll('#mm_images [data-resources-generation]').forEach((button) => {
        const { card } = drawnGeneration(Number(button.dataset.resourcesGeneration));
        const label = card ? resourceButtonLabel(generationResourcesImage(card), currentVersionId) : '';
        if (label) button.textContent = label;
        else button.remove();
    });
}
// New hash answers (resources.mjs): the Civitai Browser relabels its own.
window.addEventListener('mm-resource-hashes', updateResourceButtons);

/**
 * Learn what the server already knows about the gallery's hashes - its
 * images', and your generations' - and relabel the buttons with it
 * (learnResourceHashes in resources.mjs).
 */
function refreshResourceButtons(images = [...imageGallery.images, ...generationCards.map(generationResourcesImage)]) {
    return learnResourceHashes(images);
}

// Show the resources behind an image, resolved and merged
window.mmShowResources = function(imageIndex) {
    return showImageResources(imageGallery.images[imageIndex], currentVersionId);
};

/**
 * One of your generations' resources, in the same dialog: its LoRAs and
 * embeddings, as its images list them (api/generations.image_resources).
 */
window.mmShowGenerationResources = function(id) {
    const { card } = drawnGeneration(id);
    return card ? showImageResources(generationResourcesImage(card), currentVersionId) : undefined;
};

/**
 * A generation card's resources as one image's: every LoRA and embedding of
 * the images it holds, each once - a batch's iterations can each load their
 * own.
 */
function generationResourcesImage(card) {
    const seen = new Set();
    const resources = [];
    for (const img of card.all || card.images || []) {
        for (const r of (img.meta || {}).resources || []) {
            const key = `${(r.hash || '').toLowerCase()}|${r.type}:${r.name}`;
            if (seen.has(key)) continue;
            seen.add(key);
            resources.push(r);
        }
    }
    return { meta: { resources } };
}

// Load the next page, filled from Civitai first if the library cannot fill it.
window.mmLoadMoreImages = () => imageGallery.more((number) => loadGalleryPage(number, { append: true }));

/**
 * The version whose gallery is showing: the one picked in the details panel,
 * or the grid's own row where the model has one version.
 */
function shownVersion(model) {
    return (currentVersions.length && currentVersions[selectedVersionIndex]) || model;
}

window.mmSendToTxt2img = async function(imageIndex) {
    const img = imageGallery.images[imageIndex];
    if (!img || !img.meta) {
        console.error('[ModelManager] No image data at index', imageIndex);
        return;
    }

    // Save current scroll position before navigating away
    rememberScrollPosition(`#mm_images .mm-image-card[data-index="${Number(imageIndex)}"]`);

    const model = currentModels[selectedModelIndex];
    await sendGalleryImage({ img, model, version: model ? shownVersion(model) : null });
};

// Close details panel
// Jump straight to one model, e.g. from the Civitai Browser: this tab first,
// once it shows - the grid measures itself, and a hidden tab measures nothing.
// Every filter is relaxed first - an active NSFW, type or SFW-only filter
// would otherwise hide the very model the caller asked to show. SFW only was
// once left on, and a generation's model with one explicit image was "not
// found", its file in the library.
async function showModel(query) {
    await showTab('modelManager');
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };
    const setChecked = (selector, checked) => {
        document.querySelectorAll(selector).forEach(cb => { cb.checked = checked; });
    };

    setValue('mm_type', '');
    setValue('mm_civitai', '');
    setValue('mm_base_model', '');
    setValue('mm_is_bookmarked', '');
    setValue('mm_min_versions', '');
    setValue('mm_min_size', '');
    setValue('mm_max_size', '');

    setChecked('#mm_nsfw_panel input[type="checkbox"][value]', true);
    const useMax = document.getElementById('mm_nsfw_use_max');
    if (useMax) useMax.checked = true;
    updateNsfwDisplay();

    setChecked('#mm_commercial_panel input[type="checkbox"][value]', true);
    updateCommercialDisplay();

    const sfwOnly = document.getElementById('mm_sfw_only');
    if (sfwOnly) sfwOnly.checked = false;
    syncSfwOnlyBanner();

    setValue('mm_checkpoint_type', '');
    setValue('mm_allow_derivatives', '');
    setValue('mm_allow_different_license', '');

    setValue('mm_search', query);

    await loadModels(1);
    // The model asked for is in whichever tab holds it: a pinned one is not
    // in Unpinned.
    if (!currentModels.length && gridTabCounts) {
        const other = gridTab === 'pinned' ? 'others' : 'pinned';
        if (gridTabCounts[other] > 0) {
            gridTab = other;
            updateGridTabs();
            await loadModels(1);
        }
    }

    // A targeted lookup normally returns exactly one model - open it
    if (currentModels.length === 1) {
        await window.mmSelectModel(0);
    } else if (currentModels.length === 0) {
        // A file looked up by its path is named by its file name.
        const what = query.startsWith('path:') ? query.slice(5).split(/[\\/]/).pop() : query;
        setStatus(`Nothing found for "${what}". It may not be downloaded, or the database needs a refresh.`, true);
    }
}
provide('modelManager.showModel', showModel);

/**
 * Show one model file here, from another tab: this tab, the file's model,
 * and the version that file is - not the one the model's row happens to name.
 * The Generations tab's "Show model in Model Manager" asks with the
 * checkpoint a generation's record names.
 */
async function showFile(path) {
    if (!path) return;
    await showModel(`path:${path}`);
    const wanted = currentVersions.findIndex((v) => (v.file_path || '').toLowerCase() === path.toLowerCase());
    if (wanted >= 0) await window.mmSelectVersion(wanted);
}
provide('modelManager.showFile', showFile);

/**
 * Show one version here, from another tab, by its id - this tab, its model,
 * and that version. What the Generations tab asks for: a path was passed
 * about before, and printed back as "path:F:\..." when nothing was found.
 */
async function showVersion(versionId) {
    const id = Number(versionId);
    if (!id) return;
    await showModel(`version:${id}`);
    const wanted = currentVersions.findIndex((v) => Number(v.id) === id);
    if (wanted >= 0) await window.mmSelectVersion(wanted);
}
provide('modelManager.showVersion', showVersion);

/**
 * The Information table's first row. The button works out which version to
 * send when pressed - the one shown then - rather than carrying an id that a
 * switch of version would leave behind.
 */
function showInCivitaiRow() {
    return `<tr class="mm-show-in-cb-row"><td colspan="2">`
        + `<button class="mm-btn secondary mm-btn-small" onclick="window.mmShowInCivitaiBrowser()" `
        + `title="Open this version in the Civitai Browser tab">Show in Civitai Browser</button></td></tr>`;
}

/** The query that shows the version on screen in the Civitai Browser. */
function civitaiBrowserQuery() {
    const model = currentModels[selectedModelIndex];
    const modelId = safeId(model?.model_id);
    if (!modelId) return null;
    const versionId = safeId(remoteVersionId !== null ? remoteVersionId : shownVersion(model).id);
    return versionId ? `model:${modelId} version:${versionId}` : `model:${modelId}`;
}

window.mmShowInCivitaiBrowser = function() {
    openInCivitaiBrowser(civitaiBrowserQuery());
};

/** "model:<id> version:<id>" in the Civitai Browser tab, which shows itself. */
function openInCivitaiBrowser(query) {
    if (!query) return;
    if (!ready('civitaiBrowser.showModel')) {
        setStatus('Civitai Browser tab has not initialised yet - open it once and try again.', true);
        return;
    }
    call('civitaiBrowser.showModel', query);
}

window.mmCloseDetails = function() {
    const detailsContainer = document.getElementById('mm_details');
    const imagesContainer = document.getElementById('mm_images');

    if (detailsContainer) detailsContainer.style.display = 'none';
    if (imagesContainer) imagesContainer.style.display = 'none';

    document.querySelectorAll('.model-card').forEach(card => card.classList.remove('selected'));
    selectedModelIndex = null;
};

// ==================== SYNC FUNCTIONS ====================

// Start sync with Civitai
/**
 * Identify files by hashing them, and ask Civitai what they are.
 *
 * `targets` picks which of the files on disk to read: all of them, only the
 * ones that already resolve to a Civitai model, or only the ones that do not.
 */
async function startSync(targets = 'all') {
    if (isSyncing) return;

    isSyncing = true;
    updateSyncUI(true);
    setStatus(`Starting force sync (${targets})...`);

    try {
        const bodyData = `force=true&targets=${encodeURIComponent(targets)}`;
        console.log('[ModelManager] Sending sync request with body:', bodyData);

        const response = await fetch('/model-manager/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: bodyData
        });

        const data = await response.json();

        if (data.success) {
            // Start polling for progress
            syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
        } else {
            setStatus('Sync failed: ' + (data.error || 'Unknown error'), true);
            isSyncing = false;
            updateSyncUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Sync error:', error);
        setStatus('Sync error: ' + error.message, true);
        isSyncing = false;
        updateSyncUI(false);
    }
}

// Poll sync progress
async function pollSyncProgress() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/sync/progress' });

        if (data.success && data.progress) {
            const p = data.progress;

            // Update progress bar
            const percent = p.total > 0 ? (p.processed / p.total * 100) : 0;
            const fillEl = document.getElementById('mm_sync_fill');
            const textEl = document.getElementById('mm_sync_text');

            if (fillEl) fillEl.style.width = percent + '%';
            if (textEl) {
                textEl.textContent = `Syncing: ${p.processed}/${p.total} - ${p.current_model || 'Preparing...'}`;
            }

            // Update status
            setStatus(`Sync: ${p.synced} synced, ${p.not_found} not found, ${p.skipped} skipped, ${p.errors} errors`);

            // Check if complete
            if (p.is_complete) {
                clearInterval(syncPollInterval);
                syncPollInterval = null;
                isSyncing = false;
                updateSyncUI(false);

                // Show final status
                const errorInfo = p.errors > 0 ? ` (${p.error_messages.slice(-3).join('; ')})` : '';
                setStatus(`Sync complete: ${p.synced} synced, ${p.not_found} not found, ${p.skipped} skipped, ${p.errors} errors${errorInfo}`);
                loadBaseModelOptions();

                // Reload models to show updated data
                if (p.synced > 0) {
                    setTimeout(loadModels, 500);
                }
            }
        }
    } catch (error) {
        console.error('[ModelManager] Progress poll error:', error);
    }
}

// Cancel sync
async function cancelSync() {
    try {
        await fetch('/model-manager/sync/cancel', { method: 'POST' });
        setStatus('Canceling sync...');
    } catch (error) {
        console.error('[ModelManager] Cancel error:', error);
    }
}

/**
 * Refresh Civitai data for models that were already identified.
 *
 * "Sync with Civitai" hashes every file to work out what it is. Once that
 * has happened the answer is stored, so this only re-reads the metadata,
 * a hundred models per request. Images are optional because they are the
 * slow half - they cannot be batched.
 */
// The sync dialog asks two questions - which models, and how much of each -
// and answers a third before either is committed to: what it will cost. The
// estimate comes from the server, counted by the same code that does the
// batching, so the figure cannot drift from what actually happens.

let syncEstimateTimer = null;
let syncResultPaths = null;     // resolved lazily, for the "these results" scope
let syncDepthBeforeRehash = null;   // restored when the scope leaves "force"
let syncImagesWereOn = false;       // to tell "just switched on" from "still on"
let syncUnidentified = null;        // {unidentified, never_asked, asked_not_found, identified}

/**
 * The hashing option's own cost, in files rather than requests.
 *
 * The asterisk is the point: this comes from the database, which holds what
 * the last scan found. A file added since is not counted, and the sync walks
 * the model folders itself - so the number is a floor.
 */
function describeForceSync(counts, mode) {
    if (!counts) return 'Scans your model folders and reads each file in full.';

    const files = mode === 'identified' ? counts.identified
        : mode === 'unidentified' ? counts.unidentified
        : counts.total;
    const head = `${files.toLocaleString()} files* to read in full`;

    if (mode === 'identified') {
        return `${head} - the ones that already resolve to a Civitai model,`
            + ' read again in case anything about them has changed.';
    }
    if (mode === 'unidentified') {
        const parts = [];
        if (counts.never_asked) {
            parts.push(`${counts.never_asked.toLocaleString()} never asked about`);
        }
        if (counts.asked_not_found) {
            parts.push(`${counts.asked_not_found.toLocaleString()} asked before and not on Civitai`);
        }
        return `${head}${parts.length ? ` - ${parts.join(', ')}` : ''}.`;
    }
    return `${head} - every model you have, identified or not.`;
}

/** The counts beside each force-sync mode. */
function updateForceModeLabels() {
    const select = document.getElementById('mm_sync_force_mode');
    if (!select) return;
    const counts = syncUnidentified;
    const LABELS = [['all', 'All', 'total'],
                    ['identified', 'All identified', 'identified'],
                    ['unidentified', 'All unidentified', 'unidentified']];
    Array.from(select.options).forEach((option) => {
        const row = LABELS.find((l) => l[0] === option.value);
        if (!row) return;
        option.textContent = counts
            ? `${row[1]} (${counts[row[2]].toLocaleString()}*)`
            : row[1];
    });
}

function syncDialogChoice() {
    const scope = document.querySelector('input[name="mm_sync_scope"]:checked')?.value || 'all';
    return {
        scope,
        staleDays: scope === 'stale'
            ? parseInt(document.getElementById('mm_sync_stale_days')?.value || '0', 10)
            : 0,
        downloadedDays: scope === 'downloaded'
            ? parseInt(document.getElementById('mm_sync_downloaded_days')?.value || '0', 10)
            : 0,
        images: document.getElementById('mm_sync_images')?.checked || false,
        prompts: document.getElementById('mm_sync_prompts')?.checked || false,
        // A force sync reads files rather than asking about ids, so it is a
        // scope of its own rather than a depth.
        forceMode: scope === 'force'
            ? (document.getElementById('mm_sync_force_mode')?.value || 'all')
            : null,
    };
}

/** The file paths the filter bar currently selects, fetched once per opening. */
async function resolveResultPaths() {
    if (syncResultPaths) return syncResultPaths;
    const filters = getFilters();
    filters.paths_only = true;
    const data = await apiCall({ endpoint: '/model-manager/models', params: filters });
    syncResultPaths = (data && data.success) ? (data.paths || []) : [];
    return syncResultPaths;
}

/**
 * Ask the server what the current choice would cost, and show it.
 *
 * Debounced, because every control in the dialog calls it.
 */
function refreshSyncEstimate() {
    clearTimeout(syncEstimateTimer);
    syncEstimateTimer = setTimeout(async () => {
        const choice = syncDialogChoice();
        const estimateEl = document.getElementById('mm_sync_estimate');
        const startBtn = document.getElementById('mm_sync_dialog_start');

        if (choice.scope === 'force') {
            // Costed in files, not requests: this one is bound by reading
            // bytes off the disk. The count comes from the database, so
            // opening the dialog stays instant - the sync walks the model
            // folders itself and may find more, which the asterisk says.
            if (estimateEl) {
                estimateEl.textContent = describeForceSync(syncUnidentified, choice.forceMode)
                    + ' Also scans your model folders for files that are not in'
                    + ' the database yet, so the real number may be higher.';
            }
            if (startBtn) startBtn.disabled = false;
            return;
        }

        try {
            const params = {
                include_images: choice.images,
                include_prompts: choice.images && choice.prompts,
                stale_days: choice.staleDays,
                downloaded_days: choice.downloadedDays,
            };
            if (choice.scope === 'results') {
                params.paths = (await resolveResultPaths()).join(',');
            }
            const data = await apiCall({ endpoint: '/model-manager/sync/estimate', params });
            if (!data || !data.success) return;

            const { estimate, windows } = data;
            const { requests } = estimate;

            // Requests, not minutes: how long they take depends on the rate
            // limit, the round trip and any retries - none of which this knows,
            // and two of which differ from one machine to the next.
            //
            // The prompt count is an estimate - a gallery's size is only known
            // once it is fetched, so the server works from the ones already
            // cached - and says so with a ~, as does a total that includes it.
            // The rest are exact counts of the requests the sync will make.
            const cost = (id, count, approximate = false) => {
                const el = document.getElementById(id);
                if (el) {
                    el.textContent = count
                        ? `${approximate ? '~' : ''}${count.toLocaleString()} req`
                        : '-';
                }
            };
            // The checkpoint trained/merged check is part of fetching metadata
            // (two requests per hundred checkpoints). The total always counted
            // it; no line did, so the lines came to less than the total.
            cost('mm_cost_metadata', requests.metadata + (requests.checkpoints || 0));
            cost('mm_cost_images', requests.images);
            cost('mm_cost_prompts', requests.prompts, true);
            const totalApproximate = requests.prompts > 0;

            syncUnidentified = data.unidentified || null;
            updateForceModeLabels();

            fillWindows('mm_sync_stale_days', windows);
            fillWindows('mm_sync_downloaded_days', data.download_windows);

            const allEl = document.getElementById('mm_scope_all');
            if (allEl && typeof estimate.all_versions === 'number') {
                allEl.textContent = `(${estimate.all_versions})`;
            }
            const resultsEl = document.getElementById('mm_scope_results');
            if (resultsEl && syncResultPaths) {
                resultsEl.textContent = `(${syncResultPaths.length})`;
            }

            if (estimateEl) {
                estimateEl.textContent = estimate.versions
                    ? `${estimate.versions.toLocaleString()} models`
                      + ` - ${totalApproximate ? '~' : ''}${requests.total.toLocaleString()}`
                      + ' requests to Civitai'
                    : 'Nothing selected - this would do nothing.';
            }
            if (startBtn) startBtn.disabled = !estimate.versions;
        } catch (error) {
            console.error('[ModelManager] Sync estimate failed:', error);
        }
    }, TIMING.estimate);
}

/** A window dropdown, each option carrying how many models it would take. */
function fillWindows(selectId, windows) {
    const select = document.getElementById(selectId);
    if (!select || !windows || !windows.length) return;

    const chosen = select.value;
    select.textContent = '';
    windows.forEach((w) => {
        const option = document.createElement('option');
        option.value = String(w.days);
        option.textContent = `${w.label} (${w.versions})`;
        select.appendChild(option);
    });
    select.value = chosen || String(windows[2] ? windows[2].days : 7);
}

/**
 * "These search results" only means something once a search has run.
 *
 * Before that the grid is empty, so the option would either sync nothing or
 * quietly sync everything depending on how the empty filter set was read. It
 * is disabled instead, and carries its count once there is one - without
 * waiting to be picked, since the count is half of what makes it choosable.
 */
async function syncDialogResultsScope() {
    const radio = document.querySelector('input[name="mm_sync_scope"][value="results"]');
    if (!radio) return;
    const row = radio.closest('.mm-dialog-option');
    const label = document.getElementById('mm_scope_results');

    const searched = totalModels > 0;
    radio.disabled = !searched;
    if (row) row.classList.toggle('mm-dialog-muted', !searched);

    if (!searched) {
        if (radio.checked) {
            const all = document.querySelector('input[name="mm_sync_scope"][value="all"]');
            if (all) all.checked = true;
        }
        if (label) label.textContent = '';
        return;
    }

    if (label) label.textContent = '...';
    const paths = await resolveResultPaths();
    if (label) label.textContent = `(${paths.length})`;
}

/** Prompts only mean anything once the images they belong to are refetched. */
function syncDialogDependencies() {
    const images = document.getElementById('mm_sync_images');
    const prompts = document.getElementById('mm_sync_prompts');
    const promptsRow = document.getElementById('mm_sync_prompts_row');
    const imagesRow = images && images.closest('.mm-dialog-option');
    const scope = document.querySelector('input[name="mm_sync_scope"]:checked');
    const hashing = !!(scope && scope.value === 'force');

    // Identifying a file fetches its metadata, its gallery and the prompts
    // behind it - sync_model() does all three - so the depth is not a choice
    // while it is on. Whatever was chosen before comes back afterwards.
    if (hashing && images && prompts) {
        if (!syncDepthBeforeRehash) {
            syncDepthBeforeRehash = { images: images.checked, prompts: prompts.checked };
        }
        images.checked = true;
        prompts.checked = true;
    } else if (!hashing && syncDepthBeforeRehash && images && prompts) {
        images.checked = syncDepthBeforeRehash.images;
        prompts.checked = syncDepthBeforeRehash.prompts;
        syncDepthBeforeRehash = null;
    }

    // A disabled box must not sit there ticked: that reads as "this will
    // happen", when the whole point of disabling it is that it cannot. So
    // prompts follow images on the way down, and are offered again - ticked,
    // since that is the useful default - when images come back.
    if (!hashing && images && prompts) {
        if (!images.checked) {
            prompts.checked = false;
        } else if (!syncImagesWereOn) {
            prompts.checked = true;
        }
    }
    if (images) syncImagesWereOn = images.checked;

    if (images) images.disabled = hashing;
    if (prompts) prompts.disabled = hashing || !images.checked;
    if (imagesRow) imagesRow.classList.toggle('mm-dialog-muted', hashing);
    if (promptsRow) promptsRow.classList.toggle('mm-dialog-muted', hashing || !images.checked);

    updateForceModeLabels();
}

function openSyncDialog() {
    if (isSyncing) return;
    syncResultPaths = null;
    const dialog = document.getElementById('mm_sync_dialog');
    if (!dialog) return;
    dialog.style.display = 'flex';
    syncDialogDependencies();
    syncDialogResultsScope();
    refreshSyncEstimate();
}

/**
 * The Sync dialog, from elsewhere - a note: with Force sync and its mode
 * chosen if asked ("unidentified": the files Civitai has not identified
 * yet). Opened, never started.
 */
provide('modelManager.openSyncDialog', ({ force = null } = {}) => {
    openSyncDialog();
    if (!force) return;
    const scope = document.querySelector('input[name="mm_sync_scope"][value="force"]');
    const mode = document.getElementById('mm_sync_force_mode');
    if (mode) mode.value = force;
    if (scope) {
        scope.checked = true;
        scope.dispatchEvent(new Event('change', { bubbles: true }));
    }
    mode?.dispatchEvent(new Event('change', { bubbles: true }));
});

function closeSyncDialog() {
    const dialog = document.getElementById('mm_sync_dialog');
    if (dialog) dialog.style.display = 'none';
}

async function startSyncFromDialog() {
    const choice = syncDialogChoice();
    closeSyncDialog();

    if (choice.scope === 'force') {
        startSync(choice.forceMode || 'all');
        return;
    }

    const paths = choice.scope === 'results' ? await resolveResultPaths() : null;
    startMetadataSync({
        includeImages: choice.images,
        includePrompts: choice.images && choice.prompts,
        staleDays: choice.staleDays,
        downloadedDays: choice.downloadedDays,
        paths,
    });
}

async function startMetadataSync({ includeImages = false, includePrompts = true,
                                   staleDays = 0, downloadedDays = 0,
                                   paths = null } = {}) {
    if (isSyncing) return;

    isSyncing = true;
    updateSyncUI(true);
    setStatus(includeImages
        ? 'Refreshing Civitai metadata and images...'
        : 'Refreshing Civitai metadata...');

    try {
        const body = new URLSearchParams({
            include_images: String(includeImages),
            include_prompts: String(includePrompts),
            stale_days: String(staleDays),
            downloaded_days: String(downloadedDays),
        });
        if (paths && paths.length) body.set('paths', paths.join(','));

        const response = await fetch('/model-manager/sync/metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString()
        });
        const data = await response.json();

        if (data.success) {
            // pollSyncProgress() is a single sample that clears this
            // interval once the run reports complete - without the
            // interval the bar freezes and isSyncing is never released.
            syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
        } else {
            setStatus(`Metadata sync failed: ${data.error}`, true);
            isSyncing = false;
            updateSyncUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Metadata sync error:', error);
        setStatus(`Metadata sync failed: ${error.message}`, true);
        isSyncing = false;
        updateSyncUI(false);
    }
}

// Update UI based on sync state
function updateSyncUI(syncing) {
    const syncBtn = document.getElementById('mm_sync_btn');
    const cancelBtn = document.getElementById('mm_sync_cancel_btn');
    const progressDiv = document.getElementById('mm_sync_progress');
    const loadBtn = document.getElementById('mm_load_btn');
    const refreshBtn = document.getElementById('mm_refresh_btn');

    if (syncBtn) syncBtn.disabled = syncing || isScanning;
    if (loadBtn) loadBtn.disabled = syncing || isScanning;
    if (refreshBtn) refreshBtn.disabled = syncing || isScanning;
    if (cancelBtn) cancelBtn.style.display = syncing ? 'inline-block' : 'none';
    if (progressDiv) progressDiv.style.display = syncing ? 'block' : 'none';

    // Reset progress bar when starting
    if (syncing) {
        const fillEl = document.getElementById('mm_sync_fill');
        const textEl = document.getElementById('mm_sync_text');
        if (fillEl) fillEl.style.width = '0%';
        if (textEl) textEl.textContent = 'Preparing...';
    }
}

// ==================== SCAN/REFRESH FUNCTIONS ====================

// Start database refresh scan
/**
 * Say what Scan Disk will do before it does it.
 *
 * It adds and removes rows to match what is on disk, which is not something to
 * discover after the fact - and unlike the sync dialog there is nothing to
 * choose here, so it is a confirmation rather than a form.
 */
function openScanDialog() {
    if (isScanning || isSyncing) return;
    const dialog = document.getElementById('mm_scan_dialog');
    if (!dialog) {
        startScan();     // no dialog in the page: do the thing rather than nothing
        return;
    }
    // Every scan starts as the usual one: reading every header, or moving
    // files, is asked for each time.
    const reread = document.getElementById('mm_scan_reread');
    if (reread) reread.checked = false;
    const move = document.getElementById('mm_scan_move');
    if (move) move.checked = false;
    dialog.style.display = 'flex';
    showMisplaced();
}

/**
 * Which files Scan Disk would move into their type's folder, before anyone
 * ticks the box: the count, why each would move, and the ones that will stay
 * because their name is taken there. Its box is never ticked for anyone - a
 * note's button ticks "Re-evaluate file headers", and must not move files.
 */
async function showMisplaced() {
    const move = document.getElementById('mm_scan_move');
    const note = document.getElementById('mm_scan_move_note');
    const details = document.getElementById('mm_scan_misplaced');
    const list = document.getElementById('mm_scan_misplaced_list');
    if (!move || !note) return;
    move.disabled = true;
    if (details) details.hidden = true;
    let files = [];
    try {
        const data = await apiCall({ endpoint: '/model-manager/scan/misplaced' });
        files = data.success ? data.files || [] : null;
    } catch (e) {
        files = null;
    }
    if (files === null) {
        setText(note, 'Could not tell which files are in another type\'s folder.');
        return;
    }
    if (!files.length) {
        setText(note, 'No file is in a folder for another type.');
        return;
    }
    const staying = files.filter((f) => f.clash).length;
    setText(note, `${files.length} file${files.length === 1 ? ' is' : 's are'} in a folder for another type - `
        + 'a VAE in Stable-diffusion, say, where Forge offers it as a checkpoint. Ticked, each is moved '
        + 'with its .civitai.info and preview into its type\'s folder; its place in the library, its pin '
        + 'and its generations go with it.'
        + (staying ? ` ${staying} will stay where ${staying === 1 ? 'it is' : 'they are'}: `
            + 'a file of that name is already in the folder.' : ''));
    const clashText = { same: 'the same file is already there', different: 'a different file of that name is already there',
                        exists: 'a file of that name is already there' };
    if (list) {
        list.innerHTML = files.map((f) => `<li>${escapeHtml(f.path)} → ${escapeHtml(f.to)}
            <span class="mm-scan-misplaced-why">(${escapeHtml(f.file_type)}${f.identified_by ? ': ' + escapeHtml(f.identified_by) : ''})${
            f.clash ? ' - stays: ' + clashText[f.clash] : ''}</span></li>`).join('');
    }
    if (details) details.hidden = false;
    move.disabled = false;
}

/** Scan Disk's dialog, from elsewhere - a note: "Re-evaluate file headers" ticked if asked. */
provide('modelManager.openScanDialog', ({ rereadHeaders = false } = {}) => {
    openScanDialog();
    const reread = document.getElementById('mm_scan_reread');
    if (reread) reread.checked = rereadHeaders;
});

function closeScanDialog() {
    const dialog = document.getElementById('mm_scan_dialog');
    if (dialog) dialog.style.display = 'none';
}

/**
 * @param {{rereadHeaders?: boolean, moveMisplaced?: boolean}} options -
 *     rereadHeaders: read what every file is from its header again, not only
 *     new or changed files. moveMisplaced: move files in another type's
 *     folder into their own.
 */
async function startScan({ rereadHeaders = false, moveMisplaced = false } = {}) {
    if (isScanning || isSyncing) return;

    isScanning = true;
    updateScanUI(true);
    setStatus('Starting database refresh...');

    try {
        const response = await fetch('/model-manager/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reread_headers: rereadHeaders, move_misplaced: moveMisplaced }),
        });

        const data = await response.json();

        if (data.success) {
            // Start polling for progress
            scanPollInterval = setInterval(pollScanProgress, TIMING.scanPoll);
        } else {
            setStatus('Scan failed: ' + (data.error || 'Unknown error'), true);
            isScanning = false;
            updateScanUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Scan error:', error);
        setStatus('Scan error: ' + error.message, true);
        isScanning = false;
        updateScanUI(false);
    }
}

// Poll scan progress
async function pollScanProgress() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/scan/progress' });

        if (data.success && data.progress) {
            const p = data.progress;

            // Update progress bar
            const percent = p.total > 0 ? (p.processed / p.total * 100) : 0;
            const fillEl = document.getElementById('mm_scan_fill');
            const textEl = document.getElementById('mm_scan_text');

            if (fillEl) fillEl.style.width = percent + '%';
            if (textEl) {
                textEl.textContent = `Scanning: ${p.processed}/${p.total} - ${p.current_file || 'Preparing...'}`;
            }

            // Update status
            setStatus(`Scan: ${p.processed}/${p.total} models processed`);

            // Check if complete
            if (p.is_complete) {
                clearInterval(scanPollInterval);
                scanPollInterval = null;
                isScanning = false;
                updateScanUI(false);

                // Show final status
                const errorInfo = p.error_count > 0 ? ` (${p.error_count} errors)` : '';
                const moveInfo = (p.moved ? `, ${p.moved} moved into their type's folder` : '')
                    + (p.not_moved ? `, ${p.not_moved} left where ${p.not_moved === 1 ? 'it was' : 'they were'} (a file of that name is already there)` : '');
                setStatus(`Scan complete: ${p.processed} models indexed${moveInfo}${errorInfo}`);
                loadBaseModelOptions();

                // Reload models to show updated data
                setTimeout(loadModels, 500);
            }
        }
    } catch (error) {
        console.error('[ModelManager] Scan progress poll error:', error);
    }
}

// Cancel scan
async function cancelScan() {
    try {
        await fetch('/model-manager/scan/cancel', { method: 'POST' });
        setStatus('Canceling scan...');
    } catch (error) {
        console.error('[ModelManager] Scan cancel error:', error);
    }
}

// Update UI based on scan state
function updateScanUI(scanning) {
    const refreshBtn = document.getElementById('mm_refresh_btn');
    const scanCancelBtn = document.getElementById('mm_scan_cancel_btn');
    const scanProgressDiv = document.getElementById('mm_scan_progress');
    const loadBtn = document.getElementById('mm_load_btn');
    const syncBtn = document.getElementById('mm_sync_btn');

    if (refreshBtn) refreshBtn.disabled = scanning || isSyncing;
    if (loadBtn) loadBtn.disabled = scanning || isSyncing;
    if (syncBtn) syncBtn.disabled = scanning || isSyncing;
    if (scanCancelBtn) scanCancelBtn.style.display = scanning ? 'inline-block' : 'none';
    if (scanProgressDiv) scanProgressDiv.style.display = scanning ? 'block' : 'none';

    // Reset progress bar when starting
    if (scanning) {
        const fillEl = document.getElementById('mm_scan_fill');
        const textEl = document.getElementById('mm_scan_text');
        if (fillEl) fillEl.style.width = '0%';
        if (textEl) textEl.textContent = 'Preparing...';
    }
}

// Utility functions

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}


function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString();
    } catch {
        return dateStr;
    }
}

// Format commercial use value for display
// Value comes in PostgreSQL array format: "{Image,RentCivit,Rent}"
function formatCommercialUse(value) {
    if (!value) return 'Unknown';

    const labels = {
        'None': 'No commercial use',
        'Image': 'Sell generated images',
        'Rent': 'Use in generation services',
        'RentCivit': 'Civitai generation only',
        'Sell': 'Sell model allowed'
    };

    // Parse brace-delimited format: {val1,val2,val3}
    const match = value.match(/^\{(.+)\}$/);
    if (match) {
        const values = match[1].split(',').map(v => v.trim());
        return values.map(v => labels[v] || v).join(', ');
    }

    // Fallback for single value or other formats
    return labels[value] || value;
}


/**
 * Remember what was sent, for "Previous Position", before a Send takes the
 * page to txt2img or img2img: `target`, a selector for the image or card sent,
 * which the button brings back into view - from the viewer, the image shown
 * last, not the one it opened on. And where the page was, for when that is no
 * longer drawn: where it was when the viewer opened, if it is open, as the
 * page is held still while it is.
 */
function rememberScrollPosition(target) {
    const pos = viewerPageScroll() ?? (window.scrollY || document.documentElement.scrollTop || 0);
    localStorage.setItem('mm_scroll_position', String(pos));
    if (target) localStorage.setItem('mm_scroll_target', target);
    else localStorage.removeItem('mm_scroll_target');
    updateScrollRestoreButton();
    console.log('[ModelManager] Saved scroll position:', pos, target || '');
}

// Scroll position restore functionality
function updateScrollRestoreButton() {
    const savedPos = localStorage.getItem('mm_scroll_position');
    let btn = document.getElementById('mm_scroll_restore_btn');

    if ((savedPos && parseInt(savedPos) > 0) || localStorage.getItem('mm_scroll_target')) {
        // Create button if it doesn't exist
        if (!btn) {
            const buttonsRow = document.querySelector('.filter-buttons-row');
            if (buttonsRow) {
                btn = document.createElement('button');
                btn.id = 'mm_scroll_restore_btn';
                btn.className = 'mm-btn secondary mm-scroll-restore-btn';
                btn.innerHTML = '↓ Previous Position';
                btn.title = 'Scroll to previous position. Right-click to clear.';
                btn.onclick = window.mmRestoreScrollPosition;
                btn.oncontextmenu = function(e) {
                    e.preventDefault();
                    localStorage.removeItem('mm_scroll_position');
                    localStorage.removeItem('mm_scroll_target');
                    btn.style.display = 'none';
                    console.log('[ModelManager] Cleared scroll position');
                };
                // Directly before Load Models, which stays the rightmost
                // thing on the row. First child would put it left of the
                // sync/scan group, at the other end of the row entirely.
                const loadBtn = document.getElementById('mm_load_btn');
                buttonsRow.insertBefore(btn, loadBtn || null);
            }
        }
        if (btn) {
            btn.style.display = 'inline-flex';
        }
    } else {
        if (btn) {
            btn.style.display = 'none';
        }
    }
}

window.mmRestoreScrollPosition = function() {
    const target = localStorage.getItem('mm_scroll_target');
    let sent = null;
    try {
        sent = target ? document.querySelector(target) : null;
    } catch (e) { /* not a selector: the position instead */ }
    if (sent) {
        sent.scrollIntoView({ block: 'center', behavior: 'smooth' });
        console.log('[ModelManager] Restored to the image sent');
        return;
    }
    const savedPos = localStorage.getItem('mm_scroll_position');
    if (savedPos) {
        const pos = parseInt(savedPos);
        window.scrollTo({ top: pos, behavior: 'smooth' });
        console.log('[ModelManager] Restored scroll position:', pos);
    }
};

// Save Search: one set of filters, in the database (savedSearch in
// filters.mjs) - it was in this browser's storage, and is moved from there the
// first time. It fills the filters when the tab opens; Load Models, which
// waits for it, loads them.
const LEGACY_SAVED_FILTERS = 'mm_saved_filters';

/** The filters as the bar shows them, as Save Search keeps them. */
function currentSearchFilters() {
    const filters = {
        search: document.getElementById('mm_search')?.value || '',
        type: document.getElementById('mm_type')?.value || '',
        base_model: document.getElementById('mm_base_model')?.value || '',
        civitai: document.getElementById('mm_civitai')?.value || '',
        is_bookmarked: document.getElementById('mm_is_bookmarked')?.value || '',
        min_versions: document.getElementById('mm_min_versions')?.value || '',
        min_size: document.getElementById('mm_min_size')?.value || '',
        max_size: document.getElementById('mm_max_size')?.value || '',
        sort_by: document.getElementById('mm_sort_by')?.value || 'name',
        sort_order: document.getElementById('mm_sort_order')?.value || 'asc',
        allow_derivatives: document.getElementById('mm_allow_derivatives')?.value || '',
        allow_different_license: document.getElementById('mm_allow_different_license')?.value || '',
        nsfw_use_max: document.getElementById('mm_nsfw_use_max')?.checked || false,
        preview_least_nsfw: previewLeastNsfwFromCheckbox(),
        sfw_only: document.getElementById('mm_sfw_only')?.checked || false,
        nsfw_levels: []
    };

    // Get NSFW level checkboxes
    const nsfwCheckboxes = document.querySelectorAll('#mm_nsfw_panel input[type="checkbox"][value]');
    nsfwCheckboxes.forEach(cb => {
        if (cb.checked) filters.nsfw_levels.push(cb.value);
    });
    return filters;
}

/** Say on the Save Search button what happened, for a moment. */
function flashSaveSearch(text) {
    const btn = document.getElementById('mm_save_search_btn');
    if (!btn) return;
    btn.textContent = text;
    setTimeout(() => { btn.textContent = 'Save Search'; }, 1500);
}

async function saveSearchFilters() {
    const filters = currentSearchFilters();
    if (!await saveSearch('model_manager', filters)) {
        setStatus('Could not save the search: the server did not keep it.', true);
        return;
    }
    console.log('[ModelManager] Saved search filters:', filters);
    flashSaveSearch('✓ Saved');
}

// The Base Model filter lists what this library holds, asked of the server.
// It used to be written into the markup, and named only the base models
// installed when it was written: a Wan 2.1 or Anima model could not be
// filtered to at all.
async function loadBaseModelOptions() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/filters' });
        if (data && data.success) fillBaseModels(data.base_models || []);
    } catch (error) {
        console.warn('[ModelManager] Could not load the base models:', error);
    }
}

function fillBaseModels(values) {
    const select = document.getElementById('mm_base_model');
    if (!select) return;
    const chosen = select.value;
    const option = (value, label) => {
        const element = document.createElement('option');
        element.value = value;
        element.textContent = label;
        return element;
    };
    select.replaceChildren(option('', 'All'),
                           ...sortBaseModels(values.filter(Boolean)).map((v) => option(v, v)));
    selectBaseModel(chosen);
}

/**
 * Select a base model, listing it if the filter does not. A saved search is
 * restored without waiting for the list, and may name a base model no longer
 * in the library; either way a missing option would quietly make it "All".
 */
function selectBaseModel(value) {
    const select = document.getElementById('mm_base_model');
    if (!select) return;
    if (value && ![...select.options].some((o) => o.value === value)) {
        const element = document.createElement('option');
        element.value = value;
        element.textContent = value;
        select.appendChild(element);
    }
    select.value = value || '';
}

/**
 * While "Only Show Models with SFW images" is ticked and a trained model
 * judges prompts, say so above the results. The word list needs no note.
 */
// Listened for on the page, not on the checkbox: the tab's markup may not be
// there yet when init() runs, and Gradio replaces it when it redraws - a
// listener on the element was lost, and ticking the box showed no banner.
// For the same redraw, which resets inline styles, it is shown again after.
document.addEventListener('change', (event) => {
    if (event.target?.id === 'mm_sfw_only') syncSfwOnlyBanner();
});
if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(syncSfwOnlyBanner);

function syncSfwOnlyBanner() {
    const banner = document.getElementById('mm_sfw_only_banner');
    const note = document.getElementById('mm_sfw_only_banner_model');
    if (!banner || !note) return;
    const text = nsfwModelNote();
    setText(note, text);
    banner.style.display = text && document.getElementById('mm_sfw_only')?.checked ? 'flex' : 'none';
}

/**
 * Fill the filters from the saved search, if there is one. One kept in this
 * browser, from before it was in the database, is moved there first.
 */
async function loadSearchFilters() {
    let filters = await savedSearch('model_manager');
    let legacy = null;
    try {
        legacy = localStorage.getItem(LEGACY_SAVED_FILTERS);
    } catch (e) { /* storage blocked: nothing to move */ }
    if (!filters && legacy) {
        try {
            filters = JSON.parse(legacy);
        } catch (e) {
            filters = null;
        }
        if (filters && await saveSearch('model_manager', filters)) {
            console.log('[ModelManager] Moved the saved search from this browser to the database');
        }
    }
    if (legacy) {
        try {
            localStorage.removeItem(LEGACY_SAVED_FILTERS);
        } catch (e) { /* as above */ }
    }
    if (!filters) return false;
    return applySearchFilters(filters);
}

/** Fill the filter bar from a saved search. */
function applySearchFilters(filters) {
    try {

        if (Object.prototype.hasOwnProperty.call(filters, 'search')) document.getElementById('mm_search').value = filters.search;
        if (Object.prototype.hasOwnProperty.call(filters, 'type')) document.getElementById('mm_type').value = filters.type;
        if (Object.prototype.hasOwnProperty.call(filters, 'base_model')) selectBaseModel(filters.base_model);
        if (Object.prototype.hasOwnProperty.call(filters, 'civitai')) document.getElementById('mm_civitai').value = filters.civitai;
        if (Object.prototype.hasOwnProperty.call(filters, 'is_bookmarked')) document.getElementById('mm_is_bookmarked').value = filters.is_bookmarked;
        if (Object.prototype.hasOwnProperty.call(filters, 'min_versions')) document.getElementById('mm_min_versions').value = filters.min_versions;
        for (const [key, id] of [['min_size', 'mm_min_size'], ['max_size', 'mm_max_size']]) {
            if (Object.prototype.hasOwnProperty.call(filters, key)) document.getElementById(id).value = filters[key];
        }
        if (Object.prototype.hasOwnProperty.call(filters, 'sort_by')) document.getElementById('mm_sort_by').value = filters.sort_by;
        if (Object.prototype.hasOwnProperty.call(filters, 'sort_order')) document.getElementById('mm_sort_order').value = filters.sort_order;
        if (Object.prototype.hasOwnProperty.call(filters, 'allow_derivatives')) document.getElementById('mm_allow_derivatives').value = filters.allow_derivatives;
        if (Object.prototype.hasOwnProperty.call(filters, 'allow_different_license')) document.getElementById('mm_allow_different_license').value = filters.allow_different_license;

        const sfwOnly = document.getElementById('mm_sfw_only');
        if (sfwOnly && Object.prototype.hasOwnProperty.call(filters, 'sfw_only')) {
            sfwOnly.checked = Boolean(filters.sfw_only);
            syncSfwOnlyBanner();
        }

        // Set NSFW checkboxes
        const useMaxCb = document.getElementById('mm_nsfw_use_max');
        if (useMaxCb) useMaxCb.checked = filters.nsfw_use_max || false;

        // Saved searches store the API's flag, not the checkbox's, so ones
        // saved before the checkbox was reworded still restore correctly.
        if (Object.prototype.hasOwnProperty.call(filters, 'preview_least_nsfw') && filters.preview_least_nsfw !== null) {
            if (setPreviewCheckboxFrom(filters.preview_least_nsfw)) {
                previewLeastNsfwInitialized = true;
            }
        }

        const nsfwCheckboxes = document.querySelectorAll('#mm_nsfw_panel input[type="checkbox"][value]');
        nsfwCheckboxes.forEach(cb => {
            cb.checked = filters.nsfw_levels?.includes(cb.value) || false;
        });

        // Update NSFW display
        updateNsfwDisplay();

        console.log('[ModelManager] Loaded saved filters:', filters);
        return true;
    } catch (e) {
        console.error('[ModelManager] Error loading saved filters:', e);
        return false;
    }
}

async function clearSearchFilters() {
    if (!await saveSearch('model_manager', null)) {
        setStatus('Could not clear the saved search: the server did not answer.', true);
        return;
    }
    console.log('[ModelManager] Cleared saved filters');
    flashSaveSearch('✗ Cleared');
}

// Initialize with retry logic for Gradio-rendered content
function init() {
    console.log('[ModelManager] Initializing...');
    bindElements();
    loadNsfwDetection().then(syncSfwOnlyBanner);

}

function bindElements() {
    const loadBtn = document.getElementById('mm_load_btn');
    const syncBtn = document.getElementById('mm_sync_btn');
    const cancelBtn = document.getElementById('mm_sync_cancel_btn');
    const refreshBtn = document.getElementById('mm_refresh_btn');
    const scanCancelBtn = document.getElementById('mm_scan_cancel_btn');
    const searchInput = document.getElementById('mm_search');
    const previewLeastNsfwCheckbox = document.getElementById('mm_preview_show_nsfw');

    if (!loadBtn) {
        console.log('[ModelManager] Button not found yet, retrying...');
        setTimeout(bindElements, 500);
        return;
    }

    console.log('[ModelManager] Found elements, binding events');

    // Setup NSFW controls
    setupNsfwControls();

    // Setup Commercial Use controls
    setupCommercialControls();

    // Remove any existing listeners by cloning
    const newLoadBtn = loadBtn.cloneNode(true);
    loadBtn.parentNode.replaceChild(newLoadBtn, loadBtn);

    newLoadBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        console.log('[ModelManager] Load button clicked');
        loadModels(1);  // Reset to page 1 when filters change
    });

    // Both tabs carry this; the shared helper waits for the answer
    // and the markup, in whichever order they turn up.
    showApiKeyBanner('mm_api_key_warning');
    showNotes('model_manager', 'mm_notes');

    // Trained/Merge only applies to checkpoints, so it follows the Type
    // control rather than sitting there looking usable.
    const typeFilter = document.getElementById('mm_type');
    if (typeFilter) {
        typeFilter.addEventListener('change', syncCheckpointTypeEnabled);
    }
    syncCheckpointTypeEnabled();

    // Bind sync button
    if (syncBtn) {
        const newSyncBtn = syncBtn.cloneNode(true);
        syncBtn.parentNode.replaceChild(newSyncBtn, syncBtn);

        newSyncBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openSyncDialog();
        });
    }

    // The dialog behind that button. Every control re-costs the choice, so
    // the figure at the bottom always describes what Start would do.
    const syncDialog = document.getElementById('mm_sync_dialog');
    if (syncDialog) {
        syncDialog.addEventListener('change', (e) => {
            if (e.target.id === 'mm_sync_images' || e.target.name === 'mm_sync_scope'
                    || e.target.id === 'mm_sync_force_mode') {
                syncDialogDependencies();
            }
            // Touching a window picks the scope it belongs to, so the two
            // do not have to be set in the right order.
            const SCOPE_OF = {
                mm_sync_stale_days: 'stale',
                mm_sync_downloaded_days: 'downloaded',
                mm_sync_force_mode: 'force',
            };
            const scope = SCOPE_OF[e.target.id];
            if (scope) {
                const radio = syncDialog.querySelector(
                    `input[name="mm_sync_scope"][value="${scope}"]`);
                if (radio) radio.checked = true;
            }
            refreshSyncEstimate();
        });
        syncDialog.addEventListener('click', (e) => {
            if (e.target === syncDialog) closeSyncDialog();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && syncDialog.style.display !== 'none') closeSyncDialog();
        });
        const dialogCancel = document.getElementById('mm_sync_dialog_cancel');
        if (dialogCancel) dialogCancel.addEventListener('click', closeSyncDialog);
        const dialogStart = document.getElementById('mm_sync_dialog_start');
        if (dialogStart) dialogStart.addEventListener('click', startSyncFromDialog);
    }

    // Bind sync cancel button
    if (cancelBtn) {
        const newCancelBtn = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

        newCancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            cancelSync();
        });
    }

    // Bind refresh/scan button
    if (refreshBtn) {
        const newRefreshBtn = refreshBtn.cloneNode(true);
        refreshBtn.parentNode.replaceChild(newRefreshBtn, refreshBtn);

        newRefreshBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openScanDialog();
        });
    }

    // The confirmation behind it: same dismissal rules as the sync dialog.
    const scanDialog = document.getElementById('mm_scan_dialog');
    if (scanDialog) {
        scanDialog.addEventListener('click', (e) => {
            if (e.target === scanDialog) closeScanDialog();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && scanDialog.style.display !== 'none') closeScanDialog();
        });
        const scanCancel = document.getElementById('mm_scan_dialog_cancel');
        if (scanCancel) scanCancel.addEventListener('click', closeScanDialog);
        const scanStart = document.getElementById('mm_scan_dialog_start');
        if (scanStart) {
            scanStart.addEventListener('click', () => {
                const rereadHeaders = !!document.getElementById('mm_scan_reread')?.checked;
                const moveMisplaced = !!document.getElementById('mm_scan_move')?.checked;
                closeScanDialog();
                startScan({ rereadHeaders, moveMisplaced });
            });
        }
    }

    // Bind scan cancel button
    if (scanCancelBtn) {
        const newScanCancelBtn = scanCancelBtn.cloneNode(true);
        scanCancelBtn.parentNode.replaceChild(newScanCancelBtn, scanCancelBtn);

        newScanCancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            cancelScan();
        });
    }

    // Bind save search button
    const saveSearchBtn = document.getElementById('mm_save_search_btn');
    if (saveSearchBtn) {
        saveSearchBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            saveSearchFilters();
        });
        saveSearchBtn.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            clearSearchFilters();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                loadModels(1);  // Reset to page 1 when searching
            }
        });
    }

    if (previewLeastNsfwCheckbox) {
        previewLeastNsfwCheckbox.addEventListener('change', () => {
            previewLeastNsfwUserTouched = true;
        });
    }

    console.log('[ModelManager] Ready - click handlers bound');

    // Load saved filters if available - Load Models waits for them.
    savedFiltersReady = loadSearchFilters().catch(() => false);
    loadBaseModelOptions();

    // Check for saved scroll position and show restore button
    updateScrollRestoreButton();

    // Check for ongoing processes
    checkOngoingProcesses();
}

// Check for ongoing scan/sync processes and resume polling
async function checkOngoingProcesses() {
    console.log('[ModelManager] Checking for ongoing processes...');

    // Check for ongoing scan
    try {
        const scanData = await apiCall({ endpoint: '/model-manager/scan/progress' });
        if (scanData.success && scanData.progress && !scanData.progress.is_complete) {
            console.log('[ModelManager] Found ongoing scan, resuming...');
            isScanning = true;
            updateScanUI(true);
            setStatus(`Scan in progress: ${scanData.progress.processed}/${scanData.progress.total}`);

            // Resume polling
            if (!scanPollInterval) {
                scanPollInterval = setInterval(pollScanProgress, TIMING.scanPoll);
            }
        }
    } catch (error) {
        console.log('[ModelManager] No ongoing scan');
    }

    // Check for ongoing sync
    try {
        const syncData = await apiCall({ endpoint: '/model-manager/sync/progress' });
        if (syncData.success && syncData.progress && !syncData.progress.is_complete) {
            console.log('[ModelManager] Found ongoing sync, resuming...');
            isSyncing = true;
            updateSyncUI(true);
            setStatus(`Sync in progress: ${syncData.progress.processed}/${syncData.progress.total}`);

            // Resume polling
            if (!syncPollInterval) {
                syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
            }
        }
    } catch (error) {
        console.log('[ModelManager] No ongoing sync');
    }
}

// Also check when tab becomes visible
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        // Only check if we're not already tracking a process
        if (!isScanning && !isSyncing) {
            checkOngoingProcesses();
        }
    }
});

// Setup scroll-to-top button
function setupScrollToTop() {
    // Create button if it doesn't exist
    let scrollBtn = document.querySelector('.mm-scroll-to-top');
    if (!scrollBtn) {
        scrollBtn = document.createElement('button');
        scrollBtn.className = 'mm-scroll-to-top';
        scrollBtn.innerHTML = '↑';
        scrollBtn.title = 'Scroll to top';
        scrollBtn.addEventListener('click', () => {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });
        document.body.appendChild(scrollBtn);
    }

    // Show/hide button based on scroll position
    const SCROLL_THRESHOLD = 300;  // Show after scrolling 300px

    function updateButtonVisibility() {
        if (window.scrollY > SCROLL_THRESHOLD) {
            scrollBtn.classList.add('visible');
        } else {
            scrollBtn.classList.remove('visible');
        }
    }

    // Initial check
    updateButtonVisibility();

    // Listen to scroll events (throttled)
    let scrollTimeout = null;
    window.addEventListener('scroll', () => {
        if (scrollTimeout) return;
        scrollTimeout = setTimeout(() => {
            updateButtonVisibility();
            scrollTimeout = null;
        }, 100);
    }, { passive: true });
}

onReady(init);
onReady(setupScrollToTop);
