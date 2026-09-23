// What went into an image, gathered from two lists that disagree.
//
// The generation data names an image's resources twice: Civitai's own list,
// which carries modelVersionId, and the legacy infotext list, which carries an
// AutoV2 hash and whatever filename the generator had on disk. Every row used
// to be shown from both, so each resource appeared twice under two spellings,
// and the model the gallery belongs to appeared in nearly every image.
//
// The lists share no key, so the hashes are resolved into version ids and the
// merge is done on those - never on name similarity, which does not survive
// real data: "stablydiffuseds_26" is "StablyDiffused's Aesthetic Mix". What
// this checks is therefore which endpoint was asked and what came back, not
// only the number of rows.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// --- the server -------------------------------------------------------------
const VERSION_ID = 5001;                  // the version whose gallery this is

const MODEL = {
    id: VERSION_ID, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};

const IMAGE = {
    id: 4242, url: 'https://example.invalid/4242.jpeg', browsingLevel: 1,
    meta: {
        prompt: 'a prompt long enough to read', steps: 20,
        sampler: 'Euler a', cfgScale: 7,
        civitaiResources: [
            // The model this gallery belongs to. An image is an example *of*
            // it, so naming it says nothing.
            { type: 'Checkpoint', name: 'The Model Itself', modelVersionId: VERSION_ID },
            { type: 'LORA', name: 'Sci-fi Environments', modelVersionId: 6001 },
            { type: 'LORA', name: 'Space Worlds', modelVersionId: 6002 },
        ],
        resources: [
            // The same two LoRAs, under the filenames whoever made the image had.
            { type: 'lora', name: 'scifi_env_v1', hash: 'aaaaaaaaaa' },
            { type: 'lora', name: 'spaceworlds01', hash: 'bbbbbbbbbb' },
            // A VAE, which Civitai's list does not mention at all.
            { type: 'vae', name: 'vae-ft-mse', hash: 'cccccccccc' },
            // Nothing can resolve these.
            { type: 'lora', name: 'a_private_merge', hash: 'dddddddddd' },
            { type: 'lora', name: 'eulaHard' },
            { type: 'lora', name: 'eulaHard' },      // one resource, not two
        ],
    },
};

const RESOLVED = {
    // Deliberately a different spelling from Civitai's list: whichever name
    // the row ends up with says which side the merge kept.
    aaaaaaaaaa: { version_id: 6001, name: 'Sci Fi Environments (resolved)',
                  version_name: 'v1', model_type: 'LORA' },
    bbbbbbbbbb: { version_id: 6002, name: 'Space Worlds',
                  version_name: 'v1', model_type: 'LORA' },
    cccccccccc: { version_id: 7001, name: 'VAE ft MSE',
                  version_name: '840000', model_type: 'VAE' },
    // Asked about; Civitai has never heard of it.
    dddddddddd: { version_id: null, name: null, version_name: null, model_type: null },
};

const resolveCalls = [];

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({
            success: true, samplers: ['Euler'], schedulers: ['Simple'],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        const asked = decodeURIComponent(String(init.body || '').replace('hashes=', ''));
        resolveCalls.push(asked);
        return { ok: true, json: async () => ({ success: true, resolved: RESOLVED }) };
    }
    if (href.includes('/model-manager/models/details')) {
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL, images: [IMAGE],
            images_state: { version_id: VERSION_ID, next_cursor: null,
                            sync_date: '2026-01-01T00:00:00Z', total_count: 1,
                            hidden_count: 0, hidden_nsfw: 0, hidden_promptless: 0,
                            hide_nsfw_images: false, hide_promptless_images: true },
        } }) };
    }
    if (href.includes('/model-manager/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [MODEL] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({
            success: true, total: 1, page: 1, page_size: 10, models: [MODEL] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

// --- run --------------------------------------------------------------------
const panel = () => document.querySelector('.mm-resources-modal');
const names = (selector) => Array.from(panel().querySelectorAll(selector))
    .map((row) => row.querySelector('.mm-res-name'))
    .filter(Boolean)
    .map((cell) => {
        // The version sits in a span in the same cell; the name is the rest.
        const version = cell.querySelector('.mm-res-version');
        const text = cell.textContent;
        return (version ? text.replace(version.textContent, '') : text).trim();
    });

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

document.getElementById('mm_load_btn')
    .dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card').length > 0);

const button = document.querySelector('.mm-image-actions button[onclick*="mmShowResources"]');
check('the image offers its resources', !!button, true);
check('counting everything but the model itself',
      button.textContent.trim(), 'Resources (8)');

const showing = window.mmShowResources(0);
check('the panel goes up before the lookups finish, not after',
      !!panel() && panel().textContent.includes('Looking these up'), true);
await showing;
await waitFor('the lookups', () => !!panel() && !panel().textContent.includes('Looking these up'));

check('the hashes go in one request', resolveCalls.length, 1);
check('each distinct hash asked about once',
      resolveCalls[0].split(',').sort(),
      ['aaaaaaaaaa', 'bbbbbbbbbb', 'cccccccccc', 'dddddddddd']);

const offered = names('tr:not(.mm-res-unresolved)').sort();
check('each resource appears once, under the name Civitai gives it',
      offered, ['Sci-fi Environments', 'Space Worlds', 'VAE ft MSE']);
check('the model this gallery belongs to is not among them',
      offered.includes('The Model Itself'), false);
check('nor the filename its duplicate was listed under',
      offered.includes('scifi_env_v1'), false);
check("where both lists name it, the Civitai name is the one kept",
      offered.includes('Sci Fi Environments (resolved)'), false);
check('one the legacy list alone knew about is still offered',
      offered.includes('VAE ft MSE'), true);
check('and every offer can be opened or downloaded',
      panel().querySelectorAll('.mm-res-actions a').length, 6);

const unresolved = names('.mm-res-unresolved').sort();
check('what nothing could be found for is shown rather than dropped',
      unresolved, ['a_private_merge', 'eulaHard']);
check('listed once, not once per mention',
      unresolved.filter((n) => n === 'eulaHard').length, 1);
check('with nothing to click',
      panel().querySelectorAll('.mm-res-unresolved a').length, 0);
check('under a heading that says why',
      panel().textContent.includes('not found on Civitai'), true);

check('nothing offers a lookup any more, it has already happened',
      panel().textContent.includes('Lookup'), false);

done();
