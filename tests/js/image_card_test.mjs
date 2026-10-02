// One Civitai image, the same in both tabs (#88). The Model Manager and the
// Civitai Browser each drew a Civitai image's card, from copies that had
// drifted: two sampler splits gave one image two readings - the browser's
// looked for six schedulers anywhere in the text, the Model Manager's for
// Forge's own at its end - and only the Model Manager listed ADetailer's
// "inpaint only masked". Show All opened a table in one and the JSON in the
// other.
//
// Here one image is drawn in both tabs: the card says the same in each, and
// Show All opens the same window - the table, with a Copy JSON button.
import { readFileSync } from 'node:fs';
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('beforeend', readFileSync(`${ROOT}/model_manager/ui/tab_model_manager.py`, 'utf8')
    .match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/)[2]);

const IMAGE = {
    id: 4242, url: 'https://example.invalid/4242.jpeg', width: 512, height: 768, nsfwLevel: 1, browsingLevel: 1,
    mm_level: 1, mm_level_from_prompt: false,
    meta: {
        prompt: 'a lighthouse at dusk', negativePrompt: 'blurry', steps: 20, cfgScale: 7, seed: 9,
        // A scheduler Forge has and the browser's six did not.
        sampler: 'Euler a Uniform', Size: '512x768',
        'ADetailer model': 'face_yolov8n.pt', 'ADetailer inpaint only masked': 'True',
    },
};
const MODEL = { id: 1, model_id: 7, version_id: 70, name: 'Lighthouse', model_type: 'Checkpoint',
                file_path: 'C:/models/Stable-diffusion/lighthouse.safetensors' };

globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: false, hide_promptless_images: false, has_api_key: true,
                       samplers: ['Euler', 'Euler a', 'DPM++ 2M'],
                       schedulers: ['Automatic', 'Uniform', 'Karras', 'Exponential', 'SGM Uniform'] });
    }
    // The Model Manager, showing the model whose image this is.
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions: [MODEL], civitai_versions: [] });
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: { civitai_version: { id: 70 }, images: [], images_state: { version_id: 70 } } });
    }
    if (href.includes('/model-manager/models')) return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    if (href.includes('/model-manager/images/gallery-page')) {
        return reply({ success: true, images: [IMAGE], page: { number: 1, shown: 1 },
                       images_state: { version_id: 70, total_count: 1, filtered_count: 1 } });
    }
    // The Civitai Browser, showing the same model's gallery.
    if (href.includes('/images')) return reply(browserGalleryAnswer(href, [IMAGE]));
    if (href.includes('/model-manager/civitai/models')) {
        return reply({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'Lighthouse', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: 70, images: [IMAGE], files: [] }] }] });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
// What a card says about its image: all but its buttons, which are the tab's.
const said = (card) => {
    const right = card?.querySelector('.mm-image-right')?.cloneNode(true);
    right?.querySelector('.mm-image-actions')?.remove();
    return (right?.textContent || '').replace(/\s+/g, ' ').trim();
};
const managerCard = () => document.querySelector('#mm_images .mm-image-card');
const browserCard = () => document.querySelector('#cb_images .mm-image-card');

$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Model Manager\'s grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0, 40);
await window.mmSelectModel(0);
await waitFor('its gallery', () => managerCard(), 40);
$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the browser\'s grid', () => $('cb_status').textContent.startsWith('Showing'), 40);
await window.cbOpenModel(0);
await waitFor('its gallery', () => browserCard(), 40);

check('the same image says the same in both tabs', said(browserCard()), said(managerCard()));
check('its sampler and scheduler read apart, by Forge\'s schedulers',
      [said(managerCard()).includes('Sampler: Euler a'), said(managerCard()).includes('Scheduler: Uniform')], [true, true]);
check('with its id and every ADetailer setting',
      [said(managerCard()).includes('4242'), said(managerCard()).includes('Inpaint masked: True')], [true, true]);

// ------------------------------------------------------------ Show All
const shown = () => document.querySelector('.mm-modal-overlay');
const windowSays = () => ({
    table: !!shown()?.querySelector('table.mm-meta-table'),
    rows: shown()?.querySelectorAll('table.mm-meta-table tr').length || 0,
    copy: (() => { try { return JSON.parse(shown()?.querySelector('[data-copy]')?.getAttribute('data-copy') || 'null'); }
                   catch { return 'not JSON'; } })(),
});
window.mmShowImageMeta(0);
const inManager = windowSays();
shown()?.remove();
window.cbShowImageMeta(0);
const inBrowser = windowSays();
shown()?.remove();
check('Show All opens the same window in both', inBrowser, inManager);
check('a table of every field, with a Copy JSON of the image\'s generation data',
      [inManager.table, inManager.rows > 5, inManager.copy], [true, true, IMAGE.meta]);

done();
