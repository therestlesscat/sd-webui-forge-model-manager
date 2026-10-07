// Images as uploaded, not resized (#192): two settings, off by default.
//
// A card and a gallery tile load Civitai's copy at the width they draw
// (card_media_test.mjs). With "Gallery images: load as uploaded" on, a
// gallery tile loads the upload instead; with "Model cards: load as
// uploaded", a model card does. Measured on 20 library images: a card's
// 320-wide copy 54 KB on average, the upload 3,576 KB - 66 times as much. A
// video is always a copy, whatever the setting: an upload can be a GIF a card
// cannot play. The page learns both settings from its one ui-options answer,
// and draws with them once it is in.
import { ROOT, act, checker, mountTab, sharedModule, startTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const { cardMediaUrl, sizedMediaUrl } = await import(`file:///${ROOT}/javascript/shared/media.mjs`);
const C = 'https://image.civitai.com/acct/1234-abcd';

// ------------------------------------------------------------------ the rule
check('as uploaded: an image is asked for as the upload',
      sizedMediaUrl(`${C}/width=450/a.jpeg`, { cssWidth: 200, asUploaded: true }), `${C}/original=true/a.jpeg`);
check('a video still as the copy for its width',
      sizedMediaUrl(`${C}/original=true/a.mp4`, { cssWidth: 200, asUploaded: true }), `${C}/width=320/a.mp4`);
check('as is one Civitai says is a video',
      sizedMediaUrl(`${C}/original=true/a.jpeg`, { cssWidth: 200, type: 'video', asUploaded: true }),
      `${C}/width=320/a.jpeg`);
check('a card the same, through cardMediaUrl',
      [cardMediaUrl(`${C}/width=450/a.jpeg`, 'image', 200, 4000, true), cardMediaUrl(`${C}/width=450/a.jpeg`, 'image', 200, 4000)],
      [`${C}/original=true/a.jpeg`, `${C}/width=320/a.jpeg`]);
check('anything not Civitai\'s is left as it is',
      sizedMediaUrl('https://example.invalid/a.jpeg', { cssWidth: 200, asUploaded: true }), 'https://example.invalid/a.jpeg');

// --------------------------------------------------------- the page's flags
const uiModule = await sharedModule('ui_options.mjs');
let answer = { success: true, gallery_originals: true, card_originals: false };
const MODEL = {
    id: 20937, model_id: 11718, name: 'Still cover', display_name: 'Still cover',
    version_name: 'v1', base_model: 'SD 1.5', model_type: 'Checkpoint',
    file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors', file_size: 1, nsfw_level: 1,
    has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
    preview_url: `${C}/width=450/cover.jpeg`,
};
const GALLERY = [
    { id: 1, url: `${C}/original=true/still.jpeg`, width: 1024, height: 1536, type: 'image',
      nsfw: false, mm_level: 1, meta: { prompt: 'a lighthouse by the sea' } },
    { id: 2, url: `${C}/original=true/moving.mp4`, width: 720, height: 1280, type: 'video',
      nsfw: false, mm_level: 1, meta: { prompt: 'waves roll in on a beach' } },
];
globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    // Slowly, as a busy server would: what draws first has to wait for it.
    if (href.includes('/ui-options')) {
        const now = answer;
        await new Promise((r) => setTimeout(r, 120));
        return reply(now);
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: GALLERY, generations_count: 0,
            images_state: { version_id: 20937, total_count: 2, filtered_count: 2, offset: 0,
                            hide_nsfw_images: false, hide_promptless_images: false } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true });
});

const asUploaded = uiModule.asUploaded;
check('the page can say how images load', typeof asUploaded, 'function');
check('resized until the answer is in', asUploaded?.(), { gallery: false, cards: false });

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the card', () => document.querySelector('#mm_grid .model-card img'));
check('Model cards off: the card loads the copy for its width',
      document.querySelector('#mm_grid .model-card img')?.getAttribute('src'), `${C}/width=320/cover.jpeg`);

await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-image-card'));
check('Gallery images on: a tile loads the upload',
      document.querySelector('#mm_images .mm-image-card img')?.getAttribute('data-src'), `${C}/original=true/still.jpeg`);
check('and a video tile, a copy still',
      document.querySelector('#mm_images .mm-image-card video')?.getAttribute('data-src'), `${C}/width=320/moving.mp4`);

// Saved the other way: the settings window's save asks the answer again.
answer = { success: true, gallery_originals: false, card_originals: true };
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_card_originals'],
    settings: { model_manager_card_originals: { value: true } } } }));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the card drawn again', () => document.querySelector('#mm_grid .model-card img')?.getAttribute('src')?.includes('original'));
check('Model cards on: the card, drawn again - before the new answer was in - loads the upload',
      document.querySelector('#mm_grid .model-card img')?.getAttribute('src'), `${C}/original=true/cover.jpeg`);
check('after a save, the page has the new answer', asUploaded?.(), { gallery: false, cards: true });

done();
