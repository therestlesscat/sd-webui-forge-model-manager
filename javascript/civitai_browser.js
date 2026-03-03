/**
 * Civitai Browser JavaScript
 * Handles searching, displaying, and downloading models from Civitai.
 * Layout matches Model Manager exactly.
 */

(function() {
    'use strict';

    // State
    let currentModels = [];
    let currentPage = 1;
    let pageSize = 10;
    let isLoading = false;
    let selectedModel = null;
    let selectedVersionIndex = 0;
    let currentImages = [];
    let currentImagePage = 1;
    let nextImagesCursor = null;
    let isLoadingImages = false;
    let activeDownloads = {};
    let showAllNsfwImages = false;  // Toggle for showing all images regardless of NSFW filter
    const IMAGE_PAGE_SIZE = 100;
    let lazyMediaObserver = null;

    // Card sizing (default values, updated from API)
    let cardWidth = 200;
    let cardHeight = 280;

    // Apply card size from API response
    function applyCardSize(width, height) {
        if (width && height && (width !== cardWidth || height !== cardHeight)) {
            cardWidth = width;
            cardHeight = height;
            const container = document.getElementById('civitai_browser_app');
            if (container) {
                container.style.setProperty('--cb-card-width', `${width}px`);
                container.style.setProperty('--cb-card-height', `${height}px`);
                console.log(`[CivitaiBrowser] Card size set to ${width}x${height}`);
            }
        }
    }

    // Cursor-based pagination state
    // cursors[N-1] = cursor to fetch page N
    // cursors[0] = "" (first page needs no cursor)
    // cursors[1] = nextCursor from page 1 (use to fetch page 2)
    let cursors = [""];
    let hasMorePages = true;

    // LocalStorage key prefix for cursor cache
    const CURSOR_CACHE_PREFIX = "civitai_cursors_";

    // Get current filters hash
    function getFiltersHash() {
        return hashFilters(getFilters());
    }

    // Hash filters to create a cache key
    function hashFilters(filters) {
        const str = JSON.stringify(filters);
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash.toString(36);
    }

    // Load cache data from localStorage
    function loadFromCache(hash) {
        try {
            const cached = localStorage.getItem(CURSOR_CACHE_PREFIX + hash);
            if (cached) {
                return JSON.parse(cached);
            }
        } catch (e) {
            console.warn('[CivitaiBrowser] Failed to load cache:', e);
        }
        return null;
    }

    // Save cache data to localStorage
    function saveToCache(hash, cursorsArray, lastPage) {
        try {
            localStorage.setItem(CURSOR_CACHE_PREFIX + hash, JSON.stringify({
                cursors: cursorsArray,
                lastPage: lastPage
            }));
        } catch (e) {
            console.warn('[CivitaiBrowser] Failed to save cache:', e);
        }
    }

    // Clear cache for specific hash
    function clearCursorCache(hash) {
        try {
            localStorage.removeItem(CURSOR_CACHE_PREFIX + hash);
            console.log('[CivitaiBrowser] Cleared cursor cache for', hash);
        } catch (e) {
            // Ignore
        }
    }

    // Tag state (single tag)
    let selectedTag = '';
    let tagDebounceTimer = null;
    let tagSuggestions = [];
    let tagSelectedIndex = -1;
    let tagInputInitialized = false;

    // Placeholder SVG for missing images
    const placeholderSvg = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect fill='%23333' width='100' height='100'/%3E%3Ctext x='50' y='50' text-anchor='middle' dy='.3em' fill='%23666' font-size='10'%3ENo Image%3C/text%3E%3C/svg%3E";
    const IMAGE_PLACEHOLDER_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200'%3E%3Crect fill='%23222933' width='320' height='200'/%3E%3Cg fill='%236b7280'%3E%3Cpath d='M130 78h60v44h-60z'/%3E%3Cpath d='M92 132l34-30 28 24 18-14 56 44H92z'/%3E%3Ccircle cx='208' cy='82' r='10'/%3E%3C/g%3E%3Ctext x='160' y='176' text-anchor='middle' fill='%239ca3af' font-size='14'%3EImage unavailable%3C/text%3E%3C/svg%3E";

    // Calculate effective NSFW level using same algorithm as Python backend
    // NSFW levels: 1=PG, 2=PG-13, 4=R, 8=X, 16=XXX, 32=Blocked, 64=Unknown
    function calculateEffectiveNsfwLevel(img) {
        // browsingLevel is the primary source (integer)
        const browsingLevel = img.browsingLevel || 64;  // Default to Unknown

        // nsfwLevel string mapping
        const nsfwLevelStr = img.nsfwLevel || '';
        const nsfwLevelMap = {
            'None': 1,
            'Soft': 4,
            'Mature': 8,
            'X': 16,
        };
        const nsfwLevel = nsfwLevelMap[nsfwLevelStr] || 64;  // Default to Unknown

        // nsfw boolean
        const nsfwBool = img.nsfw ? 2 : 1;

        return Math.max(browsingLevel, nsfwLevel, nsfwBool);
    }

    // Check if image is safe to show (NSFW level <= 5)
    function isImageSafe(img) {
        return calculateEffectiveNsfwLevel(img) <= 5;
    }

    function getImagePageCount(totalImages) {
        return Math.max(1, Math.ceil(totalImages / IMAGE_PAGE_SIZE));
    }

    function setupLazyMedia(container) {
        if (!container) return;

        const lazyNodes = container.querySelectorAll('.mm-lazy-media[data-src]');
        if (lazyNodes.length === 0) return;

        const loadNode = (node) => {
            const src = node.getAttribute('data-src');
            if (!src) return;
            node.setAttribute('src', src);
            node.removeAttribute('data-src');
            node.classList.remove('mm-lazy-media');
            if (node.tagName === 'VIDEO') {
                node.load();
            }
        };

        if (!('IntersectionObserver' in window)) {
            lazyNodes.forEach(loadNode);
            return;
        }

        if (!lazyMediaObserver) {
            lazyMediaObserver = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting) return;
                    loadNode(entry.target);
                    lazyMediaObserver.unobserve(entry.target);
                });
            }, {
                root: null,
                rootMargin: '350px 0px',
                threshold: 0.01,
            });
        }

        lazyNodes.forEach((node) => lazyMediaObserver.observe(node));
    }

    function renderImagePagination(totalPages) {
        if (totalPages <= 1) return '';

        const firstDisabled = currentImagePage <= 1 ? 'disabled' : '';
        const prevDisabled = currentImagePage <= 1 ? 'disabled' : '';
        const nextDisabled = currentImagePage >= totalPages ? 'disabled' : '';
        const lastDisabled = currentImagePage >= totalPages ? 'disabled' : '';

        const maxVisible = 5;
        let startPage = Math.max(1, currentImagePage - Math.floor(maxVisible / 2));
        let endPage = Math.min(totalPages, startPage + maxVisible - 1);
        if (endPage - startPage < maxVisible - 1) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }

        const pageNumbers = [];
        if (startPage > 1) {
            pageNumbers.push({ page: 1, label: '1' });
            if (startPage > 2) {
                pageNumbers.push({ page: null, label: '...' });
            }
        }
        for (let i = startPage; i <= endPage; i++) {
            pageNumbers.push({ page: i, label: String(i) });
        }
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
            const activeClass = page === currentImagePage ? 'active' : '';
            return `<button class="mm-page-num ${activeClass}" onclick="window.cbGoToImagePage(${page})">${label}</button>`;
        }).join('');

        return `
            <div class="mm-image-pagination mm-pagination">
                <button class="mm-btn mm-page-btn" onclick="window.cbFirstImagePage()" ${firstDisabled}>|&lt;</button>
                <button class="mm-btn mm-page-btn" onclick="window.cbPrevImagePage()" ${prevDisabled}>← Prev</button>
                <div class="mm-page-numbers">${pageNumbersHtml}</div>
                <button class="mm-btn mm-page-btn" onclick="window.cbNextImagePage()" ${nextDisabled}>Next →</button>
                <button class="mm-btn mm-page-btn" onclick="window.cbLastImagePage()" ${lastDisabled}>&gt;|</button>
            </div>
        `;
    }

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
        return {
            query: document.getElementById('cb_search')?.value || '',
            types: document.getElementById('cb_type')?.value || '',
            base_models: document.getElementById('cb_base_model')?.value || '',
            sort: document.getElementById('cb_sort')?.value || 'Most Downloaded',
            period: document.getElementById('cb_period')?.value || 'AllTime',
            nsfw: document.getElementById('cb_nsfw')?.checked || false,
            tag: selectedTag,
        };
    }

    // Update status
    function updateStatus(message) {
        const status = document.getElementById('cb_status');
        if (status) status.textContent = message;
    }

    // Search models using cursor-based pagination
    async function searchModels(page = 1) {
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
        isLoading = true;

        const filters = getFilters();
        updateStatus('Searching...');

        try {
            const cursor = cursors[cursorIndex] || "";
            const params = {
                ...filters,
                cursor: cursor
            };

            const result = await apiCall('/model-manager/civitai/models', params);

            if (result.success) {
                // Apply card size from API response
                if (result.cardWidth && result.cardHeight) {
                    applyCardSize(result.cardWidth, result.cardHeight);
                }

                currentModels = result.models || [];
                currentPage = page;
                pageSize = result.pageSize || 10;

                // Store nextCursor for the next page
                if (result.nextCursor) {
                    cursors[page] = result.nextCursor;  // cursors[page] = cursor to fetch page+1
                    hasMorePages = true;
                } else {
                    hasMorePages = false;
                }

                // Save cursors and current page to cache (only for page 2+)
                if (page >= 2) {
                    saveToCache(getFiltersHash(), cursors, page);
                    // Hide resume button once user navigates beyond page 1
                    const resumeBtn = document.getElementById('cb_resume_btn');
                    if (resumeBtn) resumeBtn.style.display = 'none';
                }

                renderGrid();
                closeDetails();
                updateStatus(`Showing ${currentModels.length} models (page ${currentPage})`);
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

    // Render model grid
    function renderGrid() {
        const grid = document.getElementById('cb_grid');
        if (!grid) return;

        if (currentModels.length === 0) {
            grid.innerHTML = '<div class="model-grid-empty">No models found.</div>';
            return;
        }

        const cards = currentModels.map((model, index) => renderCard(model, index)).join('');
        // Show pagination if we have visited pages or there might be more
        const maxPageVisited = cursors.length;  // cursors.length = number of pages we can navigate to
        const showPagination = maxPageVisited > 1 || hasMorePages;
        const paginationHtml = showPagination ? renderPaginationControls() : '';
        grid.innerHTML = `<div class="model-grid-inner">${cards}</div>${paginationHtml}`;
    }

    // Render pagination controls - builds dynamically as user navigates
    function renderPaginationControls() {
        // cursors.length = max page we can navigate to (we have cursor for each)
        const maxPageVisited = cursors.length;

        // Build page numbers with ellipsis for large ranges
        let pageNumbers = [];
        const maxVisible = 5;
        let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(maxPageVisited, startPage + maxVisible - 1);

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
        if (endPage < maxPageVisited) {
            if (endPage < maxPageVisited - 1) {
                pageNumbers.push({ page: null, label: '...' });
            }
            pageNumbers.push({ page: maxPageVisited, label: String(maxPageVisited) });
        }

        const pageNumbersHtml = pageNumbers.map(({ page, label }) => {
            if (page === null) {
                return `<span class="mm-page-ellipsis">${label}</span>`;
            }
            const activeClass = page === currentPage ? 'active' : '';
            return `<button class="mm-page-num ${activeClass}" onclick="window.cbGoToPage(${page})">${label}</button>`;
        }).join('');

        return `
            <div class="mm-pagination">
                ${currentPage > 1 ? `<button class="mm-btn mm-page-btn" onclick="window.cbPrevPage()">← Prev</button>` : ''}
                <div class="mm-page-numbers">
                    ${pageNumbersHtml}
                </div>
                ${hasMorePages ? `<button class="mm-btn mm-page-btn" onclick="window.cbNextPage()">Next →</button>` : ''}
            </div>
        `;
    }

    // Render single model card - EXACTLY like Model Manager
    function renderCard(model, index) {
        const name = escapeHtml(model.name || 'Unknown');
        const nameShort = name.length > 30 ? name.substring(0, 30) + '...' : name;
        const type = model.type || 'Unknown';
        const downloads = formatNumber(model.stats?.downloadCount || 0);
        const rating = (model.stats?.rating || 0).toFixed(1);

        // Get preview image from first version
        const firstVersion = model.modelVersions?.[0];
        const firstImage = firstVersion?.images?.[0];
        const previewImage = firstImage?.url || '';
        const previewUrl = previewImage ? getThumbnailUrl(previewImage, 250) : '';
        const hasPreview = previewUrl !== '';
        const previewIsVideo = isVideoUrl(previewUrl, firstImage?.type);

        // Base model badge
        const baseModel = firstVersion?.baseModel || '';
        const baseModelBadge = baseModel
            ? `<span class="badge base-model">${escapeHtml(baseModel)}</span>`
            : '';

        // Ownership indicator
        const owned = model.owned_locally;
        const ownedClass = owned ? 'owned' : '';
        const ownedBadge = owned ? '<div class="cb-owned-badge">Owned</div>' : '';

        const ratingHtml = rating > 0
            ? `<span title="Rating">★ ${rating}</span>`
            : '';

        const downloadsHtml = downloads
            ? `<span title="Downloads">↓ ${downloads}</span>`
            : '';

        // Build preview HTML (video or image)
        const previewHtml = hasPreview
            ? (previewIsVideo
                ? `<video src="${previewUrl}" loop muted autoplay playsinline></video>`
                : `<img src="${previewUrl}" alt="${name}" loading="lazy" onerror="this.src='${placeholderSvg}'">`)
            : `<img src="${placeholderSvg}" alt="${name}">`;

        return `
            <div class="model-card ${ownedClass}" data-index="${index}" onclick="window.cbOpenModel(${index})">
                <div class="model-card-image">
                    ${previewHtml}
                    ${ownedBadge}
                </div>
                <div class="model-card-info">
                    <div class="model-card-name" title="${name}">${nameShort}</div>
                    <div class="model-card-meta">
                        <span class="badge type-badge">${type}</span>
                        ${baseModelBadge}
                    </div>
                    <div class="model-card-stats">
                        ${ratingHtml}
                        ${downloadsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    // Get thumbnail URL
    function getThumbnailUrl(url, width = 250) {
        if (!url) return '';
        if (url.includes('civitai.com')) {
            return url.replace(/\/width=\d+/, `/width=${width}`);
        }
        return url;
    }

    // Open model detail
    function openModel(index) {
        const model = currentModels[index];
        if (!model) return;

        selectedModel = model;
        selectedVersionIndex = 0;

        // Highlight selected card
        document.querySelectorAll('#cb_grid .model-card').forEach((card, i) => {
            card.classList.toggle('selected', i === index);
        });

        renderModelDetails();
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
        currentImages = [];
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
            const versionName = version.name || `v${index + 1}`;
            const ownedIndicator = version.owned_locally ? ' ✓' : '';
            const tooltip = `${versionName}\nBase: ${version.baseModel || 'Unknown'}${version.owned_locally ? '\n(Owned)' : ''}`;

            return `<button class="mm-version-pill ${activeClass} ${ownedClass}"
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
        const file = version?.files?.[0];

        // Version selector pills
        const versionSelectorHtml = renderVersionSelector();

        // Trained words / Trigger words
        const trainedWords = version?.trainedWords && version.trainedWords.length > 0
            ? `<div class="detail-section">
                 <h4>Trigger Words</h4>
                 <div class="trigger-words">
                   ${version.trainedWords.map(w => `<span class="trigger-word" onclick="navigator.clipboard.writeText('${escapeHtml(w)}'); this.style.background='#059669'; setTimeout(() => this.style.background='', 500)">${escapeHtml(w)}</span>`).join('')}
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
                 <div class="mm-description collapsed" id="cb_description_content">${description}</div>
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

        // Download button
        const downloadBtn = file && !isOwned
            ? `<button class="mm-btn primary" onclick="window.cbDownload(${model.id}, ${version?.id})">Download</button>`
            : (isOwned ? `<button class="mm-btn secondary" disabled>Already Owned</button>` : '');

        container.innerHTML = `
            <div class="model-details-content">
                <div class="detail-header">
                    <h3>${escapeHtml(model.name)}</h3>
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
                        <tr><td>Published</td><td>${version?.publishedAt ? formatDate(version.publishedAt) : 'Unknown'}</td></tr>
                        <tr><td>Updated</td><td>${version?.updatedAt ? formatDate(version.updatedAt) : 'Unknown'}</td></tr>
                        <tr><td>Rating</td><td>★ ${(stats.rating || 0).toFixed(1)} (${formatNumber(stats.ratingCount || 0)} ratings)</td></tr>
                        <tr><td>Downloads</td><td>${formatNumber(stats.downloadCount || 0)}</td></tr>
                        <tr><td>Favorites</td><td>${formatNumber(stats.favoriteCount || 0)}</td></tr>
                        <tr><td>Comments</td><td>${formatNumber(stats.commentCount || 0)}</td></tr>
                        <tr><td>File</td><td>${escapeHtml(fileName)}</td></tr>
                        <tr><td>File Size</td><td>${fileSize}</td></tr>
                        <tr><td>Images</td><td id="cb_images_count">${currentImages.length || '...'}</td></tr>
                    </table>
                </div>

                ${trainedWords}
                ${tags}
                ${descriptionHtml}

                <div class="detail-section detail-actions">
                    <a class="mm-btn secondary" href="https://civitai.com/models/${model.id}?modelVersionId=${version?.id}" target="_blank">View on Civitai</a>
                    ${downloadBtn}
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
    function selectVersion(versionIndex) {
        if (versionIndex === selectedVersionIndex) return;
        selectedVersionIndex = versionIndex;

        // Update pills UI
        document.querySelectorAll('.mm-version-pill').forEach((pill, idx) => {
            pill.classList.toggle('active', idx === selectedVersionIndex);
        });

        // Update version-specific info
        renderModelDetails();
        loadImagesFromVersion();
    }

    // Load images from API (with full metadata)
    async function loadImagesFromVersion() {
        const version = getSelectedVersion();
        if (!version?.id) {
            currentImages = [];
            nextImagesCursor = null;
            renderImages();
            return;
        }

        // Reset state
        currentImages = [];
        currentImagePage = 1;
        nextImagesCursor = null;
        isLoadingImages = true;

        const container = document.getElementById('cb_images');
        if (container) {
            container.innerHTML = '<div class="mm-images-loading">Loading images...</div>';
            container.style.display = 'block';
        }

        try {
            const result = await apiCall(`/model-manager/civitai/versions/${version.id}/images`, {
                model_id: selectedModel.id
            });

            if (result.success) {
                currentImages = result.images || [];
                nextImagesCursor = result.next_cursor || null;
                renderImages();
            } else {
                if (container) {
                    container.innerHTML = `<div class="mm-images-error">Error: ${result.error}</div>`;
                }
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
                if (result.images && result.images.length > 0) {
                    const oldCount = currentImages.length;
                    // Append new images (avoid duplicates by checking IDs)
                    const existingIds = new Set(currentImages.map(img => img.id));
                    const newImages = result.images.filter(img => !existingIds.has(img.id));
                    currentImages = [...currentImages, ...newImages];

                    const oldPages = getImagePageCount(oldCount);
                    const newPages = getImagePageCount(currentImages.length);
                    if (newPages > oldPages) {
                        currentImagePage = newPages;
                    }
                }
                // Update cursor from server response
                nextImagesCursor = result.next_cursor || null;
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

    // Update images count in the details table
    function updateImagesCount() {
        const countCell = document.getElementById('cb_images_count');
        if (countCell) {
            countCell.textContent = currentImages.length;
        }
    }

    // Render images - EXACTLY like Model Manager
    function renderImages() {
        const container = document.getElementById('cb_images');
        if (!container) return;

        if (currentImages.length === 0) {
            container.innerHTML = '<div class="mm-images-empty">No images available for this version.</div>';
            container.style.display = 'block';
            return;
        }

        // Check if NSFW filter is enabled (checkbox unchecked)
        const nsfwCheckbox = document.getElementById('cb_nsfw');
        const nsfwEnabled = nsfwCheckbox?.checked || false;

        // Filter images if NSFW not enabled and showAllNsfwImages is false
        let imagesToShow = currentImages;
        let hiddenCount = 0;

        if (!nsfwEnabled && !showAllNsfwImages) {
            imagesToShow = currentImages.filter(img => isImageSafe(img));
            hiddenCount = currentImages.length - imagesToShow.length;
        }

        const totalPages = getImagePageCount(imagesToShow.length);
        currentImagePage = Math.min(Math.max(1, currentImagePage), totalPages);
        const pageStart = (currentImagePage - 1) * IMAGE_PAGE_SIZE;
        const pageEnd = Math.min(pageStart + IMAGE_PAGE_SIZE, imagesToShow.length);
        const pageImages = imagesToShow.slice(pageStart, pageEnd);

        // Build NSFW filter warning panel with checkbox
        // Show warning when there are hidden images, OR when showAllNsfwImages is true and there would be hidden images
        const wouldHideCount = currentImages.filter(img => !isImageSafe(img)).length;
        const showWarning = !nsfwEnabled && wouldHideCount > 0;
        const nsfwWarningHtml = showWarning
            ? `<div class="cb-nsfw-warning">
                <span>${showAllNsfwImages
                    ? `Showing all ${currentImages.length} images (${wouldHideCount} NSFW)`
                    : `Showing ${imagesToShow.length} of ${currentImages.length} images (${hiddenCount} hidden due to NSFW filter)`}</span>
                <label class="cb-show-all-label">
                    <input type="checkbox" id="cb_show_all_images" ${showAllNsfwImages ? 'checked' : ''} onchange="window.cbToggleShowAllImages(this.checked)">
                    Show All
                </label>
               </div>`
            : '';

        const imageCards = pageImages.map((img) => {
            // Find original index for correct metadata lookup
            const originalIndex = currentImages.indexOf(img);
            return renderImageCard(img, originalIndex);
        }).join('');

        // Only show "Load More" button if there's a cursor (more images available)
        const loadMoreHtml = currentImagePage === totalPages && nextImagesCursor
            ? `<div class="mm-load-more">
                <button class="mm-btn secondary" id="cb_load_more_btn" onclick="window.cbLoadMoreImages()">
                    Load More Images
                </button>
                <span class="mm-load-more-info">${currentImages.length} images loaded</span>
               </div>`
            : (currentImagePage === totalPages ? `<div class="mm-load-more">
                <span class="mm-load-more-info">${currentImages.length} images (all loaded)</span>
               </div>` : '');

        container.innerHTML = `
            <div class="mm-images-header">
                <h4>Example Images</h4>
                <span class="mm-images-count">${imagesToShow.length > 0 ? `${pageStart + 1}-${pageEnd} of ${imagesToShow.length}` : '0'}${hiddenCount > 0 ? ` (${hiddenCount} hidden)` : ''} images (Page ${currentImagePage}/${totalPages})</span>
            </div>
            ${nsfwWarningHtml}
            <div class="model-images-list">${imageCards}</div>
            ${hiddenCount > 0 ? nsfwWarningHtml : ''}
            ${loadMoreHtml}
            ${renderImagePagination(totalPages)}
        `;

        container.style.display = 'block';
        setupLazyMedia(container);

        // Update the images count in the details table
        updateImagesCount();
    }

    // Toggle show all images checkbox
    window.cbToggleShowAllImages = function(checked) {
        showAllNsfwImages = checked;
        currentImagePage = 1;
        renderImages();
    };

    window.cbFirstImagePage = function() {
        if (currentImagePage === 1) return;
        currentImagePage = 1;
        renderImages();
    };

    window.cbLastImagePage = function() {
        const totalPages = getImagePageCount((!document.getElementById('cb_nsfw')?.checked && !showAllNsfwImages)
            ? currentImages.filter(img => isImageSafe(img)).length
            : currentImages.length);
        if (currentImagePage === totalPages) return;
        currentImagePage = totalPages;
        renderImages();
    };

    window.cbPrevImagePage = function() {
        if (currentImagePage <= 1) return;
        currentImagePage -= 1;
        renderImages();
    };

    window.cbNextImagePage = function() {
        const totalPages = getImagePageCount((!document.getElementById('cb_nsfw')?.checked && !showAllNsfwImages)
            ? currentImages.filter(img => isImageSafe(img)).length
            : currentImages.length);
        if (currentImagePage >= totalPages) return;
        currentImagePage += 1;
        renderImages();
    };

    window.cbGoToImagePage = function(page) {
        const totalPages = getImagePageCount((!document.getElementById('cb_nsfw')?.checked && !showAllNsfwImages)
            ? currentImages.filter(img => isImageSafe(img)).length
            : currentImages.length);
        if (page < 1 || page > totalPages || page === currentImagePage) return;
        currentImagePage = page;
        renderImages();
    };

    // Helper to detect video URLs
    function isVideoUrl(url, type) {
        if (!url) return false;
        if (type === 'video') return true;
        const lowerUrl = url.toLowerCase();
        return lowerUrl.endsWith('.mp4') ||
               lowerUrl.endsWith('.webm') ||
               lowerUrl.includes('.mp4?') ||
               lowerUrl.includes('.webm?');
    }

    // Render single image card - EXACTLY like Model Manager
    function renderImageCard(img, index) {
        const src = img.url || '';

        // Detect media type from URL or type field
        const isVideo = isVideoUrl(src, img.type);

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
        const nsfwLevel = img.nsfw || img.nsfwLevel || '';
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
                    onclick="${src ? `window.open('${escapeHtml(src)}', '_blank')` : 'return false;'}"
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
                        <button class="mm-btn secondary" onclick="navigator.clipboard.writeText(\`${escapeHtml(prompt).replace(/`/g, '\\`')}\`); this.textContent='Copied!'; setTimeout(() => this.textContent='Copy Prompt', 1500)">
                            Copy Prompt
                        </button>
                        <button class="mm-btn secondary" onclick="window.cbShowImageMeta(${index})">
                            Show All
                        </button>
                        ${img.id ? `<a class="mm-btn secondary" href="https://civitai.com/images/${img.id}" target="_blank">View on Civitai</a>` : ''}
                        ${(civitaiResources.length > 0 || resources.length > 0) ? `<button class="mm-btn secondary" onclick="window.cbShowResources(${index})">Resources (${civitaiResources.length + resources.length})</button>` : ''}
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
                    <button class="mm-btn secondary" onclick="navigator.clipboard.writeText(\`${escapeHtml(metaStr).replace(/`/g, '\\`')}\`); this.textContent='Copied!'; setTimeout(() => this.textContent='Copy JSON', 1500)">Copy JSON</button>
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
                ${r.weight !== undefined ? `<span class="mm-resource-weight">Weight: ${r.weight}</span>` : ''}
                ${r.modelVersionId ? `<a class="mm-btn secondary small" href="https://civitai.com/models/${r.modelId}?modelVersionId=${r.modelVersionId}" target="_blank">View</a>` : ''}
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

    // Start download
    async function startDownload(modelId, versionId) {
        try {
            updateStatus('Starting download...');

            const result = await apiPost('/model-manager/civitai/download', {
                model_id: modelId,
                version_id: versionId
            });

            if (result.success) {
                activeDownloads[versionId] = result.progress;
                showDownloadsPanel();
                pollDownloadProgress();
                updateStatus(`Download started: ${result.progress?.file_name || 'Unknown'}`);
            } else {
                updateStatus(`Download error: ${result.error}`);
            }
        } catch (e) {
            console.error('[CivitaiBrowser] Download error:', e);
            updateStatus(`Download error: ${e.message}`);
        }
    }

    // Show downloads panel
    function showDownloadsPanel() {
        const panel = document.getElementById('cb_downloads');
        if (panel) panel.style.display = 'block';
        renderDownloads();
    }

    // Render downloads list with clear status indicators
    function renderDownloads() {
        const list = document.getElementById('cb_download_list');
        const summary = document.getElementById('cb_downloads_summary');
        if (!list) return;

        const downloads = Object.values(activeDownloads);
        if (downloads.length === 0) {
            const panel = document.getElementById('cb_downloads');
            if (panel) panel.style.display = 'none';
            return;
        }

        // Sort: downloading first, then pending, then completed/error/cancelled
        const statusOrder = { 'downloading': 0, 'pending': 1, 'complete': 2, 'error': 3, 'cancelled': 4 };
        downloads.sort((a, b) => (statusOrder[a.status] || 5) - (statusOrder[b.status] || 5));

        // Count by status
        const downloadingCount = downloads.filter(d => d.status === 'downloading').length;
        const pendingCount = downloads.filter(d => d.status === 'pending').length;
        const completedCount = downloads.filter(d => d.status === 'complete' || d.status === 'error' || d.status === 'cancelled').length;

        // Update summary
        if (summary) {
            const parts = [];
            if (downloadingCount > 0) parts.push(`${downloadingCount} downloading`);
            if (pendingCount > 0) parts.push(`${pendingCount} pending`);
            if (completedCount > 0) parts.push(`${completedCount} finished`);
            summary.textContent = parts.join(', ') || `${downloads.length} total`;
        }

        list.innerHTML = downloads.map(dl => {
            const status = dl.status || 'pending';
            const percent = dl.percent?.toFixed(1) || 0;
            const downloaded = formatFileSize(dl.downloaded_bytes || 0);
            const total = formatFileSize(dl.total_bytes || 0);
            const showProgress = status === 'downloading' || status === 'pending';
            const showCancel = status === 'downloading' || status === 'pending';
            const showDismiss = status === 'complete' || status === 'error' || status === 'cancelled';

            // Status badge text
            let statusText = status;
            if (status === 'downloading') statusText = 'Downloading';
            else if (status === 'pending') statusText = 'Queued';
            else if (status === 'complete') statusText = 'Complete';
            else if (status === 'error') statusText = 'Error';
            else if (status === 'cancelled') statusText = 'Cancelled';

            return `
                <div class="cb-download-item ${status}">
                    <div class="cb-download-item-header">
                        <div class="cb-download-name" title="${escapeHtml(dl.file_name || 'Unknown')}">${escapeHtml(dl.file_name || 'Unknown')}</div>
                        <span class="cb-download-status-badge ${status}">${statusText}</span>
                    </div>
                    ${showProgress ? `
                        <div class="cb-download-progress">
                            <div class="cb-download-bar" style="width: ${status === 'pending' ? 100 : percent}%"></div>
                        </div>
                    ` : ''}
                    <div class="cb-download-info">
                        <span class="cb-download-percent">
                            ${status === 'downloading' ? `${percent}% - ${downloaded} / ${total}` : ''}
                            ${status === 'pending' ? 'Waiting...' : ''}
                            ${status === 'complete' ? `${total}` : ''}
                            ${status === 'error' ? (dl.error || 'Download failed') : ''}
                            ${status === 'cancelled' ? 'Download cancelled' : ''}
                        </span>
                        <div class="cb-download-actions">
                            ${showCancel ? `
                                <button class="cb-btn-small danger" onclick="window.cbCancelDownload(${dl.version_id})">Cancel</button>
                            ` : ''}
                            ${showDismiss ? `
                                <button class="cb-btn-small secondary" onclick="window.cbDismissDownload(${dl.version_id})">Dismiss</button>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Dismiss a completed download from the UI
    function dismissDownload(versionId) {
        delete activeDownloads[versionId];
        renderDownloads();
    }

    // Poll download progress
    let downloadPollInterval = null;
    let pendingModelRefresh = false;  // Track if we need to refresh models after downloads complete

    function pollDownloadProgress() {
        if (downloadPollInterval) return;

        downloadPollInterval = setInterval(async () => {
            try {
                const result = await apiCall('/model-manager/civitai/download/progress');
                if (result.success && result.downloads) {
                    // Track newly completed downloads for model refresh
                    result.downloads.forEach(dl => {
                        const prev = activeDownloads[dl.version_id];
                        // If status changed to complete, mark for refresh
                        if (dl.status === 'complete' && (!prev || prev.status !== 'complete')) {
                            pendingModelRefresh = true;
                        }
                        activeDownloads[dl.version_id] = dl;
                    });

                    renderDownloads();

                    // Check if there are any active (downloading/pending) downloads
                    const hasActive = Object.values(activeDownloads).some(dl => dl.status === 'downloading' || dl.status === 'pending');

                    if (!hasActive) {
                        // All downloads finished, stop polling
                        clearInterval(downloadPollInterval);
                        downloadPollInterval = null;

                        // Refresh models once if any completed successfully
                        if (pendingModelRefresh) {
                            pendingModelRefresh = false;
                            searchModels(currentPage);
                        }
                    }
                }
            } catch (e) {
                console.error('[CivitaiBrowser] Poll error:', e);
            }
        }, 1000);
    }

    // Cancel download
    async function cancelDownload(versionId) {
        try {
            await apiPost('/model-manager/civitai/download/cancel', { version_id: versionId });
        } catch (e) {
            console.error('[CivitaiBrowser] Cancel error:', e);
        }
    }

    // Utility functions
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    function formatFileSize(bytes) {
        if (!bytes) return 'Unknown';
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
        if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
        return bytes + ' B';
    }

    function formatDate(dateStr) {
        if (!dateStr) return 'Unknown';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }

    // ===== Tag Autocomplete (Single Tag) =====

    // Search tags from API
    async function searchTags(query) {
        if (query.length < 3) {
            tagSuggestions = [];
            renderTagDropdown();
            return;
        }

        try {
            const result = await apiCall('/model-manager/civitai/tags', { query, limit: 20 });
            if (result.success) {
                tagSuggestions = result.tags || [];
                tagSelectedIndex = -1;
                renderTagDropdown();
            }
        } catch (e) {
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

    // Select a tag
    function selectTag(tagName) {
        selectedTag = tagName || '';
        const input = document.getElementById('cb_tag_input');
        if (input) input.value = selectedTag;
        tagSuggestions = [];
        renderTagDropdown();
    }

    // Initialize tag input
    function initTagInput() {
        const input = document.getElementById('cb_tag_input');
        const dropdown = document.getElementById('cb_tag_dropdown');

        if (!input || tagInputInitialized) return;
        tagInputInitialized = true;

        console.log('[CivitaiBrowser] Tag input initialized');

        // Debounced input handler
        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            selectedTag = query; // Update selected tag as user types

            // Clear previous timer
            if (tagDebounceTimer) {
                clearTimeout(tagDebounceTimer);
            }

            // Set new timer (1 second debounce)
            tagDebounceTimer = setTimeout(() => {
                searchTags(query);
            }, 1000);
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
                } else {
                    // Just use what's typed
                    selectedTag = input.value.trim();
                    tagSuggestions = [];
                    renderTagDropdown();
                }
            } else if (e.key === 'Escape') {
                tagSuggestions = [];
                renderTagDropdown();
            }
        });

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

        // Initialize tag input (try now and also watch for dynamic loading)
        initTagInput();

        // Retry initialization for dynamically loaded elements (Gradio tabs)
        const initRetry = setInterval(() => {
            if (!tagInputInitialized) {
                initTagInput();
            }
            if (tagInputInitialized) {
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
        const hash = getFiltersHash();

        // Try loading from cache
        const cached = loadFromCache(hash);
        if (cached && cached.cursors && cached.cursors.length > 1) {
            cursors = cached.cursors;
            console.log('[CivitaiBrowser] Loaded', cached.cursors.length, 'cursors from cache');
        } else {
            cursors = [""];
        }
        hasMorePages = true;

        // Show/hide "Resume" button for last viewed page
        const resumeBtn = document.getElementById('cb_resume_btn');
        if (resumeBtn) {
            if (cached && cached.lastPage && cached.lastPage > 1) {
                resumeBtn.textContent = `Resume (page ${cached.lastPage})`;
                resumeBtn.style.display = 'inline-block';
            } else {
                resumeBtn.style.display = 'none';
            }
        }

        searchModels(1);
    };

    // Resume to last viewed page
    window.cbResumePage = function() {
        const hash = getFiltersHash();
        const cached = loadFromCache(hash);
        if (cached && cached.lastPage && cached.cursors) {
            cursors = cached.cursors;
            searchModels(cached.lastPage);
            // Hide button after resuming
            const resumeBtn = document.getElementById('cb_resume_btn');
            if (resumeBtn) resumeBtn.style.display = 'none';
        }
    };

    // Right-click on search clears cache for current filters
    window.cbClearSearchCache = function() {
        initTagInput();
        const hash = getFiltersHash();
        clearCursorCache(hash);
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
    window.cbDownload = startDownload;
    window.cbCancelDownload = cancelDownload;
    window.cbDismissDownload = dismissDownload;
    window.cbLoadMoreImages = loadMoreImages;

    // Initialize when ready
    onReady(init);
})();
