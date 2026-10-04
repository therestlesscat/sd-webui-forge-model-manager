/**
 * What the server's ui-options say to the page, asked once for it: whether
 * there is a Civitai API key, whether your generations are shown, which
 * judges NSFW, and how a gallery opens. Asked again when the settings are
 * saved.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING } = await shared('core.mjs');
const { showTab, tabButton, tabShowing } = await shared('tabs.mjs');

/**
 * Show a tab's "no Civitai API key" banner, once both halves exist.
 *
 * Without a key the rate limit is 0.5 requests a second rather than 6, the
 * tRPC endpoint carrying image prompts refuses outright, and some models will
 * not download - so most of what this extension does either crawls or quietly
 * fails, and both tabs need to say so.
 *
 * Nothing orders the two things this needs. The answer comes from a fetch
 * started at import, from a <script type="module"> in the head; the markup
 * appears when Gradio renders the tab. Applying it at fixed moments failed,
 * because whichever ran first found the other half missing. So it waits for
 * both, briefly, rather than guessing when they will be ready.
 *
 * The answer is fetched once however many tabs ask for it.
 */
const API_KEY_BANNER_TRIES = 20;        // 5 seconds, at 250ms apart

let apiKeyMissing = null;
let apiKeyRequest = null;
let uiOptionsRequest = null;

/** The server's ui-options, as they are now. A failed call answers null. */
function fetchUiOptions() {
    return fetch('/model-manager/ui-options', { cache: 'no-store' })
        .then((r) => r.json())
        .catch(() => null);
}

/**
 * The same, asked once for the page: whether there is an API key, and which
 * judges NSFW.
 */
export function uiOptions() {
    uiOptionsRequest ||= fetchUiOptions();
    return uiOptionsRequest;
}

export function apiKeyStatus() {
    if (apiKeyMissing !== null) return Promise.resolve(apiKeyMissing);
    if (!apiKeyRequest) {
        apiKeyRequest = uiOptions()
            .then((data) => {
                if (!data) throw new Error('ui-options did not answer');
                // Answered even when the rest of that call failed.
                apiKeyMissing = data.has_api_key === false;
                return apiKeyMissing;
            })
            .catch(() => {
                // Unreachable is not the same as unconfigured; say nothing
                // rather than blame the key for a WebUI that is not answering.
                apiKeyMissing = false;
                return false;
            });
    }
    return apiKeyRequest;
}

/** Whether the page knows there is no API key: false until ui-options has said. */
export function apiKeyIsMissing() {
    return apiKeyMissing === true;
}

const apiKeyBanners = new Set();

/**
 * Forget what the page was told by ui-options, after the settings window
 * saved: the API key banner and the NSFW note are asked again - for every
 * tab, which share this module's one copy (#53).
 */
export function refreshUiOptions() {
    uiOptionsRequest = null;
    apiKeyMissing = null;
    apiKeyRequest = null;
    nsfwDetectionAsked = null;
    apiKeyBanners.forEach((bannerId) => showApiKeyBanner(bannerId));
    return loadNsfwDetection();
}

export function showApiKeyBanner(bannerId, attempt = 0) {
    apiKeyStatus();                     // starts the one fetch, if needed
    apiKeyBanners.add(bannerId);

    const banner = document.getElementById(bannerId);
    if (apiKeyMissing === null || !banner) {
        if (attempt < API_KEY_BANNER_TRIES) {
            setTimeout(() => showApiKeyBanner(bannerId, attempt + 1), TIMING.drawRetry);
        }
        return;
    }

    banner.style.display = apiKeyMissing ? 'flex' : 'none';
}

/**
 * Put the banners back after Gradio has redrawn the page.
 *
 * Gradio re-renders a gr.HTML block wholesale, and an inline style set on
 * something inside it does not survive that - the element comes back as the
 * markup declares it, which is hidden. Setting it once during startup is
 * therefore not enough: it has to be reasserted whenever the UI is rebuilt,
 * which is what this hook is for.
 */
if (typeof onAfterUiUpdate === 'function') {
    onAfterUiUpdate(() => {
        if (apiKeyMissing === null) return;
        apiKeyBanners.forEach((bannerId) => {
            const banner = document.getElementById(bannerId);
            if (banner) banner.style.display = apiKeyMissing ? 'flex' : 'none';
        });
    });
}

// ------------------------------------------------------ your generations
// "Your generations" off: nothing is recorded, and every tab of them goes -
// at once, without a restart: the Generations tab's button is hidden (from
// the next start the tab is not created at all), and each model's gallery
// shows only its Civitai images. What was recorded is kept. Known from
// ui-options, and again when the setting is saved, in the settings window or
// on the Settings page. Once for the page: the tabs share one copy of this
// module, under one version (#53).

let generationsOn;          // undefined until the server says

/** Whether your generations are shown: false only once the server said so. */
export function generationsEnabled() {
    return generationsOn !== false;
}

function applyGenerationsEnabled() {
    const button = tabButton('generations');
    if (!button) return;
    const off = !generationsEnabled();
    button.style.display = off ? 'none' : '';
    // Off while its tab shows: to the Model Manager, rather than a tab whose button is gone.
    if (off && tabShowing('generations')) showTab('modelManager');
}

/** Take a new answer: hide or show, and tell the tabs (the gallery listens). */
export function setGenerationsEnabled(enabled) {
    const changed = generationsOn !== undefined && generationsOn !== enabled;
    generationsOn = enabled;
    applyGenerationsEnabled();
    if (changed) window.dispatchEvent(new CustomEvent('mm-generations-enabled', { detail: { enabled } }));
}

// ------------------------------------------------------------- paths shown
// A file's path as the pages show it, the same for every kind of file: under
// a folder Forge was given on the command line, from that option -
// --lora-dir\x.safetensors - else from Forge's own folder -
// models\text_encoder\y.safetensors. Only what follows \models\ was shown,
// and an embedding, not under it, showed its whole path. A path under none -
// the other WebUI's, sharing the database, in a folder this Forge was not
// given - shows whole: cut, it would read as this Forge's. The folders are
// the server's (model_dirs.shown_roots), longest first.

let pathRoots = [];         // [label, folder]; none until the server says

export function shownPath(path) {
    if (!path) return '';
    const lower = path.toLowerCase();
    for (const [label, folder] of pathRoots) {
        const base = String(folder || '').replace(/[\\/]+$/, '');
        if (!base || lower.slice(0, base.length) !== base.toLowerCase()) continue;
        if (path.length === base.length) return label || path;
        const separator = path.charAt(base.length);
        if (separator !== '\\' && separator !== '/') continue;
        const rest = path.slice(base.length + 1);
        return label ? label + separator + rest : rest;
    }
    return path;
}

if (typeof window !== 'undefined' && typeof fetch === 'function') {
    uiOptions().then((data) => {
        if (data && typeof data.generations_enabled === 'boolean') setGenerationsEnabled(data.generations_enabled);
        if (data && Array.isArray(data.path_roots)) pathRoots = data.path_roots;
    });
    // Saved in the settings window: its answer says the setting's new value.
    window.addEventListener?.('mm-settings-saved', (event) => {
        const value = event.detail?.settings?.model_manager_record_generations?.value;
        if (typeof value === 'boolean') setGenerationsEnabled(value);
    });
    // Applied on the Settings page: which keys changed is known, not their values.
    window.addEventListener?.('mm-settings-page-applied', (event) => {
        if (!(event.detail?.changed || []).includes('model_manager_record_generations')) return;
        fetchUiOptions().then((data) => {
            if (data && typeof data.generations_enabled === 'boolean') setGenerationsEnabled(data.generations_enabled);
        });
    });
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(applyGenerationsEnabled);
}

// ---------------------------------------------------- which judges prompts
// The settings' NSFW detection: a trained model, or the word
// list alone. The model is sometimes wrong in ways nobody can point at, so
// wherever it decides what is hidden, the page says so and where to switch.
// The word list says nothing: it does exactly what it says.

// Text, not markup: some pages set it as textContent. So it says where the
// setting is rather than linking to it.
export const NSFW_MODEL_NOTE = 'NSFW is judged by a trained model, which can be wrong. '
    + 'NSFW detection, in the settings (\u2699 at the top right of the tab), switches to a simple word list.';

let nsfwDetection = null;
let nsfwDetectionAsked = null;

/** Ask the server which judges prompts; once per page. */
export function loadNsfwDetection() {
    nsfwDetectionAsked ||= uiOptions()
        .then((data) => { nsfwDetection = data?.nsfw_detection === 'model' ? 'model' : 'words'; });
    return nsfwDetectionAsked;
}

/**
 * How a model's gallery opens, as the settings say now: asked each time a
 * model is opened, not once per page, so a change on the Settings page applies
 * to the next model without a reload. Hidden, both, if the server cannot say.
 *
 * @returns {Promise<{hideNsfw: boolean, hidePromptless: boolean}>}
 */
export async function galleryDefaults() {
    const data = await fetchUiOptions();
    return { hideNsfw: data?.gallery_hide_nsfw !== false,
             hidePromptless: data?.hide_promptless_images !== false,
             // The Generations tab's own; a model's Your generations follows hideNsfw.
             generationsHideNsfw: data?.generations_hide_nsfw !== false };
}

/** The note, while the trained model is in force; '' otherwise, or before the answer. */
export function nsfwModelNote() {
    return nsfwDetection === 'model' ? NSFW_MODEL_NOTE : '';
}
