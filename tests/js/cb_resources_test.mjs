// The Civitai Browser's images have the Model Manager's Resources.
//
// An image in the browser names what went into it, and a person looking at it
// may want one LoRA it used without the model it is an example of. The
// browser once had a dialog of its own: a bare list, unstyled, every
// resource named twice (Civitai's list and the infotext's), the model the
// gallery belongs to among them, a View link and no Download. It now opens
// the Model Manager's - the same table, the same lookups, the same Download
// into the library - with its own gallery's version left out. Both tabs'
// scripts are on one page, as in the WebUI.
import { readFileSync } from 'node:fs';
import { ROOT, browserGalleryAnswer, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
const managerMarkup = readFileSync(`${ROOT}/model_manager/ui/tab_model_manager.py`, 'utf8')
    .match(/gr\.HTML\(\s*("""|''')([\s\S]*?)\1/)[2];
document.body.insertAdjacentHTML('beforeend', managerMarkup);

const GALLERY_VERSION = 70;               // the version whose images these are
const IMAGE = {
    id: 1, url: 'https://example.invalid/1.jpeg', nsfw: true, nsfwLevel: 1, browsingLevel: 1,
    mm_level: 1, mm_level_from_prompt: false,
    meta: {
        prompt: 'a lighthouse by the sea',
        civitaiResources: [
            { type: 'Checkpoint', name: 'The Model Itself', modelVersionId: GALLERY_VERSION },
            { type: 'LORA', name: 'Sea Spray', modelVersionId: 6001, modelId: 600 },
        ],
        resources: [
            // The same LoRA, by the filename whoever made it had, and a VAE
            // only the infotext names.
            { type: 'lora', name: 'sea_spray_v1', hash: 'aaaaaaaaaa' },
            { type: 'vae', name: 'vae-ft-mse', hash: 'cccccccccc' },
        ],
    },
};
const RESOLVED = {
    aaaaaaaaaa: { version_id: 6001, model_id: 600, name: 'Sea Spray', version_name: 'v1', model_type: 'LORA' },
    cccccccccc: { version_id: 7001, model_id: 700, name: 'VAE ft MSE', version_name: '840000', model_type: 'VAE' },
};
const downloads = [];

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, gallery_hide_nsfw: false, hide_promptless_images: false, has_api_key: true });
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        const hashes = (new URLSearchParams(String(init.body || '')).get('hashes') || '').split(',');
        const resolved = {};
        for (const hash of hashes) if (hash in RESOLVED) resolved[hash] = RESOLVED[hash];
        return reply({ success: true, resolved, deferred: [] });
    }
    // The download itself - not its progress, which the page asks for at load.
    if (href.endsWith('/model-manager/civitai/download')) {
        downloads.push(Object.fromEntries(new URLSearchParams(String(init.body || ''))));
        return reply({ success: true, version_id: 6001, version_name: 'v1' });
    }
    if (href.includes('/images')) return reply(browserGalleryAnswer(href, [IMAGE]));
    if (href.includes('/model-manager/civitai/models')) {
        return reply({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'Model 7', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: GALLERY_VERSION, images: [IMAGE], files: [] }] }] });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
await import(`file:///${ROOT}/javascript/civitai_browser.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const $ = (id) => document.getElementById(id);
const card = () => document.querySelector('#cb_images .mm-image-card');
const button = () => Array.from(card()?.querySelectorAll('.mm-image-actions button') || [])
    .find((b) => b.textContent.trim().startsWith('Resources'));
const panel = () => document.querySelector('.mm-resources-modal');
const rows = () => Array.from(panel()?.querySelectorAll('tbody tr') || [])
    .map((row) => [row.querySelector('.mm-res-type')?.textContent.trim(),
                   row.querySelector('.mm-res-name')?.childNodes[0]?.textContent.trim()]);

$('cb_status').textContent = '';
window.cbSearch();
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
await window.cbOpenModel(0);
await waitFor('the gallery', () => card());
check('a PG image has no badge, whatever Civitai\'s old nsfw flag says (it once read "true")',
      card().querySelector('.mm-nsfw-badge')?.textContent ?? null, null);
await waitFor('the button relabelled', () => button()?.textContent.trim() === 'Resources (2)');
check('the button counts each resource once, and not the model the gallery shows',
      button()?.textContent.trim(), 'Resources (2)');

// (This DOM does not run inline handlers; the button's own is read, and run.)
check('its button opens the image\'s resources', button()?.getAttribute('onclick'), 'window.cbShowResources(0)');
window.cbShowResources(0);
await waitFor('the dialog', () => rows().length === 2);
check('it opens the Model Manager\'s Resources dialog: the same table, the same rows',
      [!!panel()?.querySelector('table.mm-resources-table'), rows()],
      [true, [['LORA', 'Sea Spray'], ['VAE', 'VAE ft MSE']]]);

const download = panel().querySelector('[data-res-download="6001"] button');
check('with a Download for each: the LoRA alone, into the library',
      download?.getAttribute('onclick'), 'window.mmDownloadResource(6001, 600)');
await window.mmDownloadResource(6001, 600);
check('which downloads that version, not the model the image is an example of',
      downloads.map((d) => d.version_id), ['6001']);

done();
