/**
 * A gallery of images, as both tabs draw it: the bar while it loads, the
 * filter banner and its switches, each page's separator and note, and its
 * pages kept and paged through (createPagedGallery).
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');
const { setupLazyMedia } = await shared('media.mjs');

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

// ------------------------------------------------------------ a gallery's pages
// The Model Manager's gallery and the Civitai Browser's are lists of pages,
// paged through the same way, and each kept them in its own code (#115) -
// which had drifted. Each tab now makes one of these, naming its ids, how it
// draws a card and its banner, and keeps only how it fetches a page.

/**
 * A gallery's pages: the images drawn, every page's in turn; each page loaded,
 * with where its images start and its own counts, for its note; why the last
 * page asked for did not come; and whether Load More is under way.
 *
 * `showing()` says whether the list is on screen - the Model Manager's is not
 * while it shows your generations; `redraw()` draws the gallery whole, which
 * adding a page falls back on when its list is not there to add to; and
 * `afterDraw(images)` runs once cards are drawn.
 */
const always = () => true;
const nothing = () => {};

export function createPagedGallery({ containerId, bannerClass, loadMoreId, loadMoreCall, card, bannerHtml,
                                     showing = always, redraw, afterDraw = nothing }) {
    const gallery = {
        images: [],
        pages: [],
        error: '',
        loading: false,

        /** The page last added, if any. */
        last: () => gallery.pages[gallery.pages.length - 1],

        /** Take a page's answer: the list starts again with it, or it goes at the end. */
        take: (answer, { append, number = 1 }) => {
            const images = answer.images || [];
            const page = { ...(answer.page || { number }), first: append ? gallery.images.length : 0 };
            if (append) {
                gallery.images = gallery.images.concat(images);
                gallery.pages.push(page);
            } else {
                gallery.images = images;
                gallery.pages = [page];
            }
            return { page, images };
        },

        /**
         * One page of the list: its separator, after the first, its cards, and
         * its note, which says what that page held - what it shows, and what
         * each switch hid - so a page showing few images, or none, says why.
         * `images` are the page's shown images; their cards take their places
         * in the gallery's images.
         */
        pageHtml: (page, images) => {
            const cards = images.map((img, i) => card(img, page.first + i)).filter(Boolean).join('');
            return (page.number > 1 ? pageSeparator(page.number) : '') + cards + pageNoteHtml(page);
        },

        /** Every page, and the foot under them. */
        pagesHtml: () => {
            return `<div class="model-images-list">${gallery.pages.map((page) =>
                gallery.pageHtml(page, gallery.images.slice(page.first, page.first + (page.shown || 0)))).join('')}</div>
        <div class="mm-images-footer">${gallery.footerHtml()}</div>`;
        },

        /** The foot of the list: why a page did not come, and Load More while there is a next. */
        footerHtml: () => {
            const last = gallery.last();
            const error = gallery.error
                ? `<div class="mm-page-note">${escapeHtml(gallery.error)}</div>` : '';
            if (!last || !last.more) return error;
            return `${error}<div class="mm-load-more">
             <button class="mm-btn secondary" id="${loadMoreId}" onclick="window.${loadMoreCall}()"
                     ${gallery.loading ? 'disabled' : ''}>
               ${gallery.loading ? 'Loading...' : 'Load More Images'}
             </button>
           </div>`;
        },

        /**
         * Add a page to the end of the list: what Load More brings. The cards
         * already drawn are left alone - the whole gallery used to be drawn
         * again, and every image above came back as a blank square until it
         * reloaded, moving the page under the reader. Only the banner and the
         * foot are drawn again. Anything else - a filter, another model - draws
         * it all.
         */
        append: (page, images) => {
            const list = document.getElementById(containerId)?.querySelector('.model-images-list');
            if (!list || !showing() || !list.querySelector('.mm-page-note')) {
                redraw();
                return;
            }
            list.insertAdjacentHTML('beforeend', gallery.pageHtml(page, images));
            gallery.refreshChrome();
            setupLazyMedia(list);
            afterDraw(images);
        },

        /** Draw again what sums the gallery up - the banner, the foot - and not the images. */
        refreshChrome: () => {
            const container = document.getElementById(containerId);
            if (!container || !showing()) return;
            const banner = container.querySelector(`.${bannerClass}`);
            if (banner) banner.outerHTML = bannerHtml();
            const footer = container.querySelector('.mm-images-footer');
            if (footer) footer.innerHTML = gallery.footerHtml();
        },

        /**
         * Load More: the next page, once at a time - the button says so, and
         * takes no clicks meanwhile. `loadPage(number)` fetches it, adds it
         * (take, append), and says in `error` why it did not come.
         */
        more: async function more(loadPage) {
            const last = gallery.last();
            if (gallery.loading || !last || !last.more) return;
            gallery.loading = true;
            gallery.error = '';
            gallery.refreshChrome();
            try {
                await loadPage(last.number + 1);
            } catch (e) {
                console.error('[ModelManager] Load more error:', e);
                gallery.error = `Page ${last.number + 1} could not be loaded: ${e.message}`;
            } finally {
                gallery.loading = false;
                gallery.refreshChrome();
            }
        },
    };
    return gallery;
}
