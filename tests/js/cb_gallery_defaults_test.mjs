// Each model the Civitai Browser opens starts its gallery as the settings say,
// and the switches then last while that model is open - as in the Model
// Manager (mm_gallery_defaults_test.mjs), which has to behave the same.
//
// It used to open as the search was set: Include NSFW models showed explicit
// images, Only with usable prompts hid images without one. Those choose which
// models are listed, not which of their images are shown. Then it read the
// settings once per page, so a change on the Settings page reached a model
// opened afterwards only after a reload.
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();

const image = (id, level, prompt) => ({
    id, url: `https://example.invalid/${id}.jpeg`, nsfwLevel: level, browsingLevel: level,
    mm_level: level, mm_level_from_prompt: false,
    meta: prompt ? { prompt: 'a lighthouse by the sea' } : null,
});
// Safe with a prompt, explicit with a prompt, safe without one. The prompt
// has no steps, sampler or CFG: the Model Manager's rule is a readable prompt.
const images = [image(1, 1, true), image(2, 8, true), image(3, 1, false)];
const settings = { gallery_hide_nsfw: true, hide_promptless_images: true };

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, ...settings }) };
    }
    if (href.includes('/images')) {
        return { ok: true, json: async () => browserGalleryAnswer(href, images) };
    }
    if (href.includes('/model-manager/civitai/models')) {
        return { ok: true, json: async () => ({ success: true, nextCursor: null, pageSize: 20,
            models: [7, 8].map((id) => ({ id, name: `Model ${id}`, type: 'Checkpoint', stats: {},
                creator: {}, modelVersions: [{ id: id * 10, images, files: [] }] })) }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const shown = () => Array.from(document.querySelectorAll('#cb_images .mm-image-card img'))
    .map((img) => (img.getAttribute('data-src') || img.getAttribute('src') || '').split('/').pop());
const ticked = () => [$('cb_show_all_images')?.checked ?? null,
                      $('cb_show_promptless_images')?.checked ?? null];

async function open(index) {
    $('cb_images').innerHTML = '';
    await window.cbOpenModel(index);
    await waitFor('the gallery', () => document.querySelectorAll('#cb_images .mm-image-card').length > 0);
}

// The search says the opposite of the settings throughout.
$('cb_nsfw').checked = true;
$('cb_require_prompt').checked = false;
$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));

await open(0);
check('hiding both, the gallery opens with only the safe image with a prompt',
      shown(), ['1.jpeg']);
check('whatever Include NSFW models and Only with usable prompts say', ticked(), [false, false]);

await window.cbToggleShowAllImages(true);
await window.cbToggleShowPromptless(true);
check('the switches show everything for this model', shown(), ['1.jpeg', '2.jpeg', '3.jpeg']);

await open(1);
check('the next model starts from the settings again, not from the switches',
      [shown(), ticked()], [['1.jpeg'], [false, false]]);

// Changed on the Settings page, with this page left open.
settings.gallery_hide_nsfw = false;
settings.hide_promptless_images = false;
await open(0);
check('a change to the settings reaches the next model opened, without a reload',
      [shown(), ticked()], [['1.jpeg', '2.jpeg', '3.jpeg'], [true, true]]);

settings.gallery_hide_nsfw = true;
await open(1);
check('each setting on its own', [shown(), ticked()], [['1.jpeg', '3.jpeg'], [false, true]]);

done();
