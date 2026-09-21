/**
 * Helpers shared by the Model Manager and Civitai Browser tabs.
 *
 * Both tabs render the same image cards, paginate them the same way and talk to
 * the same API, so the helpers that were identical in both scripts live here
 * instead of being maintained twice.
 *
 * The leading underscore matters: the WebUI loads an extension's javascript/
 * files in filename order, and this one has to be in place before the two tab
 * scripts run.
 */

window.MMCommon = (function() {
    'use strict';

    const IMAGE_PAGE_SIZE = 100;

    // Shared across both tabs - only one tab renders images at a time
    let lazyMediaObserver = null;

    function onReady(callback) {
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            setTimeout(callback, 100);
        } else {
            document.addEventListener('DOMContentLoaded', callback);
        }
    }

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

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    function isVideoUrl(url, type) {
        if (!url) return false;
        if (type === 'video') return true;
        const lowerUrl = url.toLowerCase();
        return lowerUrl.endsWith('.mp4') ||
               lowerUrl.endsWith('.webm') ||
               lowerUrl.includes('.mp4?') ||
               lowerUrl.includes('.webm?');
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

    /**
     * Page controls for an image gallery.
     *
     * `prefix` names the tab's global handlers: 'mm' calls window.mmGoToImagePage
     * and friends, 'cb' calls the window.cb* equivalents.
     */
    function renderImagePagination(currentImagePage, totalPages, position, prefix) {
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
            return `<button class="mm-page-num ${activeClass}" onclick="window.${prefix}GoToImagePage(${page})">${label}</button>`;
        }).join('');

        return `
            <div class="mm-image-pagination mm-pagination mm-image-pagination-${position}">
                <button class="mm-btn mm-page-btn" onclick="window.${prefix}FirstImagePage()" ${firstDisabled}>|&lt;</button>
                <button class="mm-btn mm-page-btn" onclick="window.${prefix}PrevImagePage()" ${prevDisabled}>← Prev</button>
                <div class="mm-page-numbers">${pageNumbersHtml}</div>
                <button class="mm-btn mm-page-btn" onclick="window.${prefix}NextImagePage()" ${nextDisabled}>Next →</button>
                <button class="mm-btn mm-page-btn" onclick="window.${prefix}LastImagePage()" ${lastDisabled}>&gt;|</button>
            </div>
        `;
    }

    /**
     * Push a card size onto a tab's container as CSS custom properties.
     * Each tab owns its container id, variable prefix and log tag.
     */
    function applyCardSize(width, height, containerId, cssPrefix, logTag) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.style.setProperty(`--${cssPrefix}-card-width`, `${width}px`);
        container.style.setProperty(`--${cssPrefix}-card-height`, `${height}px`);
        console.log(`[${logTag}] Card size set to ${width}x${height}`);
    }

    return {
        IMAGE_PAGE_SIZE,
        onReady,
        apiCall,
        escapeHtml,
        formatNumber,
        isVideoUrl,
        getImagePageCount,
        setupLazyMedia,
        renderResource,
        renderImagePagination,
        applyCardSize,
    };
})();
