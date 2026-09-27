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
 * The judging is the server's (nsfw.py); the page reads what it sends.
 */
export const NSFW_UNKNOWN = 64;
export const NSFW_SFW_MAX = 3;  // PG | PG-13

/**
 * How explicit an image is - as the server judged it. Every image the page
 * shows comes through the server, which stamps mm_level on it (stamp_levels()
 * in nsfw.py). The page used to judge for itself, with a copy of the rule and
 * the words fetched to feed it. An image without a stamp is Unknown - so
 * hidden where anything unsafe is - rather than judged here on less.
 */
export function nsfwImageLevel(image) {
    return typeof image?.mm_level === 'number' ? image.mm_level : NSFW_UNKNOWN;
}

/**
 * The NSFW badge's text for an image: "X · prompt" when its prompt is what
 * made it NSFW, so an image hidden or badged against its rating says why;
 * otherwise the rating label the gallery would show.
 */
export function nsfwBadgeLabel(image, ratingLabel) {
    return image?.mm_level_from_prompt ? 'X · prompt' : ratingLabel;
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

/** How wide a card's video is asked for: twice a card, for high-DPI screens. */
export const CARD_VIDEO_WIDTH = 450;

/**
 * The URL a card should load a Civitai image or video from.
 *
 * The path segment before a Civitai image URL's file name tells its image
 * server what to send: original=true is the file exactly as uploaded,
 * width=N a copy the server makes on first request and keeps.
 *
 * A video needs the copy. An animated upload is kept as the GIF it was, even
 * under a .mp4 name: original=true sent a 17 MB GIF, which a card read as
 * video by its name and could not play, so it stayed blank. width=450 is a
 * real MP4 of about 1 MB.
 *
 * An image does not, so it is asked for as uploaded. Resizing is Civitai
 * generating a file on request; a card for every image would ask it for a
 * great many, and there is no knowing how it is throttled.
 *
 * Anything that is not a Civitai image URL with such a segment is returned
 * as it is.
 */
export function cardMediaUrl(url, type) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    const options = isVideoUrl({ url, type }) ? `width=${CARD_VIDEO_WIDTH}` : 'original=true';
    return url.replace(/\/[a-z]+=[^/]*\/([^/]+)$/i, `/${options}/$1`);
}

/**
 * The URL of a Civitai image or video exactly as uploaded - full size, where
 * cardMediaUrl() asks for a card's copy. Anything else is returned as it is.
 */
export function originalMediaUrl(url) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    return url.replace(/\/[a-z]+=[^/]*\/([^/]+)$/i, '/original=true/$1');
}

// Wan generates at 16 frames a second, and Forge Neo's Frames slider stops at
// fifteen seconds of them (modules_forge/presets.py).
export const WAN_FPS = 16;
export const WAN_MAX_FRAMES = WAN_FPS * 15 + 1;

/**
 * How many frames Wan needs for a video this many seconds long, or null if
 * the length is unknown. By length rather than by frame count: an uploader
 * who interpolated to 32 frames a second kept the length, not the count.
 * Wan's latent packs four frames to one after the first, so it takes 4n + 1
 * and would round anything else itself (processing.py).
 */
export function videoFrames(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return null;
    const frames = 4 * Math.round((seconds * WAN_FPS - 1) / 4) + 1;
    return Math.min(Math.max(frames, 1), WAN_MAX_FRAMES);
}

/** A video's size as Wan can make it: its 2x2 patches of 8x latents, 16 px. */
export function videoSize(width, height) {
    const snap = (v) => Math.max(16, Math.round(v / 16) * 16);
    return { width: snap(width), height: snap(height) };
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

/**
 * Base model names in the order a filter lists them: alphabetical, with
 * 'Other' - a catch-all - at the bottom rather than in the middle.
 */
export function sortBaseModels(values) {
    const named = values.filter(v => v !== 'Other');
    named.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    return values.includes('Other') ? named.concat('Other') : named;
}

/**
 * The one banner above a gallery: what its filters are holding back, and a
 * switch for each, on the right.
 *
 *   Showing 91 of 100 images (6 hidden due to NSFW filter, 3 hidden due to unusable prompt)
 *                                             [ ] Show NSFW (6)  [ ] Show unusable prompts (3)
 *
 * The hidden figures add up with what is shown to the total, so an image both
 * filters would hide is counted once - by the first filter to hide it, which
 * the caller decides by the order it applies them. Each switch states the same
 * number as its clause while it hides; once ticked its clause drops out, since
 * it hides nothing, and the switch says how many of its kind it now shows.
 *
 * Both tabs build their banner here, so the two cannot drift apart.
 *
 * @param {object} options
 * @param {number} options.shown - images on screen after both filters.
 * @param {number} options.total - images loaded for this version.
 * @param {string} options.bannerClass - the tab's banner class.
 * @param {string} options.labelClass - the tab's switch label class.
 * @param {boolean} [options.withSwitches=true] - false for a repeat of the
 *     sentence alone, under a long list; a second set of switches would
 *     duplicate their ids.
 * @param {Array<object>} options.switches - one per filter:
 *     id, onchange (a fixed call, never data), label, reason (for "hidden due
 *     to ..."), showing (ticked), hidden (what it hides now), count (what it
 *     would show once ticked, i.e. its kind among what the other filter lets
 *     through), and applies (false to leave it out altogether).
 */
export function renderFilterBanner({ shown, total, bannerClass, labelClass,
                                     switches, withSwitches = true }) {
    const active = switches.filter((s) => s.applies !== false);

    const clauses = active
        .filter((s) => !s.showing && s.hidden > 0)
        .map((s) => `${s.hidden} hidden due to ${s.reason}`);

    const offered = active
        .map((s) => ({ ...s, number: s.showing ? s.count : s.hidden }))
        .filter((s) => s.number > 0 || s.showing);

    if (!clauses.length && !offered.length) return '';

    const sentence = clauses.length
        ? `Showing ${shown} of ${total} images (${clauses.join(', ')})`
        : `Showing all ${total} images`;

    const controls = withSwitches && offered.length
        ? `<div class="filter-banner-switches">${offered.map((s) => `
                <label class="${labelClass}">
                    <input type="checkbox" id="${s.id}" ${s.showing ? 'checked' : ''} onchange="${s.onchange}">
                    ${s.label} (${s.number})
                </label>`).join('')}
           </div>`
        : '';

    return `<div class="${bannerClass}"><span>${sentence}</span>${controls}</div>`;
}

// ------------------------------------------------------------ resource chips
// A send puts an image's LoRAs and embeddings under the prompts as chips: a
// click puts the resource's tag in, or takes it out. Most images list their
// LoRAs as resources without a tag in the prompt, which meant finding each
// one by hand. The rules are here, apart from the page, so they can be tested.

// What Forge loads through <lora:...>, by the file's own type or Civitai's.
const LORA_TYPES = new Set(['lora', 'locon', 'loha', 'lokr', 'dora', 'lycoris', 'lycoris full']);
const EMBEDDING_TYPES = new Set(['textualinversion', 'embedding', 'embed']);

// A LoRA an image gives no weight gets this one.
export const DEFAULT_LORA_WEIGHT = 0.5;

function resourceKind(type) {
    const value = String(type || '').toLowerCase();
    if (LORA_TYPES.has(value)) return 'lora';
    if (EMBEDDING_TYPES.has(value)) return 'embedding';
    return null;
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The text a chip puts in a prompt. */
export function chipTag(chip) {
    return chip.kind === 'lora' ? `<lora:${chip.name}:${chip.weight}>` : chip.name;
}

// A LoRA's tag at any weight - one edited by hand is still that LoRA's - and
// an embedding as a word of its own, not part of a longer one.
function chipPattern(chip) {
    const name = escapeRegExp(chip.name);
    return chip.kind === 'lora' ? `<lora:${name}(?::[^>]*)?>` : `(?<![\\w-])${name}(?![\\w-])`;
}

/** Whether a prompt holds a chip's resource. */
export function promptHasChip(prompt, chip) {
    return new RegExp(chipPattern(chip), 'i').test(prompt || '');
}

/**
 * A prompt with a chip's resource taken out if it is there - every copy, and
 * the comma that separated it - or put at the end if it is not.
 */
export function toggleChip(prompt, chip) {
    const text = prompt || '';
    if (!promptHasChip(text, chip)) {
        const kept = text.replace(/[\s,]+$/, '');
        return kept ? `${kept}, ${chipTag(chip)}` : chipTag(chip);
    }
    const tag = chipPattern(chip);
    return text
        .replace(new RegExp(`\\s*,\\s*${tag}`, 'gi'), '')
        .replace(new RegExp(`${tag}\\s*,?\\s*`, 'gi'), '');
}

/** A prompt with <lora:from...> tags naming the same file as <lora:to...>. */
export function renameLoraTags(prompt, from, to) {
    if (!prompt || !from || !to || from === to) return prompt;
    return prompt.replace(new RegExp(`<lora:${escapeRegExp(from)}(?=[:>])`, 'gi'), `<lora:${to}`);
}

/**
 * The chips for an image, and the LoRA tags its prompts use under a name
 * that is not the local file's.
 *
 * Its resources come twice: Civitai's list, by version id, and the
 * infotext's, by hash and under the name the prompt used. `files` is the
 * server's answer for both (/model-manager/image-resources); a resource with
 * no file there is shown, but cannot be put in. `gallery` is the file whose
 * gallery the image is in: an image often does not list the LoRA it was
 * posted to show. One chip per file, whichever list named it, with the
 * image's weight where either gives one.
 *
 * Returns { chips, renames }: a chip is { key, kind, name, weight,
 * installed, where, title, versionId, modelId, hash }, `name` being what goes
 * in the prompt - the file's stem, which Forge always knows it by. `where` is
 * the prompt the image had it in, else the positive one. versionId, modelId
 * and hash are what the image names it by, for downloading one that is not
 * installed; any may be null. renames: [{ from, to }].
 */
export function collectResourceChips(meta, files, gallery = null) {
    const byVersion = (files && files.versions) || {};
    const byHash = (files && files.hashes) || {};
    const chips = new Map();
    const renames = [];

    const add = ({ file, type, label, weight, versionId, modelId, hash, alias }) => {
        const kind = resourceKind((file && file.file_type) || type);
        if (!kind) return;
        const name = file ? file.file_stem : label;
        if (!name) return;
        const key = file ? `file:${name.toLowerCase()}`
            : versionId ? `version:${versionId}` : `name:${name.toLowerCase()}`;
        const known = chips.get(key);
        if (known) {
            if (known.weight === null && weight !== undefined && weight !== null) known.weight = weight;
            known.versionId = known.versionId || versionId || (file && file.version_id) || null;
            known.modelId = known.modelId || modelId || null;
            known.hash = known.hash || hash || null;
        } else {
            chips.set(key, { key, kind, name, weight: weight ?? null, installed: !!file,
                             aliases: new Set(), title: label || name,
                             versionId: versionId || (file && file.version_id) || null,
                             modelId: modelId || null, hash: hash || null });
        }
        if (file && alias && alias !== name) {
            chips.get(key).aliases.add(alias);
            if (kind === 'lora') renames.push({ from: alias, to: name });
        }
    };

    if (gallery && gallery.file_stem) {
        add({ file: gallery, type: gallery.file_type, label: gallery.file_stem });
    }
    for (const r of (meta && meta.civitaiResources) || []) {
        const id = r.modelVersionId;
        add({ file: id ? byVersion[String(id)] : null, type: r.type, versionId: id, modelId: r.modelId,
              label: [r.name || r.modelName, r.modelVersionName].filter(Boolean).join(' - '),
              weight: r.weight });
    }
    for (const r of (meta && meta.resources) || []) {
        const hash = String(r.hash || '').toLowerCase();
        add({ file: hash ? byHash[hash] : null, type: r.type, label: r.name,
              weight: r.weight, alias: r.name, hash: hash || null });
    }

    let negative = (meta && meta.negativePrompt) || '';
    for (const { from, to } of renames) negative = renameLoraTags(negative, from, to);
    const result = [...chips.values()].map(({ aliases, ...chip }) => {
        chip.weight = chip.weight ?? (chip.kind === 'lora' ? DEFAULT_LORA_WEIGHT : null);
        const named = [chip.name, ...aliases].some((n) => promptHasChip(negative, { ...chip, name: n }));
        chip.where = named ? 'negative' : 'positive';
        return chip;
    });
    return { chips: result, renames };
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
 * How many columns to lay a page of cards out in, so its rows come out even.
 *
 * Use the fewest rows the width allows, then spread the cards across them:
 * ten cards with room for nine is 5 + 5, not 9 + 1, and stays 5 + 5 down to
 * room for five. Only when another row is unavoidable does it change - room
 * for four is 4 + 4 + 2, which is as even as equal columns get.
 */
export function balancedColumns(cardCount, fit) {
    if (cardCount < 1 || fit < 1) return Math.max(fit, 1);
    const rows = Math.ceil(cardCount / fit);
    return Math.ceil(cardCount / rows);
}

/**
 * Keep a card grid's rows even: cap its card list at the balanced column
 * count, so the flex-wrap layout wraps there.
 *
 * Call it after each render. The first call also starts watching the grid's
 * width, so a resize re-balances it. The card width is measured from the
 * cards, so the card size setting needs no wiring of its own; a hidden tab
 * has no width and is left as it was until it is shown.
 *
 * @param {string} gridId - the element holding the .model-grid-inner list.
 */
export function balanceGridRows(gridId) {
    const grid = document.getElementById(gridId);
    const inner = grid?.querySelector('.model-grid-inner');
    if (!inner) return;
    watchGridWidth(gridId, grid);

    const cards = inner.querySelectorAll('.model-card');
    const cardWidth = cards[0]?.getBoundingClientRect().width || 0;
    const available = grid.clientWidth;
    if (!cards.length || !cardWidth || !available) return;

    const gap = parseFloat(window.getComputedStyle(inner).columnGap) || 0;
    const fit = Math.max(1, Math.floor((available + gap) / (cardWidth + gap)));
    const cols = balancedColumns(cards.length, fit);
    inner.style.maxWidth = `${Math.ceil(cols * cardWidth + (cols - 1) * gap)}px`;
}

// One observer per grid element. Capping the inner list's width does not
// change the grid's own, so an observer cannot feed itself.
const gridObservers = new Map();   // gridId -> { grid, observer }
function watchGridWidth(gridId, grid) {
    if (gridObservers.get(gridId)?.grid === grid || typeof ResizeObserver !== 'function') return;
    gridObservers.get(gridId)?.observer.disconnect();   // the tab's markup was replaced
    let lastWidth = -1;
    const observer = new ResizeObserver(() => {
        if (grid.clientWidth === lastWidth) return;
        lastWidth = grid.clientWidth;
        balanceGridRows(gridId);
    });
    observer.observe(grid);
    gridObservers.set(gridId, { grid, observer });
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

// ------------------------------------------------------ a version to download
// Both tabs show a version that is not in the library the same way: what it
// is, what it costs, which of its files a download produces. The Civitai
// Browser shows every version of a search result; the Model Manager shows the
// versions of a local model that were never downloaded.

/** Bytes as a version's files read: "1.99 GB". */
export function formatBytes(bytes) {
    if (!bytes) return 'Unknown';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return bytes + ' B';
}

/** A date as a version's details read it: "Mar 1, 2025". */
export function formatDay(dateStr) {
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

/**
 * Describe a version's paywall, or '' when it is free.
 *
 * `paid_access` is attached by the backend: Civitai leaves `availability`
 * as "Public" for paid versions, so the field is the only marker.
 */
export function paidAccessLabel(version) {
    const paid = version?.paid_access;
    if (!paid) return '';
    if (paid.permanent) return 'Paid';
    return paid.ends_at ? `Early Access until ${formatDay(paid.ends_at)}` : 'Early Access';
}

export function isPaid(version) {
    return !!version?.paid_access;
}

/**
 * Index of the file a download of this version will produce.
 *
 * Mirrors DownloadService.pick_file_index: files[0] is often the full
 * fp32 weights, roughly twice the size of the pruned file Civitai marks
 * primary, so the primary one is the default rather than the first.
 */
export function primaryFileIndex(version) {
    const files = version?.files || [];
    const primary = files.findIndex(f => f.primary);
    return primary === -1 ? 0 : primary;
}

/**
 * How a file reads in the picker: "pruned fp16 - 1.99 GB".
 *
 * metadata carries format/size/fp for model files; anything without it
 * (a VAE, a config, training data) falls back to its name and type.
 */
export function describeFile(file) {
    const meta = file?.metadata || {};
    const parts = [meta.size, meta.fp].filter(Boolean);

    if (!parts.length) {
        const type = file?.type && file.type !== 'Model' ? file.type : '';
        parts.push(type || file?.name || 'File');
    } else if (file?.type && file.type !== 'Model') {
        parts.push(file.type);
    }

    const size = file?.sizeKB ? formatBytes(file.sizeKB * 1024) : '';
    return size ? `${parts.join(' ')} - ${size}` : parts.join(' ');
}

/**
 * The Download button and, when there is a choice, the file picker.
 *
 * `prefix` is the tab's: the button is `<prefix>_download_btn` and calls
 * window.<prefix>Download(modelId, versionId, fileId), the picker calls
 * window.<prefix>SelectFile(index). A paid version answers the download URL
 * with 401/403 until it is bought on Civitai, so it is not offered.
 */
export function renderDownloadControls({ prefix, modelId, version, fileIndex, owned }) {
    const files = version?.files || [];
    const file = files[fileIndex];
    const paidLabel = paidAccessLabel(version);

    let button = '';
    if (owned) {
        button = `<button class="mm-btn secondary" disabled>Already Owned</button>`;
    } else if (paidLabel) {
        button = `<button class="mm-btn secondary" disabled `
            + `title="Buy it on Civitai first">${escapeHtml(paidLabel)}</button>`;
    } else if (file) {
        button = `<button class="mm-btn primary" id="${prefix}_download_btn" `
            + `onclick="window.${prefix}Download(${safeId(modelId)}, ${safeId(version?.id)}, ${safeId(file?.id)})">Download</button>`;
    }

    // Only worth a control when there is something to choose between.
    const picker = files.length > 1
        ? `<select class="${prefix}-file-select" onchange="window.${prefix}SelectFile(this.value)"
                   title="Which file to download">
             ${files.map((f, i) => `<option value="${i}" ${i === fileIndex ? 'selected' : ''}
                    title="${escapeHtml(f.name || '')}">${escapeHtml(describeFile(f))}`
                    + `${f.primary ? ' (default)' : ''}</option>`).join('')}
           </select>`
        : '';

    return `${button}\n${picker}`;
}

/**
 * Point the File and File Size rows and the Download button at another file.
 *
 * In place rather than re-rendering the panel, which would scroll the reader
 * back to the top. The rows are `<prefix>_file_name` and `<prefix>_file_size`.
 */
export function showChosenFile(prefix, modelId, version, file) {
    const nameCell = document.getElementById(`${prefix}_file_name`);
    if (nameCell) nameCell.textContent = file.name || 'Unknown';

    const sizeCell = document.getElementById(`${prefix}_file_size`);
    if (sizeCell) {
        sizeCell.textContent = file.sizeKB ? formatBytes(file.sizeKB * 1024) : 'Unknown';
    }

    const button = document.getElementById(`${prefix}_download_btn`);
    if (button) {
        button.setAttribute('onclick',
            `window.${prefix}Download(${safeId(modelId)}, ${safeId(version?.id)}, ${safeId(file.id)})`);
    }
}

// ---------------------------------------------------------------- downloads
// A download takes minutes, and neither tab should make anyone stay in it to
// see how it is going. So there is one list, polled once, and each tab draws
// it in a panel of its own: a download started in either shows in both.
//
// Each tab imports this module under its own ?mtime (see the top of either
// tab script), so the two get separate copies of it and module state would
// not be shared. The list lives on window instead.

/**
 * Tell the WebUI about newly downloaded files.
 *
 * Downloading writes the file but the WebUI has already listed its model
 * directories, so a new checkpoint does not appear in the native dropdown
 * until something re-scans. Click the refresh control next to that
 * dropdown - the same one a user would press. Forge and Forge Neo both
 * expose it as #forge_refresh_checkpoint, and both hand back only new
 * choices, so the current selection is left alone.
 */
export function refreshWebUiModelList() {
    const root = (typeof gradioApp === 'function') ? gradioApp() : document;
    const refreshButton = root.querySelector('#forge_refresh_checkpoint');

    if (refreshButton) {
        refreshButton.click();
        console.log('[ModelManager] Refreshed the WebUI model list');
    } else {
        console.warn('[ModelManager] Could not find the checkpoint refresh button; '
            + 'the new model may need a manual refresh');
    }
}

const DOWNLOAD_STATUS_TEXT = {
    downloading: 'Downloading', pending: 'Queued', finishing: 'Adding to library',
    complete: 'Complete', error: 'Error', cancelled: 'Cancelled',
};

/** One download, as a panel shows it. Classes are the tab's own: `<prefix>-download-*`. */
function renderDownloadItem(dl, prefix) {
    const status = dl.status || 'pending';
    const percent = dl.percent?.toFixed(1) || 0;
    const downloaded = formatBytes(dl.downloaded_bytes || 0);
    const total = formatBytes(dl.total_bytes || 0);
    // finishing: on disk, being added to the library. Not complete until
    // it is, so that Complete and "Show in MM" arrive together.
    const showProgress = status === 'downloading' || status === 'pending' || status === 'finishing';
    const showCancel = status === 'downloading' || status === 'pending';
    const showDismiss = status === 'complete' || status === 'error' || status === 'cancelled';
    const p = prefix;

    return `
        <div class="${p}-download-item ${status}">
            <div class="${p}-download-item-header">
                <div class="${p}-download-name" title="${escapeHtml(dl.file_name || 'Unknown')}">${escapeHtml(dl.file_name || 'Unknown')}</div>
                <span class="${p}-download-status-badge ${status}">${DOWNLOAD_STATUS_TEXT[status] || status}</span>
            </div>
            ${showProgress ? `
                <div class="${p}-download-progress">
                    <div class="${p}-download-bar" style="width: ${status === 'pending' || status === 'finishing' ? 100 : percent}%"></div>
                </div>
            ` : ''}
            <div class="${p}-download-info">
                <span class="${p}-download-percent">
                    ${status === 'downloading' ? `${percent}% - ${downloaded} / ${total}` : ''}
                    ${status === 'pending' ? 'Waiting...' : ''}
                    ${status === 'finishing' ? `Adding to library... ${total}` : ''}
                    ${status === 'complete' ? `${total}` : ''}
                    ${status === 'error' ? escapeHtml(dl.error || 'Download failed') : ''}
                    ${status === 'cancelled' ? 'Download cancelled' : ''}
                </span>
                <div class="${p}-download-actions">
                    ${showCancel ? `
                        <button class="mm-btn mm-btn-small danger" onclick="window.mmCancelDownload(${safeId(dl.version_id)})">Cancel</button>
                    ` : ''}
                    ${showDismiss ? `
                        <button class="mm-btn mm-btn-small secondary" onclick="window.mmDismissDownload(${safeId(dl.version_id)})">Dismiss</button>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

function createDownloads() {
    const items = {};          // version id -> the server's progress
    const panels = new Set();  // tab prefixes with a panel on the page
    const completed = [];      // callbacks, each given a download once it is in the library
    const batchDone = [];      // callbacks, once nothing is left running
    let poll = null;
    let landed = false;        // a download reached the library in this batch

    const running = (dl) => dl.status === 'downloading' || dl.status === 'pending'
        || dl.status === 'finishing' || (dl.status === 'complete' && !dl.synced);

    function render() {
        const downloads = Object.values(items);
        // Downloading first, then queued, then whatever has finished.
        const order = { downloading: 0, finishing: 0, pending: 1, complete: 2, error: 3, cancelled: 4 };
        downloads.sort((a, b) => (order[a.status] ?? 5) - (order[b.status] ?? 5));

        const active = downloads.filter(d => d.status === 'downloading' || d.status === 'finishing').length;
        const queued = downloads.filter(d => d.status === 'pending').length;
        const finished = downloads.filter(d => ['complete', 'error', 'cancelled'].includes(d.status)).length;
        const summary = [active && `${active} downloading`, queued && `${queued} pending`,
                         finished && `${finished} finished`].filter(Boolean).join(', ')
            || `${downloads.length} total`;

        for (const prefix of panels) {
            const panel = document.getElementById(`${prefix}_downloads`);
            const list = document.getElementById(`${prefix}_download_list`);
            const summaryEl = document.getElementById(`${prefix}_downloads_summary`);
            if (panel) panel.style.display = downloads.length ? 'block' : 'none';
            if (!list || !downloads.length) continue;
            if (summaryEl) summaryEl.textContent = summary;
            list.innerHTML = downloads.map(dl => renderDownloadItem(dl, prefix)).join('');
        }
    }

    async function tick() {
        try {
            const result = await apiCall({ endpoint: '/model-manager/civitai/download/progress' });
            if (!result.success || !result.downloads) return;
            for (const dl of result.downloads) {
                const prev = items[dl.version_id];
                // The file lands well before its database row does; until
                // `synced` the model is not in the library yet.
                const arrived = dl.status === 'complete' && dl.synced && !(prev && prev.synced);
                items[dl.version_id] = dl;
                if (arrived) {
                    landed = true;
                    for (const callback of completed) {
                        try { callback(dl); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
            render();

            if (!Object.values(items).some(running)) {
                clearInterval(poll);
                poll = null;
                // Once per batch - re-scanning walks every model directory,
                // so there is no point doing it per file.
                if (landed) {
                    landed = false;
                    refreshWebUiModelList();
                    for (const callback of batchDone) {
                        try { callback(); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
        } catch (e) {
            console.error('[ModelManager] Download poll error:', e);
        }
    }

    const store = {
        /** Draw the list in this tab's panel: `<prefix>_downloads` and the ids inside it. */
        addPanel: (prefix) => { panels.add(prefix); render(); },
        onComplete: (callback) => { completed.push(callback); },
        onBatchDone: (callback) => { batchDone.push(callback); },

        /** Follow a download the server has accepted. */
        track: (progress) => {
            if (!progress || progress.version_id == null) return;
            items[progress.version_id] = progress;
            render();
            if (!poll) poll = setInterval(tick, 1000);
        },

        /** Ask for a version, and follow it. Returns the server's answer. */
        start: async function start(modelId, versionId, fileId) {
            const form = new FormData();
            if (modelId) form.append('model_id', modelId);
            form.append('version_id', versionId);
            // Omitted when unknown, which leaves the backend on the primary.
            if (fileId !== undefined && fileId !== null) form.append('file_id', fileId);
            const response = await fetch('/model-manager/civitai/download', { method: 'POST', body: form });
            const result = await response.json();
            if (result.success && result.progress) store.track(result.progress);
            return result;
        },

        cancel: async function cancel(versionId) {
            try {
                const form = new FormData();
                form.append('version_id', versionId);
                await fetch('/model-manager/civitai/download/cancel', { method: 'POST', body: form });
            } catch (e) {
                console.error('[ModelManager] Cancel error:', e);
            }
        },

        dismiss: (versionId) => {
            delete items[versionId];
            render();
        },

        get: (versionId) => items[versionId],
    };

    window.mmCancelDownload = (versionId) => store.cancel(versionId);
    window.mmDismissDownload = (versionId) => store.dismiss(versionId);
    return store;
}

/** The downloads both tabs show. See above. */
export function downloads() {
    if (!window.mmDownloads) window.mmDownloads = createDownloads();
    return window.mmDownloads;
}
