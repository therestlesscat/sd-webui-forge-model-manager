/**
 * Helpers shared by the Model Manager and Civitai Browser tabs.
 *
 * Both tabs render the same image cards, paginate them the same way and talk to
 * the same API, so the helpers that were identical in both scripts live here
 * instead of being maintained twice.
 *
 * An ES module, so the two tab scripts import what they need by name rather
 * than reaching for a global and depending on load order.
 */

export const IMAGE_PAGE_SIZE = 100;

/**
 * Show a tab's "no Civitai API key" banner, once both halves exist.
 *
 * Without a key the rate limit is 0.5 requests a second rather than 6, the
 * tRPC endpoint carrying image prompts refuses outright, and some models will
 * not download - so most of what this extension does either crawls or quietly
 * fails, and both tabs need to say so.
 *
 * Nothing orders the two things this needs. The answer comes from a fetch
 * started at import, from a <script type="module"> in the head; the markup
 * appears when Gradio renders the tab. Applying it at fixed moments failed,
 * because whichever ran first found the other half missing. So it waits for
 * both, briefly, rather than guessing when they will be ready.
 *
 * The answer is fetched once however many tabs ask for it.
 */
const API_KEY_BANNER_TRIES = 20;        // 5 seconds, at 250ms apart

let apiKeyMissing = null;
let apiKeyRequest = null;

export function apiKeyStatus() {
    if (apiKeyMissing !== null) return Promise.resolve(apiKeyMissing);
    if (!apiKeyRequest) {
        apiKeyRequest = fetch('/model-manager/ui-options')
            .then((r) => r.json())
            .then((data) => {
                // Answered even when the rest of that call failed.
                apiKeyMissing = data.has_api_key === false;
                return apiKeyMissing;
            })
            .catch(() => {
                // Unreachable is not the same as unconfigured; say nothing
                // rather than blame the key for a WebUI that is not answering.
                apiKeyMissing = false;
                return false;
            });
    }
    return apiKeyRequest;
}

const apiKeyBanners = new Set();

export function showApiKeyBanner(bannerId, attempt = 0) {
    apiKeyStatus();                     // starts the one fetch, if needed
    apiKeyBanners.add(bannerId);

    const banner = document.getElementById(bannerId);
    if (apiKeyMissing === null || !banner) {
        if (attempt < API_KEY_BANNER_TRIES) {
            setTimeout(() => showApiKeyBanner(bannerId, attempt + 1), 250);
        }
        return;
    }

    banner.style.display = apiKeyMissing ? 'flex' : 'none';
}

/**
 * Put the banners back after Gradio has redrawn the page.
 *
 * Gradio re-renders a gr.HTML block wholesale, and an inline style set on
 * something inside it does not survive that - the element comes back as the
 * markup declares it, which is hidden. Setting it once during startup is
 * therefore not enough: it has to be reasserted whenever the UI is rebuilt,
 * which is what this hook is for.
 */
if (typeof onAfterUiUpdate === 'function') {
    onAfterUiUpdate(() => {
        if (apiKeyMissing === null) return;
        apiKeyBanners.forEach((bannerId) => {
            const banner = document.getElementById(bannerId);
            if (banner) banner.style.display = apiKeyMissing ? 'flex' : 'none';
        });
    });
}

// Shared across both tabs - only one tab renders images at a time
export let lazyMediaObserver = null;

export function onReady(callback) {
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(callback, 100);
    } else {
        document.addEventListener('DOMContentLoaded', callback);
    }
}

export async function apiCall({ endpoint, params = {} }) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.append(key, value);
        }
    });
    const response = await fetch(url);
    return response.json();
}

/**
 * Make text safe to place in HTML - as content, or inside a quoted attribute.
 *
 * This used to serialize a text node, which escapes & < > and, per the HTML
 * spec, nothing else. Almost every caller puts the result inside a quoted
 * attribute, and a Civitai prompt containing `"` then closed the attribute and
 * added one of its own: `onmouseover`, say. Prompts, tags, trigger words and
 * file names are all written by whoever uploaded them, so quotes are escaped
 * too.
 *
 * Not enough for a script context. An attribute is decoded before its handler
 * runs, so `&#39;` inside an onclick is a quote again by the time JavaScript
 * sees it. Data never goes inside an inline handler: see data-copy and
 * data-open-url below.
 */
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/**
 * An id from Civitai, as a number, or null if it is not one.
 *
 * Ids go into URLs and handler calls unquoted, so a string arriving where a
 * number was expected would be code. Civitai sends numbers today; this is so
 * that stays true of what reaches the page, whatever it sends tomorrow.
 */
export function safeId(value) {
    const n = Number(value);
    return Number.isSafeInteger(n) && n > 0 ? n : null;
}

/**
 * The http(s) URL in `value`, or null.
 *
 * Relative URLs are read against Civitai, since that is where the text they
 * come from was written.
 */
export function safeUrl(value, protocols = ['http:', 'https:']) {
    if (!value) return null;
    try {
        const url = new URL(String(value), 'https://civitai.com');
        return protocols.includes(url.protocol) ? url.href : null;
    } catch (e) {
        return null;
    }
}

/**
 * A model description, reduced to formatting.
 *
 * Descriptions are HTML by design, so they cannot be escaped - but they were
 * inserted raw, and the scan also reads them from .civitai.info files other
 * tools write. Anything not on the list goes: tags are unwrapped to their text,
 * and script-bearing ones are dropped with their contents. Only a link's href,
 * an image's src and a title survive as attributes, and only as http(s).
 *
 * Parsed with DOMParser, which is inert. Setting innerHTML on a detached
 * element is not: an <img onerror> fires there too.
 */
const DESCRIPTION_TAGS = new Set([
    'A', 'ABBR', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'DIV', 'EM', 'H1', 'H2',
    'H3', 'H4', 'H5', 'H6', 'HR', 'I', 'IMG', 'LI', 'OL', 'P', 'PRE', 'S', 'SMALL',
    'SPAN', 'STRIKE', 'STRONG', 'SUB', 'SUP', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD',
    'TR', 'U', 'UL',
]);
const DESCRIPTION_DROPPED = new Set([
    'SCRIPT', 'STYLE', 'IFRAME', 'FRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE',
    'FORM', 'INPUT', 'BUTTON', 'TEXTAREA', 'SELECT', 'SVG', 'MATH', 'NOSCRIPT',
    'TEMPLATE', 'AUDIO', 'VIDEO', 'SOURCE',
]);

function cleanDescriptionNode(node) {
    for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === 3) continue;               // text
        if (child.nodeType !== 1) { child.remove(); continue; }   // comments and the rest

        const tag = child.tagName.toUpperCase();
        if (DESCRIPTION_DROPPED.has(tag)) { child.remove(); continue; }

        cleanDescriptionNode(child);

        if (!DESCRIPTION_TAGS.has(tag)) {
            child.replaceWith(...Array.from(child.childNodes));
            continue;
        }

        for (const attr of Array.from(child.attributes)) {
            const name = attr.name.toLowerCase();
            const kept = name === 'title'
                || (tag === 'A' && name === 'href')
                || (tag === 'IMG' && (name === 'src' || name === 'alt'));
            if (!kept) child.removeAttribute(attr.name);
        }

        if (tag === 'A') {
            const href = safeUrl(child.getAttribute('href'), ['http:', 'https:', 'mailto:']);
            if (href) child.setAttribute('href', href);
            else child.removeAttribute('href');
            child.setAttribute('target', '_blank');
            child.setAttribute('rel', 'noopener noreferrer');
        } else if (tag === 'IMG') {
            const src = safeUrl(child.getAttribute('src'));
            if (src) child.setAttribute('src', src);
            else child.remove();
        }
    }
}

export function sanitizeHtml(html) {
    if (!html) return '';
    // A whole document rather than the bare fragment: browsers put a fragment
    // into <body> either way, but not every DOM implementation does.
    const doc = new DOMParser().parseFromString(
        '<!doctype html><html><body>' + String(html) + '</body></html>', 'text/html');
    cleanDescriptionNode(doc.body);
    return doc.body.innerHTML;
}

/**
 * Copying and opening, without putting data inside an onclick.
 *
 * Buttons that used to carry the text in their handler -
 * `writeText(\`${prompt}\`)` ran any ${...} in a prompt - now carry it in a
 * data attribute, which is never executed, and this one listener acts on it.
 * Installed once, on the document, so it covers markup rendered later.
 */
if (typeof document !== 'undefined'
        && typeof document.addEventListener === 'function'
        && !globalThis.__mmDelegatedClicks) {
    globalThis.__mmDelegatedClicks = true;
    document.addEventListener('click', (event) => {
        const target = event.target && event.target.closest
            ? event.target.closest('[data-copy], [data-open-url]')
            : null;
        if (!target) return;

        if (target.hasAttribute('data-open-url')) {
            const url = safeUrl(target.getAttribute('data-open-url'));
            if (url) window.open(url, '_blank', 'noopener');
            return;
        }

        const text = target.getAttribute('data-copy') || '';
        if (navigator.clipboard) navigator.clipboard.writeText(text);

        if (target.tagName === 'BUTTON') {
            const label = target.textContent;
            target.textContent = 'Copied!';
            setTimeout(() => { target.textContent = label; }, 1500);
        } else {
            target.classList.add('mm-copied');
            setTimeout(() => target.classList.remove('mm-copied'), 600);
        }
    });
}

export function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

/**
 * A model's reception, as Civitai reports it since star ratings went away.
 *
 * Renders nothing when nobody has voted, so a card is not cluttered with
 * two zeroes. A down count of zero still shows once there are up votes,
 * because "52.9K up, 0 down" is worth knowing.
 */
export function renderThumbs(up, down) {
    const ups = Number(up) || 0;
    const downs = Number(down) || 0;
    if (!ups && !downs) return '';

    const total = ups + downs;
    const share = Math.round((ups / total) * 100);
    const title = `${ups.toLocaleString()} up, ${downs.toLocaleString()} down (${share}% positive)`;

    return `<span class="mm-thumbs" title="${escapeHtml(title)}">`
         + `<span class="mm-thumbs-up">▲ ${formatNumber(ups)}</span>`
         + `<span class="mm-thumbs-down">▼ ${formatNumber(downs)}</span>`
         + `</span>`;
}

/**
 * How explicit an image is, on Civitai's scale:
 *   PG 1 · PG-13 2 · R 4 · X 8 · XXX 16 · Blocked 32 · Unknown 64
 *
 * browsingLevel is the integer Civitai maintains, so it wins whenever it
 * is there. The legacy string and the bare boolean stay as fallbacks
 * because none of these fields has been dependable.
 *
 * Mirrors image_level() in model_manager/nsfw.py - the two must agree, or
 * the grid and the server disagree about what to hide.
 */
export const NSFW_LEGACY_LEVELS = { None: 1, Soft: 2, Mature: 4, X: 16 };
export const NSFW_UNKNOWN = 64;
export const NSFW_SFW_MAX = 3;  // PG | PG-13

export function nsfwImageLevel(image) {
    const browsing = image?.browsingLevel;
    if (typeof browsing === 'number' && browsing > 0) return browsing;

    const legacy = image?.nsfwLevel;
    if (typeof legacy === 'number' && legacy > 0) return legacy;
    if (typeof legacy === 'string' && NSFW_LEGACY_LEVELS[legacy]) {
        return NSFW_LEGACY_LEVELS[legacy];
    }

    if (image?.nsfw === true) return 4;   // cautious: nothing else to go on
    if (image?.nsfw === false) return 1;

    return NSFW_UNKNOWN;
}

/** Is this image safe for a work-safe view? */
export function isImageSafe(image) {
    return nsfwImageLevel(image) <= NSFW_SFW_MAX;
}

/**
 * The shortest prompt worth showing, in characters after trimming.
 *
 * Measured against a library of 101,369 images: 10,476 carry no prompt at all,
 * and everything from one to ten characters together is 627. There is a cliff
 * rather than a slope, so the exact number matters far less than having one.
 * Below four is "1", ".", "???" - never a prompt someone wrote.
 */
export const MIN_PROMPT_LENGTH = 4;

/** Does this image carry a prompt worth reading? */
export function hasReadablePrompt(image) {
    const meta = image?.meta || {};
    return (meta.prompt || '').trim().length >= MIN_PROMPT_LENGTH;
}

/**
 * Does this image carry a prompt you could reproduce it from?
 *
 * A prompt on its own is not enough - "Send to txt2img" without steps, sampler
 * and CFG produces something unrelated. Built on hasReadablePrompt() rather
 * than beside it, so the length floor cannot apply to one and not the other:
 * before it did, this accepted a prompt of "1" as long as the settings were
 * present.
 */
export function hasUsablePrompt(image) {
    if (!hasReadablePrompt(image)) return false;
    const meta = image?.meta || {};
    if (!meta.steps) return false;
    if (!(meta.sampler || meta.Sampler)) return false;
    if (!(meta.cfgScale || meta['CFG scale'])) return false;
    return true;
}

export function isVideoUrl({ url, type }) {
    if (!url) return false;
    if (type === 'video') return true;
    const lowerUrl = url.toLowerCase();
    return lowerUrl.endsWith('.mp4') ||
           lowerUrl.endsWith('.webm') ||
           lowerUrl.includes('.mp4?') ||
           lowerUrl.includes('.webm?');
}

export function getImagePageCount(totalImages) {
    return Math.max(1, Math.ceil(totalImages / IMAGE_PAGE_SIZE));
}

export function setupLazyMedia(container) {
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

export function renderResource(resource) {
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

    const weightStr = weight !== null ? ` (${escapeHtml(String(weight))})` : '';

    return `<span class="mm-resource ${typeClass}" title="${escapeHtml(type)}: ${escapeHtml(name)}${weightStr}">
              <span class="mm-resource-type">${escapeHtml(typeLabel)}</span>
              <span class="mm-resource-name">${escapeHtml(name)}${weightStr}</span>
            </span>`;
}

/**
 * Page controls for an image gallery.
 *
 * `prefix` names the tab's global handlers: 'mm' calls window.mmGoToImagePage
 * and friends, 'cb' calls the window.cb* equivalents.
 */
export function renderImagePagination({ currentPage, totalPages, position, prefix }) {
    if (totalPages <= 1) return '';

    const firstDisabled = currentPage <= 1 ? 'disabled' : '';
    const prevDisabled = currentPage <= 1 ? 'disabled' : '';
    const nextDisabled = currentPage >= totalPages ? 'disabled' : '';
    const lastDisabled = currentPage >= totalPages ? 'disabled' : '';

    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
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
        const activeClass = page === currentPage ? 'active' : '';
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
export function applyCardSize({ width, height, containerId, cssPrefix, logTag }) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.style.setProperty(`--${cssPrefix}-card-width`, `${width}px`);
    container.style.setProperty(`--${cssPrefix}-card-height`, `${height}px`);
    console.log(`[${logTag}] Card size set to ${width}x${height}`);
}
