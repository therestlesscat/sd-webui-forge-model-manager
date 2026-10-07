// The Civitai Browser card's image, with NSFW models included or not.
//
// A card shows its version's first showcase image. With NSFW models not
// included, Civitai sends PG images only, so that is safe as it comes - but
// the card no longer depends on it: an image above PG-13 is passed over for
// the first PG or PG-13 one, and a version with none shows no image at all.
// With NSFW models included, the first image is shown whatever it is.
import { ROOT, act, browserGalleryAnswer, checker, mountTab, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

// Stamped as the server stamps every image it sends (nsfw.stamp_levels()).
const img = (name, level) => ({ url: `https://example.invalid/${name}.jpeg`, nsfwLevel: level,
                                mm_level: level, mm_level_from_prompt: false });
const MODELS = [
    { id: 1, name: 'Safe first', showcase: [img('pg', 1), img('r', 4)] },
    { id: 2, name: 'Unsafe first', showcase: [img('x', 8), img('r', 4), img('pg13', 2), img('pg', 1)] },
    { id: 3, name: 'Nothing safe', showcase: [img('r', 4), img('xxx', 16)] },
];

let cardOriginals = false;      // "Model cards: load as uploaded" (#192), as ui-options says
globalThis.fetch = async (url) => {
    // Slowly, as a busy server would: a search has to wait for it.
    if (String(url).includes('/ui-options')) {
        const now = cardOriginals;
        await new Promise((r) => setTimeout(r, 120));
        return { ok: true, json: async () => ({ success: true, card_originals: now, gallery_originals: now }) };
    }
    if (String(url).includes('/versions/')) {
        return { ok: true, json: async () => browserGalleryAnswer(String(url), [
            { id: 7, url: 'https://image.civitai.com/acct/5678-efgh/original=true/tile.jpeg', width: 1024, height: 1536,
              type: 'image', nsfwLevel: 1, mm_level: 1, mm_level_from_prompt: false, meta: { prompt: 'a lighthouse' } }]) };
    }
    if (!String(url).includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true }) };
    }
    return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
        models: MODELS.map((m) => ({ id: m.id, name: m.name, type: 'Checkpoint', stats: {},
            creator: {}, modelVersions: [{ id: m.id * 10, images: m.showcase, files: [] }] })) }) };
};

await startTab('civitaiBrowser');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
function previews() {
    return Array.from(document.querySelectorAll('#cb_grid .model-card')).map((card) => {
        const media = card.querySelector('.model-card-image img, .model-card-image video, img, video');
        const src = media?.getAttribute('src') || '';
        const name = (src.match(/example\.invalid\/([a-z0-9]+)\.jpeg/) || [])[1];
        return name || 'none';
    });
}
async function search() {
    $('cb_status').textContent = '';
    act('civitaiBrowser.search');
    await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
}

$('cb_nsfw').checked = false;
await search();
check('NSFW models not included: a safe first image is shown as it is, an unsafe one is passed over '
      + 'for the first PG or PG-13, and a version with none shows no image',
      previews(), ['pg', 'pg13', 'none']);

$('cb_nsfw').checked = true;
await search();
check('NSFW models included: the first image, whatever it is', previews(), ['pg', 'x', 'r']);

// The Civitai Browser's card asks Civitai for a copy the card's size, as the
// Model Manager's does (see card_media_test.mjs).
MODELS.splice(0, MODELS.length,
    { id: 4, name: 'Animated', showcase: [
        { url: 'https://image.civitai.com/acct/1234-abcd/original=true/293422.mp4', type: 'video', nsfwLevel: 1 }] },
    { id: 5, name: 'Still', showcase: [
        { url: 'https://image.civitai.com/acct/5678-efgh/width=450/a.jpeg', type: 'image', nsfwLevel: 1 }] });
await search();
const sources = Array.from(document.querySelectorAll('#cb_grid .model-card'))
    .map((card) => card.querySelector('video, img')?.getAttribute('src'));
check('the Civitai Browser card asks for a video and an image as copies the card\'s size, '
      + 'as the Model Manager does',
      sources, ['https://image.civitai.com/acct/1234-abcd/width=320/293422.mp4',
                'https://image.civitai.com/acct/5678-efgh/width=320/a.jpeg']);

// "Model cards: load as uploaded" saved on (#192): from the next search, an
// image card loads the upload, and a video card a copy still.
cardOriginals = true;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_card_originals'],
    settings: { model_manager_card_originals: { value: true } } } }));
await search();
check('Model cards on: the image card loads the upload, the video card a copy',
      Array.from(document.querySelectorAll('#cb_grid .model-card')).map((card) => card.querySelector('video, img')?.getAttribute('src')),
      ['https://image.civitai.com/acct/1234-abcd/width=320/293422.mp4',
       'https://image.civitai.com/acct/5678-efgh/original=true/a.jpeg']);

// "Gallery images: load as uploaded", saved on with it: a model's gallery tile
// loads the upload too.
act('civitaiBrowser.openModel', { index: 1 });
await waitFor('the gallery', () => document.querySelector('#cb_images .mm-image-card img'));
check('Gallery images on: the Civitai Browser\'s tile loads the upload',
      document.querySelector('#cb_images .mm-image-card img')?.getAttribute('data-src'),
      'https://image.civitai.com/acct/5678-efgh/original=true/tile.jpeg');

done();
