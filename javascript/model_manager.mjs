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
    getImagePageCount,
    setupLazyMedia,
    renderResource,
    renderFilterBanner,
    balanceGridRows,
    IMAGE_PAGE_SIZE,
    applyCardSize: sharedApplyCardSize,
    renderImagePagination: sharedImagePagination,
} = await import(sharedModule.href);

// State
let currentModels = [];
let selectedModelIndex = null;
let isLoading = false;

// Version grouping state
let currentVersions = [];  // All versions for currently selected model
let selectedVersionIndex = 0;  // Currently selected version within the group

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
            cssPrefix: 'mm',
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
// How many of the loaded images the continuous list is showing. Paging mode
// ignores it, so the two modes cannot disagree about where you are.
let visibleImageCount = IMAGE_PAGE_SIZE;
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

// Render model card
function renderModelCard(model, index) {
    const previewSrc = cardMediaUrl(model.preview_url);

    const hasPreview = previewSrc !== '';
    const placeholderSvg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect fill='%23333' width='100' height='100'/%3E%3Ctext x='50' y='50' text-anchor='middle' dy='.3em' fill='%23666' font-size='10'%3ENo Image%3C/text%3E%3C/svg%3E";

    const name = escapeHtml(model.display_name || 'Unknown');
    const nameShort = name.length > 30 ? name.substring(0, 30) + '...' : name;

    // NSFW class based on integer bitmask (1=PG, 2=PG-13, 4=R, 8=X, 16=XXX)
    let nsfwClass = '';
    const nsfwLevel = model.nsfw_level || 1;
    if (nsfwLevel >= 16) {
        nsfwClass = 'nsfw-xxx';
    } else if (nsfwLevel >= 8) {
        nsfwClass = 'nsfw-x';
    } else if (nsfwLevel >= 4) {
        nsfwClass = 'nsfw-r';
    } else if (nsfwLevel >= 2) {
        nsfwClass = 'nsfw-pg13';
    }

    const civitaiClass = model.has_civitai_data ? 'has-civitai' : 'no-civitai';

    const baseModelBadge = model.base_model
        ? `<span class="badge base-model">${escapeHtml(model.base_model)}</span>`
        : '';

    // Civitai retired star ratings; thumbs are what it reports now, and
    // our stats_rating is only those two numbers folded into one. Show the
    // pair rather than the derivation.
    const thumbsHtml = renderThumbs(model.thumbs_up, model.thumbs_down);

    const downloadsHtml = model.download_count > 0
        ? `<span title="Downloads">↓ ${formatNumber(model.download_count)}</span>`
        : '';

    // Version count badge (only show if multiple local versions)
    const versionCount = model.local_version_count || 1;
    const versionsBadge = versionCount > 1
        ? `<span class="badge versions-badge" title="${versionCount} local versions">v${versionCount}</span>`
        : '';

    // Bookmark indicator
    const bookmarkIndicator = model.is_bookmarked
        ? '<div class="mm-bookmark-indicator" title="Bookmarked">★</div>'
        : '';

    // Check if preview is a video
    const isVideo = isVideoUrl({ url: previewSrc });
    const previewHtml = hasPreview
        ? (isVideo
            ? `<video src="${escapeHtml(previewSrc)}" loop muted autoplay playsinline></video>`
            : `<img src="${escapeHtml(previewSrc)}" alt="${name}" loading="lazy" onerror="this.src='${placeholderSvg}'">`)
        : `<img src="${placeholderSvg}" alt="${name}">`;

    return `
        <div class="model-card ${civitaiClass} ${nsfwClass}" data-index="${index}" data-model-id="${model.civitai_model_id || ''}" onclick="window.mmSelectModel(${index})">
            <div class="model-card-image">
                ${previewHtml}
                ${!model.has_civitai_data ? '<div class="no-data-overlay">No Civitai Data</div>' : ''}
                ${bookmarkIndicator}
            </div>
            <div class="model-card-info">
                <div class="model-card-name" title="${name}">${nameShort}</div>
                <div class="model-card-meta">
                    <span class="badge type-badge">${model.model_type || 'Unknown'}</span>
                    ${baseModelBadge}
                    ${versionsBadge}
                </div>
                <div class="model-card-stats">
                    <span>${formatFileSize(model.file_size)}</span>
                    ${thumbsHtml}
                    ${downloadsHtml}
                </div>
            </div>
        </div>
    `;
}

// Render model grid
function renderModelGrid(models) {
    const container = document.getElementById('mm_grid');
    if (!container) return;

    if (!models || models.length === 0) {
        container.innerHTML = '<div class="model-grid-empty">No models found matching your filters.</div>';
        return;
    }

    const cards = models.map((model, index) => renderModelCard(model, index)).join('');

    // Build pagination controls
    const paginationHtml = totalPages > 1 ? renderPaginationControls() : '';

    container.innerHTML = `<div class="model-grid-inner">${cards}</div>${paginationHtml}`;
    balanceGridRows('mm_grid');
}

// Render pagination controls
function renderPaginationControls() {
    const prevDisabled = currentPage <= 1 ? 'disabled' : '';
    const nextDisabled = currentPage >= totalPages ? 'disabled' : '';

    // Generate page numbers to show
    let pageNumbers = [];
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    // Adjust start if we're near the end
    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    // Add first page and ellipsis if needed
    if (startPage > 1) {
        pageNumbers.push({ page: 1, label: '1' });
        if (startPage > 2) {
            pageNumbers.push({ page: null, label: '...' });
        }
    }

    // Add visible page range
    for (let i = startPage; i <= endPage; i++) {
        pageNumbers.push({ page: i, label: String(i) });
    }

    // Add ellipsis and last page if needed
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            pageNumbers.push({ page: null, label: '...' });
        }
        pageNumbers.push({ page: totalPages, label: String(totalPages) });
    }

    const pageNumbersHtml = pageNumbers.map(({ page, label }) => {
        if (page === null) {
            return `<span class="mm-page-ellipsis">${label}</span>`;
        }
        const activeClass = page === currentPage ? 'active' : '';
        return `<button class="mm-page-num ${activeClass}" onclick="window.mmGoToPage(${page})">${label}</button>`;
    }).join('');

    return `
        <div class="mm-pagination">
            <button class="mm-btn mm-page-btn" onclick="window.mmPrevPage()" ${prevDisabled}>
                ← Prev
            </button>
            <div class="mm-page-numbers">
                ${pageNumbersHtml}
            </div>
            <button class="mm-btn mm-page-btn" onclick="window.mmNextPage()" ${nextDisabled}>
                Next →
            </button>
        </div>
    `;
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
    visibleImageCount = IMAGE_PAGE_SIZE;
    nextImagesCursor = null;
    imagesSyncDate = null;

    // Reset version state
    currentVersions = [];
    selectedVersionIndex = 0;

    // Highlight selected card
    document.querySelectorAll('.model-card').forEach(card => card.classList.remove('selected'));
    const selectedCard = document.querySelector(`.model-card[data-index="${index}"]`);
    if (selectedCard) selectedCard.classList.add('selected');

    // If model has multiple versions, fetch them
    const hasMultipleVersions = model.model_id && (model.local_version_count || 1) > 1;
    if (hasMultipleVersions) {
        try {
            const versionsData = await apiCall({ endpoint: '/model-manager/models/versions', params: { model_id: model.model_id } });
            if (versionsData.success && versionsData.versions) {
                currentVersions = versionsData.versions;
                // Find current version in list (it should be there since it's the latest)
                selectedVersionIndex = currentVersions.findIndex(v => v.file_path === model.file_path);
                if (selectedVersionIndex < 0) selectedVersionIndex = 0;
                console.log(`[ModelManager] Loaded ${currentVersions.length} versions for model ${model.model_id}`);
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
        const params = {
            path: filePath,
            hide_nsfw_images: hideNsfwImages,
            hide_promptless_images: hidePromptlessImages,
        };
        const data = await apiCall({ endpoint: '/model-manager/models/details', params });
        if (data.success && data.model) {
            // Store version ID for load-more
            if (data.model.civitai_version) {
                currentVersionId = data.model.civitai_version.id;
            }

            // Update description if available
            if (data.model.civitai_model?.description) {
                updateDescription(data.model.civitai_model.description);
            }

            // Store images
            const images = data.model.images || [];
            currentImages = images;

            // Get cursor state from images_state
            const imagesState = data.model.images_state || {};
            currentVersionId = imagesState.version_id || null;
            nextImagesCursor = imagesState.next_cursor || null;
            imagesSyncDate = imagesState.sync_date || null;
            totalImageCount = imagesState.total_count || 0;
            hiddenImageCount = imagesState.hidden_nsfw ?? imagesState.hidden_count ?? 0;
            hiddenPromptlessCount = imagesState.hidden_promptless || 0;
            nsfwImageCount = imagesState.nsfw_count || 0;
            promptlessImageCount = imagesState.promptless_count || 0;

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

            console.log(`[ModelManager] Loaded ${images.length} images (total: ${totalImageCount}, hidden: ${hiddenImageCount}, cursor: ${nextImagesCursor ? 'yes' : 'no'}, synced: ${imagesSyncDate ? 'yes' : 'no'})`);

            renderModelImages(images);
            updateImagesCountCell();
        }
    } catch (error) {
        console.error('[ModelManager] Failed to load model details:', error);
        updateImagesCountCell();  // Update even on error to show "None"
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
    currentImagePage = 1;
    visibleImageCount = IMAGE_PAGE_SIZE;
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
    currentImagePage = 1;
    visibleImageCount = IMAGE_PAGE_SIZE;
    if (currentModelPath) {
        await loadVersionDetails(currentModelPath);
    }
};

// Update the images count cell in the Information table
function updateImagesCountCell() {
    const cell = document.getElementById('mm_images_count_cell');
    if (!cell) return;

    const downloaded = currentImages.length;
    cell.textContent = downloaded > 0 ? `${downloaded}` : 'None';
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
    visibleImageCount = IMAGE_PAGE_SIZE;
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
    document.querySelectorAll('.mm-version-pill').forEach((pill, idx) => {
        if (idx === selectedVersionIndex) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });
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

// Render version selector pills
function renderVersionSelector() {
    if (currentVersions.length <= 1) return '';

    const pills = currentVersions.map((version, index) => {
        const activeClass = index === selectedVersionIndex ? 'active' : '';
        const versionName = version.version_name || `v${index + 1}`;
        const fileName = version.file_name ? version.file_name.replace(/\.(safetensors|ckpt|pt|pth|bin)$/i, '') : '';
        const displayName = version.version_name ? versionName : fileName;
        const tooltip = `${versionName}\n${version.file_name}\n${formatFileSize(version.file_size)}`;

        return `<button class="mm-version-pill ${activeClass}"
                       onclick="window.mmSelectVersion(${index})"
                       title="${escapeHtml(tooltip)}">${escapeHtml(displayName)}</button>`;
    }).join('');

    return `
        <div class="detail-section mm-version-selector">
            <h4>Local Versions (${currentVersions.length})</h4>
            <div class="mm-version-pills">
                ${pills}
            </div>
        </div>
    `;
}

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

    // Bookmark button (only for models with Civitai data)
    const isBookmarked = model.is_bookmarked || false;
    const bookmarkBtn = modelId
        ? `<button class="mm-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" onclick="window.mmToggleBookmark(${safeId(modelId)})" title="${isBookmarked ? 'Remove bookmark' : 'Bookmark this model'}">${isBookmarked ? '★' : '☆'}</button>`
        : '';

    container.innerHTML = `
        <div class="model-details-content">
            <div class="detail-header">
                <h3>${escapeHtml(model.display_name)}</h3>
                ${bookmarkBtn}
                ${modelId ? `<button class="mm-btn primary mm-btn-small header-action" onclick="window.mmForceSyncModel()" title="Force sync this model">Sync</button>` : ''}
                ${modelId ? `<button class="mm-btn secondary mm-btn-small header-action" onclick="window.mmShowInCivitaiBrowser(${safeId(modelId)})" title="Open this model in the Civitai Browser tab">Show in Civitai Browser</button>` : ''}
                <button class="close-details" onclick="window.mmCloseDetails()">×</button>
            </div>

            ${versionSelectorHtml}

            <div class="detail-section">
                <h4>Information</h4>
                <table class="detail-table">
                    ${modelId ? `<tr><td>Model ID</td><td>${modelId}</td></tr>` : ''}
                    ${model.id ? `<tr><td>Version ID</td><td>${model.id}</td></tr>` : ''}
                    <tr><td>Type</td><td>${model.model_type || 'Unknown'}</td></tr>
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
                <button class="action-btn danger" onclick="window.mmDeleteModel()">Delete Model</button>
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
            // Update images display and cursor state
            currentImages = data.images || [];
            nextImagesCursor = data.next_cursor || null;
            imagesSyncDate = new Date().toISOString();
            renderModelImages(currentImages);
            updateImagesCountCell();
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

// Delete model and all related files
window.mmDeleteModel = async function() {
    const model = currentModels[selectedModelIndex];
    if (!model) return;

    const confirmed = confirm(
        `Are you sure you want to delete "${model.display_name}"?\n\n` +
        `This will delete:\n` +
        `• The model file\n` +
        `• All metadata files (.civitai.info, .preview.png, etc.)\n` +
        `• The containing folder if it's named after the model and becomes empty\n\n` +
        `This action cannot be undone.`
    );

    if (!confirmed) return;

    try {
        setStatus('Deleting model...');

        const response = await fetch('/model-manager/models/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `path=${encodeURIComponent(model.file_path)}`
        });

        const data = await response.json();

        if (data.success) {
            setStatus(`Deleted: ${model.display_name}`);
            // Close details panel
            window.mmCloseDetails();
            // Reload current page
            loadModels(currentPage);
        } else {
            setStatus('Delete failed: ' + (data.error || 'Unknown error'), true);
        }
    } catch (error) {
        console.error('[ModelManager] Delete error:', error);
        setStatus('Delete error: ' + error.message, true);
    }
};

// Render model images - new list layout
function renderModelImages(images) {
    const container = document.getElementById('mm_images');
    if (!container) return;

    const totalPages = getImagePageCount(images.length);
    currentImagePage = Math.min(Math.max(1, currentImagePage), totalPages);

    // One banner for both filters: what they are holding back, which adds up
    // with what is shown to the total, and a switch for each on the right. The
    // server splits the hidden images between the filters so that none is
    // counted twice - NSFW first, as it filters - and reports what each switch
    // would show once ticked. Built in shared/common.mjs, as the Civitai
    // Browser's is.
    const filterBannerHtml = renderFilterBanner({
        shown: images.length,
        total: totalImageCount,
        bannerClass: 'mm-nsfw-warning',
        labelClass: 'mm-show-all-label',
        switches: [
            { id: 'mm_show_nsfw_images', label: 'Show NSFW', reason: 'NSFW filter',
              showing: !hideNsfwImages, hidden: hiddenImageCount, count: nsfwImageCount,
              onchange: 'window.mmToggleShowNsfwImages(this.checked)' },
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
    // reader has got to; paging shows one page. Only the slice differs - the
    // cards, the counts and the download button are the same either way.
    const paging = imageBrowsing === 'pages';
    const pageStart = paging ? (currentImagePage - 1) * IMAGE_PAGE_SIZE : 0;
    const pageEnd = paging
        ? Math.min(pageStart + IMAGE_PAGE_SIZE, images.length)
        : Math.min(visibleImageCount, images.length);
    const pageImages = images.slice(pageStart, pageEnd);
    const imageCards = pageImages.map((img, index) => renderImageCard(img, pageStart + index)).filter(Boolean).join('');
    const moreToShow = !paging && pageEnd < images.length;

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
    const infoText = neverSynced ? 'Images not yet downloaded' : `${totalImageCount} images downloaded`;

    // One button at the foot of the list. While there are images already
    // downloaded but not yet on screen it shows those - no request, no wait.
    // Once they are all up, it offers to fetch more from Civitai.
    const atEnd = paging ? currentImagePage === totalPages : !moreToShow;
    const downloadMoreHtml = moreToShow
        ? `<div class="mm-load-more">
             <button class="mm-btn secondary" id="mm_show_more_btn" onclick="window.mmShowMoreImages()">
               Show More Images
             </button>
             <span class="mm-load-more-info">${pageEnd} of ${images.length} shown</span>
           </div>`
        : (showDownloadBtn && atEnd
            ? `<div class="mm-load-more">
                 <button class="mm-btn secondary" id="mm_load_more_btn" onclick="window.mmLoadMoreImages()">
                   ${buttonText}
                 </button>
                 <span class="mm-load-more-info">${infoText}</span>
               </div>`
            : '');

    const countText = paging
        ? `${pageStart + 1}-${pageEnd} of ${images.length} images (Page ${currentImagePage}/${totalPages})`
        : `${pageEnd} of ${images.length} images`;

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
    const nsfwLevel = img.nsfw || 'Unknown';
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
                ${nsfwClass ? `<span class="mm-nsfw-badge">${nsfwLevel}</span>` : ''}
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
    renderResourcesModal(mergeImageResources(img, knownHashes, !hashes.length), hashes.length);
    if (!hashes.length) return;

    const resolved = await resolveResourceHashes(hashes, (partial, remaining) => {
        Object.assign(knownHashes, partial);
        updateResourceButtons();
        if (stillWanted()) renderResourcesModal(mergeImageResources(img, partial, false), remaining);
    });
    Object.assign(knownHashes, resolved);
    updateResourceButtons();

    if (stillWanted()) renderResourcesModal(mergeImageResources(img, resolved, true), 0);
};

function renderResourcesModal(resources, pending = 0) {
    const rows = resources.known.map(resource => `
            <tr>
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name">${escapeHtml(resource.name)}${resource.versionName
                    ? ` <span class="mm-res-version">${escapeHtml(resource.versionName)}</span>` : ''}</td>
                <td class="mm-res-actions">
                    <a class="mm-btn secondary mm-btn-small" href="https://civitai.com/model-versions/${safeId(resource.versionId)}" target="_blank">View</a>
                    <a class="mm-btn primary mm-btn-small" href="https://civitai.com/api/download/models/${safeId(resource.versionId)}" target="_blank">Download</a>
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

        if (data.success && data.images && data.images.length > 0) {
            // Deduplicate: filter out images that already exist in currentImages
            const existingIds = new Set(currentImages.map(img => img.id));
            const newImages = data.images.filter(img => !existingIds.has(img.id));

            if (newImages.length > 0) {
                const oldCount = currentImages.length;
                currentImages = currentImages.concat(newImages);

                // Update cursor state from response
                nextImagesCursor = data.next_cursor || null;
                imagesSyncDate = new Date().toISOString();  // Mark as synced

                if (imageBrowsing === 'pages') {
                    const oldPages = getImagePageCount(oldCount);
                    const newPages = getImagePageCount(currentImages.length);
                    if (newPages > oldPages) {
                        await scrollToModelImagesTop();
                        currentImagePage = newPages;
                    }
                } else {
                    // Show what just arrived, and stay where the reader is.
                    visibleImageCount = Math.max(visibleImageCount,
                                                 oldCount + newImages.length);
                }

                renderModelImages(currentImages);

                // Update all count displays
                updateAllImageCounts();

                console.log(`[ModelManager] Downloaded ${newImages.length} new images (${data.images.length - newImages.length} duplicates filtered, ${currentImages.length} total, has_more: ${nextImagesCursor !== null})`);
            } else {
                // All returned images were duplicates
                console.log(`[ModelManager] All ${data.images.length} returned images were duplicates, skipped`);
                nextImagesCursor = data.next_cursor || null;
            }

            // Update or hide button based on cursor
            if (nextImagesCursor && loadMoreBtn) {
                loadMoreBtn.textContent = 'Download More Images';
                loadMoreBtn.disabled = false;
            }
        } else {
            // No more images
            nextImagesCursor = null;
            renderModelImages(currentImages);

            if (data.message) {
                console.log('[ModelManager]', data.message);
            }
        }
    } catch (error) {
        console.error('[ModelManager] Download more error:', error);
        if (loadMoreBtn) {
            loadMoreBtn.textContent = 'Download More Images';
            loadMoreBtn.disabled = false;
        }
    } finally {
        isLoadingMore = false;
    }
};

// Update all image count displays
function updateAllImageCounts() {
    // Header count
    const headerCount = document.querySelector('.mm-images-count');
    if (headerCount && currentImages.length === 0) {
        headerCount.textContent = '0 images';
    } else if (headerCount && imageBrowsing === 'pages') {
        const totalPages = getImagePageCount(currentImages.length);
        const pageStart = ((currentImagePage - 1) * IMAGE_PAGE_SIZE) + 1;
        const pageEnd = Math.min(currentImagePage * IMAGE_PAGE_SIZE, currentImages.length);
        headerCount.textContent =
            `${pageStart}-${pageEnd} of ${currentImages.length} images (Page ${currentImagePage}/${totalPages})`;
    } else if (headerCount) {
        headerCount.textContent =
            `${Math.min(visibleImageCount, currentImages.length)} of ${currentImages.length} images`;
    }

    // Load more info. Left alone while the button is offering images that are
    // already here - "downloaded" would be answering a different question.
    const loadMoreInfo = document.querySelector('.mm-load-more-info');
    if (loadMoreInfo && !document.getElementById('mm_show_more_btn')) {
        loadMoreInfo.textContent = `${currentImages.length} images downloaded`;
    }

    // Info table cell
    updateImagesCountCell();
}

window.mmFirstImagePage = function() {
    if (currentImagePage === 1) return;
    currentImagePage = 1;
    renderModelImages(currentImages);
};

window.mmLastImagePage = function() {
    const totalPages = getImagePageCount(currentImages.length);
    if (currentImagePage === totalPages) return;
    currentImagePage = totalPages;
    renderModelImages(currentImages);
};

window.mmPrevImagePage = function() {
    if (currentImagePage <= 1) return;
    currentImagePage -= 1;
    renderModelImages(currentImages);
};

window.mmNextImagePage = function() {
    const totalPages = getImagePageCount(currentImages.length);
    if (currentImagePage >= totalPages) return;
    currentImagePage += 1;
    renderModelImages(currentImages);
};

window.mmGoToImagePage = async function(page) {
    const totalPages = getImagePageCount(currentImages.length);
    if (page < 1 || page > totalPages || page === currentImagePage) return;

    await scrollToModelImagesTop();
    currentImagePage = page;
    renderModelImages(currentImages);
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
            lower.replace(/\.(safetensors|pt|ckpt|bin)$/i, '') === wanted) {
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
 * What to set up in Forge for the model an image is sent with: its UI
 * preset, and the modules to select. A checkpoint's gallery is judged by its
 * file; any other by Civitai's baseModel. null if the server cannot say.
 */
async function fetchForgePlan(model) {
    if (!model) return null;
    const params = new URLSearchParams();
    if (model.model_type === 'Checkpoint' && model.file_path) params.set('file_path', model.file_path);
    if (model.base_model) params.set('base_model', model.base_model);
    try {
        const response = await fetch('/model-manager/forge-modules?' + params.toString());
        const plan = await response.json();
        return plan && plan.success ? plan : null;
    } catch (e) {
        console.warn('[ModelManager] Could not work out the model\'s architecture:', e);
        return null;
    }
}

/** Forge Neo's UI preset as it stands, or null where there is none. */
function currentForgePreset() {
    return gradioApp().querySelector('#forge_ui_preset input')?.value || null;
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
    if (input.value === preset) return true;

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

    for (let i = 0; i < 30 && currentForgePreset() !== preset; i++) await nextFrame(100);
    await nextFrame(FORGE_PRESET_SETTLE_MS);
    console.log('[ModelManager] Forge UI preset now:', currentForgePreset());
    return currentForgePreset() === preset;
}

// How long a preset change is given, after its value shows, to reset the
// sampler, steps and modules before the image's own are applied.
let FORGE_PRESET_SETTLE_MS = 600;

/**
 * Select the modules the plan picked, and say what it could not find.
 * Called after the paste, as applyVaeSelection() is: the paste re-renders
 * much of the page but never touches the modules.
 */
async function applyPlannedModules(plan) {
    await applyForgeModules(plan.select || []);
    if (plan.missing && plan.missing.length) {
        const names = plan.missing.map((kind) => MODULE_KIND_NAMES[kind] || kind).join(', ');
        showNotice(`This ${plan.preset} model also needs ${names}, which is not installed. `
                   + 'Add it to Forge\'s VAE or text_encoder folder, or select it in "VAE / Text Encoder".');
    }
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
function buildInfotext(meta) {
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

    // Only include hires-related fields if there's a complete hires fix setup
    // This prevents paste from enabling hires when image doesn't have hires data
    if (hasHiresFix) {
        if (meta['Denoising strength']) params.push(`Denoising strength: ${meta['Denoising strength']}`);
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
        const plan = await fetchForgePlan(model);
        if (plan && plan.preset) await switchForgePreset(plan.preset);

        // If current model is a Checkpoint, get its path
        let checkpointPath = null;
        if (model && model.model_type === 'Checkpoint') {
            checkpointPath = getDropdownPath(model.file_path, 'Checkpoint');
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

        // Build infotext from metadata
        const infotext = buildInfotext(meta);
        if (!infotext) {
            console.error('[ModelManager] No infotext to send');
            return;
        }

        // Find prompt textarea and paste button
        const promptTextarea = gradioApp().querySelector('#txt2img_prompt textarea');
        let pasteButton = gradioApp().querySelector('#paste');
        if (!pasteButton) {
            // Fallback for SD.Next or other variants
            pasteButton = gradioApp().querySelector('#txt2img_paste');
        }

        if (!promptTextarea) {
            console.error('[ModelManager] Could not find txt2img prompt textarea');
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
        // Also reset hires fix if not present in metadata
        setTimeout(() => {
            setGradioDropdown('txt2img_scheduler', scheduler);

            // After the paste: it re-renders much of the page, and it never
            // touches the modules itself - Neo reads "Module 1"/"Module 2"
            // from an infotext, not the "VAE:" line we write. A model whose
            // text encoders and VAE are separate gets the ones it needs; an
            // SD or SDXL one, the image's own VAE as before.
            if (plan && plan.manage_modules) applyPlannedModules(plan);
            else applyVaeSelection(vaePath);

            // Reset hires fix if image doesn't have hires data
            // InputAccordion uses a hidden checkbox - need to set value and dispatch events
            if (!hasHiresFix) {
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
        }, 100);

        // Switch to txt2img tab
        const txt2imgTab = document.querySelector('#tabs button:first-child');
        if (txt2imgTab) {
            txt2imgTab.click();
        }

        console.log('[ModelManager] Sent to txt2img via paste:', {
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
window.mmShowInCivitaiBrowser = function(modelId) {
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
    setTimeout(() => window.cbShowModel('model:' + modelId), 100);
};

// Reveal more of what is already downloaded. No request, and deliberately no
// scroll: the point of the continuous list is that the images you were
// reading stay where they were.
window.mmShowMoreImages = function() {
    visibleImageCount += IMAGE_PAGE_SIZE;
    renderModelImages(currentImages);
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
            syncPollInterval = setInterval(pollSyncProgress, 1000);
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
    }, 120);
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
            syncPollInterval = setInterval(pollSyncProgress, 1000);
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
            scanPollInterval = setInterval(pollScanProgress, 500);
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

function loadSearchFilters() {
    const saved = localStorage.getItem('mm_saved_filters');
    if (!saved) return false;

    try {
        const filters = JSON.parse(saved);

        if (Object.prototype.hasOwnProperty.call(filters, 'search')) document.getElementById('mm_search').value = filters.search;
        if (Object.prototype.hasOwnProperty.call(filters, 'type')) document.getElementById('mm_type').value = filters.type;
        if (Object.prototype.hasOwnProperty.call(filters, 'base_model')) document.getElementById('mm_base_model').value = filters.base_model;
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
                scanPollInterval = setInterval(pollScanProgress, 500);
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
                syncPollInterval = setInterval(pollSyncProgress, 1000);
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
