// The Civitai Images tab's viewer shows a Civitai image as the other tabs'
// viewers do (#267).
//
// Those show a copy of the image's card: its id, the resources its data lists,
// its prompt and settings, and Send, Copy Prompt, Show All, View on Civitai
// and Resources with its count. This tab's viewer (0.57.0) built a panel of
// its own with part of it: no id, no resources list, no Copy Prompt, Show All
// or View on Civitai, and a Resources with no count, offered on an image
// with none. It now draws the card's own text, and the card's buttons.
import { checker, mountTab, press, startServices, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

const image = (id, meta) => ({
    id, url: `https://image.civitai.com/x/original=true/${id}.jpeg`, width: 1024, height: 1536, mm_level: 1,
    mm_level_from_prompt: false, meta,
});
const tile = (img) => ({
    kind: 'image', image: img,
    model: { id: 40, name: 'A LoRA', civitai_type: 'LORA', model_type: 'LORA', base_model: 'SDXL 1.0' },
    version: { id: 400, name: 'v1', file_path: 'C:/models/Lora/a.safetensors', file_type: 'LORA', base_model: 'SDXL 1.0' },
});
const WITH = image(9001, {
    prompt: 'a lighthouse at dusk', steps: 20, sampler: 'Euler', Model: 'someCheckpoint',
    civitaiResources: [{ type: 'LORA', name: 'Sea Spray', modelVersionId: 6001, modelId: 600 }],
    resources: [{ type: 'lora', name: 'sea_spray_v1', weight: 0.8 }],
});
const WITHOUT = image(9002, { prompt: 'no resources here', Model: 'someCheckpoint' });
// A checkpoint's image Civitai gave no generation data (#266).
const NO_DATA = image(9003, null);
const checkpointTile = (img) => ({ ...tile(img),
    model: { id: 50, name: 'A Checkpoint', civitai_type: 'Checkpoint', model_type: 'Checkpoint', base_model: 'SDXL 1.0' },
    version: { id: 500, name: 'v1', file_path: 'C:/models/a.safetensors', file_type: 'Checkpoint', base_model: 'SDXL 1.0' } });

globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/gallery/browse')) {
        return reply({ success: true, seed: 1, more: false, state: { total: 3, filtered: 3 }, scope: { count: 3 },
                       tiles: [tile(WITH), tile(WITHOUT), checkpointTile(NO_DATA)] });
    }
    if (href.includes('/model-manager/ui-options')) return reply({ success: true, samplers: [], schedulers: [], gallery_grid: 'Classic' });
    return reply({ success: true });
};

// The page's one listener for data-action, which another tab would have started.
await startServices('calls.mjs');
await startTab('gallery');
await waitFor('the grid', () => document.querySelectorAll('#gal_grid .gen-tile').length === 3);

const viewer = () => document.querySelector('.mm-viewer');
const buttons = () => Array.from(viewer()?.querySelectorAll('.mm-viewer-actions > button') || [])
    .map((b) => b.textContent.trim());
const button = (label) => Array.from(viewer()?.querySelectorAll('.mm-viewer-actions > button') || [])
    .find((b) => b.textContent.trim().startsWith(label));

await press(document.querySelector('#gal_grid [data-action="gallery.view"][data-tile="0"]'));
await waitFor('the viewer', () => viewer());
check('its id, as the card shows it', viewer()?.querySelector('.mm-image-id')?.textContent.replace(/\s+/g, ' ').trim(),
      'Image ID: 9001');
check('the resources its data lists, as the card shows them',
      viewer()?.querySelector('.mm-image-resources')?.textContent.includes('sea_spray_v1'), true);
check('its prompt, as before', viewer()?.querySelector('.mm-image-prompt')?.textContent.includes('a lighthouse at dusk'), true);
check('the card\'s buttons, in its order, and Show model',
      buttons().map((b) => b.replace(/ \(.*\)$/, '')),
      ['Send to txt2img', 'Copy Prompt', 'Show All', 'View on Civitai', 'Resources', 'Show model']);
check('Resources with its count', /^Resources \(\d+\+?\)$|^Resources$/.test(button('Resources')?.textContent.trim() || ''), true);
check('Copy Prompt copies the prompt', button('Copy Prompt')?.getAttribute('data-copy'), 'a lighthouse at dusk');
check('View on Civitai opens the image there', button('View on Civitai')?.getAttribute('data-open-url'),
      'https://civitai.com/images/9001');
button('Show All')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('Show All', () => document.querySelector('#mm_meta_modal'));
check('Show All opens every field, over the viewer', !!document.querySelector('#mm_meta_modal'), true);
document.querySelector('#mm_meta_modal .mm-modal-close')?.dispatchEvent(new window.Event('click', { bubbles: true }));

viewer()?.querySelector('.mm-viewer-next')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the second image', () => viewer()?.querySelector('.mm-image-id')?.textContent.includes('9002'));
check('an image whose data names no resource offers no Resources', buttons(),
      ['Send to txt2img', 'Copy Prompt', 'Show All', 'View on Civitai', 'Show model']);

// No generation data, in a checkpoint's gallery: Send disabled on the tile
// and in the viewer, saying why - it was pressable, and threw (#266).
const WHY = 'Civitai gave this image no generation data: nothing to send.';
const tileSend = document.querySelector('#gal_grid [data-action="gallery.send"][data-tile="2"]');
check('the tile\'s Send disabled, saying why', [tileSend?.disabled, tileSend?.getAttribute('title')], [true, WHY]);
viewer()?.querySelector('.mm-viewer-next')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the third image', () => viewer()?.querySelector('.mm-image-id')?.textContent.includes('9003'));
check('the viewer\'s Send disabled, saying why', [button('Send')?.disabled, button('Send')?.getAttribute('title')], [true, WHY]);

done();
