/**
 * Send to txt2img or img2img: Forge set up for an image, then its settings
 * pasted as Forge's own PNG Info sends them (#91). A gallery image's Send
 * (sendGalleryImage) and one of your own generations' (sendInfotext) both
 * come here, from the Model Manager and the Generations tab alike - which
 * once sent only through the Model Manager's script, and so not at all
 * without it.
 *
 * Forge's VAE / Text Encoder control, its UI preset and the server's send
 * plan for a model, the sampler and scheduler an image names, its infotext
 * and the paste, and an image-to-video model's start frame. The LoRAs and
 * embeddings a send leaves under the prompt are chips.mjs's.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, apiCall } = await shared('core.mjs');
const { showTab } = await shared('tabs.mjs');
const { originalMediaUrl, isVideoUrl, videoCopyUrl } = await shared('media.mjs');
const {
    collectResourceChips, renameLoraTags, resourceChipSources, fetchImageFiles, arrangeChips,
    showResourceChips, lookUpMissingChips, updateResourceChipStates,
} = await shared('chips.mjs');
const { videoFrames, videoSize } = await shared('wan.mjs');
const { showImageResources } = await shared('resources.mjs');
const { splitSamplerScheduler } = await shared('samplers.mjs');

/** Where a generation's settings go: back to the tab it was made in. */
export function sendTab(card) {
    return card?.mode === 'img2img' ? 'img2img' : 'txt2img';
}

/**
 * Send one of your own generations' infotexts back to the tab it was made
 * in - `mode`, txt2img or img2img - as the Generations tab and this one's
 * generation cards both do.
 *
 * Forge is first set up as the generation was made with, from its record
 * (api/generations.send_plan): its checkpoint's UI preset, the checkpoint,
 * and after the paste exactly the modules it loaded - the same for every kind
 * of model. The paste alone did none of it: Forge Neo ignores the checkpoint
 * and modules an infotext names by default, and an SD 1.5 image, naming no
 * modules, left an Anima model's in place.
 *
 * @returns {Promise<boolean>} whether it could be pasted
 */
export async function sendInfotext({ infotext, mode, meta = {}, generationId = null }) {
    if (!infotext) return false;
    meta = meta || {};
    let plan = null;
    if (generationId !== null && generationId !== undefined) {
        try {
            const answer = await apiCall({ endpoint: `/model-manager/generations/${Number(generationId)}/send-plan` });
            plan = answer && answer.success ? answer : null;
        } catch (error) {
            console.warn('[ModelManager] Could not ask how the generation was made:', error);
        }
    }
    if (plan?.preset) await switchForgePreset(plan.preset);
    if (plan?.checkpoint && typeof selectCheckpoint === 'function') {
        console.log('[ModelManager] Setting checkpoint:', plan.checkpoint);
        selectCheckpoint(plan.checkpoint);
    }
    let scheduler = meta['Schedule type'];
    if (!scheduler && meta.sampler) scheduler = splitSamplerScheduler(meta.sampler).scheduler;
    const hasHiresFix = meta['Denoising strength'] &&
        (meta['Hires upscale'] || meta['Hires upscaler'] || meta['Hires resize-1'] || meta['Hires resize-2']);
    const tab = sendTab({ mode });
    // An earlier send's chips would stay; this one's come from its own record.
    showResourceChips(tab, []);
    const image = { meta };
    // Its LoRAs and embeddings as chips, as a Civitai image's Send shows them:
    // the server gives your images a Civitai image's `resources`. A LoRA the
    // prompt names otherwise than its file - by its alias, as Forge writes it
    // with "Alias from file" - is pasted under the file's name, as there: its
    // chip names the file, and is lit only by a tag with that name.
    const files = meta.resources?.length ? await fetchImageFiles(image) : null;
    const resources = files ? collectResourceChips(meta, files, null) : null;
    if (resources) {
        infotext = resources.renames.reduce((text, { from, to }) => renameLoraTags(text, from, to), infotext);
    }
    const afterPaste = plan ? () => applyRecordedModules(plan) : undefined;
    if (!pasteInfotext(tab, infotext, { scheduler, hasHiresFix, afterPaste })) return false;
    showGenerationTab(tab);
    if (resources) {
        resourceChipSources[tab] = { img: image, gallery: null, files };
        showResourceChips(tab, arrangeChips(resources.chips, resourceChipSources[tab]));
        lookUpMissingChips(tab);
    }
    if (tab === 'img2img') {
        showNotice('The settings are in img2img. The image this generation started from '
                   + 'is not kept: drop an image in before generating.');
    }
    return true;
}

// Convert full file path to dropdown-compatible path
// Full: F:\...\models\Stable-diffusion\_SD_1_5\model.safetensors
// Dropdown: _SD_1_5/model.safetensors (relative to type folder)
function getDropdownPath(filePath, modelType) {
    if (!filePath) return null;

    // Map model types to their folder names
    const typeFolderMap = {
        'Checkpoint': 'Stable-diffusion',
        'LORA': 'Lora',
        'TextualInversion': 'embeddings',
        'VAE': 'VAE',
        'Controlnet': 'ControlNet',
        'Upscaler': 'ESRGAN',
    };

    const typeFolder = typeFolderMap[modelType];
    if (!typeFolder) return null;

    // Find the type folder in the path and take everything after it
    // Match: /Stable-diffusion/ or \Stable-diffusion\
    // Escape special regex chars in folder name, then match separator + folder + separator
    const escapedFolder = typeFolder.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`[\\\\\/]${escapedFolder}[\\\\\/](.+)$`, 'i');
    const match = filePath.match(regex);

    if (match) {
        // Return path as-is (preserve original separators)
        return match[1];
    }

    return null;
}

// Match VAE name from metadata to dropdown option
// Metadata often has VAE without extension, dropdown has with extension
// Forge Neo's "VAE / Text Encoder" control: a Gradio multiselect backed by
// the forge_additional_modules setting. Classic Forge and A1111 instead
// expose a single-value #setting_sd_vae plus a selectVAE() global, which
// Neo does not have at all - so the old reset-to-None silently did nothing
// there and whatever was selected last stayed selected.
const NEO_MODULES_ID = 'setting_sd_modules';

const MODULES_LABEL = 'VAE / Text Encoder';

/**
 * Find the multiselect holding the VAE / Text Encoder modules.
 *
 * Neo gives it elem_id="setting_sd_modules". Classic Forge builds the same
 * gr.Dropdown with no elem_id and no elem_classes, so there it has to be
 * found by its label. Both render Gradio's div.wrap-inner, which is also
 * what Neo's own modelHelp.js keys off.
 */
function getModulesControl() {
    const app = gradioApp();

    const byId = app.querySelector(`#${NEO_MODULES_ID}`);
    if (byId) return byId;

    for (const span of app.querySelectorAll('span')) {
        if (!span.textContent.trim().startsWith(MODULES_LABEL)) continue;
        // Climb to the ancestor that actually holds the selection.
        let node = span.parentElement;
        while (node) {
            if (node.querySelector('div.wrap-inner')) return node;
            node = node.parentElement;
        }
    }

    return null;
}

function nextFrame(ms = 60) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/** The options Gradio is currently offering, as {label, element} pairs. */
function readModuleOptions(container) {
    // The open list is portalled in some Gradio builds, so fall back to a
    // document-wide lookup - only one dropdown can be open at a time.
    let nodes = container.querySelectorAll('[data-testid="dropdown-option"]');
    if (!nodes.length) {
        nodes = gradioApp().querySelectorAll('[data-testid="dropdown-option"]');
    }
    return Array.from(nodes).map((el) => ({
        label: el.getAttribute('aria-label') || el.textContent.trim(),
        element: el,
    }));
}

/**
 * Match a VAE name from image metadata to one of `labels`.
 *
 * Metadata usually carries the bare name while the control lists the file,
 * so "vae-ft-mse-840000" has to find "vae-ft-mse-840000.safetensors".
 */
function matchVAEName(vaeName, labels) {
    if (!vaeName) return null;
    if (!labels || !labels.length) return vaeName;

    if (labels.includes(vaeName)) return vaeName;

    const wanted = vaeName.toLowerCase();
    for (const label of labels) {
        const lower = label.toLowerCase();
        if (lower.startsWith(wanted) ||
            lower.replace(/\.(safetensors|sft|gguf|pt|ckpt|bin)$/i, '') === wanted) {
            console.log('[ModelManager] Matched VAE:', vaeName, '->', label);
            return label;
        }
    }

    console.log('[ModelManager] No VAE match found for:', vaeName);
    return null;
}

/**
 * Commit a choice in Gradio's open option list.
 *
 * The list is bound to mousedown, not click: element.click() dispatches a
 * click event only, so the list opens and then nothing is ever selected.
 * The token remove buttons are the other way round and do take click.
 */
function pressOption(element) {
    element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
}

/** Drop every module currently selected. */
function clearModules(container) {
    // One ✕ clears the lot; otherwise drop the tokens one by one. Both are
    // real click paths, so Gradio commits the change to the setting.
    const removeAll = container.querySelector('.token-remove.remove-all');
    if (removeAll) {
        removeAll.click();
        return;
    }
    container.querySelectorAll('.token .token-remove, .token > .token-remove')
        .forEach((button) => button.click());
}

/** A token's label: its text, less the ✕ that removes it. */
function tokenLabel(token) {
    return token.textContent.replace(/\s*×\s*$/, '').trim();
}

function selectedModuleLabels(container) {
    return Array.from(container.querySelectorAll('.wrap-inner .token'))
        .map(tokenLabel)
        .filter(Boolean);
}

/**
 * Make Forge's VAE / Text Encoder control hold exactly `target`, with as few
 * changes to it as there can be: what is there and wanted stays, what is
 * extra is removed one by one, what is missing is added. Nothing different,
 * nothing touched.
 *
 * Every change to that control is a request of Forge's own, each carrying
 * the whole selection as it stands, and they can land out of order: after
 * the old clear-and-reselect, Neo would sometimes load an Anima model with no
 * VAE, the control showing it all the while. So the fewer changes, the fewer
 * chances. The whole control is cleared only if one file cannot be taken out
 * alone.
 *
 * @param {string[]} target - the labels, exactly as Forge lists them.
 * @returns {Promise<boolean>} false when the control is absent (not Forge).
 */
async function patchForgeModules(target) {
    const container = getModulesControl();
    if (!container) return false;

    const current = selectedModuleLabels(container);
    const extra = current.filter((label) => !target.includes(label));
    let missing = target.filter((label) => !current.includes(label));
    if (!extra.length && !missing.length) {
        console.log('[ModelManager] VAE / Text Encoder already as needed:', current);
        return true;
    }

    for (const label of extra) {
        const token = Array.from(container.querySelectorAll('.wrap-inner .token'))
            .find((t) => tokenLabel(t) === label);
        const remove = token && token.querySelector('.token-remove');
        if (!remove) {
            console.warn(`[ModelManager] Could not take "${label}" out on its own; clearing the lot`);
            clearModules(container);
            await nextFrame();
            missing = [...target];
            break;
        }
        remove.click();
        await nextFrame();
    }

    const input = container.querySelector('input');
    for (const label of missing) {
        if (!input) break;
        input.focus();
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await nextFrame();

        const option = readModuleOptions(container).find((o) => o.label === label);
        if (!option) {
            console.warn(`[ModelManager] "${label}" is not offered by the control; left out`);
            continue;
        }
        pressOption(option.element);
        await nextFrame();
    }
    input?.blur();
    console.log('[ModelManager] VAE / Text Encoder: removed', extra, 'added', missing,
                'now', selectedModuleLabels(container));
    return true;
}

/**
 * Ask Forge what it holds now, and say so if it is not `target`: the control
 * can show one thing while Forge's setting - what it loads - holds another.
 * Only said, for now, so that it is seen before anything is done about it.
 * Forge takes each change on a request of its own, so it is given a moment.
 */
async function checkForgeModules(target) {
    const wanted = [...target].sort();
    const deadline = Date.now() + TIMING.modulesCheckMax;
    let held = null;
    for (;;) {
        try {
            const answer = await (await fetch('/model-manager/forge-modules/current')).json();
            held = answer && answer.modules;
        } catch (e) {
            return;
        }
        if (!Array.isArray(held)) return;                 // not Forge: nothing to compare
        if (held.length === wanted.length && held.every((label, i) => label === wanted[i])) return;
        if (Date.now() >= deadline) break;
        await nextFrame(TIMING.modulesCheck);
    }
    const list = (labels) => (labels.length ? labels.join(', ') : 'nothing');
    showNotice(`Forge did not take the VAE / Text Encoder change: it holds ${list(held)}, `
               + `where the image needs ${list(wanted)}. Check "VAE / Text Encoder" before generating.`);
}

/**
 * Point Neo's VAE / Text Encoder control at exactly `names`.
 *
 * An image whose metadata names no VAE must end up with none selected:
 * leaving a previous pick in place is how a Qwen VAE ends up decoding an
 * SDXL latent, which produces a flat single-colour image.
 *
 * Returns false when the control is absent, i.e. this is not Forge Neo.
 */
async function applyForgeModules(names) {
    const container = getModulesControl();
    if (!container) return false;

    clearModules(container);
    await nextFrame();

    if (!names.length) {
        console.log('[ModelManager] Cleared VAE / Text Encoder (none in metadata)');
        return true;
    }

    const input = container.querySelector('input');
    if (!input) {
        console.warn('[ModelManager] VAE control has no input; left cleared');
        return true;
    }

    for (const name of names) {
        input.focus();
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await nextFrame();

        const options = readModuleOptions(container);
        const match = matchVAEName(name, options.map((o) => o.label));
        const option = match && options.find((o) => o.label === match);

        if (!option) {
            console.warn(`[ModelManager] VAE "${name}" is not offered by this install;`
                         + ' leaving it unselected rather than guessing');
            continue;
        }

        pressOption(option.element);
        await nextFrame();
    }

    input.blur();
    console.log('[ModelManager] VAE / Text Encoder now:', selectedModuleLabels(container));
    return true;
}

/**
 * The VAE an image was made with, whatever Civitai called the field.
 *
 * Counted over 67,458 stored images, a VAE name turns up under several
 * spellings, and they do not overlap:
 *
 *   VAE       11,304   the usual A1111 field
 *   vaes       2,392   a list, from ComfyUI workflows Civitai normalised.
 *                      Every one of these has no VAE field at all, so
 *                      reading only VAE misses them entirely
 *   vae_name      62   ComfyUI's own node field, when it survives
 *   Vae / vae     13   case, as written by whatever made the image
 *
 * "VAE hash" is deliberately not read: it identifies a file we cannot
 * name, and a hash in the dropdown would match nothing.
 */
/**
 * Does this name a file, or is it a way of saying "no separate VAE"?
 *
 * Seen in the library: "Default (model)" 131, "automatic" 30, "Default"
 * 14, "Baked VAE" 5. All of them mean the checkpoint's own VAE, which is
 * what an empty selection already gives, so they must not be searched for
 * in the dropdown.
 */
function isVaeFileName(value) {
    const name = String(value || '').trim();
    if (!name) return false;
    return !/^(automatic|none|null|default.*|baked vae|use same vae)$/i.test(name);
}

function vaeFromMeta(meta) {
    if (!meta) return null;

    const direct = meta.VAE || meta.Vae || meta.vae || meta.vae_name;
    if (typeof direct === 'string' && isVaeFileName(direct)) return direct.trim();

    // ComfyUI workflows arrive with a list, newest-normalised first.
    const listed = Array.isArray(meta.vaes)
        ? meta.vaes.find(v => typeof v === 'string' && isVaeFileName(v))
        : null;
    if (listed) return listed.trim();

    const resource = (meta.resources || []).find(r => r && r.type === 'vae');
    if (resource && resource.name) return resource.name;

    return null;
}

// ------------------------------------------------ Forge Neo UI preset + modules
// An image's generation data never names a Flux model's CLIP-L and T5-XXL, or
// a Qwen-Image model's Qwen2.5-VL - whoever made it had them loaded. So
// before sending, the server works out the model's architecture from its file
// (or Civitai's baseModel), and which of the modules it needs are installed
// (architecture.py, forge_modules.py); the send then switches Forge's UI
// preset to match, and selects them.

// What the server calls each kind of module, as a person would.
const MODULE_KIND_NAMES = {
    clip_l: 'CLIP-L', clip_g: 'CLIP-G', t5xxl: 'T5-XXL', umt5xxl: 'UMT5-XXL',
    qwen25_7b: 'Qwen2.5-VL 7B', qwen3_06b: 'Qwen3 0.6B', qwen3_4b: 'Qwen3 4B',
    qwen3_8b: 'Qwen3 8B', qwen3vl_4b: 'Qwen3-VL 4B', gemma2_2b: 'Gemma 2 2B',
    ministral3_3b: 'Ministral 3 3B', vae_ae: 'Flux VAE (ae)', vae_flux2: 'Flux.2 VAE',
    vae_wan21: 'Qwen-Image / Wan VAE', vae_sd: 'SD VAE',
};

/** What a version's file is: read from it, else Civitai's type meanwhile. */
function fileTypeOf(entry, model) {
    return entry.file_type || entry.model_type || (model && model.civitai_type) || null;
}

/**
 * The checkpoint an image names: the Civitai version ids of its resources
 * filed as checkpoints, the hashes its generation data gives the model, and
 * the model's name. The server matches them against the library, and asks
 * Civitai about one it does not have.
 */
function imageCheckpoint(img) {
    const meta = (img && img.meta) || {};
    const versionIds = (meta.civitaiResources || [])
        .filter((r) => String(r.type || '').toLowerCase() === 'checkpoint' && r.modelVersionId)
        .map((r) => r.modelVersionId);
    const hashes = (meta.resources || [])
        .filter((r) => r.type === 'model' && r.hash)
        .map((r) => r.hash);
    if (meta['Model hash']) hashes.push(meta['Model hash']);
    return { versionIds, hashes: [...new Set(hashes)], name: meta.Model || '' };
}

/**
 * What to set up in Forge for an image: its UI preset, and the modules to
 * select. Which model that is for - the gallery's checkpoint, the image's
 * own, a LoRA's, Civitai's say - the server works out (send_plan.py).
 * null if the server cannot say.
 */
async function fetchForgePlan(model, version, img, vae) {
    if (!model) return null;
    const checkpoint = imageCheckpoint(img);
    const params = new URLSearchParams();
    if (version.file_path) params.set('file_path', version.file_path);
    const baseModel = version.base_model || model.base_model;
    if (baseModel) params.set('base_model', baseModel);
    if (checkpoint.versionIds.length) params.set('version_ids', checkpoint.versionIds.join(','));
    if (checkpoint.hashes.length) params.set('hashes', checkpoint.hashes.join(','));
    if (checkpoint.name) params.set('model_name', checkpoint.name);
    if (vae) params.set('vae', vae);
    try {
        const response = await fetch('/model-manager/forge-modules?' + params.toString());
        const plan = await response.json();
        return plan && plan.success ? plan : null;
    } catch (e) {
        console.warn('[ModelManager] Could not work out the model\'s architecture:', e);
        return null;
    }
}

/**
 * Forge's UI preset as it stands, or null where there is none. Neo shows it
 * as a dropdown; the original Forge as radio buttons (sd, xl, flux, all).
 */
function currentForgePreset() {
    const container = gradioApp().querySelector('#forge_ui_preset');
    if (!container) return null;
    if (container.querySelector('input[type="radio"]')) {
        return container.querySelector('input[type="radio"]:checked')?.value || null;
    }
    return container.querySelector('input')?.value || null;
}

/**
 * Switch Forge Neo's UI preset, and wait for it to take.
 *
 * Done before anything of the image is sent: a preset change resets the
 * sampler, scheduler and steps to its defaults and restores its saved
 * modules, which would overwrite what the image asked for. Forge's own
 * scripts read the preset from this control's input, so that is what is
 * waited on, then a moment for the rest of the change to land.
 *
 * Returns whether Forge is now on `preset`. False where this is not Forge
 * Neo, or the preset is not offered - and then the send goes on as before.
 */
async function switchForgePreset(preset) {
    const container = gradioApp().querySelector('#forge_ui_preset');
    const input = container?.querySelector('input');
    if (!input || !preset) return false;
    if (currentForgePreset() === preset) return true;
    watchForgeCalls();
    const callsBefore = forgeCalls.started;

    // The original Forge's radio buttons: press the one for the preset. The
    // dropdown path below would type into a radio's value - which it did,
    // clearing the first choice's.
    const radios = Array.from(container.querySelectorAll('input[type="radio"]'));
    if (radios.length) {
        const radio = radios.find((r) => r.value === preset);
        if (!radio) {
            console.warn(`[ModelManager] Forge offers no "${preset}" preset; left as it was`);
            return false;
        }
        radio.click();
        return await presetTaken(preset, callsBefore);
    }

    input.focus();
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await nextFrame();
    const option = readModuleOptions(container).find((o) => o.label === preset);
    if (!option) {
        input.blur();
        console.warn(`[ModelManager] Forge offers no "${preset}" preset; left as it was`);
        return false;
    }
    pressOption(option.element);
    input.blur();
    return await presetTaken(preset, callsBefore);
}

/**
 * The calls Gradio makes to the server for a control's events. They go to
 * <root>/run/<event> through the page's fetch - in Forge Neo's Gradio 4.39
 * and the original Forge's 4.40 alike - so wrapping fetch sees each one start
 * and finish.
 */
const forgeCalls = { started: 0, inFlight: 0, last: 0 };

function watchForgeCalls() {
    if (globalThis.fetch?.mmWatched) return;
    const original = globalThis.fetch;
    const watched = function(resource, ...rest) {
        let path = '';
        try {
            path = new URL(typeof resource === 'string' ? resource : resource?.url || String(resource),
                           window.location.origin).pathname;
        } catch { /* not a URL we can read: not one of Gradio's */ }
        if (!path.includes('/run/')) return original.call(this, resource, ...rest);
        forgeCalls.started++;
        forgeCalls.inFlight++;
        forgeCalls.last = Date.now();
        const settle = () => { forgeCalls.inFlight--; forgeCalls.last = Date.now(); };
        const call = original.call(this, resource, ...rest);
        call.then(settle, settle);
        return call;
    };
    watched.mmWatched = true;
    globalThis.fetch = watched;
}

/**
 * Wait for a preset change to show, then for Forge to finish answering it.
 *
 * Forge answers from the server, with no progress shown: the preset's
 * sampler, scheduler, steps, size and CFG, then - chained on that - its
 * checkpoint and modules. Each lands when the server is done. A fixed 600 ms
 * lost to a slow answer (a Krea model's, sent from the Model Manager): the
 * image's settings went in first and the preset's defaults then overwrote
 * them. So wait until every call started since the switch has come back and
 * none has started for a moment - the chained one starts as the first ends.
 * A switch that makes no call at all is given the old 600 ms.
 */
async function presetTaken(preset, callsBefore = forgeCalls.started) {
    const start = Date.now();
    for (let i = 0; i < 30 && currentForgePreset() !== preset; i++) await nextFrame(100);
    while (Date.now() - start < FORGE_PRESET_MAX_MS) {
        const called = forgeCalls.started > callsBefore;
        if (called && forgeCalls.inFlight === 0 && Date.now() - forgeCalls.last >= FORGE_PRESET_QUIET_MS) break;
        if (!called && Date.now() - start >= FORGE_PRESET_SETTLE_MS) break;
        await nextFrame(50);
    }
    await nextFrame(100);   // Gradio writes the last answer into the page after it arrives
    console.log('[ModelManager] Forge UI preset now:', currentForgePreset(),
                `(${forgeCalls.started - callsBefore} server calls, ${Date.now() - start} ms)`);
    return currentForgePreset() === preset;
}

// How long a preset switch is waited on: TIMING in core.mjs.
const FORGE_PRESET_SETTLE_MS = TIMING.presetSettle;

const FORGE_PRESET_QUIET_MS = TIMING.presetQuiet;

const FORGE_PRESET_MAX_MS = TIMING.presetMax;

/**
 * Select the modules the plan picked, and say what it could not find.
 * Called after the paste: it re-renders much of the page but never touches
 * the modules. Every model goes this way, SD and SDXL too - theirs is the
 * image's own VAE, or none.
 */
async function applyPlannedModules(plan, vaeName) {
    const target = plan.target || plan.select || [];
    if (await patchForgeModules(target)) {
        await checkForgeModules(target);
    } else if (!plan.manage_modules) {
        await applyVaeSelection(vaeName);      // no Forge control: the A1111 way
    }
    const problems = [];
    if (plan.missing && plan.missing.length) {
        const names = plan.missing.map((kind) => MODULE_KIND_NAMES[kind] || kind).join(', ');
        problems.push(`This ${plan.preset} model also needs ${names}, which is not installed. `
                      + 'Add it to Forge\'s VAE or text_encoder folder, or select it in "VAE / Text Encoder".');
    }
    if (plan.not_found && plan.not_found.length) {
        problems.push(`The settings (\u2699 at the top right of the tab, under "Send to txt2img: text encoders `
                      + `and VAE") name ${plan.not_found.join(', ')} for ${plan.preset} models, but Forge does not `
                      + 'list it: check the name, or put the file in Forge\'s VAE or text_encoder folder.');
    }
    if (plan.own_not_listed) {
        problems.push(`Forge does not list ${plan.own_not_listed} in "VAE / Text Encoder", so it is not selected: `
                      + 'it is in a folder this WebUI does not load, or was added since Forge started.');
    }
    if (plan.vae_not_found) {
        console.warn(`[ModelManager] VAE "${plan.vae_not_found}" is not installed; none selected`);
    }
    // A checkpoint that carries its own text encoders or VAE gets none of
    // those selected - Forge uses the checkpoint's - and says so: an empty
    // "VAE / Text Encoder" read as a send that had failed.
    let bundled = '';
    if (plan.bundled && plan.bundled.length) {
        const names = listNames(plan.bundled.map((kind) => MODULE_KIND_NAMES[kind] || kind));
        bundled = target.length
            ? `This checkpoint brings its own ${names}: only what it lacks is selected in "VAE / Text Encoder".`
            : `This checkpoint brings its own ${names}: nothing is selected in "VAE / Text Encoder", `
              + 'and Forge uses the checkpoint\'s.';
    }
    if (problems.length) showNotice([...problems, bundled].filter(Boolean).join(' '));
    else if (bundled) showNotice(bundled, { info: true });
}

/**
 * A generation's own modules, after the paste, as applyPlannedModules() does a
 * Civitai image's: patched to exactly what was loaded, checked with Forge, and
 * what is no longer there said.
 */
async function applyRecordedModules(plan) {
    const target = plan.target || [];
    if (await patchForgeModules(target)) await checkForgeModules(target);
    const gone = [];
    if (plan.checkpoint_missing) gone.push(`its checkpoint ${plan.checkpoint_missing}`);
    if (plan.modules_missing?.length) gone.push(plan.modules_missing.join(', '));
    if (gone.length) {
        showNotice(`This generation was made with ${gone.join(' and ')}, which Forge does not list any more: `
                   + 'the rest is sent, and the current choice is kept for what is missing.');
    }
}

/**
 * A send stopped for the image's checkpoint: said at the top of the image's
 * Resources dialog, where a missing one can be downloaded - or, for an image
 * with no resources to list, in a notice. Nothing is moved or downloaded by
 * itself.
 */
async function stopForCheckpoint(img, version, problem) {
    const made = `The checkpoint this image was made with, ${problem.name}`;
    const note = {
        missing: `${made}, is not in your library. Download it here, then send the image again.`,
        elsewhere: `${made}, is in your library at ${problem.path}, a folder this WebUI does not load. `
                   + 'Move it into this WebUI\'s models folder, or download it here; then send the image again.',
        not_listed: `${made}, is in your library at ${problem.path}, but Forge does not list it yet: `
                    + 'refresh Forge\'s checkpoint list, then send the image again.',
        not_checkpoint: 'This image does not say which checkpoint it was made with: what it names as one is '
                        + 'not a checkpoint, in your library or on Civitai.',
    }[problem.reason];
    if (!note) return;
    console.log('[ModelManager] Not sent:', note);
    if (!await showImageResources(img, version?.id, { note })) showNotice(note);
}

/** A short message in the corner of the page, gone after a while. */
/**
 * A notice in the corner, for twelve seconds. `info` is something to know
 * rather than something wrong: drawn and logged as such.
 */
function showNotice(text, { info = false } = {}) {
    const notice = document.createElement('div');
    notice.className = info ? 'mm-notice mm-notice-info' : 'mm-notice';
    notice.textContent = text;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 12000);
    (info ? console.log : console.warn)('[ModelManager]', text);
}

/** "a", "a and b", "a, b and c". */
function listNames(names) {
    return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0] || '';
}

/**
 * An image's generation data with a video's frames and size added: Civitai
 * keeps neither its length nor its frame rate, so they are read from the
 * video itself. A copy is read rather than the upload - the upload can be a
 * GIF under an .mp4 name (sizedMediaUrl), whose length a video element
 * cannot read. What cannot be read is left to the preset, and said.
 */
async function withVideoParams(meta, img, isVideo = true) {
    const params = { ...meta };
    const [w, h] = String(meta.Size || '').split('x').map(Number);
    if ((w || img.width) && (h || img.height)) {
        const size = videoSize(w || img.width, h || img.height);
        params.Size = `${size.width}x${size.height}`;
    }
    if (!isVideo) return params;
    const frames = videoFrames(await videoDuration(videoCopyUrl(img)));
    if (frames) params['Batch size'] = frames;
    else showNotice('Could not read this video\'s length: Frames are left as the Wan preset has them.');
    return params;
}

/**
 * The image an image-to-video model starts from, as a file for img2img, or
 * null. Civitai does not keep the one the uploader used, so for a video it is
 * the first frame - after the video's encoding, and any upscaling since, but
 * the nearest there is. The original first; if the browser cannot decode it
 * (an animated upload is kept as a GIF under an .mp4 name) the card's copy,
 * which is small. For a still, the still.
 */
async function startFrame(img, isVideo) {
    const name = `civitai-${img.id || 'image'}`;
    if (!isVideo) {
        try {
            const response = await fetch(originalMediaUrl(img.url));
            const blob = response.ok ? await response.blob() : null;
            return blob ? { file: new File([blob], name, { type: blob.type }), small: false } : null;
        } catch (error) {
            console.warn('[ModelManager] Could not fetch the image:', error);
            return null;
        }
    }
    let blob = await firstFrame(originalMediaUrl(img.url));
    const small = !blob;
    if (!blob) blob = await firstFrame(videoCopyUrl(img));
    return blob ? { file: new File([blob], `${name}.png`, { type: 'image/png' }), small } : null;
}

/**
 * A video's first frame as a PNG, or null. Drawn from a video element onto a
 * canvas: Civitai's image server allows it (CORS), and if it ever stops, the
 * canvas refuses to export - an error, never a blank frame. Only enough of
 * the file is fetched to decode one frame.
 */
function firstFrame(url, timeoutMs = 20000) {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        let settled = false;
        const finish = (blob) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            video.removeAttribute('src');
            video.load();
            resolve(blob || null);
        };
        const timer = setTimeout(() => finish(null), timeoutMs);
        video.crossOrigin = 'anonymous';
        video.muted = true;
        video.preload = 'auto';
        video.onloadeddata = () => {
            try {
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                canvas.toBlob(finish, 'image/png');
            } catch (error) {
                console.warn('[ModelManager] Could not read the video\'s first frame:', error);
                finish(null);
            }
        };
        video.onerror = () => finish(null);
        video.src = url;
    });
}

/** Load a file into img2img's image, as its Upload button would. */
function giveImg2imgImage(file) {
    const input = gradioApp().querySelector('#img2img_image input[type="file"]');
    if (!input || typeof DataTransfer === 'undefined') return false;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
}

/** The gallery's own file, described as the server describes one. */
function galleryFile(model, version) {
    if (!version || !version.file_path) return null;
    const name = version.file_path.split(/[\\/]/).pop();
    return { file_stem: name.replace(/\.[^.]+$/, ''), file_type: fileTypeOf(version, model) };
}

/** Show txt2img, or img2img on its plain img2img mode - by their ids (shared/tabs.mjs). */
function showGenerationTab(tab) {
    if (tab === 'img2img') {
        showTab('img2img');
        showTab('img2imgMode');
        return;
    }
    showTab('txt2img');
}

/** A video's length in seconds, from its metadata alone; null if unreadable. */
function videoDuration(url, timeoutMs = 10000) {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        const finish = (seconds) => {
            clearTimeout(timer);
            video.removeAttribute('src');
            video.load();
            resolve(seconds);
        };
        const timer = setTimeout(() => finish(null), timeoutMs);
        video.preload = 'metadata';
        video.muted = true;
        video.onloadedmetadata = () => finish(Number.isFinite(video.duration) ? video.duration : null);
        video.onerror = () => finish(null);
        video.src = url;
    });
}

/**
 * Apply a VAE choice on whichever UI this is.
 *
 * `vaeName` of null means the image named none, which must clear the
 * selection rather than leave the last one in place.
 */
async function applyVaeSelection(vaeName) {
    if (await applyForgeModules(vaeName ? [vaeName] : [])) return;

    // Classic Forge / A1111.
    if (typeof selectVAE === 'function') {
        selectVAE(vaeName || 'None');
        console.log('[ModelManager] Set VAE via selectVAE:', vaeName || 'None');
        return;
    }

    console.warn('[ModelManager] No VAE control found; leaving it alone');
}


/**
 * A prompt without the double quotes around the whole of it. Some tools
 * write the prompt to Civitai as a quoted string, and pasted as it is, a
 * model reading prompts as instructions took it all as one quotation: a
 * Krea 2 model drew noise from 35 such prompts. Only a pair around the
 * whole, with no other quote inside - '"a" and "b"' is two quotations.
 * Of 84,677 prompts in one library, 60 were wrapped; 56 of them so.
 */
function unquotePrompt(text) {
    const trimmed = String(text ?? '').trim();
    const inner = trimmed.slice(1, -1);
    return trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"') && !inner.includes('"')
        ? inner.trim() : text;
}

// Build infotext string from image metadata (A1111 format)
function buildInfotext(meta, { denoisingStrength = null } = {}) {
    if (!meta) return '';

    let infotext = '';

    // Prompt
    const prompt = unquotePrompt(meta.prompt);
    if (prompt) {
        infotext += prompt;
    }

    // Negative prompt
    const negativePrompt = unquotePrompt(meta.negativePrompt);
    if (negativePrompt) {
        infotext += '\nNegative prompt: ' + negativePrompt;
    }

    // Split sampler if it contains scheduler
    let sampler = meta.sampler;
    let scheduler = meta['Schedule type'];

    // If no explicit scheduler, try to extract from combined sampler string
    if (!scheduler && sampler) {
        const split = splitSamplerScheduler(sampler);
        sampler = split.sampler;
        scheduler = split.scheduler;
    }

    // Check if this has actual hires fix data (need all required fields)
    // Only include Denoising strength and hires fields if there's a complete hires setup
    const hasHiresFix = meta['Denoising strength'] &&
        (meta['Hires upscale'] || meta['Hires upscaler'] || meta['Hires resize-1'] || meta['Hires resize-2']);

    // Build parameters line
    const params = [];

    if (meta.steps) params.push(`Steps: ${meta.steps}`);
    if (sampler) params.push(`Sampler: ${sampler}`);
    if (scheduler) params.push(`Schedule type: ${scheduler}`);
    if (meta.cfgScale) params.push(`CFG scale: ${meta.cfgScale}`);
    if (meta.seed) params.push(`Seed: ${meta.seed}`);
    if (meta.Size) params.push(`Size: ${meta.Size}`);
    if (meta.Model) params.push(`Model: ${meta.Model}`);
    if (meta['Model hash']) params.push(`Model hash: ${meta['Model hash']}`);
    if (meta.VAE) params.push(`VAE: ${meta.VAE}`);
    if (meta['Clip skip']) params.push(`Clip skip: ${meta['Clip skip']}`);

    // img2img always takes one - an image-to-video model needs 1 - and
    // txt2img only as part of a hires fix, where it would otherwise turn
    // hires on for an image that had none.
    const denoise = denoisingStrength ?? (hasHiresFix ? meta['Denoising strength'] : null);
    if (denoise !== null && denoise !== undefined) params.push(`Denoising strength: ${denoise}`);

    // Only include hires-related fields if there's a complete hires fix setup
    // This prevents paste from enabling hires when image doesn't have hires data
    if (hasHiresFix) {
        if (meta['Hires upscale']) params.push(`Hires upscale: ${meta['Hires upscale']}`);
        if (meta['Hires upscaler']) params.push(`Hires upscaler: ${meta['Hires upscaler']}`);
        if (meta['Hires steps']) params.push(`Hires steps: ${meta['Hires steps']}`);
    }

    // Add any other parameters from meta that we haven't explicitly handled
    // Lora hashes are not pasted: see withoutLoraHashes().
    const handledKeys = ['prompt', 'negativePrompt', 'steps', 'sampler', 'Schedule type', 'cfgScale', 'seed',
                        'Size', 'Model', 'Model hash', 'VAE', 'Denoising strength', 'Clip skip',
                        'Hires upscale', 'Hires upscaler', 'Hires steps', 'Hires resize-1', 'Hires resize-2',
                        'resources', 'civitaiResources', 'Lora hashes'];

    // Check if ADetailer fields exist - toggle "ADetailer enable" accordingly
    // This is required for ADetailer's paste handler to auto-enable/disable the checkbox
    const hasADetailer = Object.keys(meta).some(key => key.startsWith('ADetailer '));
    if (hasADetailer) {
        params.push('ADetailer enable: True');
    } else {
        params.push('ADetailer enable: False');
    }

    for (const [key, value] of Object.entries(meta)) {
        if (!handledKeys.includes(key) && value !== null && value !== undefined && value !== '') {
            if (typeof value !== 'object') {
                params.push(`${key}: ${value}`);
            }
        }
    }

    if (params.length > 0) {
        infotext += '\n' + params.join(', ');
    }

    return infotext;
}

// Set Gradio dropdown value programmatically
function setGradioDropdown(elem_id, value) {
    const container = gradioApp().querySelector(`#${elem_id}`);
    if (!container) {
        console.warn(`[ModelManager] Dropdown not found: ${elem_id}`);
        return false;
    }

    // Try input element (common in newer Gradio)
    const input = container.querySelector('input');
    if (input) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`[ModelManager] Set ${elem_id} via input:`, value);
        return true;
    }

    // Try select element
    const select = container.querySelector('select');
    if (select) {
        select.value = value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`[ModelManager] Set ${elem_id} via select:`, value);
        return true;
    }

    console.warn(`[ModelManager] Could not find input/select in ${elem_id}`);
    return false;
}

// Send image generation params to txt2img using paste button
// The last send's work after the paste - scheduler, modules, hires - which
// runs on after a gallery's Send returns. Resolved once all of it is done.
let sendSettled = Promise.resolve();

/** Wait for the last send to finish setting Forge up. */
export function whenSendSettled() {
    return sendSettled;
}

/**
 * Put an infotext into a generation tab and press the tab's paste button, as
 * Forge's own "Send to txt2img" from PNG Info does; then, once the paste has
 * redrawn the page, what the paste leaves undone: the scheduler, which Forge
 * does not set from it, and hires fix, turned off when the infotext has none.
 * afterPaste runs at that point too, and may return a promise to wait for.
 * sendSettled waits for all of it.
 *
 * Used by both Sends: a Civitai image's, whose infotext is built from its
 * generation data, and one of your own generations', whose is its own.
 *
 * @returns {boolean} whether the paste could be made at all
 */
/**
 * An infotext without its Lora hashes. Forge's paste renames each LoRA they
 * list to its own choice of name for the file - its alias, with "Alias from
 * file" - over the file names Send has given them, which the chips name
 * (sd_forge_lora's infotext_pasted, the same in both WebUIs). Forge's own
 * settings let a paste ignore the field ("Ignore fields when reading
 * infotext"); this does so for a Send. Forge quotes the value - it holds
 * colons - and it is a field of the last line, the settings.
 */
function withoutLoraHashes(infotext) {
    const lines = String(infotext || '').split('\n');
    const last = lines.length - 1;
    lines[last] = lines[last].replace(/(^|,\s*)Lora hashes: "(?:[^"\\]|\\.)*"(\s*,\s*)?/,
                                      (match, before, after) => (before && after ? ', ' : ''));
    return lines.join('\n');
}

function pasteInfotext(tab, infotext, { scheduler, hasHiresFix, afterPaste } = {}) {
    // Both tabs' paste buttons are id="paste"; each sits in its own tab's
    // tools row.
    const promptTextarea = gradioApp().querySelector(`#${tab}_prompt textarea`);
    let pasteButton = gradioApp().querySelector(`#${tab}_tools #paste`);
    if (!pasteButton && tab === 'txt2img') {
        pasteButton = gradioApp().querySelector('#paste')
            || gradioApp().querySelector('#txt2img_paste');   // SD.Next and others
    }

    if (!promptTextarea) {
        console.error(`[ModelManager] Could not find ${tab} prompt textarea`);
        return false;
    }
    if (!pasteButton) {
        console.error('[ModelManager] Could not find paste button');
        return false;
    }

    promptTextarea.value = withoutLoraHashes(infotext);
    promptTextarea.dispatchEvent(new Event('input', { bubbles: true }));
    pasteButton.click();

    sendSettled = new Promise((settled) => setTimeout(async () => {
        setGradioDropdown(`${tab}_scheduler`, scheduler || 'Automatic');
        const pending = afterPaste ? afterPaste() : null;

        // Reset hires fix if the infotext has no hires data. InputAccordion
        // uses a hidden checkbox - its value is set and events dispatched.
        if (!hasHiresFix && tab === 'txt2img') {
            const hiresContainer = gradioApp().querySelector('#txt2img_hr-checkbox');
            const hiresCheckbox = hiresContainer?.querySelector('input[type="checkbox"]');
            if (hiresCheckbox && hiresCheckbox.checked) {
                hiresCheckbox.checked = false;
                hiresCheckbox.dispatchEvent(new Event('input', { bubbles: true }));
                hiresCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof inputAccordionChecked === 'function') {
                    inputAccordionChecked('txt2img_hr', false);
                }
                console.log('[ModelManager] Disabled hires fix (not in metadata)');
            }
        }
        await Promise.resolve(pending).catch(() => {});
        settled();
    }, 100));
    return true;
}

/**
 * Send a gallery image to txt2img - img2img for an image-to-video model -
 * with Forge set up for it: its UI preset, checkpoint, modules, scheduler and
 * hires fix, its LoRAs and embeddings as chips. `model` is the library's
 * model the gallery is of, `version` the one it shows.
 */
export async function sendGalleryImage({ img, model, version }) {
    const meta = img.meta;

    // Debug: log available size-related fields
    console.log('[ModelManager] Image size data:', {
        'meta.Size': meta.Size,
        'img.width': img.width,
        'img.height': img.height,
        'meta.width': meta.width,
        'meta.height': meta.height
    });

    // Ensure Size is set - try multiple sources
    if (!meta.Size) {
        if (img.width && img.height) {
            meta.Size = `${img.width}x${img.height}`;
        } else if (meta.width && meta.height) {
            meta.Size = `${meta.width}x${meta.height}`;
        }
    }

    try {
        // Forge's UI preset first: changing it resets what the image is about
        // to set. Anything failing here leaves the send as it was before.
        const filesAsked = fetchImageFiles(img);
        const plan = await fetchForgePlan(model, version, img, vaeFromMeta(meta));

        // The gallery's own file is loaded when it is a checkpoint - by what
        // the file is, so a VAE Civitai files as a "Checkpoint" is not. Any
        // other gallery's image needs its own checkpoint, the one thing a
        // send cannot go without: one Forge cannot load stops it (#134).
        const galleryIsCheckpoint = !!version && fileTypeOf(version, model) === 'Checkpoint';
        if (!galleryIsCheckpoint && plan?.checkpoint_problem) {
            await stopForCheckpoint(img, version, plan.checkpoint_problem);
            return;
        }

        // An image-to-video model starts from an image, which txt2img has
        // no way to give it - it failed in the sampler - so it goes to
        // img2img, with the image. Fetched meanwhile: the preset takes time.
        const isVideo = isVideoUrl({ url: img.url, type: img.type });
        const tab = plan && plan.video === 'i2v' ? 'img2img' : 'txt2img';
        const framing = tab === 'img2img' ? startFrame(img, isVideo) : null;

        if (plan && plan.preset) await switchForgePreset(plan.preset);

        // After the preset, which brings back a checkpoint of its own: the
        // gallery's, or the image's by the name Forge lists it under.
        const checkpointPath = galleryIsCheckpoint
            ? getDropdownPath(version.file_path, 'Checkpoint') : plan?.checkpoint || null;

        const vaePath = vaeFromMeta(meta);

        // Set checkpoint if available
        if (checkpointPath && typeof selectCheckpoint === 'function') {
            console.log('[ModelManager] Setting checkpoint:', checkpointPath);
            selectCheckpoint(checkpointPath);
        }

        // Extract scheduler from metadata or sampler string
        let scheduler = meta['Schedule type'];
        if (!scheduler && meta.sampler) {
            const split = splitSamplerScheduler(meta.sampler);
            scheduler = split.scheduler;
        }
        // Default to Automatic if no scheduler found
        scheduler = scheduler || 'Automatic';

        // Check if image has hires fix data (must match what paste button checks)
        // Paste enables hires if: "Denoising strength" AND ("Hires upscale" OR "Hires upscaler" OR "Hires resize-1")
        const hasHiresFix = meta['Denoising strength'] &&
            (meta['Hires upscale'] || meta['Hires upscaler'] || meta['Hires resize-1'] || meta['Hires resize-2']);

        // A video model makes a still unless it is told how many frames:
        // Neo reads Batch size as Frames on the Wan preset.
        let sendMeta = plan && plan.video
            ? await withVideoParams(meta, img, isVideo) : meta;

        // The image's LoRAs and embeddings, for the chips; a LoRA its prompt
        // names under another name than the file here is renamed to it.
        const files = await filesAsked;
        const resources = collectResourceChips(meta, files, galleryFile(model, version));
        if (resources.renames.length) {
            const rename = (text) => resources.renames
                .reduce((out, { from, to }) => renameLoraTags(out, from, to), text);
            sendMeta = { ...sendMeta, prompt: rename(sendMeta.prompt),
                         negativePrompt: rename(sendMeta.negativePrompt) };
        }

        // Build infotext from metadata
        const infotext = buildInfotext(sendMeta,
                                       { denoisingStrength: tab === 'img2img' ? 1 : null });
        if (!infotext) {
            console.error('[ModelManager] No infotext to send');
            return;
        }

        const pasted = pasteInfotext(tab, infotext, {
            scheduler,
            hasHiresFix,
            afterPaste: () => {
                updateResourceChipStates(tab);
                // After the paste: it re-renders much of the page, and it never
                // touches the modules itself - Neo reads "Module 1"/"Module 2"
                // from an infotext, not the "VAE:" line we write. A model whose
                // text encoders and VAE are separate gets the ones it needs; an
                // SD or SDXL one, the image's own VAE. With no plan - the
                // server did not answer - the image's VAE, the old way.
                return plan ? applyPlannedModules(plan, vaePath) : applyVaeSelection(vaePath);
            },
        });
        if (!pasted) return;

        showGenerationTab(tab);
        resourceChipSources[tab] = { img, gallery: galleryFile(model, version), files };
        showResourceChips(tab, arrangeChips(resources.chips, resourceChipSources[tab]));
        lookUpMissingChips(tab);

        // The start frame goes in once img2img is showing: its canvas sizes
        // the image to itself, and a hidden one has no size.
        if (framing) {
            const frame = await framing;
            if (!frame || !giveImg2imgImage(frame.file)) {
                showNotice('This image-to-video model needs a start image, and this one\'s could '
                           + 'not be loaded: drop an image into img2img before generating.');
            } else if (frame.small) {
                showNotice('The video could not be decoded at full size, so its start frame comes '
                           + 'from Civitai\'s small preview copy: consider a larger image.');
            }
        }

        console.log(`[ModelManager] Sent to ${tab} via paste:`, {
            infotextLength: infotext.length,
            prompt: meta.prompt?.substring(0, 50) + '...',
            checkpoint: checkpointPath,
            vae: vaePath,
            scheduler: scheduler,
            hasHiresFix: !!hasHiresFix,
            fullInfotext: infotext
        });

    } catch (error) {
        console.error('[ModelManager] Error sending to txt2img:', error);
    }
}
