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
    isVideoUrl,
    cardMediaUrl,
    originalMediaUrl,
    collectResourceChips,
    resourceNames,
    promptHasChip,
    toggleChip,
    renameLoraTags,
    sortBaseModels,
    videoFrames,
    videoSize,
    getImagePageCount,
    downloadedImagesNote,
    downloadFailedNote,
    setupLazyMedia,
    renderResource,
    renderFilterBanner,
    balanceGridRows,
    nsfwBadgeLabel,
    paidAccessLabel,
    isPaid,
    primaryFileIndex,
    renderDownloadControls,
    showChosenFile,
    downloads,
    formatBytes,
    formatDay,
    loadNsfwDetection,
    nsfwModelNote,
    refreshUiOptions,
    IMAGE_PAGE_SIZE,
    applyCardSize: sharedApplyCardSize,
    renderImagePagination: sharedImagePagination,
    TIMING,
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
let currentImages = [];
let currentVersionId = null;
let currentModelPath = null;
let currentImagePage = 1;
// "continuous" grows one list downwards; "pages" shows a page at a time. The
// setting is read once at load, below, and defaults to continuous so a WebUI
// that has never seen the option behaves like the one that has.
let imageBrowsing = 'continuous';
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
// The images the prompt filter is hiding right now, not counting any the NSFW
// filter hides first - the other half of the banner's "hidden due to" split.
let hiddenPromptlessCount = 0;
// The gallery is fetched a page at a time; it used to arrive whole and be
// sliced here. currentImages holds what is loaded - the page on show, or in
// the continuous list every page so far - and imagesOffset is where the first
// of them sits among the images the switches let through, of which there are
// filteredImageCount.
let imagesOffset = 0;
let filteredImageCount = 0;
// Each fetch of the gallery takes a number; an answer to anything but the
// latest is dropped, so a slow page cannot land over a newer one.
let imagesRequest = 0;
// What the last "Download More Images" brought, beside the button, until the
// gallery is next loaded some other way.
let downloadNote = '';
let nextImagesCursor = null;  // Cursor for loading more images
let imagesSyncDate = null;    // Last sync date (null = never synced)
let isLoadingMore = false;
const IMAGE_PLACEHOLDER_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200'%3E%3Crect fill='%23222933' width='320' height='200'/%3E%3Cg fill='%236b7280'%3E%3Cpath d='M130 78h60v44h-60z'/%3E%3Cpath d='M92 132l34-30 28 24 18-14 56 44H92z'/%3E%3Ccircle cx='208' cy='82' r='10'/%3E%3C/g%3E%3Ctext x='160' y='176' text-anchor='middle' fill='%239ca3af' font-size='14'%3EImage unavailable%3C/text%3E%3C/svg%3E";

// NSFW image filtering state
let hideNsfwImages = true;  // Default to hide, will be set from setting on first load
let hideNsfwImagesInitialized = false;
let totalImageCount = 0;
let hiddenImageCount = 0;

// Helper to detect video URLs



function renderImagePagination(totalPages, position = 'bottom') {
    return sharedImagePagination({
        currentPage: currentImagePage, totalPages, position, prefix: 'mm',
    });
}

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

// Wait for DOM

// API call helper

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
(window.mmCardPreviews ||= {}).model_manager_card_size = cardPreview;

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
        // first load reads it.
        await ensureFilterDefaults();

        // No page_size: the server uses the Models per page setting.
        const filters = getFilters();
        filters.page = page;
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
    const src = cardMediaUrl(model.preview_url);
    const versions = model.local_version_count || 1;
    return renderModelCard({
        index,
        onclick: `window.mmSelectModel(${index})`,
        name: model.display_name,
        media: { src, video: isVideoUrl({ url: src }) },
        classes: [model.has_civitai_data ? 'has-civitai' : 'no-civitai', nsfwCardClass(model.nsfw_level || 1)],
        data: { 'model-id': model.civitai_model_id || '' },
        overlays: [
            ...(model.has_civitai_data ? [] : [{ cls: 'no-data-overlay', text: 'No Civitai Data' }]),
            ...(model.is_bookmarked ? [{ cls: 'mm-bookmark-indicator', text: '★', title: 'Bookmarked' }] : []),
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

// Render model grid
function renderModelGrid(models) {
    renderSharedGrid({
        gridId: 'mm_grid',
        cards: (models || []).map((model, index) => mmCard(model, index)),
        empty: 'No models found matching your filters.',
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
    currentImages = [];
    currentVersionId = null;
    currentModelPath = model.file_path;
    currentImagePage = 1;
    imagesOffset = 0;
    filteredImageCount = 0;
    nextImagesCursor = null;
    imagesSyncDate = null;
    // Each model's gallery starts from the settings; its switches then last
    // while this model is open - as in the Civitai Browser.
    hideNsfwImagesInitialized = false;
    hidePromptlessInitialised = false;

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
            image_limit: IMAGE_PAGE_SIZE,
        };
        const request = ++imagesRequest;
        downloadNote = '';
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

            // The gallery's first page, and the state it is drawn with
            const images = data.model.images || [];
            currentImages = images;
            currentImagePage = 1;
            const imagesState = data.model.images_state || {};
            applyImagesState(imagesState);

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

            console.log(`[ModelManager] Loaded ${images.length} of ${filteredImageCount} images (total: ${totalImageCount}, hidden: ${hiddenImageCount}, cursor: ${nextImagesCursor ? 'yes' : 'no'}, synced: ${imagesSyncDate ? 'yes' : 'no'})`);

            renderModelImages(images);
            updateImagesCountCell();
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load model details:', error);
        updateImagesCountCell();  // Update even on error to show "None"
    }
}

/**
 * Take the gallery's state from the server's images_state: what Civitai has
 * left, the counts the banner states, and where the loaded images start. Every
 * page carries it, so the counts are always those of the images drawn.
 */
function applyImagesState(state) {
    currentVersionId = state.version_id || null;
    nextImagesCursor = state.next_cursor || null;
    imagesSyncDate = state.sync_date || null;
    imagesOffset = state.offset || 0;
    totalImageCount = state.total_count || 0;
    filteredImageCount = state.filtered_count || 0;
    hiddenImageCount = state.hidden_nsfw ?? state.hidden_count ?? 0;
    hiddenPromptlessCount = state.hidden_promptless || 0;
    nsfwImageCount = state.nsfw_count || 0;
    promptlessImageCount = state.promptless_count || 0;
}

/**
 * Fetch a page of the open version's gallery, through its two switches, and
 * draw it. Appended to what is loaded for the continuous list's Show More;
 * otherwise it replaces it.
 *
 * @returns {Promise<boolean>} whether the page arrived and was drawn
 */
async function loadImagesPage(offset, { append = false } = {}) {
    const versionId = currentVersionId;
    if (!versionId) return false;
    const request = ++imagesRequest;
    try {
        const data = await apiCall({ endpoint: '/model-manager/images/page', params: {
            version_id: versionId, offset, limit: IMAGE_PAGE_SIZE,
            hide_nsfw_images: hideNsfwImages, hide_promptless_images: hidePromptlessImages,
        } });
        if (request !== imagesRequest || versionId !== currentVersionId) return false;
        if (!data.success) {
            console.error('[ModelManager] Failed to load images:', data.error);
            return false;
        }
        const images = data.images || [];
        if (append) {
            // The loaded list keeps its start; only the counts move.
            const start = imagesOffset;
            applyImagesState(data.images_state || {});
            imagesOffset = start;
            const have = new Set(currentImages.map((img) => img.id));
            currentImages = currentImages.concat(images.filter((img) => !have.has(img.id)));
        } else {
            applyImagesState(data.images_state || {});
            currentImages = images;
        }
        renderModelImages(currentImages);
        updateImagesCountCell();
        return true;
    } catch (error) {
        console.error('[ModelManager] Failed to load images:', error);
        return false;
    }
}

/** The gallery's counts, as downloadedImagesNote() compares them. */
function galleryCounts() {
    return { total: totalImageCount, filtered: filteredImageCount,
             hidden_nsfw: hiddenImageCount, hidden_promptless: hiddenPromptlessCount };
}

/** Fetch and show one page of the gallery, when it is paged. */
async function showImagePage(page) {
    downloadNote = '';
    const totalPages = getImagePageCount(filteredImageCount);
    const target = Math.min(Math.max(1, page), totalPages);
    currentImagePage = target;
    return loadImagesPage((target - 1) * IMAGE_PAGE_SIZE);
}

// The no-prompt switch. It reads "Show images without prompts", as the Civitai
// Browser's does, while the server is still asked whether to *hide* them -
// hide_promptless_images. This is the one place the two meet. It reloads,
// because the filtering is done in SQL: the hidden images are not in the page
// to be revealed.
window.mmToggleShowPromptless = async function(showPromptless) {
    hidePromptlessImages = !showPromptless;
    hidePromptlessInitialised = true;
    currentImagePage = 1;
    if (currentModelPath) {
        await loadVersionDetails(currentModelPath);
    }
};

// The gallery's NSFW switch. It reads "Show NSFW", as every other NSFW switch
// in both tabs does, while the server is still asked whether to *hide* them -
// hide_nsfw_images, and hideNsfwImages here. This is the one place the two
// meet, so the inversion is done here and nowhere else.
window.mmToggleShowNsfwImages = async function(showNsfw) {
    hideNsfwImages = !showNsfw;
    hideNsfwImagesInitialized = true;
    currentImagePage = 1;
    if (currentModelPath) {
        await loadVersionDetails(currentModelPath);
    }
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
    currentImages = [];
    currentVersionId = null;
    currentImagePage = 1;
    imagesOffset = 0;
    filteredImageCount = 0;
    nextImagesCursor = null;
    imagesSyncDate = null;

    // Update version selector UI
    updateVersionSelectorUI();

    // Update version-specific info in details panel
    updateVersionInfo(version);

    // Load details for new version
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
    currentImages = [];
    currentVersionId = null;
    currentImagePage = 1;
    imagesOffset = 0;
    filteredImageCount = 0;
    nextImagesCursor = null;
    imagesSyncDate = null;
}

/** The header's buttons: the same for any version, but deleting needs a file. */
function renderDetailHeader(model, { deletable = true } = {}) {
    const modelId = model.model_id || model.civitai_model_id;
    const isBookmarked = model.is_bookmarked || false;
    const bookmarkBtn = modelId
        ? `<button class="mm-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" onclick="window.mmToggleBookmark(${safeId(modelId)})" title="${isBookmarked ? 'Remove bookmark' : 'Bookmark this model'}">${isBookmarked ? '★' : '☆'}</button>`
        : '';

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
                ${renderDownloadControls({ prefix: 'mm', modelId, version, fileIndex, owned: false })}
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
    showChosenFile('mm', currentModels[selectedModelIndex]?.model_id, version, file);
};

// The list and its panel are shared with the Civitai Browser: see
// downloads() in shared/common.mjs.
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
            currentImagePage = 1;
            await loadImagesPage(0);
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
function renderModelImages(images) {
    const container = document.getElementById('mm_images');
    if (!container) return;

    const totalPages = getImagePageCount(filteredImageCount);
    currentImagePage = Math.min(Math.max(1, currentImagePage), totalPages);

    // One banner for both filters: what they are holding back, which adds up
    // with what is shown to the total, and a switch for each on the right. The
    // server splits the hidden images between the filters so that none is
    // counted twice - NSFW first, as it filters - and reports what each switch
    // would show once ticked. Built in shared/common.mjs, as the Civitai
    // Browser's is.
    const filterBannerHtml = renderFilterBanner({
        shown: filteredImageCount,
        total: totalImageCount,
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        switches: [
            { id: 'mm_show_nsfw_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: !hideNsfwImages, hidden: hiddenImageCount, count: nsfwImageCount,
              onchange: 'window.mmToggleShowNsfwImages(this.checked)', note: nsfwModelNote() },
            { id: 'mm_show_promptless_images', label: 'Show unusable prompts',
              reason: 'unusable prompt',
              showing: !hidePromptlessImages, hidden: hiddenPromptlessCount,
              count: promptlessImageCount,
              onchange: 'window.mmToggleShowPromptless(this.checked)' },
        ],
    });

    if (!images || images.length === 0) {
        // Still show the banner if a filter is what emptied it
        if (hiddenImageCount > 0 || hiddenPromptlessCount > 0) {
            container.innerHTML = `
                <div class="mm-images-header">
                    <h4>Example Images</h4>
                </div>
                ${filterBannerHtml}
                <div class="model-images-list"><p class="mm-no-images">No images to show with the filters above.</p></div>
            `;
            container.style.display = 'block';
            return;
        }
        container.style.display = 'none';
        return;
    }

    // Continuous shows everything from the first image down to wherever the
    // reader has got to; paging shows one page. Either way what is drawn is
    // what is loaded - the server sends a page at a time - and the cards, the
    // counts and the download button are the same.
    const paging = imageBrowsing === 'pages';
    const pageStart = imagesOffset;
    const pageEnd = imagesOffset + images.length;
    const imageCards = images.map((img, index) => renderImageCard(img, index)).filter(Boolean).join('');
    const moreToShow = !paging && pageEnd < filteredImageCount;

    if (!imageCards) {
        container.style.display = 'none';
        return;
    }

    // Download button visibility:
    // - Show if never synced (imagesSyncDate is null) OR
    // - Show if cursor exists (more images available)
    const showDownloadBtn = (nextImagesCursor !== null && nextImagesCursor !== '') || (imagesSyncDate === null);
    const neverSynced = imagesSyncDate === null;
    const buttonText = neverSynced ? 'Download Images' : 'Download More Images';
    const infoText = downloadNote ? escapeHtml(downloadNote)
        : (neverSynced ? 'Images not yet downloaded' : `${totalImageCount} images downloaded`);

    // One button at the foot of the list. While there are images already
    // downloaded but not yet on screen it fetches the next page of those from
    // the server. Once they are all up, it offers to fetch more from Civitai.
    const atEnd = paging ? currentImagePage === totalPages : !moreToShow;
    const downloadMoreHtml = moreToShow
        ? `<div class="mm-load-more">
             <button class="mm-btn secondary" id="mm_show_more_btn" onclick="window.mmShowMoreImages()">
               Show More Images
             </button>
             <span class="mm-load-more-info">${pageEnd} of ${filteredImageCount} shown</span>
           </div>`
        : (showDownloadBtn && atEnd
            ? `<div class="mm-load-more">
                 <button class="mm-btn secondary" id="mm_load_more_btn" onclick="window.mmLoadMoreImages()">
                   ${buttonText}
                 </button>
                 <span class="mm-load-more-info">${infoText}</span>
               </div>`
            : (downloadNote && atEnd
                ? `<div class="mm-load-more"><span class="mm-load-more-info">${infoText}</span></div>`
                : ''));

    const countText = paging
        ? `${pageStart + 1}-${pageEnd} of ${filteredImageCount} images (Page ${currentImagePage}/${totalPages})`
        : `${pageEnd} of ${filteredImageCount} images`;

    container.innerHTML = `
        <div class="mm-images-header">
            <h4>Example Images</h4>
            <span class="mm-images-count">${countText}</span>
        </div>
        ${filterBannerHtml}
        ${paging ? renderImagePagination(totalPages, 'top') : ''}
        <div class="model-images-list">${imageCards}</div>
        ${downloadMoreHtml}
        ${paging ? renderImagePagination(totalPages, 'bottom') : ''}
    `;
    container.style.display = 'block';
    setupLazyMedia(container);
    refreshResourceButtons();
}

// Render a single image card in list format
function renderImageCard(img, index) {
    const src = img.url || '';

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

    // Get size (prefer meta.Size which is generation size, not final image size after hires)
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
    if (meta['ADetailer inpaint only masked']) adetailerParams.push(`Inpaint masked: ${meta['ADetailer inpaint only masked']}`);

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
    const resourcesLabel = resourceButtonLabel(img);

    const promptShort = prompt.length > 300 ? prompt.substring(0, 300) + '...' : prompt;
    const promptHtml = prompt
        ? `<div class="mm-image-prompt">
             <span class="mm-prompt-label">Prompt:</span>
             <span class="mm-prompt-text" title="${escapeHtml(prompt)}">${escapeHtml(promptShort)}</span>
           </div>`
        : '';

    // Negative prompt (truncated more)
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
    const nsfwLevel = nsfwBadgeLabel(img, img.nsfw || 'Unknown');
    const nsfwClass = nsfwLevel !== 'PG' && nsfwLevel !== 'Unknown' && nsfwLevel !== 'None'
        ? 'mm-nsfw-indicator'
        : '';

    // Detect video
    const isVideo = isVideoUrl({ url: src, type: img.type });
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
                ${nsfwClass ? `<span class="mm-nsfw-badge">${escapeHtml(nsfwLevel)}</span>` : ''}
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
                    <button class="mm-btn primary mm-send-btn" onclick="window.mmSendToTxt2img(${index})">
                        Send to txt2img
                    </button>
                    <button class="mm-btn secondary" data-copy="${escapeHtml(prompt)}">
                        Copy Prompt
                    </button>
                    <button class="mm-btn secondary" onclick="window.mmShowImageMeta(${index})">
                        Show All
                    </button>
                    ${img.id ? `<a class="mm-btn secondary" href="https://civitai.com/images/${safeId(img.id)}" target="_blank">View on Civitai</a>` : ''}
                    ${resourcesLabel ? `<button class="mm-btn secondary" data-resources-index="${index}" onclick="window.mmShowResources(${index})">${resourcesLabel}</button>` : ''}
                </div>
            </div>
        </div>
    `;
}

// Render a single resource (LoRA, VAE, etc)

// Show image metadata in modal
window.mmShowImageMeta = function(imageIndex) {
    const img = currentImages[imageIndex];
    if (!img) return;

    const meta = img.meta || {};

    // Build table rows - show ALL data
    let tableRows = '';

    // Helper to format value for display
    function formatValue(value) {
        if (value === null || value === undefined) return '';
        if (Array.isArray(value)) {
            return value.map(v => {
                if (typeof v === 'object') {
                    return '<pre>' + escapeHtml(JSON.stringify(v, null, 2)) + '</pre>';
                }
                return escapeHtml(String(v));
            }).join('<br>');
        }
        if (typeof value === 'object') {
            return '<pre>' + escapeHtml(JSON.stringify(value, null, 2)) + '</pre>';
        }
        return escapeHtml(String(value));
    }

    // Image-level fields
    for (const [key, value] of Object.entries(img)) {
        if (key === 'meta' || key === 'url') continue; // Skip meta (shown separately) and url
        if (value === null || value === undefined || value === '') continue;
        tableRows += `<tr><th>${escapeHtml(key)}</th><td>${formatValue(value)}</td></tr>`;
    }

    // All meta fields
    for (const [key, value] of Object.entries(meta)) {
        if (value === null || value === undefined || value === '') continue;
        const isLongText = typeof value === 'string' && value.length > 100;
        const cellClass = isLongText ? 'mm-meta-prompt' : '';
        tableRows += `<tr><th>${escapeHtml(key)}</th><td class="${cellClass}">${formatValue(value)}</td></tr>`;
    }

    // Create modal
    const modalHtml = `
        <div class="mm-modal-overlay" onclick="window.mmCloseMetaModal(event)">
            <div class="mm-modal" onclick="event.stopPropagation()">
                <div class="mm-modal-header">
                    <h3>Image Metadata</h3>
                    <button class="mm-modal-close" onclick="window.mmCloseMetaModal()">&times;</button>
                </div>
                <div class="mm-modal-body">
                    <table class="mm-meta-table">
                        <tbody>
                            ${tableRows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    const existingModal = document.querySelector('.mm-modal-overlay');
    if (existingModal) existingModal.remove();

    // Add modal to body and lock scroll
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    document.body.classList.add('mm-modal-open');
};

// Close metadata modal
window.mmCloseMetaModal = function(event) {
    // If called with event, only close if clicking overlay (not modal content)
    if (event && event.target !== event.currentTarget) return;
    const modal = document.querySelector('.mm-modal-overlay');
    if (modal) {
        modal.remove();
        document.body.classList.remove('mm-modal-open');
    }
};

/**
 * Turn resource hashes into Civitai versions, a round at a time.
 *
 * The server asks Civitai about a bounded number per request and hands the
 * rest back as `deferred`, so a big image is resolved over several requests
 * instead of one that runs for minutes. onRound is called after each round
 * that leaves work outstanding, so the panel can show what is known so far.
 *
 * Returns every answer the server gave: hash -> { version_id, ... }, where a
 * null version_id means Civitai does not know that hash. A hash missing from
 * the result was never answered - its lookup failed.
 */
async function resolveResourceHashes(hashes, onRound) {
    const resolved = {};
    let pending = hashes;

    while (pending.length) {
        let data;
        try {
            const response = await fetch('/model-manager/resolve-hashes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'hashes=' + encodeURIComponent(pending.join(',')),
            });
            data = await response.json();
        } catch (e) {
            console.warn('[ModelManager] Could not resolve resource hashes:', e);
            break;
        }
        if (!data.success) break;

        Object.assign(resolved, data.resolved || {});
        const deferred = data.deferred || [];
        // A round that gets nowhere would loop for ever; stop instead.
        if (deferred.length >= pending.length) break;
        pending = deferred;
        if (pending.length && onRound) onRound(resolved, pending.length);
    }

    return resolved;
}

/**
 * Gather an image's resources into one list, without guessing.
 *
 * The generation data names them twice. Civitai's own list carries
 * modelVersionId; the legacy infotext list carries an AutoV2 hash and the
 * filename whoever generated the image had on disk. The two share no key, so
 * the hashes are resolved into version ids and the lists merged on that -
 * never on name similarity, which does not survive contact with real data:
 * "stablydiffuseds_26" is "StablyDiffused's Aesthetic Mix".
 *
 * Anything naming the version whose gallery this is gets dropped. An image is
 * an example *of* that model, so listing it says nothing - and it is a quarter
 * of all the rows in this library.
 *
 * `finished` says whether every hash has had its answer. Until then a hash
 * with no answer yet is still being looked up, and is left out rather than
 * listed as unknown.
 *
 * Returns { known, unknown }: resources with a Civitai version behind them,
 * and the rest - a filename with no hash, a hash Civitai does not know, or one
 * that could not be checked. Those are shown as they are rather than guessed at.
 */
function mergeImageResources(img, resolved, finished) {
    const meta = img.meta || {};
    const civitai = meta.civitaiResources || [];
    const legacy = meta.resources || [];

    const byVersion = new Map();
    for (const resource of civitai) {
        const versionId = resource.modelVersionId;
        if (!versionId || versionId === currentVersionId) continue;
        if (byVersion.has(versionId)) continue;
        byVersion.set(versionId, {
            versionId,
            modelId: resource.modelId || null,
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            versionName: resource.modelVersionName || '',
        });
    }

    const unknown = [];
    const seenUnknown = new Set();
    for (const resource of legacy) {
        const hash = (resource.hash || '').toLowerCase();
        const answered = hash && Object.prototype.hasOwnProperty.call(resolved, hash);
        const match = answered ? resolved[hash] : null;

        if (match && match.version_id) {
            if (match.version_id === currentVersionId) continue;
            if (byVersion.has(match.version_id)) continue;   // Civitai named it already
            byVersion.set(match.version_id, {
                versionId: match.version_id,
                modelId: match.model_id || null,
                type: match.model_type || resource.type || 'Unknown',
                name: match.name || resource.name || 'Unknown',
                versionName: match.version_name || '',
            });
            continue;
        }

        // Asked about, but its answer has not come back yet.
        if (hash && !answered && !finished) continue;

        // No hash, or Civitai has never heard of it, or the lookup failed.
        // Nothing more can be done with these, so they are shown rather than
        // dropped - deduplicated only where they are exactly the same thing.
        const key = hash || ((resource.type || '') + ':' + (resource.name || ''));
        if (seenUnknown.has(key)) continue;
        seenUnknown.add(key);
        unknown.push({
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            reason: !hash ? 'no hash recorded'
                : answered ? 'not on Civitai'
                : 'could not be checked',
        });
    }

    return { known: [...byVersion.values()], unknown };
}

// Which resources panel is current. A slow one - many hashes, no API key -
// must not paint over one opened after it, and it now repaints each round.
let resourcesRequest = 0;

// Every hash answer this page has seen: hash -> { version_id, ... }, as
// resolveResourceHashes() returns them. The answers are the server's too -
// it keeps them - so this only saves asking again within a page load.
const knownHashes = {};

/** An image's legacy resource hashes, lower-cased and each once. */
function imageResourceHashes(img) {
    const legacy = (img.meta || {}).resources || [];
    return [...new Set(legacy.map(r => (r.hash || '').toLowerCase()).filter(Boolean))];
}

/**
 * What an image's Resources button says, or '' for no button.
 *
 * The count is the panel's own - mergeImageResources() over the hashes
 * answered so far - so the button and the list it opens agree: duplicates
 * counted once, the model this gallery belongs to not at all. It used to add
 * the two lists up raw, and said 5 over a panel of 2, or appeared over an
 * empty one.
 *
 * A hash nobody has looked up yet may turn out to be another resource, a
 * duplicate, or this model, so while any is outstanding the count is a
 * floor: "Resources (2+)", or just "Resources" with none known yet. Opening
 * the panel looks them up, and the button becomes exact.
 */
function resourceButtonLabel(img) {
    const meta = img.meta || {};
    if (!(meta.civitaiResources || []).length && !(meta.resources || []).length) return '';

    const pending = imageResourceHashes(img)
        .some(hash => !Object.prototype.hasOwnProperty.call(knownHashes, hash));
    const { known, unknown } = mergeImageResources(img, knownHashes, false);
    const count = known.length + unknown.length;

    if (pending) return count ? `Resources (${count}+)` : 'Resources';
    return count ? `Resources (${count})` : '';
}

/** Relabel the gallery's Resources buttons from what is known now. */
function updateResourceButtons() {
    document.querySelectorAll('#mm_images [data-resources-index]').forEach((button) => {
        const img = currentImages[Number(button.dataset.resourcesIndex)];
        const label = img ? resourceButtonLabel(img) : '';
        if (label) button.textContent = label;
        else button.remove();
    });
}

/**
 * Learn what the server already knows about the gallery's hashes, in one
 * request, and relabel the buttons with it. Nothing is asked of Civitai:
 * that happens only when a panel is opened.
 */
async function refreshResourceButtons() {
    const unknown = [...new Set(currentImages.flatMap(imageResourceHashes))]
        .filter(hash => !Object.prototype.hasOwnProperty.call(knownHashes, hash));
    if (!unknown.length) return;
    try {
        const response = await fetch('/model-manager/resolve-hashes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'hashes=' + encodeURIComponent(unknown.join(',')) + '&local_only=true',
        });
        const data = await response.json();
        if (!data.success) return;
        Object.assign(knownHashes, data.resolved || {});
        updateResourceButtons();
    } catch (e) {
        console.warn('[ModelManager] Could not read known resource hashes:', e);
    }
}

// Show the resources behind an image, resolved and merged
window.mmShowResources = async function(imageIndex) {
    const img = currentImages[imageIndex];
    if (!img || !img.meta) return;

    const civitai = img.meta.civitaiResources || [];
    const legacy = img.meta.resources || [];
    if (civitai.length === 0 && legacy.length === 0) return;

    const request = ++resourcesRequest;
    const stillWanted = () => request === resourcesRequest
        && !!document.querySelector('.mm-resources-modal');

    // Up straight away, with whatever needs no lookup, because an uncached
    // hash takes a moment and a dialog that opens late reads as a dead button.
    const hashes = imageResourceHashes(img);
    const first = mergeImageResources(img, knownHashes, !hashes.length);
    renderResourcesModal(first, hashes.length);
    checkInstalledResources(first.known);
    if (!hashes.length) return;

    const resolved = await resolveResourceHashes(hashes, (partial, remaining) => {
        Object.assign(knownHashes, partial);
        updateResourceButtons();
        if (stillWanted()) renderResourcesModal(mergeImageResources(img, partial, false), remaining);
    });
    Object.assign(knownHashes, resolved);
    updateResourceButtons();

    if (stillWanted()) {
        const merged = mergeImageResources(img, resolved, true);
        renderResourcesModal(merged, 0);
        checkInstalledResources(merged.known);
    }
};

function renderResourcesModal(resources, pending = 0) {
    const rows = resources.known.map(resource => `
            <tr>
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name">${escapeHtml(resource.name)}${resource.versionName
                    ? ` <span class="mm-res-version">${escapeHtml(resource.versionName)}</span>` : ''}</td>
                <td class="mm-res-actions">
                    <a class="mm-btn secondary mm-btn-small" href="https://civitai.com/model-versions/${safeId(resource.versionId)}" target="_blank">View</a>
                    <span data-res-download="${safeId(resource.versionId)}">${resourceDownloadCell(resource)}</span>
                </td>
            </tr>
        `).join('');

    // Still asking: say how many are left rather than claim there is nothing.
    const stillLooking = pending > 0
        ? `<tr><td colspan="3" class="mm-res-loading">Looking up ${pending} more on Civitai...</td></tr>`
        : '';

    const nothingKnown = pending === 0 && resources.known.length === 0
        ? '<tr><td colspan="3" class="mm-res-loading">Nothing here has a Civitai model behind it.</td></tr>'
        : '';

    const unknownRows = resources.unknown.length
        ? '<tr><td colspan="3" class="mm-res-group">Named in the generation data, but not found on Civitai</td></tr>'
          + resources.unknown.map(resource => `
            <tr class="mm-res-unresolved">
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name">${escapeHtml(resource.name)}</td>
                <td class="mm-res-actions"><span class="mm-res-no-hash">${escapeHtml(resource.reason)}</span></td>
            </tr>
        `).join('')
        : '';

    const modalHtml = `
        <div class="mm-modal-overlay" onclick="window.mmCloseMetaModal(event)">
            <div class="mm-modal mm-resources-modal" onclick="event.stopPropagation()">
                <div class="mm-modal-header">
                    <h3>Resources</h3>
                    <button class="mm-modal-close" onclick="window.mmCloseMetaModal()">&times;</button>
                </div>
                <div class="mm-modal-body">
                    <table class="mm-resources-table">
                        <thead>
                            <tr>
                                <th>Type</th>
                                <th>Name</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows}${stillLooking}${nothingKnown}${unknownRows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;

    const existingModal = document.querySelector('.mm-modal-overlay');
    if (existingModal) existingModal.remove();

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    document.body.classList.add('mm-modal-open');
}

// ------------------------------------------- downloading from the dialog
// The dialog's Download used to be a link to Civitai's download URL: the
// right version, but saved wherever the browser saves things, and unknown to
// the library. It now downloads as the Civitai Browser does - into the folder
// for its type, and into the library - the version the image names, or the
// model's newest if that version is gone from Civitai.

// Version ids of the dialog's resources that are in the library.
const installedResourceVersions = new Set();
// Version id (as the image names it) -> { state, percent, target, versionName,
// substituted, error }: state is downloading, installed or error.
const resourceDownloads = {};
let resourceDownloadPoll = null;

function resourceDownloadCell(resource) {
    const id = resource.versionId;
    const job = resourceDownloads[id];
    if (installedResourceVersions.has(id) && !job) {
        return '<span class="mm-res-state installed">Installed</span>';
    }
    if (job && job.state === 'installed') {
        const which = job.substituted ? ` ${escapeHtml(job.versionName || '')} (the image's is gone)` : '';
        return `<span class="mm-res-state installed">Installed${which}</span>`;
    }
    if (job && job.state === 'downloading') {
        const shown = job.finishing ? 'Adding to library...' : job.percent ? `${job.percent}%` : 'Queued';
        return `<span class="mm-res-state">${shown}</span>`;
    }
    if (job && job.state === 'unavailable') {
        return `<span class="mm-res-state error" title="${escapeHtml(job.error || '')}">Not on Civitai</span>`;
    }
    const retry = job && job.state === 'error'
        ? `<span class="mm-res-state error" title="${escapeHtml(job.error || '')}">Failed</span> ` : '';
    const modelId = resource.modelId || (job && job.modelId);
    return `${retry}<button type="button" class="mm-btn primary mm-btn-small"
        onclick="window.mmDownloadResource(${safeId(id)}, ${modelId ? safeId(modelId) : 'null'})">Download</button>`;
}

/** Redraw one row's download cell, if the dialog is showing it. */
function redrawResourceDownload(versionId, resource) {
    const cell = document.querySelector(`.mm-resources-modal [data-res-download="${versionId}"]`);
    if (cell) cell.innerHTML = resourceDownloadCell(resource || { versionId, modelId: null });
}

/** Mark which of the dialog's versions the library holds, and redraw them. */
async function checkInstalledResources(resources) {
    const ids = resources.map((r) => r.versionId).filter(Boolean);
    if (!ids.length) return;
    try {
        const data = await apiCall({ endpoint: '/model-manager/image-resources',
                                     params: { version_ids: ids.join(',') } });
        for (const id of Object.keys((data && data.versions) || {})) installedResourceVersions.add(Number(id));
    } catch (error) {
        console.warn('[ModelManager] Could not check which resources are installed:', error);
    }
    for (const resource of resources) redrawResourceDownload(resource.versionId, resource);
}

window.mmDownloadResource = async function(versionId, modelId) {
    resourceDownloads[versionId] = { state: 'downloading', percent: 0, modelId };
    redrawResourceDownload(versionId, { versionId, modelId });
    redrawResourceChips();
    const form = new URLSearchParams({ version_id: versionId, newer_if_gone: 'true' });
    if (modelId) form.set('model_id', modelId);
    let data;
    let status = 0;
    try {
        const response = await fetch('/model-manager/civitai/download', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form });
        status = response.status;
        data = await response.json();
    } catch (error) {
        data = { success: false, error: String(error) };
    }
    const job = resourceDownloads[versionId];
    if (!data || !data.success) {
        // Not found is for good - the version and its model are gone - and
        // is said as such, with nothing to retry; anything else can be.
        Object.assign(job, { state: status === 404 ? 'unavailable' : 'error',
                             error: (data && data.error) || 'Download failed' });
        console.warn(`[ModelManager] Download of version ${versionId} refused: ${job.error}`);
    } else {
        Object.assign(job, { target: data.version_id, versionName: data.version_name,
                             substituted: !!data.substituted });
        // In the downloads panel too, with every other download.
        if (data.progress) downloads().track(data.progress);
        if (data.already_installed) finishResourceDownload(versionId);
        else pollResourceDownloads();
    }
    redrawResourceDownload(versionId, { versionId, modelId });
    redrawResourceChips();
};

function finishResourceDownload(versionId) {
    resourceDownloads[versionId].state = 'installed';
    installedResourceVersions.add(versionId);
    refreshResourceChips();
}

/** Follow the dialog's downloads until each is in the library, or failed. */
function pollResourceDownloads() {
    if (resourceDownloadPoll) return;
    resourceDownloadPoll = setInterval(async () => {
        const active = Object.entries(resourceDownloads).filter(([, job]) => job.state === 'downloading');
        if (!active.length) {
            clearInterval(resourceDownloadPoll);
            resourceDownloadPoll = null;
            return;
        }
        for (const [id, job] of active) {
            let progress = null;
            try {
                const data = await apiCall({ endpoint: '/model-manager/civitai/download/progress',
                                             params: { version_id: job.target } });
                progress = data && data.progress;
            } catch (error) {
                continue;
            }
            if (!progress) continue;
            job.percent = Math.floor(progress.percent || 0);
            job.finishing = progress.status === 'finishing';
            // Complete is on disk; synced is in the library, which is what a
            // chip or a send looks at.
            if (progress.status === 'complete' && progress.synced) finishResourceDownload(Number(id));
            else if (progress.status === 'error' || progress.status === 'cancelled') {
                Object.assign(job, { state: 'error', error: progress.error || progress.status });
                console.warn(`[ModelManager] Download of ${progress.file_name || `version ${id}`} failed: ${job.error}`);
            }
            redrawResourceDownload(Number(id));
        }
        redrawResourceChips();
    }, TIMING.poll);
}

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        window.mmCloseMetaModal();
    }
});

// Download more images (appends to existing list without resetting scroll)
window.mmLoadMoreImages = async function() {
    // Guard: prevent calls if already loading, no version selected, or no more images to load
    // Allow call if: first download (imagesSyncDate null) OR cursor exists (more images available)
    const canLoadMore = imagesSyncDate === null || (nextImagesCursor !== null && nextImagesCursor !== '');
    if (isLoadingMore || !currentVersionId || !canLoadMore) return;

    isLoadingMore = true;
    const loadMoreBtn = document.getElementById('mm_load_more_btn');
    if (loadMoreBtn) {
        loadMoreBtn.disabled = true;
        loadMoreBtn.textContent = 'Downloading...';
    }

    try {
        const response = await fetch('/model-manager/images/load-more', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `version_id=${currentVersionId}`
        });

        const data = await response.json();

        if (data.success) {
            // The answer holds what Civitai sent, filtered or not, so the
            // gallery is read again from the server rather than added to -
            // which also brings the cursor, and the counts the note compares.
            const before = galleryCounts();
            let loaded;
            if (imageBrowsing === 'pages') {
                const oldPages = getImagePageCount(filteredImageCount);
                loaded = await loadImagesPage(imagesOffset);
                const newPages = getImagePageCount(filteredImageCount);
                if (loaded && newPages > oldPages) {
                    await scrollToModelImagesTop();
                    await showImagePage(newPages);
                }
            } else {
                // Show what just arrived, and stay where the reader is: new
                // images are stored after the old, so they are the next page.
                loaded = await loadImagesPage(currentImages.length, { append: true });
            }
            if (loaded) downloadNote = downloadedImagesNote(before, galleryCounts(), data.message);
            // Drawn again either way: with the note, or the button stays at
            // "Downloading...".
            renderModelImages(currentImages);
            console.log(`[ModelManager] Downloaded ${data.downloaded_count || 0} images (${filteredImageCount} shown of ${totalImageCount}, has_more: ${nextImagesCursor !== null})`);
        } else {
            console.error('[ModelManager] Download more failed:', data.error);
            downloadNote = downloadFailedNote(data.error);
            renderModelImages(currentImages);
        }
    } catch (error) {
        console.error('[ModelManager] Download more error:', error);
        downloadNote = downloadFailedNote(error?.message);
        renderModelImages(currentImages);
    } finally {
        isLoadingMore = false;
    }
};

window.mmFirstImagePage = async function() {
    if (currentImagePage === 1) return;
    await showImagePage(1);
};

window.mmLastImagePage = async function() {
    const totalPages = getImagePageCount(filteredImageCount);
    if (currentImagePage === totalPages) return;
    await showImagePage(totalPages);
};

window.mmPrevImagePage = async function() {
    if (currentImagePage <= 1) return;
    await showImagePage(currentImagePage - 1);
};

window.mmNextImagePage = async function() {
    const totalPages = getImagePageCount(filteredImageCount);
    if (currentImagePage >= totalPages) return;
    await showImagePage(currentImagePage + 1);
};

window.mmGoToImagePage = async function(page) {
    const totalPages = getImagePageCount(filteredImageCount);
    if (page < 1 || page > totalPages || page === currentImagePage) return;

    await scrollToModelImagesTop();
    await showImagePage(page);
};

// Convert full file path to dropdown-compatible path
// Full: F:\...\models\Stable-diffusion\_SD_1_5\model.safetensors
// Dropdown: _SD_1_5/model.safetensors (relative to type folder)
function getDropdownPath(filePath, modelType) {
    if (!filePath) return null;

    // Map model types to their folder names
    const typeFolderMap = {
        'Checkpoint': 'Stable-diffusion',
        'LORA': 'Lora',
        'TextualInversion': 'embeddings',
        'VAE': 'VAE',
        'Controlnet': 'ControlNet',
        'Upscaler': 'ESRGAN',
    };

    const typeFolder = typeFolderMap[modelType];
    if (!typeFolder) return null;

    // Find the type folder in the path and take everything after it
    // Match: /Stable-diffusion/ or \Stable-diffusion\
    // Escape special regex chars in folder name, then match separator + folder + separator
    const escapedFolder = typeFolder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`[\\\\\/]${escapedFolder}[\\\\\/](.+)$`, 'i');
    const match = filePath.match(regex);

    if (match) {
        // Return path as-is (preserve original separators)
        return match[1];
    }

    return null;
}

// Match VAE name from metadata to dropdown option
// Metadata often has VAE without extension, dropdown has with extension
// Forge Neo's "VAE / Text Encoder" control: a Gradio multiselect backed by
// the forge_additional_modules setting. Classic Forge and A1111 instead
// expose a single-value #setting_sd_vae plus a selectVAE() global, which
// Neo does not have at all - so the old reset-to-None silently did nothing
// there and whatever was selected last stayed selected.
const NEO_MODULES_ID = 'setting_sd_modules';
const MODULES_LABEL = 'VAE / Text Encoder';

/**
 * Find the multiselect holding the VAE / Text Encoder modules.
 *
 * Neo gives it elem_id="setting_sd_modules". Classic Forge builds the same
 * gr.Dropdown with no elem_id and no elem_classes, so there it has to be
 * found by its label. Both render Gradio's div.wrap-inner, which is also
 * what Neo's own modelHelp.js keys off.
 */
function getModulesControl() {
    const app = gradioApp();

    const byId = app.querySelector(`#${NEO_MODULES_ID}`);
    if (byId) return byId;

    for (const span of app.querySelectorAll('span')) {
        if (!span.textContent.trim().startsWith(MODULES_LABEL)) continue;
        // Climb to the ancestor that actually holds the selection.
        let node = span.parentElement;
        while (node) {
            if (node.querySelector('div.wrap-inner')) return node;
            node = node.parentElement;
        }
    }

    return null;
}

function nextFrame(ms = 60) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/** The options Gradio is currently offering, as {label, element} pairs. */
function readModuleOptions(container) {
    // The open list is portalled in some Gradio builds, so fall back to a
    // document-wide lookup - only one dropdown can be open at a time.
    let nodes = container.querySelectorAll('[data-testid="dropdown-option"]');
    if (!nodes.length) {
        nodes = gradioApp().querySelectorAll('[data-testid="dropdown-option"]');
    }
    return Array.from(nodes).map((el) => ({
        label: el.getAttribute('aria-label') || el.textContent.trim(),
        element: el,
    }));
}

/**
 * Match a VAE name from image metadata to one of `labels`.
 *
 * Metadata usually carries the bare name while the control lists the file,
 * so "vae-ft-mse-840000" has to find "vae-ft-mse-840000.safetensors".
 */
function matchVAEName(vaeName, labels) {
    if (!vaeName) return null;
    if (!labels || !labels.length) return vaeName;

    if (labels.includes(vaeName)) return vaeName;

    const wanted = vaeName.toLowerCase();
    for (const label of labels) {
        const lower = label.toLowerCase();
        if (lower.startsWith(wanted) ||
            lower.replace(/\.(safetensors|sft|gguf|pt|ckpt|bin)$/i, '') === wanted) {
            console.log('[ModelManager] Matched VAE:', vaeName, '->', label);
            return label;
        }
    }

    console.log('[ModelManager] No VAE match found for:', vaeName);
    return null;
}

/**
 * Commit a choice in Gradio's open option list.
 *
 * The list is bound to mousedown, not click: element.click() dispatches a
 * click event only, so the list opens and then nothing is ever selected.
 * The token remove buttons are the other way round and do take click.
 */
function pressOption(element) {
    element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
}

/** Drop every module currently selected. */
function clearModules(container) {
    // One ✕ clears the lot; otherwise drop the tokens one by one. Both are
    // real click paths, so Gradio commits the change to the setting.
    const removeAll = container.querySelector('.token-remove.remove-all');
    if (removeAll) {
        removeAll.click();
        return;
    }
    container.querySelectorAll('.token .token-remove, .token > .token-remove')
        .forEach((button) => button.click());
}

function selectedModuleLabels(container) {
    return Array.from(container.querySelectorAll('.wrap-inner .token'))
        .map((token) => token.textContent.replace(/\s*×\s*$/, '').trim())
        .filter(Boolean);
}

/**
 * Point Neo's VAE / Text Encoder control at exactly `names`.
 *
 * An image whose metadata names no VAE must end up with none selected:
 * leaving a previous pick in place is how a Qwen VAE ends up decoding an
 * SDXL latent, which produces a flat single-colour image.
 *
 * Returns false when the control is absent, i.e. this is not Forge Neo.
 */
async function applyForgeModules(names) {
    const container = getModulesControl();
    if (!container) return false;

    clearModules(container);
    await nextFrame();

    if (!names.length) {
        console.log('[ModelManager] Cleared VAE / Text Encoder (none in metadata)');
        return true;
    }

    const input = container.querySelector('input');
    if (!input) {
        console.warn('[ModelManager] VAE control has no input; left cleared');
        return true;
    }

    for (const name of names) {
        input.focus();
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await nextFrame();

        const options = readModuleOptions(container);
        const match = matchVAEName(name, options.map((o) => o.label));
        const option = match && options.find((o) => o.label === match);

        if (!option) {
            console.warn(`[ModelManager] VAE "${name}" is not offered by this install;`
                         + ' leaving it unselected rather than guessing');
            continue;
        }

        pressOption(option.element);
        await nextFrame();
    }

    input.blur();
    console.log('[ModelManager] VAE / Text Encoder now:', selectedModuleLabels(container));
    return true;
}

/**
 * The VAE an image was made with, whatever Civitai called the field.
 *
 * Counted over 67,458 stored images, a VAE name turns up under several
 * spellings, and they do not overlap:
 *
 *   VAE       11,304   the usual A1111 field
 *   vaes       2,392   a list, from ComfyUI workflows Civitai normalised.
 *                      Every one of these has no VAE field at all, so
 *                      reading only VAE misses them entirely
 *   vae_name      62   ComfyUI's own node field, when it survives
 *   Vae / vae     13   case, as written by whatever made the image
 *
 * "VAE hash" is deliberately not read: it identifies a file we cannot
 * name, and a hash in the dropdown would match nothing.
 */
/**
 * Does this name a file, or is it a way of saying "no separate VAE"?
 *
 * Seen in the library: "Default (model)" 131, "automatic" 30, "Default"
 * 14, "Baked VAE" 5. All of them mean the checkpoint's own VAE, which is
 * what an empty selection already gives, so they must not be searched for
 * in the dropdown.
 */
function isVaeFileName(value) {
    const name = String(value || '').trim();
    if (!name) return false;
    return !/^(automatic|none|null|default.*|baked vae|use same vae)$/i.test(name);
}

function vaeFromMeta(meta) {
    if (!meta) return null;

    const direct = meta.VAE || meta.Vae || meta.vae || meta.vae_name;
    if (typeof direct === 'string' && isVaeFileName(direct)) return direct.trim();

    // ComfyUI workflows arrive with a list, newest-normalised first.
    const listed = Array.isArray(meta.vaes)
        ? meta.vaes.find(v => typeof v === 'string' && isVaeFileName(v))
        : null;
    if (listed) return listed.trim();

    const resource = (meta.resources || []).find(r => r && r.type === 'vae');
    if (resource && resource.name) return resource.name;

    return null;
}

/**
 * Apply a VAE choice on whichever UI this is.
 *
 * `vaeName` of null means the image named none, which must clear the
 * selection rather than leave the last one in place.
 */
// ------------------------------------------------ Forge Neo UI preset + modules
// An image's generation data never names a Flux model's CLIP-L and T5-XXL, or
// a Qwen-Image model's Qwen2.5-VL - whoever made it had them loaded. So
// before sending, the server works out the model's architecture from its file
// (or Civitai's baseModel), and which of the modules it needs are installed
// (architecture.py, forge_modules.py); the send then switches Forge's UI
// preset to match, and selects them.

// What the server calls each kind of module, as a person would.
const MODULE_KIND_NAMES = {
    clip_l: 'CLIP-L', clip_g: 'CLIP-G', t5xxl: 'T5-XXL', umt5xxl: 'UMT5-XXL',
    qwen25_7b: 'Qwen2.5-VL 7B', qwen3_06b: 'Qwen3 0.6B', qwen3_4b: 'Qwen3 4B',
    qwen3_8b: 'Qwen3 8B', qwen3vl_4b: 'Qwen3-VL 4B', gemma2_2b: 'Gemma 2 2B',
    ministral3_3b: 'Ministral 3 3B', vae_ae: 'Flux VAE (ae)', vae_flux2: 'Flux.2 VAE',
    vae_wan21: 'Qwen-Image / Wan VAE', vae_sd: 'SD VAE',
};

/**
 * The version whose gallery is showing: the one picked in the details panel,
 * or the grid's own row where the model has one version.
 */
function shownVersion(model) {
    return (currentVersions.length && currentVersions[selectedVersionIndex]) || model;
}

/** What a version's file is: read from it, else Civitai's type meanwhile. */
function fileTypeOf(entry, model) {
    return entry.file_type || entry.model_type || (model && model.civitai_type) || null;
}

/**
 * The checkpoint an image names: the Civitai version ids of its resources
 * filed as checkpoints, the hashes its generation data gives the model, and
 * the model's name. The server matches them against the library, and asks
 * Civitai about one it does not have.
 */
function imageCheckpoint(img) {
    const meta = (img && img.meta) || {};
    const versionIds = (meta.civitaiResources || [])
        .filter((r) => String(r.type || '').toLowerCase() === 'checkpoint' && r.modelVersionId)
        .map((r) => r.modelVersionId);
    const hashes = (meta.resources || [])
        .filter((r) => r.type === 'model' && r.hash)
        .map((r) => r.hash);
    if (meta['Model hash']) hashes.push(meta['Model hash']);
    return { versionIds, hashes: [...new Set(hashes)], name: meta.Model || '' };
}

/**
 * What to set up in Forge for an image: its UI preset, and the modules to
 * select. Which model that is for - the gallery's checkpoint, the image's
 * own, a LoRA's, Civitai's say - the server works out (send_plan.py).
 * null if the server cannot say.
 */
async function fetchForgePlan(model, img) {
    if (!model) return null;
    const version = shownVersion(model);
    const checkpoint = imageCheckpoint(img);
    const params = new URLSearchParams();
    if (version.file_path) params.set('file_path', version.file_path);
    const baseModel = version.base_model || model.base_model;
    if (baseModel) params.set('base_model', baseModel);
    if (checkpoint.versionIds.length) params.set('version_ids', checkpoint.versionIds.join(','));
    if (checkpoint.hashes.length) params.set('hashes', checkpoint.hashes.join(','));
    if (checkpoint.name) params.set('model_name', checkpoint.name);
    try {
        const response = await fetch('/model-manager/forge-modules?' + params.toString());
        const plan = await response.json();
        return plan && plan.success ? plan : null;
    } catch (e) {
        console.warn('[ModelManager] Could not work out the model\'s architecture:', e);
        return null;
    }
}

/**
 * Forge's UI preset as it stands, or null where there is none. Neo shows it
 * as a dropdown; the original Forge as radio buttons (sd, xl, flux, all).
 */
function currentForgePreset() {
    const container = gradioApp().querySelector('#forge_ui_preset');
    if (!container) return null;
    if (container.querySelector('input[type="radio"]')) {
        return container.querySelector('input[type="radio"]:checked')?.value || null;
    }
    return container.querySelector('input')?.value || null;
}

/**
 * Switch Forge Neo's UI preset, and wait for it to take.
 *
 * Done before anything of the image is sent: a preset change resets the
 * sampler, scheduler and steps to its defaults and restores its saved
 * modules, which would overwrite what the image asked for. Forge's own
 * scripts read the preset from this control's input, so that is what is
 * waited on, then a moment for the rest of the change to land.
 *
 * Returns whether Forge is now on `preset`. False where this is not Forge
 * Neo, or the preset is not offered - and then the send goes on as before.
 */
async function switchForgePreset(preset) {
    const container = gradioApp().querySelector('#forge_ui_preset');
    const input = container?.querySelector('input');
    if (!input || !preset) return false;
    if (currentForgePreset() === preset) return true;
    watchForgeCalls();
    const callsBefore = forgeCalls.started;

    // The original Forge's radio buttons: press the one for the preset. The
    // dropdown path below would type into a radio's value - which it did,
    // clearing the first choice's.
    const radios = Array.from(container.querySelectorAll('input[type="radio"]'));
    if (radios.length) {
        const radio = radios.find((r) => r.value === preset);
        if (!radio) {
            console.warn(`[ModelManager] Forge offers no "${preset}" preset; left as it was`);
            return false;
        }
        radio.click();
        return await presetTaken(preset, callsBefore);
    }

    input.focus();
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await nextFrame();
    const option = readModuleOptions(container).find((o) => o.label === preset);
    if (!option) {
        input.blur();
        console.warn(`[ModelManager] Forge offers no "${preset}" preset; left as it was`);
        return false;
    }
    pressOption(option.element);
    input.blur();
    return await presetTaken(preset, callsBefore);
}

/**
 * The calls Gradio makes to the server for a control's events. They go to
 * <root>/run/<event> through the page's fetch - in Forge Neo's Gradio 4.39
 * and the original Forge's 4.40 alike - so wrapping fetch sees each one start
 * and finish.
 */
const forgeCalls = { started: 0, inFlight: 0, last: 0 };

function watchForgeCalls() {
    if (globalThis.fetch?.mmWatched) return;
    const original = globalThis.fetch;
    const watched = function(resource, ...rest) {
        let path = '';
        try {
            path = new URL(typeof resource === 'string' ? resource : resource?.url || String(resource),
                           window.location.origin).pathname;
        } catch { /* not a URL we can read: not one of Gradio's */ }
        if (!path.includes('/run/')) return original.call(this, resource, ...rest);
        forgeCalls.started++;
        forgeCalls.inFlight++;
        forgeCalls.last = Date.now();
        const settle = () => { forgeCalls.inFlight--; forgeCalls.last = Date.now(); };
        const call = original.call(this, resource, ...rest);
        call.then(settle, settle);
        return call;
    };
    watched.mmWatched = true;
    globalThis.fetch = watched;
}

/**
 * Wait for a preset change to show, then for Forge to finish answering it.
 *
 * Forge answers from the server, with no progress shown: the preset's
 * sampler, scheduler, steps, size and CFG, then - chained on that - its
 * checkpoint and modules. Each lands when the server is done. A fixed 600 ms
 * lost to a slow answer (a Krea model's, sent from the Model Manager): the
 * image's settings went in first and the preset's defaults then overwrote
 * them. So wait until every call started since the switch has come back and
 * none has started for a moment - the chained one starts as the first ends.
 * A switch that makes no call at all is given the old 600 ms.
 */
async function presetTaken(preset, callsBefore = forgeCalls.started) {
    const start = Date.now();
    for (let i = 0; i < 30 && currentForgePreset() !== preset; i++) await nextFrame(100);
    while (Date.now() - start < FORGE_PRESET_MAX_MS) {
        const called = forgeCalls.started > callsBefore;
        if (called && forgeCalls.inFlight === 0 && Date.now() - forgeCalls.last >= FORGE_PRESET_QUIET_MS) break;
        if (!called && Date.now() - start >= FORGE_PRESET_SETTLE_MS) break;
        await nextFrame(50);
    }
    await nextFrame(100);   // Gradio writes the last answer into the page after it arrives
    console.log('[ModelManager] Forge UI preset now:', currentForgePreset(),
                `(${forgeCalls.started - callsBefore} server calls, ${Date.now() - start} ms)`);
    return currentForgePreset() === preset;
}

// How long a preset switch is waited on: TIMING in common.mjs.
const FORGE_PRESET_SETTLE_MS = TIMING.presetSettle;
const FORGE_PRESET_QUIET_MS = TIMING.presetQuiet;
const FORGE_PRESET_MAX_MS = TIMING.presetMax;

/**
 * Select the modules the plan picked, and say what it could not find.
 * Called after the paste, as applyVaeSelection() is: the paste re-renders
 * much of the page but never touches the modules.
 */
async function applyPlannedModules(plan) {
    await applyForgeModules(plan.select || []);
    const problems = [];
    if (plan.missing && plan.missing.length) {
        const names = plan.missing.map((kind) => MODULE_KIND_NAMES[kind] || kind).join(', ');
        problems.push(`This ${plan.preset} model also needs ${names}, which is not installed. `
                      + 'Add it to Forge\'s VAE or text_encoder folder, or select it in "VAE / Text Encoder".');
    }
    if (plan.not_found && plan.not_found.length) {
        problems.push(`Settings -> Model Manager names ${plan.not_found.join(', ')} for ${plan.preset} `
                      + 'models, but Forge does not list it: check the name, or put the file in Forge\'s '
                      + 'VAE or text_encoder folder.');
    }
    if (problems.length) showNotice(problems.join(' '));
}

/** A short message in the corner of the page, gone after a while. */
function showNotice(text) {
    const notice = document.createElement('div');
    notice.className = 'mm-notice';
    notice.textContent = text;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 12000);
    console.warn('[ModelManager]', text);
}

/**
 * An image's generation data with a video's frames and size added: Civitai
 * keeps neither its length nor its frame rate, so they are read from the
 * video itself. Its card copy is read rather than the upload - the upload can
 * be a GIF under an .mp4 name (cardMediaUrl), whose length a video element
 * cannot read. What cannot be read is left to the preset, and said.
 */
async function withVideoParams(meta, img, isVideo = true) {
    const params = { ...meta };
    const [w, h] = String(meta.Size || '').split('x').map(Number);
    if ((w || img.width) && (h || img.height)) {
        const size = videoSize(w || img.width, h || img.height);
        params.Size = `${size.width}x${size.height}`;
    }
    if (!isVideo) return params;
    const frames = videoFrames(await videoDuration(cardMediaUrl(img.url, img.type)));
    if (frames) params['Batch size'] = frames;
    else showNotice('Could not read this video\'s length: Frames are left as the Wan preset has them.');
    return params;
}

/**
 * The image an image-to-video model starts from, as a file for img2img, or
 * null. Civitai does not keep the one the uploader used, so for a video it is
 * the first frame - after the video's encoding, and any upscaling since, but
 * the nearest there is. The original first; if the browser cannot decode it
 * (an animated upload is kept as a GIF under an .mp4 name) the card's copy,
 * which is small. For a still, the still.
 */
async function startFrame(img, isVideo) {
    const name = `civitai-${img.id || 'image'}`;
    if (!isVideo) {
        try {
            const response = await fetch(originalMediaUrl(img.url));
            const blob = response.ok ? await response.blob() : null;
            return blob ? { file: new File([blob], name, { type: blob.type }), small: false } : null;
        } catch (error) {
            console.warn('[ModelManager] Could not fetch the image:', error);
            return null;
        }
    }
    let blob = await firstFrame(originalMediaUrl(img.url));
    const small = !blob;
    if (!blob) blob = await firstFrame(cardMediaUrl(img.url, img.type));
    return blob ? { file: new File([blob], `${name}.png`, { type: 'image/png' }), small } : null;
}

/**
 * A video's first frame as a PNG, or null. Drawn from a video element onto a
 * canvas: Civitai's image server allows it (CORS), and if it ever stops, the
 * canvas refuses to export - an error, never a blank frame. Only enough of
 * the file is fetched to decode one frame.
 */
function firstFrame(url, timeoutMs = 20000) {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        let settled = false;
        const finish = (blob) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            video.removeAttribute('src');
            video.load();
            resolve(blob || null);
        };
        const timer = setTimeout(() => finish(null), timeoutMs);
        video.crossOrigin = 'anonymous';
        video.muted = true;
        video.preload = 'auto';
        video.onloadeddata = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                canvas.toBlob(finish, 'image/png');
            } catch (error) {
                console.warn('[ModelManager] Could not read the video\'s first frame:', error);
                finish(null);
            }
        };
        video.onerror = () => finish(null);
        video.src = url;
    });
}

/** Load a file into img2img's image, as its Upload button would. */
function giveImg2imgImage(file) {
    const input = gradioApp().querySelector('#img2img_image input[type="file"]');
    if (!input || typeof DataTransfer === 'undefined') return false;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
}

// ------------------------------------------------------------ resource chips
// A send puts the image's LoRAs and embeddings under the target tab's
// negative prompt as chips; a click puts a resource's tag in, or takes it
// out. The rules are collectResourceChips() and toggleChip() in common.mjs.

// Per tab, the chips the last send left there, the row that shows them, and
// the image and model they came from - a download from the Resources dialog
// looks them up again.
const resourceChips = {};
const resourceChipRows = {};
const resourceChipSources = {};

/**
 * What a chip for a resource not in the library says: that it is missing and
 * a click downloads it, or how the download is going. A download is shared
 * with the Resources dialog, by the version id the image names.
 */
function missingChipState(chip) {
    const what = chip.kind === 'lora' ? 'LoRA' : 'embedding';
    if (!chip.versionId && !chip.hash) {
        return { busy: true, unavailable: true, note: 'no hash recorded',
                 title: `${chip.title}: the image names it without a hash or a version, so it cannot be found` };
    }
    const job = chip.versionId ? resourceDownloads[chip.versionId] : chip.lookup;
    if (job && job.state === 'checking') {
        return { busy: true, note: 'checking Civitai...', title: `Asking Civitai what ${chip.title} is` };
    }
    if (job && job.state === 'unavailable') {
        return { busy: true, unavailable: true, note: 'not on Civitai',
                 title: `${chip.title}: ${job.error || 'Civitai does not have it'}` };
    }
    if (job && job.state === 'downloading') {
        return { busy: true, note: job.finishing ? 'adding to library...' : job.percent ? `${job.percent}%` : 'queued',
                 title: `Downloading the missing ${what} ${chip.title}` };
    }
    if (job && job.state === 'installed' && job.substituted) {
        return { busy: true, note: `got ${job.versionName || 'a newer version'} instead`,
                 title: `The image's version of ${chip.title} is gone from Civitai; the newest was downloaded` };
    }
    if (job && job.state === 'error') {
        // Why, on the chip itself - it was only in the tooltip - cut short;
        // the tooltip keeps all of it.
        const why = String(job.error || '');
        const short = why.length > CHIP_REASON_LENGTH ? `${why.slice(0, CHIP_REASON_LENGTH)}...` : why;
        return { busy: false, note: `download failed${short ? `: ${short}` : ''}, click to retry`,
                 title: `${chip.title}: ${why || 'the download failed'}` };
    }
    return { busy: false, note: `missing ${what}, click to download`,
             title: `${chip.title} is not in the library: click to download it` };
}

/** Redraw every tab's chips, to show a download's progress. */
function redrawResourceChips() {
    for (const tab of Object.keys(resourceChips)) {
        if (resourceChips[tab]) showResourceChips(tab, resourceChips[tab]);
    }
}

/**
 * Download a chip's missing resource, as the Resources dialog would. A chip
 * from the infotext's list knows only a hash: that is looked up first.
 */
async function downloadChip(chip) {
    if (!chip.versionId && chip.hash) {
        chip.lookup = { state: 'downloading', percent: 0 };
        redrawResourceChips();
        const answer = (await resolveResourceHashes([chip.hash]))[chip.hash];
        chip.versionId = (answer && answer.version_id) || null;
        chip.modelId = chip.modelId || (answer && answer.model_id) || null;
        chip.lookup = chip.versionId ? null
            : answer ? { state: 'unavailable', error: 'Civitai does not know this file' }
            : { state: 'error', error: 'Civitai could not be asked' };
    }
    if (!chip.versionId) {
        chip.lookup = chip.lookup || { state: 'error', error: 'the image does not say which version it is' };
        redrawResourceChips();
        return;
    }
    await window.mmDownloadResource(chip.versionId, chip.modelId);
}

/**
 * Find out which of a tab's missing chips can be downloaded at all. One the
 * image names by version id can; one it names only by hash is asked about,
 * as the Resources dialog asks - and a hash Civitai has never heard of is a
 * file that cannot be downloaded, which the chip should say before a click
 * rather than after it.
 */
async function checkMissingChips(tab) {
    const waiting = (resourceChips[tab] || []).filter((c) => !c.installed && !c.versionId && c.hash);
    if (!waiting.length) return;
    const settle = (answers) => {
        for (const chip of waiting) {
            if (!Object.prototype.hasOwnProperty.call(answers, chip.hash)) continue;
            const answer = answers[chip.hash];
            chip.versionId = (answer && answer.version_id) || null;
            chip.modelId = chip.modelId || (answer && answer.model_id) || null;
            chip.lookup = chip.versionId ? null
                : { state: 'unavailable', error: 'Civitai does not know this file' };
        }
        redrawResourceChips();
    };
    for (const chip of waiting) chip.lookup = { state: 'checking' };
    settle(knownHashes);
    const unasked = waiting.filter((c) => c.lookup && c.lookup.state === 'checking').map((c) => c.hash);
    if (!unasked.length) return;
    redrawResourceChips();
    const resolved = await resolveResourceHashes([...new Set(unasked)], (partial) => settle(partial));
    Object.assign(knownHashes, resolved);
    settle(resolved);
    for (const chip of waiting) {
        if (chip.lookup && chip.lookup.state === 'checking') {
            chip.lookup = { state: 'error', error: 'Civitai could not be asked' };
        }
    }
    redrawResourceChips();
}

/** Look each tab's chips up again, after a download. */
async function refreshResourceChips() {
    for (const [tab, source] of Object.entries(resourceChipSources)) {
        if (!resourceChips[tab]) continue;
        const { chips } = collectResourceChips(source.img.meta, await fetchImageFiles(source.img),
                                               source.gallery);
        showResourceChips(tab, chips);
        checkMissingChips(tab);
    }
}

/** The local file of each of an image's resources, from the library alone. */
async function fetchImageFiles(img) {
    const none = { versions: {}, hashes: {} };
    const ids = ((img.meta || {}).civitaiResources || []).map((r) => r.modelVersionId).filter(Boolean);
    const named = resourceNames(img.meta);
    // The resources' own hashes, and those the image keeps apart from them.
    const hashes = [...new Set([...imageResourceHashes(img),
                                ...named.map((n) => n.hash.toLowerCase()).filter(Boolean)])];
    if (!ids.length && !hashes.length && !named.length) return none;
    try {
        const data = await apiCall({ endpoint: '/model-manager/image-resources',
                                     params: { version_ids: ids.join(','), hashes: hashes.join(','),
                                               names: named.length ? JSON.stringify(named) : '' } });
        return data && data.success ? data : none;
    } catch (error) {
        console.warn('[ModelManager] Could not look up the image\'s resources:', error);
        return none;
    }
}

/** The gallery's own file, described as the server describes one. */
function galleryFile(model) {
    const version = model ? shownVersion(model) : null;
    if (!version || !version.file_path) return null;
    const name = version.file_path.split(/[\\/]/).pop();
    return { file_stem: name.replace(/\.[^.]+$/, ''), file_type: fileTypeOf(version, model) };
}

function promptBoxes(tab) {
    return { positive: gradioApp().querySelector(`#${tab}_prompt textarea`),
             negative: gradioApp().querySelector(`#${tab}_neg_prompt textarea`) };
}

// A failed download's reason is shown on its chip up to this many characters.
const CHIP_REASON_LENGTH = 60;

// Each chip's mark, beside its colour: whether it is here, can be
// downloaded, or cannot - so it reads without telling the colours apart.
const CHIP_MARKS = { have: '✓', download: '↓', unavailable: '⊘' };

function showResourceChips(tab, chips) {
    resourceChips[tab] = chips && chips.length ? chips : null;
    const row = resourceChipRows[tab];
    if (!resourceChips[tab]) {
        row?.remove();
        return;
    }
    const element = row || document.createElement('div');
    resourceChipRows[tab] = element;
    element.id = `mm_resource_chips_${tab}`;
    element.className = 'mm-resource-chips';
    element.innerHTML = resourceChips[tab].map((chip, index) => {
        const notes = [chip.kind === 'lora' ? `weight ${chip.weight}` : 'embedding',
                       chip.where === 'negative' ? 'negative prompt' : ''].filter(Boolean);
        const missing = chip.installed ? null : missingChipState(chip);
        const title = missing ? missing.title : `${chip.title} (${notes.join(', ')})`;
        // Whether it can be used is said by colour and a mark; whether a
        // prompt holds it, by filled or outlined (updateResourceChipStates).
        const state = !missing ? 'have' : missing.unavailable ? 'unavailable' : 'download';
        const classes = missing ? (missing.unavailable ? ' missing unavailable' : ' missing') : '';
        return `<button type="button" class="mm-resource-chip${classes}" data-state="${state}"
                        data-chip="${index}" ${missing && missing.busy ? 'disabled' : ''}
                        title="${escapeHtml(title)}">`
             + `<span class="mm-resource-chip-mark" aria-hidden="true">${CHIP_MARKS[state]}</span>`
             + `<span class="mm-resource-chip-name">${escapeHtml(chip.name)}</span>`
             + (missing ? `<span class="mm-resource-chip-note">${escapeHtml(missing.note)}</span>` : '')
             + '</button>';
    }).join('') + '<button type="button" class="mm-btn secondary mm-btn-small" data-chips-clear>Clear</button>'
        + '<div class="mm-resource-chips-key">'
        + `<span data-state="have">${CHIP_MARKS.have} in library</span>`
        + `<span data-state="download">${CHIP_MARKS.download} can download</span>`
        + `<span data-state="unavailable">${CHIP_MARKS.unavailable} not available</span>`
        + '<span>filled: in the prompt</span>'
        + (resourceChips[tab].some((chip) => chip.installed && chip.byName)
            ? '<span class="mm-resource-chips-note">Some LoRAs and embeddings are matched by name, not by hash.</span>'
            : '')
        + '</div>';
    if (!row) element.addEventListener('click', (event) => onResourceChipClick(tab, event));
    keepResourceChips();
}

function onResourceChipClick(tab, event) {
    if (event.target.closest('[data-chips-clear]')) {
        showResourceChips(tab, null);
        return;
    }
    const button = event.target.closest('[data-chip]');
    const chip = button && !button.disabled && resourceChips[tab]?.[Number(button.dataset.chip)];
    if (!chip) return;
    if (!chip.installed) {
        downloadChip(chip);
        return;
    }
    // Out of whichever prompt has it - it may have been moved by hand -
    // else into the one the image had it in.
    const { positive, negative } = promptBoxes(tab);
    const box = promptHasChip(positive?.value, chip) ? positive
        : promptHasChip(negative?.value, chip) ? negative
        : chip.where === 'negative' ? negative : positive;
    if (!box) return;
    box.value = toggleChip(box.value, chip);
    box.dispatchEvent(new Event('input', { bubbles: true }));
    updateResourceChipStates(tab);
}

/** Light each chip whose resource either prompt holds. */
function updateResourceChipStates(tab) {
    const row = resourceChipRows[tab];
    const chips = resourceChips[tab];
    if (!row || !chips) return;
    const { positive, negative } = promptBoxes(tab);
    row.querySelectorAll('[data-chip]').forEach((button) => {
        const chip = chips[Number(button.dataset.chip)];
        const held = promptHasChip(positive?.value, chip) || promptHasChip(negative?.value, chip);
        button.classList.toggle('active', !!held);
    });
}

/**
 * Keep each tab's chips under its negative prompt, and lit to match. Run
 * after every UI update: Gradio can re-render the prompt column, and a paste
 * changes the prompts without an input event.
 */
function keepResourceChips() {
    for (const tab of Object.keys(resourceChips)) {
        if (!resourceChips[tab]) continue;
        const anchor = gradioApp().querySelector(`#${tab}_neg_prompt_row`);
        const row = resourceChipRows[tab];
        if (anchor && row && anchor.nextElementSibling !== row) anchor.after(row);
        for (const box of Object.values(promptBoxes(tab))) {
            if (box && !box.dataset.mmChipsWatched) {
                box.dataset.mmChipsWatched = '1';
                box.addEventListener('input', () => updateResourceChipStates(tab));
            }
        }
        updateResourceChipStates(tab);
    }
}
if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(keepResourceChips);

/** Show txt2img, or img2img on its plain img2img mode. */
function showGenerationTab(tab) {
    if (tab === 'img2img') {
        if (typeof switch_to_img2img === 'function') {
            switch_to_img2img();
            return;
        }
        gradioApp().querySelectorAll('#tabs button')[1]?.click();
        gradioApp().querySelectorAll('#mode_img2img button')[0]?.click();
        return;
    }
    gradioApp().querySelector('#tabs button:first-child')?.click();
}

/** A video's length in seconds, from its metadata alone; null if unreadable. */
function videoDuration(url, timeoutMs = 10000) {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        const finish = (seconds) => {
            clearTimeout(timer);
            video.removeAttribute('src');
            video.load();
            resolve(seconds);
        };
        const timer = setTimeout(() => finish(null), timeoutMs);
        video.preload = 'metadata';
        video.muted = true;
        video.onloadedmetadata = () => finish(Number.isFinite(video.duration) ? video.duration : null);
        video.onerror = () => finish(null);
        video.src = url;
    });
}

async function applyVaeSelection(vaeName) {
    if (await applyForgeModules(vaeName ? [vaeName] : [])) return;

    // Classic Forge / A1111.
    if (typeof selectVAE === 'function') {
        selectVAE(vaeName || 'None');
        console.log('[ModelManager] Set VAE via selectVAE:', vaeName || 'None');
        return;
    }

    console.warn('[ModelManager] No VAE control found; leaving it alone');
}

// Cache for samplers and schedulers loaded from API
let cachedSamplers = null;
let cachedSchedulers = null;

// Load samplers and schedulers from API (called once on init)
async function loadUIOptionsFromAPI() {
    try {
        const response = await fetch('/model-manager/ui-options');
        const data = await response.json();

        if (data.success) {
            if (data.schedulers) {
                cachedSchedulers = data.schedulers.filter(s => s && s !== 'Automatic');
                console.log('[ModelManager] Loaded schedulers from API:', cachedSchedulers);
            }
            if (data.samplers) {
                cachedSamplers = data.samplers;
                console.log('[ModelManager] Loaded samplers from API:', cachedSamplers);
            }
        }
        // Outside the success check: the endpoint answers this even when the
        // samplers cannot be read, for the same reason the key banner does.
        if (data.image_browsing === 'pages' || data.image_browsing === 'continuous') {
            imageBrowsing = data.image_browsing;
            console.log('[ModelManager] Example images:', imageBrowsing);
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load UI options:', error);
        cachedSchedulers = [];
        cachedSamplers = [];
    }
}

// Get scheduler options (from cache)
function getSchedulerOptions() {
    if (cachedSchedulers === null) {
        console.log('[ModelManager] Schedulers not loaded yet');
        return [];
    }
    return cachedSchedulers;
}

// Get sampler options (from cache)
function getSamplerOptions() {
    if (cachedSamplers === null) {
        console.log('[ModelManager] Samplers not loaded yet');
        return [];
    }
    return cachedSamplers;
}

// Normalize string for comparison (lowercase, remove special chars, collapse spaces)
function normalizeForMatch(str) {
    if (!str) return '';
    return str.toLowerCase()
        .replace(/[_\-+]/g, ' ')  // Replace underscores, dashes, plus with space
        .replace(/\s+/g, ' ')      // Collapse multiple spaces
        .trim();
}

// Match sampler name from metadata to known sampler
// Handles variations like "Euler_Max" -> "Euler Max", case differences, etc.
function matchSamplerName(samplerName) {
    if (!samplerName) return samplerName;

    const samplers = getSamplerOptions();
    if (!samplers.length) return samplerName;

    // Try exact match first
    if (samplers.includes(samplerName)) {
        return samplerName;
    }

    // Normalize and match
    const normalizedInput = normalizeForMatch(samplerName);
    for (const sampler of samplers) {
        if (normalizeForMatch(sampler) === normalizedInput) {
            console.log('[ModelManager] Matched sampler:', samplerName, '->', sampler);
            return sampler;
        }
    }

    // Try partial match (input might have scheduler appended)
    for (const sampler of samplers) {
        if (normalizedInput.startsWith(normalizeForMatch(sampler) + ' ')) {
            console.log('[ModelManager] Partial sampler match:', samplerName, '-> starts with', sampler);
            // Don't return here - let splitSamplerScheduler handle it
            break;
        }
    }

    // Return original with basic normalization (underscore -> space)
    return samplerName.replace(/_/g, ' ');
}

// Load UI options on init
loadUIOptionsFromAPI();
// The words behind the "X · prompt" badge; the server has already filtered.

// Split combined "Sampler Scheduler" format into separate parts
// e.g., "Euler a Karras" -> { sampler: "Euler a", scheduler: "Karras" }
// Also handles variations like "Euler_a_Karras"
function splitSamplerScheduler(samplerString) {
    if (!samplerString) return { sampler: null, scheduler: null };

    // Normalize underscores to spaces for matching
    const normalized = samplerString.replace(/_/g, ' ');

    const schedulers = getSchedulerOptions();

    // Check if the normalized string ends with a known scheduler
    for (const scheduler of schedulers) {
        // Check both exact and case-insensitive
        if (normalized.endsWith(' ' + scheduler) ||
            normalized.toLowerCase().endsWith(' ' + scheduler.toLowerCase())) {
            const sampler = normalized.slice(0, -(scheduler.length + 1));
            // Match the sampler to known samplers
            const matchedSampler = matchSamplerName(sampler);
            console.log('[ModelManager] Split sampler+scheduler:', samplerString, '->', matchedSampler, '+', scheduler);
            return { sampler: matchedSampler, scheduler };
        }
    }

    // No scheduler suffix found - just match the sampler
    const matchedSampler = matchSamplerName(normalized);
    return { sampler: matchedSampler, scheduler: null };
}

// Build infotext string from image metadata (A1111 format)
function buildInfotext(meta, { denoisingStrength = null } = {}) {
    if (!meta) return '';

    let infotext = '';

    // Prompt
    if (meta.prompt) {
        infotext += meta.prompt;
    }

    // Negative prompt
    if (meta.negativePrompt) {
        infotext += '\nNegative prompt: ' + meta.negativePrompt;
    }

    // Split sampler if it contains scheduler
    let sampler = meta.sampler;
    let scheduler = meta['Schedule type'];

    // If no explicit scheduler, try to extract from combined sampler string
    if (!scheduler && sampler) {
        const split = splitSamplerScheduler(sampler);
        sampler = split.sampler;
        scheduler = split.scheduler;
    }

    // Check if this has actual hires fix data (need all required fields)
    // Only include Denoising strength and hires fields if there's a complete hires setup
    const hasHiresFix = meta['Denoising strength'] &&
        (meta['Hires upscale'] || meta['Hires upscaler'] || meta['Hires resize-1'] || meta['Hires resize-2']);

    // Build parameters line
    const params = [];

    if (meta.steps) params.push(`Steps: ${meta.steps}`);
    if (sampler) params.push(`Sampler: ${sampler}`);
    if (scheduler) params.push(`Schedule type: ${scheduler}`);
    if (meta.cfgScale) params.push(`CFG scale: ${meta.cfgScale}`);
    if (meta.seed) params.push(`Seed: ${meta.seed}`);
    if (meta.Size) params.push(`Size: ${meta.Size}`);
    if (meta.Model) params.push(`Model: ${meta.Model}`);
    if (meta['Model hash']) params.push(`Model hash: ${meta['Model hash']}`);
    if (meta.VAE) params.push(`VAE: ${meta.VAE}`);
    if (meta['Clip skip']) params.push(`Clip skip: ${meta['Clip skip']}`);

    // img2img always takes one - an image-to-video model needs 1 - and
    // txt2img only as part of a hires fix, where it would otherwise turn
    // hires on for an image that had none.
    const denoise = denoisingStrength ?? (hasHiresFix ? meta['Denoising strength'] : null);
    if (denoise !== null && denoise !== undefined) params.push(`Denoising strength: ${denoise}`);

    // Only include hires-related fields if there's a complete hires fix setup
    // This prevents paste from enabling hires when image doesn't have hires data
    if (hasHiresFix) {
        if (meta['Hires upscale']) params.push(`Hires upscale: ${meta['Hires upscale']}`);
        if (meta['Hires upscaler']) params.push(`Hires upscaler: ${meta['Hires upscaler']}`);
        if (meta['Hires steps']) params.push(`Hires steps: ${meta['Hires steps']}`);
    }

    // Add any other parameters from meta that we haven't explicitly handled
    const handledKeys = ['prompt', 'negativePrompt', 'steps', 'sampler', 'Schedule type', 'cfgScale', 'seed',
                        'Size', 'Model', 'Model hash', 'VAE', 'Denoising strength', 'Clip skip',
                        'Hires upscale', 'Hires upscaler', 'Hires steps', 'Hires resize-1', 'Hires resize-2',
                        'resources', 'civitaiResources'];

    // Check if ADetailer fields exist - toggle "ADetailer enable" accordingly
    // This is required for ADetailer's paste handler to auto-enable/disable the checkbox
    const hasADetailer = Object.keys(meta).some(key => key.startsWith('ADetailer '));
    if (hasADetailer) {
        params.push('ADetailer enable: True');
    } else {
        params.push('ADetailer enable: False');
    }

    for (const [key, value] of Object.entries(meta)) {
        if (!handledKeys.includes(key) && value !== null && value !== undefined && value !== '') {
            if (typeof value !== 'object') {
                params.push(`${key}: ${value}`);
            }
        }
    }

    if (params.length > 0) {
        infotext += '\n' + params.join(', ');
    }

    return infotext;
}

// Set Gradio dropdown value programmatically
function setGradioDropdown(elem_id, value) {
    const container = gradioApp().querySelector(`#${elem_id}`);
    if (!container) {
        console.warn(`[ModelManager] Dropdown not found: ${elem_id}`);
        return false;
    }

    // Try input element (common in newer Gradio)
    const input = container.querySelector('input');
    if (input) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`[ModelManager] Set ${elem_id} via input:`, value);
        return true;
    }

    // Try select element
    const select = container.querySelector('select');
    if (select) {
        select.value = value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`[ModelManager] Set ${elem_id} via select:`, value);
        return true;
    }

    console.warn(`[ModelManager] Could not find input/select in ${elem_id}`);
    return false;
}

// Send image generation params to txt2img using paste button
// The last send's work after the paste - scheduler, modules, hires - which
// runs on after mmSendToTxt2img returns. Resolved once all of it is done.
let sendSettled = Promise.resolve();

/** Wait for the last send to finish setting Forge up. */
window.mmSendSettled = () => sendSettled;

window.mmSendToTxt2img = async function(imageIndex) {
    const img = currentImages[imageIndex];
    if (!img || !img.meta) {
        console.error('[ModelManager] No image data at index', imageIndex);
        return;
    }

    // Save current scroll position before navigating away
    const scrollPos = window.scrollY || document.documentElement.scrollTop;
    localStorage.setItem('mm_scroll_position', scrollPos.toString());
    updateScrollRestoreButton();
    console.log('[ModelManager] Saved scroll position:', scrollPos);

    const meta = img.meta;
    const model = currentModels[selectedModelIndex];

    // Debug: log available size-related fields
    console.log('[ModelManager] Image size data:', {
        'meta.Size': meta.Size,
        'img.width': img.width,
        'img.height': img.height,
        'meta.width': meta.width,
        'meta.height': meta.height
    });

    // Ensure Size is set - try multiple sources
    if (!meta.Size) {
        if (img.width && img.height) {
            meta.Size = `${img.width}x${img.height}`;
        } else if (meta.width && meta.height) {
            meta.Size = `${meta.width}x${meta.height}`;
        }
    }

    try {
        // Forge's UI preset first: changing it resets what the image is about
        // to set. Anything failing here leaves the send as it was before.
        const filesAsked = fetchImageFiles(img);
        const plan = await fetchForgePlan(model, img);

        // An image-to-video model starts from an image, which txt2img has
        // no way to give it - it failed in the sampler - so it goes to
        // img2img, with the image. Fetched meanwhile: the preset takes time.
        const isVideo = isVideoUrl({ url: img.url, type: img.type });
        const tab = plan && plan.video === 'i2v' ? 'img2img' : 'txt2img';
        const framing = tab === 'img2img' ? startFrame(img, isVideo) : null;

        if (plan && plan.preset) await switchForgePreset(plan.preset);

        // The gallery's own file is loaded when it is a checkpoint - by what
        // the file is, so a VAE Civitai files as a "Checkpoint" is not.
        let checkpointPath = null;
        const version = model ? shownVersion(model) : null;
        if (version && fileTypeOf(version, model) === 'Checkpoint') {
            checkpointPath = getDropdownPath(version.file_path, 'Checkpoint');
        }

        const vaePath = vaeFromMeta(meta);

        // Set checkpoint if available
        if (checkpointPath && typeof selectCheckpoint === 'function') {
            console.log('[ModelManager] Setting checkpoint:', checkpointPath);
            selectCheckpoint(checkpointPath);
        }

        // Extract scheduler from metadata or sampler string
        let scheduler = meta['Schedule type'];
        if (!scheduler && meta.sampler) {
            const split = splitSamplerScheduler(meta.sampler);
            scheduler = split.scheduler;
        }
        // Default to Automatic if no scheduler found
        scheduler = scheduler || 'Automatic';

        // Check if image has hires fix data (must match what paste button checks)
        // Paste enables hires if: "Denoising strength" AND ("Hires upscale" OR "Hires upscaler" OR "Hires resize-1")
        const hasHiresFix = meta['Denoising strength'] &&
            (meta['Hires upscale'] || meta['Hires upscaler'] || meta['Hires resize-1'] || meta['Hires resize-2']);

        // A video model makes a still unless it is told how many frames:
        // Neo reads Batch size as Frames on the Wan preset.
        let sendMeta = plan && plan.video
            ? await withVideoParams(meta, img, isVideo) : meta;

        // The image's LoRAs and embeddings, for the chips; a LoRA its prompt
        // names under another name than the file here is renamed to it.
        const resources = collectResourceChips(meta, await filesAsked, galleryFile(model));
        if (resources.renames.length) {
            const rename = (text) => resources.renames
                .reduce((out, { from, to }) => renameLoraTags(out, from, to), text);
            sendMeta = { ...sendMeta, prompt: rename(sendMeta.prompt),
                         negativePrompt: rename(sendMeta.negativePrompt) };
        }

        // Build infotext from metadata
        const infotext = buildInfotext(sendMeta,
                                       { denoisingStrength: tab === 'img2img' ? 1 : null });
        if (!infotext) {
            console.error('[ModelManager] No infotext to send');
            return;
        }

        // Find prompt textarea and paste button. Both tabs' paste buttons
        // are id="paste"; each sits in its own tab's tools row.
        const promptTextarea = gradioApp().querySelector(`#${tab}_prompt textarea`);
        let pasteButton = gradioApp().querySelector(`#${tab}_tools #paste`);
        if (!pasteButton && tab === 'txt2img') {
            pasteButton = gradioApp().querySelector('#paste')
                || gradioApp().querySelector('#txt2img_paste');   // SD.Next and others
        }

        if (!promptTextarea) {
            console.error(`[ModelManager] Could not find ${tab} prompt textarea`);
            return;
        }

        if (!pasteButton) {
            console.error('[ModelManager] Could not find paste button');
            return;
        }

        // Set infotext in prompt and trigger paste
        promptTextarea.value = infotext;
        promptTextarea.dispatchEvent(new Event('input', { bubbles: true }));
        pasteButton.click();

        // Paste button doesn't set scheduler in Forge - set it directly after a small delay
        // Also reset hires fix if not present in metadata. Kept as a promise,
        // for anything that has to wait for all of it: see mmSendSettled.
        sendSettled = new Promise((settled) => setTimeout(async () => {
            setGradioDropdown(`${tab}_scheduler`, scheduler);
            updateResourceChipStates(tab);

            // After the paste: it re-renders much of the page, and it never
            // touches the modules itself - Neo reads "Module 1"/"Module 2"
            // from an infotext, not the "VAE:" line we write. A model whose
            // text encoders and VAE are separate gets the ones it needs; an
            // SD or SDXL one, the image's own VAE as before.
            const modules = plan && plan.manage_modules ? applyPlannedModules(plan) : applyVaeSelection(vaePath);

            // Reset hires fix if image doesn't have hires data
            // InputAccordion uses a hidden checkbox - need to set value and dispatch events
            if (!hasHiresFix && tab === 'txt2img') {
                const hiresContainer = gradioApp().querySelector('#txt2img_hr-checkbox');
                const hiresCheckbox = hiresContainer?.querySelector('input[type="checkbox"]');
                console.log('[ModelManager] Hires fix reset:', {
                    containerFound: !!hiresContainer,
                    checkboxFound: !!hiresCheckbox,
                    isChecked: hiresCheckbox?.checked
                });
                if (hiresCheckbox && hiresCheckbox.checked) {
                    // Set value and dispatch proper events for Gradio
                    hiresCheckbox.checked = false;
                    hiresCheckbox.dispatchEvent(new Event('input', { bubbles: true }));
                    hiresCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
                    // Also call the InputAccordion JS function if available
                    if (typeof inputAccordionChecked === 'function') {
                        inputAccordionChecked('txt2img_hr', false);
                    }
                    console.log('[ModelManager] Disabled hires fix (not in metadata)');
                }
            }
            await modules.catch(() => {});
            settled();
        }, 100));

        showGenerationTab(tab);
        resourceChipSources[tab] = { img, gallery: galleryFile(model) };
        showResourceChips(tab, resources.chips);
        checkMissingChips(tab);

        // The start frame goes in once img2img is showing: its canvas sizes
        // the image to itself, and a hidden one has no size.
        if (framing) {
            const frame = await framing;
            if (!frame || !giveImg2imgImage(frame.file)) {
                showNotice('This image-to-video model needs a start image, and this one\'s could '
                           + 'not be loaded: drop an image into img2img before generating.');
            } else if (frame.small) {
                showNotice('The video could not be decoded at full size, so its start frame comes '
                           + 'from Civitai\'s small preview copy: consider a larger image.');
            }
        }

        console.log(`[ModelManager] Sent to ${tab} via paste:`, {
            infotextLength: infotext.length,
            prompt: meta.prompt?.substring(0, 50) + '...',
            checkpoint: checkpointPath,
            vae: vaePath,
            scheduler: scheduler,
            hasHiresFix: !!hasHiresFix,
            fullInfotext: infotext
        });

    } catch (error) {
        console.error('[ModelManager] Error sending to txt2img:', error);
    }
};

// Close details panel
// Jump straight to one model, e.g. from the Civitai Browser.
// Every filter is relaxed first - an active NSFW or type filter would
// otherwise hide the very model the caller asked to show.
window.mmShowModel = async function(query) {
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

    setChecked('#mm_nsfw_panel input[type="checkbox"][value]', true);
    const useMax = document.getElementById('mm_nsfw_use_max');
    if (useMax) useMax.checked = true;
    updateNsfwDisplay();

    setChecked('#mm_commercial_panel input[type="checkbox"][value]', true);
    updateCommercialDisplay();

    setValue('mm_checkpoint_type', '');
    setValue('mm_allow_derivatives', '');
    setValue('mm_allow_different_license', '');

    setValue('mm_search', query);

    await loadModels(1);

    // A targeted lookup normally returns exactly one model - open it
    if (currentModels.length === 1) {
        await window.mmSelectModel(0);
    } else if (currentModels.length === 0) {
        setStatus(`Nothing found for "${query}". It may not be downloaded, or the database needs a refresh.`, true);
    }
};

// Open this model over in the Civitai Browser tab. The mirror of
// cbShowInModelManager() there, down to the tab lookup.
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
    const query = civitaiBrowserQuery();
    if (!query) return;
    if (typeof window.cbShowModel !== 'function') {
        setStatus('Civitai Browser tab has not initialised yet - open it once and try again.', true);
        return;
    }

    const root = (typeof gradioApp === 'function') ? gradioApp() : document;
    const tabs = root.querySelector('#tabs');
    const tabButton = tabs && Array.from(tabs.querySelectorAll('button'))
        .find(b => b.textContent.trim() === 'Civitai Browser');

    if (tabButton) {
        tabButton.click();
    } else {
        console.warn('[ModelManager] Could not find the Civitai Browser tab button');
    }

    // The grid sizes itself from the viewport, so let the tab become visible
    // before searching - measuring a hidden tab gives nonsense.
    setTimeout(() => window.cbShowModel(query), 100);
};

// Reveal more of what is already downloaded. No request, and deliberately no
// scroll: the point of the continuous list is that the images you were
// reading stay where they were.
window.mmShowMoreImages = async function() {
    downloadNote = '';
    await loadImagesPage(currentImages.length, { append: true });
};

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
    dialog.style.display = 'flex';
}

function closeScanDialog() {
    const dialog = document.getElementById('mm_scan_dialog');
    if (dialog) dialog.style.display = 'none';
}

async function startScan() {
    if (isScanning || isSyncing) return;

    isScanning = true;
    updateScanUI(true);
    setStatus('Starting database refresh...');

    try {
        const response = await fetch('/model-manager/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
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
                setStatus(`Scan complete: ${p.processed} models indexed${errorInfo}`);
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


// Scroll position restore functionality
function updateScrollRestoreButton() {
    const savedPos = localStorage.getItem('mm_scroll_position');
    let btn = document.getElementById('mm_scroll_restore_btn');

    if (savedPos && parseInt(savedPos) > 0) {
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
    const savedPos = localStorage.getItem('mm_scroll_position');
    if (savedPos) {
        const pos = parseInt(savedPos);
        window.scrollTo({ top: pos, behavior: 'smooth' });
        console.log('[ModelManager] Restored scroll position:', pos);
    }
};

// Save/Load search filters functionality
function saveSearchFilters() {
    const filters = {
        search: document.getElementById('mm_search')?.value || '',
        type: document.getElementById('mm_type')?.value || '',
        base_model: document.getElementById('mm_base_model')?.value || '',
        civitai: document.getElementById('mm_civitai')?.value || '',
        is_bookmarked: document.getElementById('mm_is_bookmarked')?.value || '',
        min_versions: document.getElementById('mm_min_versions')?.value || '',
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

    localStorage.setItem('mm_saved_filters', JSON.stringify(filters));
    console.log('[ModelManager] Saved search filters:', filters);

    // Update button to show saved state
    const btn = document.getElementById('mm_save_search_btn');
    if (btn) {
        btn.textContent = '✓ Saved';
        setTimeout(() => { btn.textContent = 'Save Search'; }, 1500);
    }
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
function syncSfwOnlyBanner() {
    const banner = document.getElementById('mm_sfw_only_banner');
    const note = document.getElementById('mm_sfw_only_banner_model');
    if (!banner || !note) return;
    const text = nsfwModelNote();
    note.textContent = text;
    banner.style.display = text && document.getElementById('mm_sfw_only')?.checked ? 'flex' : 'none';
}

function loadSearchFilters() {
    const saved = localStorage.getItem('mm_saved_filters');
    if (!saved) return false;

    try {
        const filters = JSON.parse(saved);

        if (Object.prototype.hasOwnProperty.call(filters, 'search')) document.getElementById('mm_search').value = filters.search;
        if (Object.prototype.hasOwnProperty.call(filters, 'type')) document.getElementById('mm_type').value = filters.type;
        if (Object.prototype.hasOwnProperty.call(filters, 'base_model')) selectBaseModel(filters.base_model);
        if (Object.prototype.hasOwnProperty.call(filters, 'civitai')) document.getElementById('mm_civitai').value = filters.civitai;
        if (Object.prototype.hasOwnProperty.call(filters, 'is_bookmarked')) document.getElementById('mm_is_bookmarked').value = filters.is_bookmarked;
        if (Object.prototype.hasOwnProperty.call(filters, 'min_versions')) document.getElementById('mm_min_versions').value = filters.min_versions;
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

function clearSearchFilters() {
    localStorage.removeItem('mm_saved_filters');
    console.log('[ModelManager] Cleared saved filters');

    const btn = document.getElementById('mm_save_search_btn');
    if (btn) {
        btn.textContent = '✗ Cleared';
        setTimeout(() => { btn.textContent = 'Save Search'; }, 1500);
    }
}

// Initialize with retry logic for Gradio-rendered content
function init() {
    console.log('[ModelManager] Initializing...');
    bindElements();
    document.getElementById('mm_sfw_only')?.addEventListener('change', syncSfwOnlyBanner);
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
                closeScanDialog();
                startScan();
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

    // Load saved filters if available
    loadSearchFilters();
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
