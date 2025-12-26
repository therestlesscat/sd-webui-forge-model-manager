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

    // Pagination state
    let currentPage = 1;
    let totalPages = 1;
    let totalModels = 0;
    let pageSize = 0;

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
    let imageTotalCount = 0;
    let hasMoreImages = false;
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
    const NSFW_LEVEL_ORDER = ['PG', 'PG-13', 'R', 'X', 'XXX', 'Unknown'];

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
            // Find the highest selected level and use it as max
            let maxIndex = -1;
            selectedLevels.forEach(level => {
                const idx = NSFW_LEVEL_ORDER.indexOf(level);
                if (idx > maxIndex) maxIndex = idx;
            });
            if (maxIndex >= 0) {
                nsfwFilter.nsfw_max = NSFW_LEVEL_ORDER[maxIndex];
            }
        } else {
            nsfwFilter.nsfw_levels = selectedLevels.join(',');
        }

        console.log('[ModelManager] NSFW mode:', useMax ? 'max' : 'levels', 'selected:', selectedLevels);

        const filters = {
            search: document.getElementById('mm_search')?.value || '',
            type: document.getElementById('mm_type')?.value || '',
            base_model: document.getElementById('mm_base_model')?.value || '',
            ...nsfwFilter,
            has_civitai: document.getElementById('mm_civitai')?.value || '',
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

                if (useMax && e.target.checked) {
                    // In max mode: clicking a level auto-selects all up to it
                    const clickedLevel = e.target.value;
                    const clickedIndex = NSFW_LEVEL_ORDER.indexOf(clickedLevel);

                    levelCheckboxes.forEach(otherCb => {
                        const otherIndex = NSFW_LEVEL_ORDER.indexOf(otherCb.value);
                        otherCb.checked = otherIndex <= clickedIndex;
                    });
                }

                updateNsfwDisplay();
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
            const filters = getFilters();
            filters.page = page;
            const data = await apiCall('/model-manager/models', filters);

            if (data.success) {
                currentModels = data.models;
                currentPage = data.page || 1;
                pageSize = data.page_size || data.models.length;
                totalModels = data.total || 0;
                totalPages = pageSize > 0 ? Math.ceil(totalModels / pageSize) : 1;

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
        const nsfwClass = model.nsfw_level && model.nsfw_level !== 'PG' && model.nsfw_level !== 'Unknown'
            ? `nsfw-${model.nsfw_level.toLowerCase().replace('-', '')}`
            : '';
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

        return `
            <div class="model-card ${civitaiClass} ${nsfwClass}" data-index="${index}" onclick="window.mmSelectModel(${index})">
                <div class="model-card-image">
                    <img src="${hasPreview ? previewSrc : placeholderSvg}" alt="${name}" loading="lazy" onerror="this.src='${placeholderSvg}'">
                    ${!model.has_civitai_data ? '<div class="no-data-overlay">No Civitai Data</div>' : ''}
                </div>
                <div class="model-card-info">
                    <div class="model-card-name" title="${name}">${nameShort}</div>
                    <div class="model-card-meta">
                        <span class="badge type-badge">${model.model_type || 'Unknown'}</span>
                        ${baseModelBadge}
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
        imageTotalCount = 0;
        hasMoreImages = false;

        // Highlight selected card
        document.querySelectorAll('.model-card').forEach(card => card.classList.remove('selected'));
        const selectedCard = document.querySelector(`.model-card[data-index="${index}"]`);
        if (selectedCard) selectedCard.classList.add('selected');

        // Show basic details immediately
        renderModelDetails(model);

        // Fetch full details including images
        try {
            const data = await apiCall('/model-manager/models/details', { path: model.file_path });
            if (data.success && data.model) {
                // Store version ID for load-more
                if (data.model.civitai_version) {
                    currentVersionId = data.model.civitai_version.id;
                }

                // Update description if available
                if (data.model.civitai_model?.description) {
                    updateDescription(data.model.civitai_model.description);
                }

                // Store pagination info if available
                const images = data.model.images || [];
                currentImages = images;

                // Use pagination info from API response
                if (data.model.images_pagination) {
                    const pagination = data.model.images_pagination;
                    imageTotalCount = pagination.total_count || images.length;
                    hasMoreImages = pagination.fetched_pages < pagination.total_pages;
                    if (pagination.version_id) {
                        currentVersionId = pagination.version_id;
                    }
                } else {
                    // Fallback: assume there's more if we got 200
                    imageTotalCount = images.length;
                    hasMoreImages = images.length >= 200;
                }

                console.log(`[ModelManager] Loaded ${images.length} images (total: ${imageTotalCount}, hasMore: ${hasMoreImages})`);

                renderModelImages(images);
            }
        } catch (error) {
            console.error('[ModelManager] Failed to load model details:', error);
        }
    };

    // Format NSFW level to show all levels up to and including current
    function formatNsfwLevels(level) {
        if (!level || level === 'Unknown') return 'Unknown';
        const allLevels = ['PG', 'PG-13', 'R', 'X', 'XXX'];
        const idx = allLevels.indexOf(level);
        if (idx < 0) return level;
        return allLevels.slice(0, idx + 1).join(', ');
    }

    // Shorten file path - remove everything before \models or /models
    function shortenFilePath(path) {
        if (!path) return '';
        const match = path.match(/[\\\/]models[\\\/].*/i);
        return match ? match[0] : path;
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

        const civitaiLink = model.civitai_model_id
            ? `<a class="action-btn secondary" href="https://civitai.com/models/${model.civitai_model_id}" target="_blank">View on Civitai</a>`
            : '';

        // Get description from full details if available
        const description = fullDetails?.civitai_model?.description || '';
        const descriptionHtml = description
            ? `<div class="detail-section">
                 <h4>Description</h4>
                 <div class="mm-description">${description}</div>
               </div>`
            : '<div class="detail-section" id="mm_description_placeholder"></div>';

        container.innerHTML = `
            <div class="model-details-content">
                <div class="detail-header">
                    <h3>${escapeHtml(model.display_name)}</h3>
                    <button class="close-details" onclick="window.mmCloseDetails()">×</button>
                </div>

                <div class="detail-section">
                    <h4>Information</h4>
                    <table class="detail-table">
                        <tr><td>Type</td><td>${model.model_type || 'Unknown'}</td></tr>
                        <tr><td>Base Model</td><td>${model.base_model || 'Unknown'}</td></tr>
                        <tr><td>NSFW Level</td><td>${formatNsfwLevels(model.nsfw_level)}</td></tr>
                        <tr><td>File Size</td><td>${formatFileSize(model.file_size)}</td></tr>
                        <tr><td>Modified</td><td>${formatDate(model.file_modified)}</td></tr>
                        ${model.published_at ? `<tr><td>Published</td><td>${formatDate(model.published_at)}</td></tr>` : ''}
                        ${model.creator ? `<tr><td>Creator</td><td>${escapeHtml(model.creator)}</td></tr>` : ''}
                        ${model.rating > 0 ? `<tr><td>Rating</td><td>★ ${model.rating.toFixed(1)} (${formatNumber(model.download_count)} downloads)</td></tr>` : ''}
                        <tr><td>File</td><td class="file-path-cell">${escapeHtml(shortenFilePath(model.file_path))}</td></tr>
                    </table>
                </div>

                ${trainedWords}
                ${tags}
                ${descriptionHtml}

                <div class="detail-section detail-actions">
                    ${civitaiLink}
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

        // Load more button
        const loadMoreHtml = hasMoreImages
            ? `<div class="mm-load-more">
                 <button class="mm-btn secondary" id="mm_load_more_btn" onclick="window.mmLoadMoreImages()">
                   Load More Images
                 </button>
                 <span class="mm-load-more-info">Showing ${images.length}${imageTotalCount > 0 ? ` of ${imageTotalCount}` : ''} images</span>
               </div>`
            : '';

        container.innerHTML = `
            <div class="mm-images-header">
                <h4>Example Images</h4>
                <span class="mm-images-count">${images.length} images</span>
            </div>
            <div class="model-images-list">${imageCards}</div>
            ${loadMoreHtml}
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

        // Build generation params string
        const genParams = [];
        if (meta.steps) genParams.push(`Steps: ${meta.steps}`);
        if (meta.sampler) genParams.push(`Sampler: ${meta.sampler}`);
        if (meta.cfgScale) genParams.push(`CFG: ${meta.cfgScale}`);
        if (meta.seed) genParams.push(`Seed: ${meta.seed}`);
        if (meta['Clip skip']) genParams.push(`Clip Skip: ${meta['Clip skip']}`);
        if (meta['Denoising strength']) genParams.push(`Denoise: ${meta['Denoising strength']}`);

        // Hires info
        const hiresParams = [];
        if (meta['Hires upscaler']) hiresParams.push(`Upscaler: ${meta['Hires upscaler']}`);
        if (meta['Hires upscale']) hiresParams.push(`Scale: ${meta['Hires upscale']}`);
        if (meta['Hires steps']) hiresParams.push(`Steps: ${meta['Hires steps']}`);

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
                    ${resourcesHtml}
                    ${promptHtml}
                    ${negPromptHtml}
                    ${genParamsHtml}
                    ${hiresHtml}
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
                return value.map(v => typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v)).join('<br>');
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

        // Add modal to body
        document.body.insertAdjacentHTML('beforeend', modalHtml);
    };

    // Close metadata modal
    window.mmCloseMetaModal = function(event) {
        // If called with event, only close if clicking overlay (not modal content)
        if (event && event.target !== event.currentTarget) return;
        const modal = document.querySelector('.mm-modal-overlay');
        if (modal) modal.remove();
    };

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            window.mmCloseMetaModal();
        }
    });

    // Load more images
    window.mmLoadMoreImages = async function() {
        if (isLoadingMore || !currentModelPath) return;

        isLoadingMore = true;
        const loadMoreBtn = document.getElementById('mm_load_more_btn');
        if (loadMoreBtn) {
            loadMoreBtn.disabled = true;
            loadMoreBtn.textContent = 'Loading...';
        }

        try {
            const response = await fetch('/model-manager/images/load-more', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `model_path=${encodeURIComponent(currentModelPath)}`
            });

            const data = await response.json();

            if (data.success && data.images && data.images.length > 0) {
                // Add new images to current list
                currentImages = currentImages.concat(data.images);
                imageTotalCount = data.total_count || imageTotalCount;
                hasMoreImages = data.has_more;

                // Re-render with all images
                renderModelImages(currentImages);

                console.log(`[ModelManager] Loaded ${data.images.length} more images (${currentImages.length}/${imageTotalCount} total)`);
            } else {
                hasMoreImages = false;
                // Re-render to hide the load more button
                renderModelImages(currentImages);

                if (data.message) {
                    console.log('[ModelManager]', data.message);
                }
            }
        } catch (error) {
            console.error('[ModelManager] Load more error:', error);
            if (loadMoreBtn) {
                loadMoreBtn.textContent = 'Load More Images';
                loadMoreBtn.disabled = false;
            }
        } finally {
            isLoadingMore = false;
        }
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

    // Set checkpoint and VAE using WebUI's internal functions
    async function setCheckpointAndVAE(checkpoint, vae) {
        try {
            let needsChange = false;

            // Use WebUI's selectCheckpoint function
            if (checkpoint) {
                if (typeof selectCheckpoint === 'function') {
                    selectCheckpoint(checkpoint);
                    needsChange = true;
                    console.log('[ModelManager] Called selectCheckpoint:', checkpoint);
                } else {
                    console.warn('[ModelManager] selectCheckpoint function not available');
                }
            }

            // Use WebUI's selectVAE function
            if (vae && vae !== 'Automatic' && vae !== 'None') {
                if (typeof selectVAE === 'function') {
                    selectVAE(vae);
                    needsChange = true;
                    console.log('[ModelManager] Called selectVAE:', vae);
                } else {
                    console.warn('[ModelManager] selectVAE function not available');
                }
            }

            // If only VAE changed, trigger the change button
            if (needsChange && !checkpoint) {
                const changeBtn = gradioApp().getElementById('change_checkpoint');
                if (changeBtn) {
                    changeBtn.click();
                    console.log('[ModelManager] Clicked change_checkpoint button');
                }
            }

            // Wait for model loading to complete
            if (needsChange) {
                await new Promise(resolve => setTimeout(resolve, 500));
            }
        } catch (error) {
            console.warn('[ModelManager] Error setting checkpoint/VAE:', error);
        }
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

        // Build parameters line
        const params = [];

        if (meta.steps) params.push(`Steps: ${meta.steps}`);
        if (meta.sampler) params.push(`Sampler: ${meta.sampler}`);
        if (meta.cfgScale) params.push(`CFG scale: ${meta.cfgScale}`);
        if (meta.seed) params.push(`Seed: ${meta.seed}`);
        if (meta.Size) params.push(`Size: ${meta.Size}`);
        if (meta.Model) params.push(`Model: ${meta.Model}`);
        if (meta['Model hash']) params.push(`Model hash: ${meta['Model hash']}`);
        if (meta['Denoising strength']) params.push(`Denoising strength: ${meta['Denoising strength']}`);
        if (meta['Clip skip']) params.push(`Clip skip: ${meta['Clip skip']}`);
        if (meta['Hires upscale']) params.push(`Hires upscale: ${meta['Hires upscale']}`);
        if (meta['Hires upscaler']) params.push(`Hires upscaler: ${meta['Hires upscaler']}`);
        if (meta['Hires steps']) params.push(`Hires steps: ${meta['Hires steps']}`);

        // Add any other parameters from meta that we haven't explicitly handled
        const handledKeys = ['prompt', 'negativePrompt', 'steps', 'sampler', 'cfgScale', 'seed',
                            'Size', 'Model', 'Model hash', 'Denoising strength', 'Clip skip',
                            'Hires upscale', 'Hires upscaler', 'Hires steps', 'resources', 'civitaiResources'];
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

    // Send image generation params to txt2img using paste button
    window.mmSendToTxt2img = async function(imageIndex) {
        const img = currentImages[imageIndex];
        if (!img || !img.meta) {
            console.error('[ModelManager] No image data at index', imageIndex);
            return;
        }

        const meta = img.meta;
        const model = currentModels[selectedModelIndex];

        try {
            // If current model is a Checkpoint, get its path
            let checkpointPath = null;
            if (model && model.model_type === 'Checkpoint') {
                checkpointPath = getDropdownPath(model.file_path, 'Checkpoint');
            }

            // Try to find VAE from image metadata resources
            let vaePath = null;
            const resources = meta.resources || [];
            const vaeResource = resources.find(r => r.type === 'vae');
            if (vaeResource && vaeResource.name) {
                vaePath = vaeResource.name;
            }

            // Load checkpoint and VAE if we have them
            if (checkpointPath || vaePath) {
                console.log('[ModelManager] Loading checkpoint:', checkpointPath, 'VAE:', vaePath);
                await setCheckpointAndVAE(checkpointPath, vaePath);
            }

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

            // Switch to txt2img tab
            const txt2imgTab = document.querySelector('#tabs button:first-child');
            if (txt2imgTab) {
                txt2imgTab.click();
            }

            console.log('[ModelManager] Sent to txt2img via paste:', {
                infotextLength: infotext.length,
                prompt: meta.prompt?.substring(0, 50) + '...',
                checkpoint: checkpointPath,
                vae: vaePath
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

        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    loadModels(1);  // Reset to page 1 when searching
                }
            });
        }

        console.log('[ModelManager] Ready - click handlers bound');

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

    onReady(init);
})();
