/**
 * What the server's ui-options say to the page, asked once for it: whether
 * there is a Civitai API key, which judges NSFW, how a gallery opens, and
 * which tabs are on - which shared/loading.mjs acts on. Asked again when the
 * settings are saved.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, once } = await shared('core.mjs');

/**
 * Show a tab's "no Civitai API key" banner, once both halves exist.
 *
 * Without a key the rate limit is 0.5 requests a second rather than 6, the
 * tRPC endpoint carrying image prompts refuses outright, and some models will
 * not download - so most of what this extension does either crawls or quietly
 * fails, and both tabs need to say so.
 *
 * Nothing orders the two things this needs. The answer comes from a fetch
 * a tab starts as its script runs, from a <script type="module"> in the
 * head; the markup appears when Gradio renders the tab. Applying it at fixed moments failed,
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
export function fetchUiOptions() {
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
 * which is what this hook is for. Run from start(), below.
 */
function keepApiKeyBanners() {
    if (apiKeyMissing === null) return;
    apiKeyBanners.forEach((bannerId) => {
        const banner = document.getElementById(bannerId);
        if (banner) banner.style.display = apiKeyMissing ? 'flex' : 'none';
    });
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

/**
 * Asked once, by the first tab that starts this module (#182): the page's
 * ui-options, and the banners kept after each update. Which tabs are on, and
 * their switches followed as they are saved: shared/loading.mjs (#183).
 */
export const start = once(() => {
    if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(keepApiKeyBanners);
    if (typeof window === 'undefined' || typeof fetch !== 'function') return;
    uiOptions().then((data) => {
        if (data && Array.isArray(data.path_roots)) pathRoots = data.path_roots;
    });
});

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
