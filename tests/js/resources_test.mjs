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
// How the fake server answers /resolve-hashes. By default it knows everything
// in RESOLVED and answers it all at once. `cap` makes it answer only that many
// per request and defer the rest, as the real one does for Civitai lookups.
// `hold` makes it wait for a promise first, to stand for a slow Civitai.
const resolver = { cap: null, hold: null, answers: RESOLVED };
// What the server already knows without asking Civitai - its library and
// earlier lookups - which is all a local_only request is answered from. The
// gallery asks it once, to label the Resources buttons.
const localAnswers = {};
const localCalls = [];

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({
            success: true, samplers: ['Euler'], schedulers: ['Simple'],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        const form = new URLSearchParams(String(init.body || ''));
        const asked = form.get('hashes') || '';
        if (form.get('local_only') === 'true') {
            localCalls.push(asked);
            const resolved = {};
            for (const hash of asked.split(',')) {
                if (hash in localAnswers) resolved[hash] = localAnswers[hash];
            }
            return { ok: true, json: async () => ({ success: true, resolved,
                deferred: asked.split(',').filter((h) => !(h in localAnswers)) }) };
        }
        resolveCalls.push(asked);
        if (resolver.hold) await resolver.hold;
        const wanted = asked.split(',').filter(Boolean);
        const now = resolver.cap ? wanted.slice(0, resolver.cap) : wanted;
        const resolved = {};
        for (const hash of now) {
            if (hash in resolver.answers) resolved[hash] = resolver.answers[hash];
        }
        return { ok: true, json: async () => ({
            success: true, resolved,
            deferred: resolver.cap ? wanted.slice(resolver.cap) : [] }) };
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

// The button counts what the panel would list - duplicates once, the model
// itself not at all - from what is known. It used to add the two lists up
// raw: "Resources (8)" over a panel of five.
await waitFor('the known answers', () => localCalls.length === 1);
check('the gallery asks the server what it already knows, once, and asks Civitai nothing',
      [(localCalls[0] || '').split(',').sort(), resolveCalls.length],
      [['aaaaaaaaaa', 'bbbbbbbbbb', 'cccccccccc', 'dddddddddd'], 0]);
check('with four hashes not looked up yet, the count is a floor: the two Civitai names '
      + 'and the one hash-less file, with more to come',
      button.textContent.trim(), 'Resources (3+)');

const showing = window.mmShowResources(0);
check('the panel goes up before the lookups finish, not after',
      !!panel() && panel().textContent.includes('Looking up 4 more'), true);
check('already showing what needed no lookup',
      names('tr:not(.mm-res-unresolved)').includes('Space Worlds'), true);
await showing;
await waitFor('the lookups', () => !!panel() && !panel().textContent.includes('Looking up'));

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

const listed = offered.length + unresolved.length;       // 3 offered, 2 not found
check('once looked up, the button says exactly what the panel lists',
      [document.querySelector('[data-resources-index="0"]')?.textContent.trim(), listed],
      ['Resources (5)', 5]);

// ------------------------------------------------------------- in rounds
// The server asks Civitai about a bounded number per request and defers the
// rest, so a big image resolves over several requests, showing what it has
// after each.
resolver.cap = 1;
resolveCalls.length = 0;
const rounds = window.mmShowResources(0);
await waitFor('a first round', () => resolveCalls.length >= 1);
await rounds;
check('a capped server is asked again for what it deferred', resolveCalls.length, 4);
check('each round asks only for what is still outstanding',
      resolveCalls.map((c) => c.split(',').length), [4, 3, 2, 1]);
check('and the finished panel is the same as in one go',
      names('tr:not(.mm-res-unresolved)').sort(),
      ['Sci-fi Environments', 'Space Worlds', 'VAE ft MSE']);
resolver.cap = null;

// ----------------------------------------------- what could not be checked
// A hash whose lookup failed is not the same as one Civitai does not know.
resolver.answers = { ...RESOLVED };
delete resolver.answers.dddddddddd;
await window.mmShowResources(0);
await waitFor('the panel', () => !!panel() && !panel().textContent.includes('Looking up'));
const reasons = Array.from(panel().querySelectorAll('.mm-res-unresolved'))
    .map((row) => row.querySelector('.mm-res-actions').textContent.trim());
check('a lookup that got no answer says it could not be checked',
      reasons.includes('could not be checked'), true);
check('rather than claiming Civitai does not have it',
      reasons.includes('not on Civitai'), false);
resolver.answers = RESOLVED;

// ------------------------------------------------ a newer panel wins
// The panel repaints after each round, so a slow one - many hashes, no API
// key - could paint over one opened after it. It must not.
let release;
resolver.hold = new Promise((resolve) => { release = resolve; });
const slow = window.mmShowResources(0);
await waitFor('the slow lookup to be in flight', () => resolveCalls.length > 0);

// Meanwhile the panel is closed and a different one opened in its place.
document.querySelector('.mm-modal-overlay')?.remove();
document.body.insertAdjacentHTML('beforeend',
    '<div class="mm-modal-overlay"><div class="mm-modal mm-resources-modal" id="newer-panel"></div></div>');
resolver.hold = null;
await window.mmShowResources(0);
const newer = panel();

release();
await slow;
check('the older lookup does not paint over the panel opened after it',
      panel() === newer, true);

done();
