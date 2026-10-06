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
import { ROOT, act, browserGalleryAnswer, checker, mountTab, press, startTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_civitai_browser.py');
const { check, waitFor, done } = checker();
const managerMarkup = tabMarkup('model_manager/ui/tab_model_manager.py');
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
const MANAGER_MODEL = { id: 1, model_id: 600, version_id: 6001, name: 'Sea Spray', model_type: 'LORA',
                        file_path: 'C:/models/Lora/sea_spray.safetensors' };

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
        // As every download is asked for (downloads().start): a form.
        downloads.push(Object.fromEntries(init.body instanceof FormData ? init.body
            : new URLSearchParams(String(init.body || ''))));
        return reply({ success: true, version_id: 6001, version_name: 'v1' });
    }
    // The Model Manager, showing the LoRA's own model: its version is 6001.
    if (href.includes('/model-manager/models/versions')) {
        return reply({ success: true, versions: [MANAGER_MODEL], civitai_versions: [] });
    }
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: { civitai_version: { id: 6001 }, images: [],
                                               images_state: { version_id: 6001 } } });
    }
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MANAGER_MODEL] });
    }
    if (href.includes('/model-manager/images/gallery-page')) {
        return reply({ success: true, images: [], images_state: { version_id: 6001 } });
    }
    if (href.includes('/images')) return reply(browserGalleryAnswer(href, [IMAGE]));
    if (href.includes('/model-manager/civitai/models')) {
        return reply({ success: true, nextCursor: null, pageSize: 20,
            models: [{ id: 7, name: 'Model 7', type: 'Checkpoint', stats: {}, creator: {},
                       modelVersions: [{ id: GALLERY_VERSION, images: [IMAGE], files: [] }] }] });
    }
    return reply({ success: true });
};

await startTab('modelManager');
await startTab('civitaiBrowser');
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
act('civitaiBrowser.search');
await waitFor('the grid', () => $('cb_status').textContent.startsWith('Showing'));
await act('civitaiBrowser.openModel', { index: 0 });
await waitFor('the gallery', () => card());
check('a PG image has no badge, whatever Civitai\'s old nsfw flag says (it once read "true")',
      card().querySelector('.mm-nsfw-badge')?.textContent ?? null, null);
await waitFor('the button relabelled', () => button()?.textContent.trim() === 'Resources (2)');
check('the button counts each resource once, and not the model the gallery shows',
      button()?.textContent.trim(), 'Resources (2)');

// The Model Manager showing the LoRA's own model, whose version its gallery
// leaves out of its Resources. The browser's leaves out its own gallery's
// version, and only that: it once fell back to the Model Manager's (#90).
$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the Model Manager\'s grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });

check('its button opens the image\'s resources', [button()?.dataset.action, button()?.dataset.index],
      ['civitaiBrowser.showResources', '0']);
press(button());
await waitFor('the dialog', () => rows().length === 2);
check('it opens the Model Manager\'s Resources dialog: the same table, the same rows - the LoRA among them, '
      + 'though the Model Manager shows its model',
      [!!panel()?.querySelector('table.mm-resources-table'), rows()],
      [true, [['LORA', 'Sea Spray'], ['VAE', 'VAE ft MSE']]]);

const download = panel().querySelector('[data-res-download="6001"] button');
check('with a Download for each: the LoRA alone, into the library',
      [download?.dataset.action, download?.dataset.versionId, download?.dataset.modelId],
      ['resources.download', '6001', '600']);
await press(download);
check('which downloads that version, not the model the image is an example of',
      downloads.map((d) => d.version_id), ['6001']);

done();
