// What the Civitai Browser's Load More brought, said beside the button.
//
// A download is filtered like everything else in the gallery, so a batch of
// explicit images changed nothing on screen: three clicks on one model stored
// 30 images, 26 of them R or above, and looked like three clicks that did
// nothing. The note says how many came, how many are shown, and what hid the
// rest.
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const image = (id, level) => ({
    id, url: `https://example.invalid/${id}.jpeg`, nsfwLevel: level, browsingLevel: level,
    mm_level: level, mm_level_from_prompt: false,
    meta: { prompt: 'a lighthouse by the sea' },
});
// What the server has cached for the version: two safe, one explicit.
const cached = [image(1, 1), image(2, 1), image(3, 8)];
let cursor = 'more';

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, gallery_hide_nsfw: true,
                                                hide_promptless_images: true }) };
    }
    if (href.includes('/images/load-more')) {
        // Ten more from Civitai, nine of them explicit; the answer lists them
        // all, as the real one does.
        const more = Array.from({ length: 10 }, (_, i) => image(100 + i, i === 0 ? 1 : 16));
        cached.push(...more);
        cursor = null;
        return { ok: true, json: async () => ({ success: true, images: more,
                                                next_cursor: null, fetched_count: 10 }) };
    }
    if (href.includes('/images')) {
        return { ok: true, json: async () => browserGalleryAnswer(href, cached,
                                                                  { next_cursor: cursor }) };
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
const cards = () => document.querySelectorAll('#cb_images .mm-image-card').length;
const note = () => (document.querySelector('#cb_images .mm-load-more-info')?.textContent || '').trim();

$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
await window.cbOpenModel(0);
await waitFor('the gallery', () => cards() > 0);

check('the gallery opens with the safe images', cards(), 2);
check('offering to load more', !!$('cb_load_more_btn'), true);

await window.cbLoadMoreImages();
await waitFor('the download', () => note().includes('more'));
check('the one safe image it brought is shown', cards(), 3);
check('and the note says what the rest were hidden by', note(),
      '10 more images: 1 shown, 9 hidden by the NSFW filter');

await window.cbToggleShowAllImages(true);
check('the note lasts only until the gallery is loaded some other way',
      note().includes('more images'), false);

done();
