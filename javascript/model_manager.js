/**
 * Model Manager JavaScript
 * Handles API calls, grid rendering, and UI interactions.
 */

(function() {
    'use strict';

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
    let pageSize = 0;
    let firstVisibleItemIndex = 0;  // Absolute index of first item on current page

    // Card sizing constants (should match CSS)
    const CARD_MIN_WIDTH = 180;  // minmax(180px, 1fr) in CSS
    const CARD_GAP = 15;         // gap: 15px in CSS
    const ROWS_TO_SHOW = 2;      // Show 2 rows of cards

    // Calculate page size based on grid width
    function calculatePageSize() {
        const grid = document.getElementById('mm_grid');
        if (!grid) return 10;  // Default fallback

        const gridWidth = grid.clientWidth;
        if (gridWidth <= 0) return 10;

        // Calculate how many cards fit per row
        // Formula: (gridWidth + gap) / (cardWidth + gap)
        const cardsPerRow = Math.floor((gridWidth + CARD_GAP) / (CARD_MIN_WIDTH + CARD_GAP));
        const calculatedSize = Math.max(1, cardsPerRow) * ROWS_TO_SHOW;

        // Minimum 4, maximum 50
        const finalSize = Math.max(4, Math.min(50, calculatedSize));
        console.log(`[ModelManager] Calculated page size: ${finalSize} (${cardsPerRow} cards/row × ${ROWS_TO_SHOW} rows, grid width: ${gridWidth}px)`);
        return finalSize;
    }

    // Recalculate pagination after page size change (without reloading data)
    function recalculatePagination(newPageSize) {
        if (newPageSize === pageSize || totalModels === 0) return false;

        const oldPageSize = pageSize;
        pageSize = newPageSize;

        // Calculate new page based on first visible item
        const newPage = Math.floor(firstVisibleItemIndex / pageSize) + 1;
        const newTotalPages = Math.ceil(totalModels / pageSize);

        console.log(`[ModelManager] Pagination recalc: page ${currentPage} (size ${oldPageSize}) -> page ${newPage} (size ${pageSize})`);

        currentPage = Math.max(1, Math.min(newPage, newTotalPages));
        totalPages = newTotalPages;

        return true;  // Pagination changed
    }

    // Update pagination controls without reloading data
    function updatePaginationControls() {
        const container = document.getElementById('mm_grid');
        if (!container) return;

        // Find existing pagination and replace it
        const existingPagination = container.querySelector('.mm-pagination');
        if (existingPagination && totalPages > 1) {
            existingPagination.outerHTML = renderPaginationControls();
        }

        // Update status
        updatePaginationStatus();
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
    let nextImagesCursor = null;  // Cursor for loading more images
    let imagesSyncDate = null;    // Last sync date (null = never synced)
    let isLoadingMore = false;

    // Wait for DOM
    function onReady(callback) {
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            setTimeout(callback, 100);
        } else {
            document.addEventListener('DOMContentLoaded', callback);
        }
    }

    // API call helper
    async function apiCall(endpoint, params = {}) {
        const url = new URL(endpoint, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                url.searchParams.append(key, value);
            }
        });

        const response = await fetch(url);
        return response.json();
    }

    // NSFW level order for "use max" mode
    const NSFW_LEVEL_ORDER = ['PG', 'PG-13', 'R', 'X', 'XXX', 'Blocked', 'Unknown'];

    // Get current filter values
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

        const filters = {
            search: document.getElementById('mm_search')?.value || '',
            type: document.getElementById('mm_type')?.value || '',
            base_model: document.getElementById('mm_base_model')?.value || '',
            ...nsfwFilter,
            has_civitai: document.getElementById('mm_civitai')?.value || '',
            ...bookmarkedFilter,
            min_versions: document.getElementById('mm_min_versions')?.value || '',
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
            // Calculate page size dynamically based on viewport
            const calculatedPageSize = calculatePageSize();

            const filters = getFilters();
            filters.page = page;
            filters.page_size = calculatedPageSize;
            const data = await apiCall('/model-manager/models', filters);

            if (data.success) {
                currentModels = data.models;
                currentPage = data.page || 1;
                pageSize = data.page_size || calculatedPageSize;
                totalModels = data.total || 0;
                totalPages = pageSize > 0 ? Math.ceil(totalModels / pageSize) : 1;

                // Track absolute position of first visible item
                firstVisibleItemIndex = (currentPage - 1) * pageSize;

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
        const previewSrc = model.preview_path
            ? `/file=${encodeURIComponent(model.preview_path)}`
            : (model.preview_url || '');

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

        const ratingHtml = model.rating > 0
            ? `<span title="Rating">★ ${model.rating.toFixed(1)}</span>`
            : '';

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

        return `
            <div class="model-card ${civitaiClass} ${nsfwClass}" data-index="${index}" data-model-id="${model.civitai_model_id || ''}" onclick="window.mmSelectModel(${index})">
                <div class="model-card-image">
                    <img src="${hasPreview ? previewSrc : placeholderSvg}" alt="${name}" loading="lazy" onerror="this.src='${placeholderSvg}'">
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
                        ${ratingHtml}
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
                const versionsData = await apiCall('/model-manager/models/versions', { model_id: model.model_id });
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
            const data = await apiCall('/model-manager/models/details', { path: filePath });
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

                console.log(`[ModelManager] Loaded ${images.length} images (cursor: ${nextImagesCursor ? 'yes' : 'no'}, synced: ${imagesSyncDate ? 'yes' : 'no'})`);

                renderModelImages(images);
                updateImagesCountCell();
            }
        } catch (error) {
            console.error('[ModelManager] Failed to load model details:', error);
            updateImagesCountCell();  // Update even on error to show "None"
        }
    }

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
                `<span class="trigger-word" onclick="navigator.clipboard.writeText('${escapeHtml(w)}')">${escapeHtml(w)}</span>`
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
                   ${model.trained_words.map(w => `<span class="trigger-word" onclick="navigator.clipboard.writeText('${escapeHtml(w)}')">${escapeHtml(w)}</span>`).join('')}
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
            ? `<a class="action-btn secondary" href="https://civitai.com/models/${modelId}" target="_blank">View on Civitai</a>`
            : '';

        // Get description from full details if available
        const description = fullDetails?.civitai_model?.description || '';
        const descriptionHtml = description
            ? `<div class="detail-section">
                 <h4>Description</h4>
                 <div class="mm-description">${description}</div>
               </div>`
            : '<div class="detail-section" id="mm_description_placeholder"></div>';

        // Version selector (only if multiple versions)
        const versionSelectorHtml = renderVersionSelector();

        // Bookmark button (only for models with Civitai data)
        const isBookmarked = model.is_bookmarked || false;
        const bookmarkBtn = modelId
            ? `<button class="mm-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" onclick="window.mmToggleBookmark(${modelId})" title="${isBookmarked ? 'Remove bookmark' : 'Bookmark this model'}">${isBookmarked ? '★' : '☆'}</button>`
            : '';

        container.innerHTML = `
            <div class="model-details-content">
                <div class="detail-header">
                    <h3>${escapeHtml(model.display_name)}</h3>
                    ${bookmarkBtn}
                    ${modelId ? `<button class="mm-sync-model-btn" onclick="window.mmForceSyncModel()" title="Force sync this model">Sync</button>` : ''}
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
                    <div class="mm-description collapsed" id="mm_description_content">${description}</div>
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

        if (!images || images.length === 0) {
            container.style.display = 'none';
            return;
        }

        const imageCards = images.map((img, index) => renderImageCard(img, index)).filter(Boolean).join('');

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
        const infoText = neverSynced ? 'Images not yet downloaded' : `${images.length} images downloaded`;

        const downloadMoreHtml = showDownloadBtn
            ? `<div class="mm-load-more">
                 <button class="mm-btn secondary" id="mm_load_more_btn" onclick="window.mmLoadMoreImages()">
                   ${buttonText}
                 </button>
                 <span class="mm-load-more-info">${infoText}</span>
               </div>`
            : '';

        container.innerHTML = `
            <div class="mm-images-header">
                <h4>Example Images</h4>
                <span class="mm-images-count">${images.length} images</span>
            </div>
            <div class="model-images-list">${imageCards}</div>
            ${downloadMoreHtml}
        `;
        container.style.display = 'block';
    }

    // Render a single image card in list format
    function renderImageCard(img, index) {
        const src = img.url || '';
        if (!src) return '';

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

        return `
            <div class="mm-image-card" data-index="${index}">
                <div class="mm-image-left">
                    <img src="${escapeHtml(src)}" alt="Example image" loading="lazy"
                         onclick="window.open('${escapeHtml(src)}', '_blank')"
                         title="Click to view full size">
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
                        <button class="mm-btn secondary" onclick="navigator.clipboard.writeText(\`${escapeHtml(prompt).replace(/`/g, '\\`')}\`)">
                            Copy Prompt
                        </button>
                        <button class="mm-btn secondary" onclick="window.mmShowImageMeta(${index})">
                            Show All
                        </button>
                        ${img.id ? `<a class="mm-btn secondary" href="https://civitai.com/images/${img.id}" target="_blank">View on Civitai</a>` : ''}
                        ${(civitaiResources.length > 0 || resources.length > 0) ? `<button class="mm-btn secondary" onclick="window.mmShowResources(${index})">Resources (${civitaiResources.length + resources.length})</button>` : ''}
                    </div>
                </div>
            </div>
        `;
    }

    // Render a single resource (LoRA, VAE, etc)
    function renderResource(resource) {
        const type = resource.type || 'unknown';
        const name = resource.name || 'Unknown';
        const weight = resource.weight !== undefined ? resource.weight : null;

        let typeClass = 'mm-resource-other';
        let typeLabel = type;

        if (type.toLowerCase() === 'lora') {
            typeClass = 'mm-resource-lora';
            typeLabel = 'LoRA';
        } else if (type.toLowerCase() === 'vae') {
            typeClass = 'mm-resource-vae';
            typeLabel = 'VAE';
        } else if (type.toLowerCase() === 'embedding' || type.toLowerCase() === 'ti') {
            typeClass = 'mm-resource-embed';
            typeLabel = 'Embed';
        }

        const weightStr = weight !== null ? ` (${weight})` : '';

        return `<span class="mm-resource ${typeClass}" title="${escapeHtml(type)}: ${escapeHtml(name)}${weightStr}">
                  <span class="mm-resource-type">${typeLabel}</span>
                  <span class="mm-resource-name">${escapeHtml(name)}${weightStr}</span>
                </span>`;
    }

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

    // Show resources popup with download options (both civitaiResources and resources)
    window.mmShowResources = function(imageIndex) {
        const img = currentImages[imageIndex];
        if (!img || !img.meta) return;

        const civitaiResources = img.meta.civitaiResources || [];
        const resources = img.meta.resources || [];

        if (civitaiResources.length === 0 && resources.length === 0) return;

        // Build table rows for civitaiResources (have versionId)
        let tableRows = '';
        for (const resource of civitaiResources) {
            const type = resource.type || 'Unknown';
            const name = resource.name || 'Unknown';
            const versionId = resource.modelVersionId;

            // Download URL for Civitai
            const downloadUrl = versionId ? `https://civitai.com/api/download/models/${versionId}` : '';
            // View URL (model-versions redirects to the correct model page)
            const viewUrl = versionId ? `https://civitai.com/model-versions/${versionId}` : '';

            tableRows += `
                <tr>
                    <td class="mm-res-type">${escapeHtml(type)}</td>
                    <td class="mm-res-name">${escapeHtml(name)}</td>
                    <td class="mm-res-actions">
                        ${viewUrl ? `<a class="mm-btn secondary mm-btn-small" href="${viewUrl}" target="_blank">View</a>` : ''}
                        ${downloadUrl ? `<a class="mm-btn primary mm-btn-small" href="${downloadUrl}" target="_blank">Download</a>` : ''}
                    </td>
                </tr>
            `;
        }

        // Build table rows for resources (have hash only, need lookup)
        for (const resource of resources) {
            const type = resource.type || 'Unknown';
            const name = resource.name || 'Unknown';
            const hash = resource.hash || '';

            // Create a unique row ID for updating after lookup
            const rowId = `mm-res-${hash || Math.random().toString(36).substr(2, 9)}`;

            tableRows += `
                <tr id="${rowId}" data-hash="${escapeHtml(hash)}">
                    <td class="mm-res-type">${escapeHtml(type)}</td>
                    <td class="mm-res-name">${escapeHtml(name)}</td>
                    <td class="mm-res-actions">
                        ${hash ? `<button class="mm-btn secondary mm-btn-small" onclick="window.mmLookupHash('${escapeHtml(hash)}', '${rowId}')">Lookup</button>` : '<span class="mm-res-no-hash">No hash</span>'}
                    </td>
                </tr>
            `;
        }

        // Create modal
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

        // Add modal to document and lock scroll
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        document.body.classList.add('mm-modal-open');
    };

    // Lookup hash to get Civitai version info
    window.mmLookupHash = async function(hash, rowId) {
        const row = document.getElementById(rowId);
        if (!row) return;

        const actionsCell = row.querySelector('.mm-res-actions');
        if (!actionsCell) return;

        // Show loading state
        actionsCell.innerHTML = '<span class="mm-res-loading">Looking up...</span>';

        try {
            const response = await fetch(`/model-manager/resolve-hash?hash=${encodeURIComponent(hash)}`);
            const data = await response.json();

            if (data.success && data.version_id) {
                // Update with View/Download buttons
                actionsCell.innerHTML = `
                    <a class="mm-btn secondary mm-btn-small" href="${data.view_url}" target="_blank">View</a>
                    <a class="mm-btn primary mm-btn-small" href="${data.download_url}" target="_blank">Download</a>
                `;
                // Update name if we got a better one from Civitai
                if (data.model_name) {
                    const nameCell = row.querySelector('.mm-res-name');
                    if (nameCell) {
                        const versionSuffix = data.version_name ? ` (${data.version_name})` : '';
                        nameCell.textContent = data.model_name + versionSuffix;
                    }
                }
            } else {
                actionsCell.innerHTML = '<span class="mm-res-not-found">Not found</span>';
            }
        } catch (error) {
            console.error('[ModelManager] Hash lookup error:', error);
            actionsCell.innerHTML = '<span class="mm-res-error">Error</span>';
        }
    };

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            window.mmCloseMetaModal();
        }
    });

    // Download more images (appends to existing list without resetting scroll)
    window.mmLoadMoreImages = async function() {
        if (isLoadingMore || !currentVersionId) return;

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
                const startIndex = currentImages.length;
                currentImages = currentImages.concat(data.images);

                // Update cursor state from response
                nextImagesCursor = data.next_cursor || null;
                imagesSyncDate = new Date().toISOString();  // Mark as synced

                // Append new images to DOM (preserves scroll position)
                const imagesList = document.querySelector('.model-images-list');
                if (imagesList) {
                    const newCardsHtml = data.images.map((img, idx) =>
                        renderImageCard(img, startIndex + idx)
                    ).filter(Boolean).join('');
                    imagesList.insertAdjacentHTML('beforeend', newCardsHtml);
                }

                // Update all count displays
                updateAllImageCounts();

                // Update or hide button based on cursor
                if (nextImagesCursor) {
                    loadMoreBtn.textContent = 'Download More Images';
                    loadMoreBtn.disabled = false;
                } else {
                    const loadMoreSection = document.querySelector('.mm-load-more');
                    if (loadMoreSection) loadMoreSection.remove();
                }

                console.log(`[ModelManager] Downloaded ${data.images.length} more images (${currentImages.length} total, has_more: ${nextImagesCursor !== null})`);
            } else {
                // No more images
                nextImagesCursor = null;
                const loadMoreSection = document.querySelector('.mm-load-more');
                if (loadMoreSection) loadMoreSection.remove();

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
        if (headerCount) {
            headerCount.textContent = `${currentImages.length} images`;
        }

        // Load more info
        const loadMoreInfo = document.querySelector('.mm-load-more-info');
        if (loadMoreInfo) {
            loadMoreInfo.textContent = `${currentImages.length} images downloaded`;
        }

        // Info table cell
        updateImagesCountCell();
    }

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
    function matchVAEName(vaeName) {
        if (!vaeName) return null;

        // Try to find VAE dropdown and get options
        const vaeDropdown = gradioApp().querySelector('#setting_sd_vae select, #setting_sd_vae input');
        if (!vaeDropdown) {
            console.log('[ModelManager] VAE dropdown not found, using name as-is:', vaeName);
            return vaeName;
        }

        // Get all options from dropdown
        let options = [];
        if (vaeDropdown.tagName === 'SELECT') {
            options = Array.from(vaeDropdown.options).map(o => o.value);
        } else {
            // For input-based dropdowns, check datalist or sibling elements
            const datalist = gradioApp().querySelector('#setting_sd_vae datalist');
            if (datalist) {
                options = Array.from(datalist.options).map(o => o.value);
            }
        }

        if (options.length === 0) {
            console.log('[ModelManager] No VAE options found, using name as-is:', vaeName);
            return vaeName;
        }

        // Try exact match first
        if (options.includes(vaeName)) {
            return vaeName;
        }

        // Try matching without extension (metadata) to with extension (dropdown)
        const vaeNameLower = vaeName.toLowerCase();
        for (const option of options) {
            const optionLower = option.toLowerCase();
            // Check if option starts with the VAE name (handles extension difference)
            if (optionLower.startsWith(vaeNameLower) ||
                optionLower.replace(/\.(safetensors|pt|ckpt)$/i, '') === vaeNameLower) {
                console.log('[ModelManager] Matched VAE:', vaeName, '->', option);
                return option;
            }
        }

        console.log('[ModelManager] No VAE match found for:', vaeName);
        return vaeName; // Return as-is, let WebUI handle it
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
            // If current model is a Checkpoint, get its path
            let checkpointPath = null;
            if (model && model.model_type === 'Checkpoint') {
                checkpointPath = getDropdownPath(model.file_path, 'Checkpoint');
            }

            // Try to find VAE from image metadata
            let vaePath = null;

            // First check meta.VAE field (common in image metadata)
            if (meta.VAE) {
                vaePath = meta.VAE;
            }

            // Fallback: check resources array
            if (!vaePath) {
                const resources = meta.resources || [];
                const vaeResource = resources.find(r => r.type === 'vae');
                if (vaeResource && vaeResource.name) {
                    vaePath = vaeResource.name;
                }
            }

            // VAE in metadata is often without extension, but dropdown has extension
            // Try to match by finding a dropdown option that starts with the VAE name
            if (vaePath) {
                vaePath = matchVAEName(vaePath);
            }

            // Set checkpoint if available
            if (checkpointPath && typeof selectCheckpoint === 'function') {
                console.log('[ModelManager] Setting checkpoint:', checkpointPath);
                selectCheckpoint(checkpointPath);
            }

            // Set VAE - use metadata value or reset to None
            const vaeValue = vaePath || 'None';
            if (typeof selectVAE === 'function') {
                console.log('[ModelManager] Setting VAE:', vaeValue);
                selectVAE(vaeValue);
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
    async function startSync() {
        if (isSyncing) return;

        const forceCheckbox = document.getElementById('mm_sync_force');
        const forceRefresh = forceCheckbox ? forceCheckbox.checked : false;

        console.log('[ModelManager] Force checkbox element:', forceCheckbox);
        console.log('[ModelManager] Force checkbox checked:', forceRefresh);

        isSyncing = true;
        updateSyncUI(true);
        setStatus(forceRefresh ? 'Starting sync with Civitai (force refresh)...' : 'Starting sync with Civitai...');

        try {
            const bodyData = `force=${forceRefresh}`;
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
            const data = await apiCall('/model-manager/sync/progress');

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
            const data = await apiCall('/model-manager/scan/progress');

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
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

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

    function formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
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

    // Debounce helper
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Handle window resize - recalculate pagination without reloading
    const handleResize = debounce(() => {
        if (totalModels === 0) return;  // No data loaded yet

        const newPageSize = calculatePageSize();
        if (recalculatePagination(newPageSize)) {
            updatePaginationControls();
            console.log(`[ModelManager] Resize: updated to page ${currentPage}/${totalPages}`);
        }
    }, 300);

    // Scroll position restore functionality
    function updateScrollRestoreButton() {
        const savedPos = localStorage.getItem('mm_scroll_position');
        let btn = document.getElementById('mm_scroll_restore_btn');

        if (savedPos && parseInt(savedPos) > 0) {
            // Create button if it doesn't exist
            if (!btn) {
                const buttonsGroup = document.querySelector('.filter-buttons-group');
                if (buttonsGroup) {
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
                    // Insert as first button
                    buttonsGroup.insertBefore(btn, buttonsGroup.firstChild);
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
            nsfw_use_max: document.getElementById('mm_nsfw_use_max')?.checked || false,
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

            if (filters.search) document.getElementById('mm_search').value = filters.search;
            if (filters.type) document.getElementById('mm_type').value = filters.type;
            if (filters.base_model) document.getElementById('mm_base_model').value = filters.base_model;
            if (filters.civitai) document.getElementById('mm_civitai').value = filters.civitai;
            if (filters.is_bookmarked) document.getElementById('mm_is_bookmarked').value = filters.is_bookmarked;
            if (filters.min_versions) document.getElementById('mm_min_versions').value = filters.min_versions;
            if (filters.sort_by) document.getElementById('mm_sort_by').value = filters.sort_by;
            if (filters.sort_order) document.getElementById('mm_sort_order').value = filters.sort_order;

            // Set NSFW checkboxes
            const useMaxCb = document.getElementById('mm_nsfw_use_max');
            if (useMaxCb) useMaxCb.checked = filters.nsfw_use_max || false;

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

        // Setup resize listener
        window.addEventListener('resize', handleResize);
    }

    function bindElements() {
        const loadBtn = document.getElementById('mm_load_btn');
        const syncBtn = document.getElementById('mm_sync_btn');
        const cancelBtn = document.getElementById('mm_sync_cancel_btn');
        const refreshBtn = document.getElementById('mm_refresh_btn');
        const scanCancelBtn = document.getElementById('mm_scan_cancel_btn');
        const searchInput = document.getElementById('mm_search');

        if (!loadBtn) {
            console.log('[ModelManager] Button not found yet, retrying...');
            setTimeout(bindElements, 500);
            return;
        }

        console.log('[ModelManager] Found elements, binding events');

        // Setup NSFW controls
        setupNsfwControls();

        // Remove any existing listeners by cloning
        const newLoadBtn = loadBtn.cloneNode(true);
        loadBtn.parentNode.replaceChild(newLoadBtn, loadBtn);

        newLoadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('[ModelManager] Load button clicked');
            loadModels(1);  // Reset to page 1 when filters change
        });

        // Bind sync button
        if (syncBtn) {
            const newSyncBtn = syncBtn.cloneNode(true);
            syncBtn.parentNode.replaceChild(newSyncBtn, syncBtn);

            newSyncBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('[ModelManager] Sync button clicked');
                startSync();
            });
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
                console.log('[ModelManager] Refresh button clicked');
                startScan();
            });
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
            const scanData = await apiCall('/model-manager/scan/progress');
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
            const syncData = await apiCall('/model-manager/sync/progress');
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
})();
