// Moving through a model's example images: a page at a time.
//
// A page is a slice of what is stored, in gallery order - 100 by default -
// before the NSFW and prompt switches, which only decide which of its images
// are drawn. Load More adds the next page to the end of the list, filled from
// Civitai first when the library cannot fill it. Each page after the first
// starts with its separator, and each ends with a note of what it held: what
// it shows, and what each switch hid. Changing a switch starts again from
// page 1, at the top.
//
// It used to be muddled: a page was 100 images that passed the switches, a
// download from Civitai was 100 before them, the two never lined up, and a
// second Load More could add images without a page of its own - "PAGE 3"
// never showed. The whole gallery was drawn again on each Load More too, and
// every image above came back blank until it reloaded, moving the page.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// --- the server ------------------------------------------------------------
// It pages as model_manager/api/images.gallery_page() does, which
// tests/py/api_test.py holds to it: slices of 100 of what is stored, filled
// from "Civitai" when short.
const SIZE = 100;
const image = (id) => ({
    id, url: `https://example.invalid/${id}.jpeg`, width: 512, height: 768,
    mm_level: id % 10 === 0 || id > 300 ? 8 : 1, meta: { prompt: `prompt ${id}`, steps: 20 },
});
// 250 stored, every tenth rated X. Civitai has 150 more: 251-300 like them,
// then 301-400 all X, and nothing after.
const stored = Array.from({ length: 250 }, (_, i) => image(i + 1));
const civitai = Array.from({ length: 150 }, (_, i) => image(251 + i));
const asked = [];
let serverDown = false;

function galleryPage(params) {
    const number = Number(params.get('page'));
    const hideNsfw = params.get('hide_nsfw_images') !== 'false';
    while (stored.length < number * SIZE && civitai.length) stored.push(...civitai.splice(0, 100));
    const rows = stored.slice((number - 1) * SIZE, number * SIZE);
    const shown = rows.filter((img) => !hideNsfw || img.mm_level <= 3);
    const all = stored.filter((img) => !hideNsfw || img.mm_level <= 3);
    return {
        success: true,
        images: shown,
        page: { number, size: SIZE, count: rows.length, shown: shown.length,
                hidden_nsfw: rows.length - shown.length, hidden_promptless: 0,
                more: stored.length > number * SIZE || civitai.length > 0, error: null },
        images_state: { version_id: 5001, next_cursor: civitai.length ? 'more' : null,
                        sync_date: '2026-01-01T00:00:00Z', total_count: stored.length,
                        filtered_count: all.length, hidden_nsfw: stored.length - all.length,
                        hidden_promptless: 0, nsfw_count: stored.length - all.length,
                        promptless_count: 0, hide_nsfw_images: hideNsfw,
                        hide_promptless_images: false },
    };
}

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};

globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    const params = new URL(href, 'http://webui').searchParams;
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/images/gallery-page')) {
        if (serverDown) return { ok: false, status: 500, json: async () => ({
            success: false, error: 'Civitai: overloaded (503)' }) };
        return reply(galleryPage(params));
    }
    if (href.includes('/model-manager/models/details')) {
        const { images_state } = galleryPage(new URLSearchParams(
            `page=1&hide_nsfw_images=${params.get('hide_nsfw_images') ?? 'true'}`));
        return reply({ success: true, model: { ...MODEL, images_state, generations_count: 0 } });
    }
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 10, models: [MODEL] });
    }
    return reply({ success: true });
};
const scrolls = [];
window.scrollTo = (to) => scrolls.push(to);

// --- run --------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const cards = () => document.querySelectorAll('#mm_images .mm-image-card');
const notes = () => Array.from(document.querySelectorAll('#mm_images .mm-page-note'))
    .map((n) => n.textContent.trim());
const separators = () => Array.from(document.querySelectorAll('#mm_images .mm-page-separator'))
    .map((s) => s.textContent.trim());
const pagesAsked = (from) => asked.slice(from)
    .filter((u) => u.includes('/images/gallery-page'))
    .map((u) => new URL(u, 'http://webui').searchParams.get('page'));
const loadMore = () => !!$('mm_load_more_btn');

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
let before = asked.length;
await window.mmSelectModel(0);
await waitFor('the gallery', () => cards().length > 0);

check('opening a model asks for its details, then page 1 on its own',
      pagesAsked(before), ['1']);
check('page 1 is its first 100 stored, less the 10 the NSFW switch hides', cards().length, 90);
check('with a note saying so, and no separator before it',
      [notes(), separators()], [['Displaying 90 images for page 1 · 10 hidden due to NSFW filter'], []]);
check('and Load More below', loadMore(), true);
check('page buttons are gone', document.querySelectorAll('#mm_images .mm-image-pagination').length, 0);

// A page that cannot be loaded says why above Load More, and changes nothing.
serverDown = true;
await window.mmLoadMoreImages();
serverDown = false;
check('a page that cannot be loaded says why, above Load More',
      [(document.querySelector('#mm_images .mm-images-footer')?.textContent || '').includes(
          'Page 2 could not be loaded: Civitai: overloaded (503)'), cards().length, loadMore()],
      [true, 90, true]);

const firstCard = cards()[0];
before = asked.length;
await window.mmLoadMoreImages();
await waitFor('page 2', () => cards().length === 180);
check('Load More asks for the next page', pagesAsked(before), ['2']);
check('and adds it after a separator, with its own note',
      [separators(), notes()[1]], [['Page 2'], 'Displaying 90 images for page 2 · 10 hidden due to NSFW filter']);
check('leaving the cards already drawn as they were, not drawn again',
      [cards()[0] === firstCard, firstCard.isConnected], [true, true]);

await window.mmLoadMoreImages();
await waitFor('page 3', () => separators().length === 2);
check('the next Load More adds page 3, as every one adds a page - filled from Civitai, '
      + 'as the library held only 50 of it', [separators(), notes()[2], cards().length],
      [['Page 2', 'Page 3'], 'Displaying 90 images for page 3 · 10 hidden due to NSFW filter', 270]);

await window.mmLoadMoreImages();
await waitFor('page 4', () => separators().length === 3);
check('a page the switches empty still has its separator and its note, which says why, '
      + 'and that Civitai has no more', [separators()[2], notes()[3], cards().length],
      ['Page 4', 'Displaying 0 images for page 4 · 100 hidden due to NSFW filter · no more images on Civitai', 270]);
check('so there is no Load More', loadMore(), false);

scrolls.length = 0;
before = asked.length;
await window.mmToggleShowNsfwImages(true);
await waitFor('the reload', () => cards().length === 100);
check('changing a switch starts again from page 1', [pagesAsked(before), separators(), notes()],
      [['1'], [], ['Displaying 100 images for page 1']]);
check('back at the top of the gallery', scrolls.length > 0, true);

// ---------------------------------------------------------------- the viewer
// A click on an image opens the shared viewer on the card as it is: its file
// large, its own buttons below, the rest of its text beside - and → through
// the gallery, loading its next page past the last card.
const viewer = () => document.querySelector('.mm-viewer');
const shown = () => viewer()?.querySelector('.mm-viewer-image')?.getAttribute('src');
const key = (name) => document.dispatchEvent(Object.assign(new window.Event('keydown'), { key: name }));
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
cards()[0].querySelector('img[data-view-index]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('a click on an image opens the viewer on it, at full size, instead of a new tab',
      [!!viewer(), shown()], [true, 'https://example.invalid/1.jpeg']);
check('with the card\'s own buttons below it',
      Array.from(viewer().querySelectorAll('.mm-viewer-actions > *')).map((b) => b.textContent.trim()),
      Array.from(cards()[0].querySelectorAll('.mm-image-actions > *')).map((b) => b.textContent.trim()));
check('and the card\'s text beside it, its prompt included',
      viewer().querySelector('.mm-viewer-info')?.textContent.includes('prompt 1'), true);
key('ArrowRight'); await settle();
check('→ is the next card\'s', shown(), 'https://example.invalid/2.jpeg');
key('Escape');
// Where the page was when the viewer opened is what "Previous Position" goes
// back to: while it is open the page is held still, and says what it likes.
const scrollTo = (y) => Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
scrollTo(1234);
cards()[99].querySelector('img[data-view-index]').dispatchEvent(new window.Event('click', { bubbles: true }));
scrollTo(0);
before = asked.length;
key('ArrowRight');
await waitFor('the next page', () => shown() === 'https://example.invalid/101.jpeg');
check('past the last card, the gallery\'s next page is loaded - into the gallery too - and shown',
      [pagesAsked(before), cards().length, shown()], [['2'], 200, 'https://example.invalid/101.jpeg']);
// (This DOM does not run inline handlers; the button's own is read instead.)
const send = viewer().querySelector('.mm-send-btn');
check('its Send is that card\'s own', send?.getAttribute('onclick'), 'window.mmSendToTxt2img(100)');
localStorage.removeItem('mm_scroll_position');
window.mmSendToTxt2img(100).catch(() => {});
check('which saves where the gallery was when the viewer opened, for Previous Position',
      localStorage.getItem('mm_scroll_position'), '1234');
send.dispatchEvent(new window.Event('click', { bubbles: true }));
check('and closes the viewer, on the way to txt2img', viewer(), null);
// "Previous Position" brings back the card sent - the one shown last, not the
// one the viewer opened on - and the saved position only once it is gone.
const intoView = [];
window.HTMLElement.prototype.scrollIntoView = function() { intoView.push(this); };
scrolls.length = 0;
window.mmRestoreScrollPosition();
check('Previous Position brings the card sent into view',
      [intoView.length, intoView[0] === cards()[100], scrolls.length], [1, true, 0]);
localStorage.setItem('mm_scroll_target', '#mm_images .mm-image-card[data-index="9999"]');
window.mmRestoreScrollPosition();
check('or, with that card no longer drawn, the page where it was', [intoView.length, scrolls[0]?.top], [1, 1234]);

done();
