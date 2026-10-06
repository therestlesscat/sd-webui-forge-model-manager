/**
 * Civitai's images and videos on the page: which copy to load for a width,
 * what to fall back to when it does not load, the shape held before it does,
 * and loading them as they come into view.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');

// Shared across both tabs - only one tab renders images at a time
export let lazyMediaObserver = null;

/**
 * The widths Civitai's image server makes copies at. Asked for a width in
 * between, it sends the next one up - 128 to 320 all came back 320 wide,
 * 400 and 450 came back 450 - so these are the only sizes there are
 * (measured on 8 images, 28 September 2026). It enlarges as readily: an
 * 832-wide upload asked for at 1600 came back 1600 wide.
 */
export const CIVITAI_WIDTHS = [320, 450, 512, 800, 1200, 1600, 2200];

/** The segment before a Civitai image URL's file name: what to send. */
const CIVITAI_OPTIONS = /\/[a-z]+=[^/]*\/([^/]+)$/i;

/** The smallest of Civitai's widths at least `pixels` wide. */
export function civitaiWidth(pixels) {
    const needed = Math.ceil(Number(pixels) || 0);
    return CIVITAI_WIDTHS.find((width) => width >= needed) || CIVITAI_WIDTHS[CIVITAI_WIDTHS.length - 1];
}

/** How many image pixels show `cssWidth` CSS pixels sharply on this screen - twice as many on a 2x one. */
function screenPixels(cssWidth) {
    const density = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    return (Number(cssWidth) || 0) * density;
}

/**
 * The URL to load a Civitai image or video from, to show it `cssWidth` CSS
 * pixels wide - or, given `pixels`, that many image pixels whatever the
 * screen: a copy at the width civitaiWidth() picks, not the upload.
 *
 * The segment before the file name tells Civitai's image server what to
 * send: original=true is the file as uploaded, width=N a copy it makes on
 * the first request and keeps. Originals ran from 107 KB to 2.9 MB where a
 * 450-wide copy was 86 KB, and a gallery page holds up to 100 of them.
 * Images were asked for as uploaded until 0.30.1, lest Civitai throttle so
 * many copies; 130 requests at five a second met no limit, and a copy that
 * fails to load falls back to the upload (mediaFallback).
 *
 * An image is never asked for wider than it was uploaded - Civitai would
 * enlarge it, larger and no sharper - but as uploaded instead. A video is
 * always asked for as a copy: an animated upload stays the GIF it was, even
 * under a .mp4 name, and original=true sent a 17 MB GIF that a card read as
 * video by its name, could not play, and left blank. A copy is a real MP4.
 *
 * Anything that is not a Civitai image URL with such a segment is returned
 * as it is.
 */
export function sizedMediaUrl(url, { cssWidth, pixels = null, originalWidth = null, type = null } = {}) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    const width = civitaiWidth(pixels ?? screenPixels(cssWidth));
    if (!isVideoUrl({ url, type }) && originalWidth && width >= Number(originalWidth)) {
        return originalMediaUrl(url);
    }
    return url.replace(CIVITAI_OPTIONS, `/width=${width}/$1`);
}

/**
 * A still of a Civitai video: its first frame as a JPEG, shown until it is
 * played. Civitai makes these at the video's own size, whatever width is
 * asked - 92 and 232 KB for two videos of 0.9 and 3.6 MB.
 */
export function videoStillUrl(url) {
    if (!url || !url.includes('image.civitai.com')) return '';
    return url.replace(CIVITAI_OPTIONS, '/anim=false/$1');
}

/**
 * What the viewer plays for a Civitai video: a copy no wider than the video -
 * Civitai would enlarge it - nor than the viewer shows it, on this screen.
 * The original upload often keeps its index at the end of the file, so the
 * browser fetched the end, then the start, before a frame - about three of
 * Civitai's ~0.6 s answers; every copy keeps it at the start, and was 45-93%
 * of the original's size. Not Civitai's (your own generations): as it is.
 *
 * @param {string} url - the video's address
 * @param {{width?: number, height?: number}} video - its size, as Civitai gives it
 * @param {{width?: number, height?: number}} box - the viewer's frame, in CSS pixels
 */
export function viewerVideoUrl(url, video = {}, box = {}) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    const own = Number(video.width) || 0;
    const aspect = own && Number(video.height) ? own / Number(video.height) : 0;
    // As wide as it is drawn: the frame's width, or its height at the video's shape.
    const drawn = box.width
        ? Math.min(box.width, aspect && box.height ? box.height * aspect : box.width) : 0;
    const wanted = drawn ? screenPixels(drawn) : own || CIVITAI_WIDTHS[CIVITAI_WIDTHS.length - 1];
    // A width Civitai already serves - but never past the video's own.
    let width = civitaiWidth(wanted);
    if (own && width > own) width = own;
    return url.replace(CIVITAI_OPTIONS, `/width=${Math.round(width)}/$1`);
}

/**
 * A video card's poster: its still, through the server's check - which
 * redirects to it when it is an image, and answers 404 when Civitai serves
 * the whole video in its place (a 32 MB MP4 for 1 video in 80), so the
 * browser does not download that for a preview it cannot draw. The browser
 * remembers each answer (/model-manager/video-still, api/images.py).
 */
export function videoPosterUrl(url) {
    const still = videoStillUrl(url);
    return still ? `/model-manager/video-still?url=${encodeURIComponent(still)}` : '';
}

/**
 * How wide a gallery card's image is drawn, in CSS pixels, when it cannot be
 * measured: style.css's --mm-card-image-width on a wide window.
 */
export const GALLERY_IMAGE_WIDTH = 200;

/**
 * How wide a gallery card's image is drawn in this container, in CSS pixels,
 * measured rather than assumed: the stylesheet decides it, and narrows it -
 * 150px under 900px, the full width under 600px - where a fixed number here
 * would drift from it. A card is drawn out of sight, measured and removed.
 * GALLERY_IMAGE_WIDTH when nothing can be measured: a hidden container, or
 * no layout at all.
 */
export function galleryImageWidth(container) {
    if (!container || typeof container.appendChild !== 'function') return GALLERY_IMAGE_WIDTH;
    const probe = document.createElement('div');
    probe.className = 'mm-image-card';
    probe.style.cssText = 'position:absolute;visibility:hidden;left:0;right:0;pointer-events:none';
    probe.innerHTML = '<div class="mm-image-left"></div>';
    container.appendChild(probe);
    const width = probe.firstElementChild?.getBoundingClientRect?.().width || 0;
    probe.remove();
    return width > 0 ? width : GALLERY_IMAGE_WIDTH;
}

/** How wide a model card is drawn when a tab has not said otherwise. */
const DEFAULT_CARD_WIDTH = 200;

/** The URL a model card loads its Civitai image or video from, at the card's width. */
export function cardMediaUrl(url, type, cardWidth = DEFAULT_CARD_WIDTH, originalWidth = null) {
    return sizedMediaUrl(url, { cssWidth: cardWidth, originalWidth, type });
}

/** What a gallery image shows when it does not load. */
export const IMAGE_PLACEHOLDER_SVG = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200'%3E%3Crect fill='%23222933' width='320' height='200'/%3E%3Cg fill='%236b7280'%3E%3Cpath d='M130 78h60v44h-60z'/%3E%3Cpath d='M92 132l34-30 28 24 18-14 56 44H92z'/%3E%3Ccircle cx='208' cy='82' r='10'/%3E%3C/g%3E%3Ctext x='160' y='176' text-anchor='middle' fill='%239ca3af' font-size='14'%3EImage unavailable%3C/text%3E%3C/svg%3E";

/**
 * The attributes that make a Civitai image or video fall back when a copy
 * does not load: to the upload, then to the placeholder, if one is given.
 */
export function mediaFallback(original, placeholder = '') {
    return `data-original="${escapeHtml(original || '')}" data-placeholder="${escapeHtml(placeholder)}"`;
}

/**
 * The shape a gallery image or video holds before it loads, from the size
 * Civitai gives: the lazy placeholder is a 1x1 GIF, drawn at the card's width
 * as a square, and a portrait image grew by half its width when it arrived -
 * moving everything below it, and a scroll to a card on the way stopped short
 * by a card or two. Nothing, when the size is not known.
 */
export function mediaShape(img) {
    const width = Number(img?.width), height = Number(img?.height);
    return width > 0 && height > 0 ? `style="aspect-ratio: ${width} / ${height}"` : '';
}

/**
 * A copy that did not load falls back, by those attributes: one listener for
 * the page, on the way down, as a load's error does not bubble. It was an
 * inline onerror calling a window global (#95). The placeholder is the last:
 * one that fails too is left.
 */
export function fallBack(node) {
    if (!node?.hasAttribute?.('data-original') || node.dataset.fellBack) return;
    const original = node.getAttribute('data-original');
    if (original && node.getAttribute('src') !== original) {
        node.setAttribute('src', original);
        if (node.tagName === 'VIDEO') node.load();
        return;
    }
    node.dataset.fellBack = 'true';
    const placeholder = node.getAttribute('data-placeholder');
    if (placeholder && node.tagName === 'IMG') node.setAttribute('src', placeholder);
}

/** The page's one fallback listener, started by the first tab that shows media (#182). */
export function start() {
    if (typeof document === 'undefined' || typeof document.addEventListener !== 'function'
            || globalThis.__mmMediaFallback) return;
    globalThis.__mmMediaFallback = true;
    document.addEventListener('error', (event) => fallBack(event.target), true);
}

/**
 * The URL of a Civitai image or video exactly as uploaded - full size, where
 * cardMediaUrl() asks for a card's copy. Anything else is returned as it is.
 */
export function originalMediaUrl(url) {
    if (!url || !url.includes('image.civitai.com')) return url || '';
    return url.replace(CIVITAI_OPTIONS, '/original=true/$1');
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

export function setupLazyMedia(container) {
    if (!container) return;

    const lazyNodes = container.querySelectorAll('.mm-lazy-media[data-src]');
    if (lazyNodes.length === 0) return;

    const loadNode = (node) => {
        const src = node.getAttribute('data-src');
        if (!src) return;
        // A video's still, lazily as well: every video's at once was one
        // request per card before any came into view.
        const poster = node.getAttribute('data-poster');
        if (poster) {
            node.setAttribute('poster', poster);
            node.removeAttribute('data-poster');
        }
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
 * A Civitai video's copy for Send to read its length and first frame from, a
 * fixed 450 pixels wide whatever the screen: what Send used before cards
 * were sized to it. A copy, not the upload: see sizedMediaUrl().
 */
export function videoCopyUrl(img) {
    return sizedMediaUrl(img.url, { pixels: 450, type: img.type });
}
