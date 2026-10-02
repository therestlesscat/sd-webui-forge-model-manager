/**
 * A Civitai image's card - its media, what it was made with, its buttons -
 * and the Show All window behind it, the same in the Model Manager and the
 * Civitai Browser (#88). Each tab drew it from its own copy, and they had
 * drifted: one sampler reading or the other, a field only one listed, a table
 * in one Show All and JSON in the other. Your generations' cards show the
 * same text (imageTextHtml).
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, safeId } = await shared('core.mjs');
const { IMAGE_PLACEHOLDER_SVG, isVideoUrl, mediaFallback, mediaShape, originalMediaUrl, sizedMediaUrl, videoPosterUrl } = await shared('media.mjs');
const { nsfwBadge } = await shared('nsfw.mjs');
const { renderResource } = await shared('chips.mjs');
const { resourceButtonLabel } = await shared('resources.mjs');
const { splitSamplerScheduler } = await shared('samplers.mjs');
const { openMetaModal } = await shared('viewer.mjs');

/**
 * The text of an image card: its prompt, negative prompt, settings, hires and
 * ADetailer lines, from the image's generation data. A Civitai image's card
 * and a card of your own generations are both drawn with it.
 */
export function imageTextHtml(img) {
    const meta = img.meta || {};
    const prompt = meta.prompt || '';
    const negPrompt = meta.negativePrompt || '';

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

    return promptHtml + negPromptHtml + genParamsHtml + hiresHtml + adetailerHtml;
}

/**
 * A Civitai image's card, as both tabs draw it. `width` is how wide the
 * gallery draws a card's image; `exclude` the version the gallery is of,
 * which its Resources leave out; `actions` the window functions the tab's
 * buttons call - `send` (the Model Manager's alone), `showAll`, `resources`.
 */
export function renderImageCard(img, index, { width, exclude, actions }) {
    const src = img.url || '';

    const meta = img.meta || {};
    const prompt = meta.prompt || '';
    const resources = meta.resources || [];
    const civitaiResources = meta.civitaiResources || [];

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

    // The Resources button's label
    const resourcesLabel = resourceButtonLabel(img, exclude);

    const nsfwLevel = nsfwBadge(img);

    // Detect video
    const isVideo = isVideoUrl({ url: src, type: img.type });
    // A copy the size the card draws it, not the upload; a click opens the upload.
    const shown = sizedMediaUrl(src, { cssWidth: width, originalWidth: img.width, type: img.type });
    // A click opens the viewer (shared/viewer.mjs) - on a video, its ⤢, as a
    // click on the video plays it.
    const mediaHtml = isVideo
        ? `<video data-src="${escapeHtml(shown)}" data-poster="${escapeHtml(videoPosterUrl(src))}"
                  class="mm-lazy-media" preload="none" controls loop muted ${mediaShape(img)}
                  ${mediaFallback(originalMediaUrl(src))}
                  onclick="event.stopPropagation()"
                  title="Click to play"></video>
           <button type="button" class="mm-view-btn" data-view-index="${index}" title="Open in the viewer">⤢</button>`
        : `<img data-src="${escapeHtml(shown || IMAGE_PLACEHOLDER_SVG)}" class="mm-lazy-media" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Example image" loading="lazy"
                ${mediaShape(img)} ${mediaFallback(originalMediaUrl(src), IMAGE_PLACEHOLDER_SVG)}
                ${src ? `data-view-index="${index}"` : ''}
                title="Click to view">`;

    return `
        <div class="mm-image-card" data-index="${index}">
            <div class="mm-image-left" data-viewer-url="${escapeHtml(src ? originalMediaUrl(src) : '')}"
                 data-viewer-video="${isVideo}" data-viewer-width="${Number(img.width) || ''}"
                 data-viewer-height="${Number(img.height) || ''}">
                ${mediaHtml}
                ${nsfwLevel ? `<span class="mm-nsfw-badge">${escapeHtml(nsfwLevel)}</span>` : ''}
            </div>
            <div class="mm-image-right">
                ${imageIdHtml}
                ${resourcesHtml}
                ${imageTextHtml(img)}
                <div class="mm-image-actions">
                    ${actions.send ? `<button class="mm-btn primary mm-send-btn" onclick="window.${actions.send}(${index})">
                        Send to txt2img
                    </button>` : ''}
                    <button class="mm-btn secondary" data-copy="${escapeHtml(prompt)}">
                        Copy Prompt
                    </button>
                    <button class="mm-btn secondary" onclick="window.${actions.showAll}(${index})">
                        Show All
                    </button>
                    ${img.id ? `<a class="mm-btn secondary" href="https://civitai.com/images/${safeId(img.id)}" target="_blank">View on Civitai</a>` : ''}
                    ${resourcesLabel ? `<button class="mm-btn secondary" data-resources-index="${index}" onclick="window.${actions.resources}(${index})">${resourcesLabel}</button>` : ''}
                </div>
            </div>
        </div>
    `;
}

/**
 * Show All: every field of an image, in a table, and its generation data to
 * copy as JSON. One window for both tabs: the Civitai Browser showed only the
 * JSON, the Model Manager only the table.
 */
export function showImageMeta(img) {
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
        <div class="mm-modal-overlay" id="mm_meta_modal">
            <div class="mm-modal" onclick="event.stopPropagation()">
                <div class="mm-modal-header">
                    <h3>Image Metadata</h3>
                    <button class="mm-modal-close">&times;</button>
                </div>
                <div class="mm-modal-body">
                    <table class="mm-meta-table">
                        <tbody>
                            ${tableRows}
                        </tbody>
                    </table>
                </div>
                <div class="mm-modal-footer">
                    <button class="mm-btn secondary" data-copy="${escapeHtml(JSON.stringify(meta, null, 2))}">Copy JSON</button>
                </div>
            </div>
        </div>
    `;

    openMetaModal(modalHtml);
}
