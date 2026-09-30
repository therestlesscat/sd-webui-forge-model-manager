// The Civitai Browser's gallery, a page at a time, as the Model Manager's.
//
// A page is Civitai's next page - pages of 3 here - read live, from the
// cursor the last one ended at, before the switches, which only decide which
// of its images are drawn. Nothing is kept on the server; the banner adds up
// the pages loaded. Load More adds
// the next page after its separator, with a note of what it held, leaving the
// cards already drawn alone. It used to fetch 10 at a time, page what passed
// the switches, and say what a download brought beside the button: three
// clicks on one model stored 30 images, 26 of them R or above, and looked
// like clicks that did nothing.
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const image = (id, level) => ({
    id, url: `https://example.invalid/${id}.jpeg`, nsfwLevel: level, browsingLevel: level,
    mm_level: level, mm_level_from_prompt: false,
    meta: { prompt: 'a lighthouse by the sea' },
});
// Cached: two safe, one explicit. Civitai has three more: one safe, two X.
const cached = [image(1, 1), image(2, 1), image(3, 8)];
const civitai = [image(100, 1), image(101, 16), image(102, 8)];
let civitaiDown = false;       // Civitai answering 503, as it does in an outage
const galleryAsks = [];

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, gallery_hide_nsfw: true,
                                                hide_promptless_images: true }) };
    }
    if (href.includes('/images')) {
        galleryAsks.push(new URL(href, 'http://webui').searchParams);
        const page = Number(new URL(href, 'http://webui').searchParams.get('page') || 1);
        if (page * 3 > cached.length && civitai.length) {
            if (civitaiDown) {
                return { ok: false, status: 500, json: async () => ({
                    success: false, error: 'Civitai: Image search is temporarily overloaded (503)' }) };
            }
            cached.push(...civitai.splice(0));
        }
        return { ok: true, json: async () => browserGalleryAnswer(href, cached, {},
                                                                  { more: civitai.length > 0, size: 3 }) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'Model 7', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: 70, images: cached.slice(0, 1), files: [] }] }] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const cards = () => document.querySelectorAll('#cb_images .mm-image-card');
const notes = () => Array.from(document.querySelectorAll('#cb_images .model-images-list .mm-page-note'))
    .map((n) => n.textContent.trim());
const separators = () => Array.from(document.querySelectorAll('#cb_images .mm-page-separator'))
    .map((s) => s.textContent.trim());
const sentence = () => (document.querySelector('#cb_images .cb-nsfw-warning span')?.textContent || '').trim();
// An empty cursor is left out of the request altogether: from the start.
const asked = (from) => galleryAsks.slice(from).map((p) => [p.get('page'), p.get('cursor') ?? '']);
const footer = () => (document.querySelector('#cb_images .mm-images-footer')?.textContent || '')
    .replace(/\s+/g, ' ').trim();

$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
await window.cbOpenModel(0);
await waitFor('the gallery', () => cards().length > 0);

check('page 1 shows its safe images, and says what it held',
      [cards().length, notes()], [2, ['Displaying 2 images for page 1 · 1 hidden due to NSFW filter']]);
check('with Load More below it', !!$('cb_load_more_btn'), true);
check('asked for from the start', asked(0), [['1', '']]);
check('its banner counts what is loaded, not stored - the server keeps nothing',
      sentence(), '3 images loaded · 2 match the filters (2 shown) · 1 hidden due to NSFW filter');
check('and the details say there are more to come', $('cb_images_count').textContent, '3+');
check('its banner is drawn once, and stays in sight as the gallery scrolls',
      Array.from(document.querySelectorAll('#cb_images .cb-nsfw-warning'))
          .map((b) => b.classList.contains('filter-banner-sticky')), [true]);
check('page buttons are gone', document.querySelectorAll('#cb_images .mm-image-pagination').length, 0);

// Civitai down: the page does not come, and the foot says why.
civitaiDown = true;
await window.cbLoadMoreImages();
civitaiDown = false;
check('a page that cannot be loaded says why, above Load More',
      footer().startsWith('Page 2 could not be loaded: Civitai: Image search is temporarily overloaded (503)'), true);
check('changing nothing else', [cards().length, separators()], [2, []]);
check('and Load More is offered again', !!$('cb_load_more_btn'), true);

const firstCard = cards()[0];
let from = galleryAsks.length;
await window.cbLoadMoreImages();
await waitFor('page 2', () => separators().length === 1);
check('Load More adds page 2 after its separator, with its own note',
      [separators(), notes()[1]], [['Page 2'],
       'Displaying 1 image for page 2 · 2 hidden due to NSFW filter · no more images on Civitai']);
check('leaving the cards already drawn as they were', [cards()[0] === firstCard, cards().length], [true, 3]);
check('asked for from where page 1 ended', asked(from), [['2', '3']]);
check('the banner adds the two pages up',
      sentence(), '6 images loaded · 3 match the filters (3 shown) · 3 hidden due to NSFW filter');
check('and the details count them, with no more to come', $('cb_images_count').textContent, '6');
check('and the foot is clear again, with nothing more to load', [footer(), !!$('cb_load_more_btn')], ['', false]);

from = galleryAsks.length;
await window.cbToggleShowAllImages(true);
await waitFor('the reload', () => separators().length === 0);
check('a switch starts again from page 1, asked for afresh', [cards().length, notes(), asked(from)],
      [3, ['Displaying 3 images for page 1'], [['1', '']]]);

// An explicit image with no usable prompt on each page: both filters hide it,
// and the banner adds up what each page counts apart - what each switch alone
// hides, what both do, and every unusable prompt on the prompt switch.
cached.splice(0, cached.length, image(1, 1), { ...image(2, 8), meta: null }, image(3, 1),
              { ...image(4, 1), meta: null }, { ...image(5, 16), meta: null }, image(6, 8));
await window.cbToggleShowAllImages(false);
await waitFor('page 1 again', () => separators().length === 0 && cards().length === 2);
await window.cbLoadMoreImages();
await waitFor('page 2', () => separators().length === 1);
const switchText = (id) => (document.getElementById(id)?.closest('label')?.textContent || '').replace(/\s+/g, ' ').trim();
check('the banner adds the pages up, counting what both filters hide apart',
      [sentence(), switchText('cb_show_all_images'), switchText('cb_show_promptless_images')],
      ['6 images loaded · 2 match the filters (2 shown) · 1 hidden due to NSFW filter, 1 hidden due to unusable prompt, '
       + '2 hidden due to both', 'Show NSFW (1)', 'Show unusable prompts (3)']);
await window.cbToggleShowAllImages(true);
await waitFor('page 1 again', () => separators().length === 0);
await window.cbLoadMoreImages();
await waitFor('page 2', () => separators().length === 1);
check('NSFW shown: its number as it was, and the prompt switch\'s as it was',
      [switchText('cb_show_all_images'), switchText('cb_show_promptless_images')],
      ['Show NSFW (1)', 'Show unusable prompts (3)']);

// The viewer: a click on an image opens it on the card as it is.
const viewer = () => document.querySelector('.mm-viewer');
cards()[0].querySelector('img[data-view-index]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click on an image opens the viewer, with the card\'s own buttons below it',
      [!!viewer(), Array.from(viewer()?.querySelectorAll('.mm-viewer-actions > *') || []).map((b) => b.textContent.trim())],
      [true, Array.from(cards()[0].querySelectorAll('.mm-image-actions > *')).map((b) => b.textContent.trim())]);
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'ArrowRight' }));
check('→ the next card\'s image', viewer()?.querySelector('.mm-viewer-image')?.getAttribute('src'),
      cards()[1].querySelector('.mm-image-left').getAttribute('data-viewer-url'));
document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: 'Escape' }));
check('and Esc closes it', viewer(), null);

done();
