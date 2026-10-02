/**
 * A gallery of images, as both tabs draw it: the bar while it loads, the
 * filter banner and its switches, and each page's separator and note.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');

// ------------------------------------------------------ loading a gallery
// A model's images come from Civitai through the server, and take seconds;
// nothing used to show meanwhile - the old gallery stayed, and a switch
// changed looked ignored. So, from the moment it starts: a bar at the top of
// the gallery, over an empty one saying so when a model or version is opened,
// or over the current images, dimmed and not answering, when a switch changes.
// Both tabs' galleries.

const LOADING_BAR = '<div class="mm-loading-bar" role="progressbar" aria-label="Loading images"></div>';

/** A gallery about to be replaced: cleared, saying it is loading. */
export function showGalleryLoading(containerId, text = 'Loading images...') {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.classList.remove('mm-gallery-loading');
    container.innerHTML = `${LOADING_BAR}<div class="mm-images-loading">${escapeHtml(text)}</div>`;
    container.style.display = 'block';
}

/** A gallery as it is, while its first page is fetched again: dimmed, its switches off. */
export function dimGalleryWhileLoading(containerId, on) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.classList.toggle('mm-gallery-loading', on);
    container.querySelector(':scope > .mm-loading-bar')?.remove();
    if (on) container.insertAdjacentHTML('afterbegin', LOADING_BAR);
    container.querySelectorAll('input[type="checkbox"]').forEach((box) => { box.disabled = on; });
}

/**
 * The gallery's filter banner: one sentence, and a switch for each filter.
 *
 *   300 images stored · 168 match the filters (100 shown) · 132 hidden due to unusable prompt
 *                                             [ ] Show unusable prompts (132)
 *
 * Three numbers, kept apart because they were once confused: what is stored,
 * what the filters let through, and what is on screen - a page at a time, so
 * fewer than match until Show More or the page buttons bring the rest. It
 * used to read "Showing 168 of 300", with 100 on screen.
 *
 * The hidden figures add up with what matches to the total, so an image both
 * filters would hide is counted once - by the first filter to hide it, which
 * the caller decides by the order it applies them. Each switch states the same
 * number as its clause while it hides; once ticked its clause drops out, since
 * it hides nothing, and the switch says how many of its kind it now shows. A
 * switch with nothing to hide or show is left out.
 *
 * Drawn whenever anything is stored, filtered or not, since it is where the
 * counts are; it stays in sight as the gallery scrolls. It used to appear only
 * while a filter hid something, and the Civitai Browser drew it again under
 * the list, before it stuck. Both tabs build it here, so the two cannot drift
 * apart.
 *
 * @param {object} options
 * @param {number} options.matching - images the filters let through, loaded or not.
 * @param {number} options.total - images stored, or loaded.
 * @param {number} options.onScreen - images drawn now.
 * @param {string} [options.word] - what `total` counts: 'stored' in the library,
 *     'loaded' from Civitai in the Civitai Browser, which keeps nothing.
 * @param {string} options.bannerClass - the tab's banner class.
 * @param {string} options.labelClass - the tab's switch label class.
 * @param {Array<object>} options.switches - one per filter:
 *     id, onchange (a fixed call, never data), label, reason (for "hidden due
 *     to ..."), showing (ticked), hidden (what it hides now), count (what it
 *     would show once ticked, i.e. its kind among what the other filter lets
 *     through), total (if given, the number on the switch whatever either
 *     switch says - the prompt switch's, every image with an unusable
 *     prompt), note (a word on what decides it), and applies (false to leave
 *     it out altogether).
 * @param {number} [options.both] - images both switches hide: counted in
 *     neither's `hidden`, so each switch's number is what it alone hides and
 *     does not change when it is flipped - and said as a clause of its own.
 */
export function renderFilterBanner({ matching, total, onScreen, word = 'stored', bannerClass,
                                     labelClass, switches, both = 0 }) {
    if (!total) return '';
    const active = switches.filter((s) => s.applies !== false);

    const clauses = active
        .filter((s) => !s.showing && s.hidden > 0)
        .map((s) => `${s.hidden} hidden due to ${s.reason}`);
    if (both > 0) clauses.push(`${both} hidden due to both`);

    const offered = active
        .map((s) => ({ ...s, number: s.total ?? (s.showing ? s.count : s.hidden) }))
        .filter((s) => s.number > 0 || s.showing);

    const counted = `${total} ${total === 1 ? 'image' : 'images'} ${word}`
        + ` · ${matching} match the filters (${onScreen} shown)`
        + (clauses.length ? ` · ${clauses.join(', ')}` : '');
    // A switch can carry a note on what decides it: the NSFW one, while a
    // trained model does.
    const notes = offered.map((s) => s.note).filter(Boolean);
    const sentence = counted + notes.map((n) => `<small class="filter-banner-note">${escapeHtml(n)}</small>`).join('');

    const controls = offered.length
        ? `<div class="filter-banner-switches">${offered.map((s) => `
                <label class="${labelClass}">
                    <input type="checkbox" id="${s.id}" ${s.showing ? 'checked' : ''} onchange="${s.onchange}">
                    ${s.label} (${s.number})
                </label>`).join('')}
           </div>`
        : '';

    return `<div class="${bannerClass} filter-banner-sticky"><span>${sentence}</span>${controls}</div>`;
}

// -------------------------------------------------------------- gallery pages
// A gallery is a list of pages, each a slice of what is stored before the
// switches filter it (model_manager/gallery.py). Both tabs draw a page the
// same way: its separator, after the first, its cards, and its note.

/** Where a page starts in the continuous list: a rule with its number on it. */
export function pageSeparator(page) {
    return `<div class="mm-page-separator" role="separator"><span>Page ${page}</span></div>`;
}

/**
 * What a page held, under its images: "Displaying 30 images for page 1 ·
 * 50 hidden due to NSFW filter · 20 hidden due to unusable prompt · 2 hidden
 * due to both", the switches' own words for why. The last page says there is no more - `end`,
 * which a gallery that does not come from Civitai leaves out - and a page
 * Civitai failed to fill says so.
 */
export function pageNoteHtml(page, { end = 'no more images on Civitai' } = {}) {
    const shown = page.shown || 0;
    const parts = [`Displaying ${shown} ${shown === 1 ? 'image' : 'images'} for page ${page.number}`];
    if (page.hidden_nsfw) parts.push(`${page.hidden_nsfw} hidden due to NSFW filter`);
    if (page.hidden_promptless) parts.push(`${page.hidden_promptless} hidden due to unusable prompt`);
    if (page.hidden_both) parts.push(`${page.hidden_both} hidden due to both`);
    if (page.error) parts.push(`more could not be fetched from Civitai: ${page.error}`);
    else if (!page.more && end) parts.push(end);
    return `<div class="mm-page-note">${escapeHtml(parts.join(' · '))}</div>`;
}
