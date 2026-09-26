// Send to txt2img sets Forge Neo up for the model first: its UI preset, and
// the text encoders and VAE the model needs.
//
// An image's generation data never names a Flux model's CLIP-L and T5-XXL -
// they were loaded already - and the send used to clear the modules whenever
// it named no VAE, which is every Flux, Qwen and Krea image. Now the server
// says what the model is and which modules to select (forge_modules_test.py
// covers how); the send switches the preset *before* anything of the image
// goes in, since a preset change resets the sampler, steps and modules, and
// selects the modules after the paste, which re-renders but never touches
// them. What is checked here is that order, and what is selected.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// ------------------------------------------------ a stand-in for Forge's page
const events = [];                       // what happened, in order
function dropdown(id, options, multi) {
    const root = document.createElement('div');
    root.id = id;
    root.innerHTML = '<div class="wrap-inner"></div><input><ul class="options"></ul>';
    const input = root.querySelector('input');
    const list = root.querySelector('ul');
    input.addEventListener('input', () => {        // typing opens the list
        list.innerHTML = '';
        for (const label of options) {
            const li = document.createElement('li');
            li.setAttribute('data-testid', 'dropdown-option');
            li.setAttribute('aria-label', label);
            li.textContent = label;
            li.addEventListener('mousedown', () => {          // Gradio commits on mousedown
                if (multi) {
                    const token = document.createElement('div');
                    token.className = 'token';
                    token.innerHTML = `${label}<span class="token-remove">×</span>`;
                    token.querySelector('.token-remove').addEventListener('click', () => token.remove());
                    root.querySelector('.wrap-inner').appendChild(token);
                } else {
                    input.value = label;
                    events.push(`preset:${label}`);
                }
                list.innerHTML = '';
            });
            list.appendChild(li);
        }
    });
    document.body.appendChild(root);
    return root;
}
const MODULE_FILES = ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors', 'sdxl_vae.safetensors'];
const preset = dropdown('forge_ui_preset', ['sd', 'xl', 'flux', 'qwen'], false);
preset.querySelector('input').value = 'sd';
const modules = dropdown('setting_sd_modules', MODULE_FILES, true);
const selected = () => Array.from(modules.querySelectorAll('.token'))
    .map((t) => t.textContent.replace(/×$/, '').trim());
// A leftover from whatever was generated last.
modules.querySelector('input').dispatchEvent(new window.Event('input', { bubbles: true }));
modules.querySelector('[aria-label="sdxl_vae.safetensors"]')
    .dispatchEvent(new window.Event('mousedown', { bubbles: true }));

const promptBox = document.createElement('div');
promptBox.id = 'txt2img_prompt';
promptBox.innerHTML = '<textarea></textarea>';
const paste = document.createElement('button');
paste.id = 'paste';
paste.addEventListener('click', () => events.push('paste'));
document.body.append(promptBox, paste);
window.selectCheckpoint = globalThis.selectCheckpoint = (name) => events.push(`checkpoint:${name}`);
Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });   // the send saves it
Object.defineProperty(document.documentElement, 'scrollTop', { value: 0, configurable: true });

// ------------------------------------------------------------- the server
const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'Flux.1 D', model_type: 'Checkpoint', file_path: 'C:/models/flux.safetensors',
    file_name: 'flux.safetensors', file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};
const IMAGE = { id: 1, url: 'https://example.invalid/1.jpeg', browsingLevel: 1,
    meta: { prompt: 'a lighthouse at dusk', steps: 20, sampler: 'Euler', cfgScale: 3.5,
            seed: 1, Size: '1024x1024' } };
let plan = null;
const planAsked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/model-manager/forge-modules')) {
        planAsked.push(new URL(href, 'http://webui').searchParams);
        if (plan === 'fail') throw new Error('server down');
        return { ok: true, json: async () => plan };
    }
    if (href.includes('/model-manager/ui-options')) {
        return { ok: true, json: async () => ({ success: true, samplers: ['Euler'],
            schedulers: ['Simple'], has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/models/details')) {
        return { ok: true, json: async () => ({ success: true, model: { ...MODEL, images: [IMAGE],
            images_state: { version_id: 5001, total_count: 1, hidden_nsfw: 0, hidden_promptless: 0 } } }) };
    }
    if (href.includes('/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [MODEL] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 1, page: 1, page_size: 20,
            models: [MODEL] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card').length > 0);

async function send() {
    events.length = 0;
    planAsked.length = 0;
    await window.mmSendToTxt2img(0);
    await new Promise((r) => setTimeout(r, 1500));       // the modules go in after the paste
}

// ------------------------------------------------------ a Flux checkpoint
plan = { success: true, preset: 'flux', manage_modules: true, source: 'file',
         select: ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'], missing: [] };
await send();
check('the plan is asked for by the checkpoint\'s own file',
      [planAsked[0]?.get('file_path'), planAsked[0]?.get('base_model')],
      ['C:/models/flux.safetensors', 'Flux.1 D']);
// (No checkpoint is set here: the harness has no checkpoint list to find it in.)
check('Forge\'s preset is switched before anything of the image is pasted',
      events.filter((e) => /^(preset|checkpoint|paste)/.test(e)).map((e) => e.split(':')[0])
          .filter((e) => e !== 'checkpoint'), ['preset', 'paste']);
check('to the model\'s', events[0], 'preset:flux');
check('and the modules it needs are selected, in place of the leftover VAE',
      selected(), ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors']);
check('nothing is missing, so nothing is said', document.querySelector('.mm-notice'), null);

// A preset already right is not switched again.
await send();
check('a preset already right is left alone', events.filter((e) => e.startsWith('preset')), []);

// ---------------------------------------------- a module not installed
plan = { ...plan, preset: 'qwen', select: ['ae.safetensors'], missing: ['qwen25_7b'] };
await send();
check('what nothing installed is, is said, by name',
      document.querySelector('.mm-notice')?.textContent.includes('Qwen2.5-VL 7B'), true);
check('while what is installed is still selected', selected(), ['ae.safetensors']);

// -------------------------------- a file the settings name, not installed
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
plan = { ...plan, not_found: ['qwen_2.5_vl_7b_q4.gguf'] };
await send();
const notices = Array.from(document.querySelectorAll('.mm-notice')).map((n) => n.textContent);
check('a file the settings name that Forge does not list is said, by name, in the same notice',
      [notices.length, notices[0]?.includes('Qwen2.5-VL 7B'),
       notices[0]?.includes('qwen_2.5_vl_7b_q4.gguf'), notices[0]?.includes('Settings')],
      [1, true, true, true]);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ---------------------------------------------------------- an SDXL model
plan = { success: true, preset: 'xl', manage_modules: false, select: [], missing: [] };
await send();
check('an SDXL model switches the preset too', events[0], 'preset:xl');
check('and keeps the image\'s own VAE, as before - none named, none selected', selected(), []);

// ------------------------------------------------------- the server failing
plan = 'fail';
await send();
check('with no plan, the send goes on as it did before',
      [events.includes('paste'), events.some((e) => e.startsWith('preset'))], [true, false]);

// ---------------------------------------------------------- a LoRA's gallery
// Which model the image is for is the server's to work out (send_plan.py):
// the image's own checkpoint first, if installed, then the LoRA's file. So
// the send passes the gallery's file whatever it is, and the checkpoint the
// image names - by Civitai version id, by hash, and by name.
plan = { success: true, preset: 'flux', manage_modules: true, select: [], missing: [] };
MODEL.model_type = 'LORA';
IMAGE.meta.Model = 'anima-preview2';
IMAGE.meta['Model hash'] = 'aaaa111122';
IMAGE.meta.resources = [{ type: 'model', name: 'anima-preview2', hash: '635cf338c923' },
                        { type: 'lora', name: 'a', hash: 'ffff' }];
IMAGE.meta.civitaiResources = [{ type: 'checkpoint', modelVersionId: 2764263 },
                               { type: 'Checkpoint', modelVersionId: 2089517 },
                               { type: 'LORA', modelVersionId: 5 }];
await send();
check('a gallery that is not a checkpoint\'s still sends its file, and its baseModel',
      [planAsked[0]?.get('file_path'), planAsked[0]?.get('base_model')],
      ['C:/models/flux.safetensors', 'Flux.1 D']);
check('with the checkpoint the image names: its version ids, of either spelling',
      planAsked[0]?.get('version_ids'), '2764263,2089517');
check('its hashes - the model resource\'s and the infotext\'s - and its name',
      [planAsked[0]?.get('hashes'), planAsked[0]?.get('model_name')],
      ['635cf338c923,aaaa111122', 'anima-preview2']);

// ------------------------------------------- an image-to-video model
// Sent to txt2img it failed in the sampler: an I2V model starts from an
// image, and txt2img has none to give. It goes to img2img instead, with the
// image - for a video its first frame, drawn onto a canvas - and a
// denoising strength of 1, which Neo asks of video models.
const tabs = document.createElement('div');
tabs.id = 'tabs';
for (const name of ['txt2img', 'img2img']) {
    const button = document.createElement('button');
    button.addEventListener('click', () => events.push(`tab:${name}`));
    tabs.appendChild(button);
}
const mode = document.createElement('div');
mode.id = 'mode_img2img';
mode.innerHTML = '<button></button>';
mode.querySelector('button').addEventListener('click', () => events.push('mode:img2img'));
const i2iPrompt = document.createElement('div');
i2iPrompt.id = 'img2img_prompt';
i2iPrompt.innerHTML = '<textarea></textarea>';
const i2iTools = document.createElement('div');
i2iTools.id = 'img2img_tools';
i2iTools.innerHTML = '<button id="paste"></button>';
i2iTools.querySelector('button').addEventListener('click', () => events.push('paste:img2img'));
const canvasBox = document.createElement('div');
canvasBox.id = 'img2img_image';
canvasBox.innerHTML = '<input type="file">';
const given = [];
canvasBox.querySelector('input').addEventListener('change', (e) => given.push(e.target.files[0]));
document.body.append(tabs, mode, i2iPrompt, i2iTools, canvasBox);
globalThis.DataTransfer = window.DataTransfer = class {
    constructor() { this.files = []; this.items = { add: (f) => this.files.push(f) }; }
};

// A browser's video and canvas, as far as the send uses them. `decodes`
// says which URLs play; the rest error, as a GIF under an .mp4 name does.
let decodes = () => true;
const loaded = [];
const createElement = document.createElement.bind(document);
document.createElement = (tag, ...rest) => {
    if (tag === 'video') {
        const video = { videoWidth: 1080, videoHeight: 1920, duration: 81 / 16,
                        removeAttribute() {}, load() {} };
        Object.defineProperty(video, 'src', { set(url) {
            loaded.push(url);
            setTimeout(() => {
                if (!decodes(url)) return video.onerror?.();
                video.onloadedmetadata?.();
                video.onloadeddata?.();
            }, 0);
        } });
        return video;
    }
    if (tag === 'canvas') {
        return { getContext: () => ({ drawImage() {} }),
                 toBlob: (done_) => done_(new Blob(['png'], { type: 'image/png' })) };
    }
    return createElement(tag, ...rest);
};
const fetchServer = globalThis.fetch;
globalThis.fetch = async (url, ...rest) => {
    if (String(url).startsWith('https://example.invalid/')) {
        return { ok: true, blob: async () => new Blob(['jpeg'], { type: 'image/jpeg' }) };
    }
    return fetchServer(url, ...rest);
};
const infotext = () => i2iPrompt.querySelector('textarea').value;
const clearNotices = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

const C = 'https://image.civitai.com/acct/8c0dc66f';
plan = { success: true, preset: 'wan', manage_modules: true, select: [], missing: [], video: 'i2v' };
IMAGE.url = `${C}/original=true/8c0dc66f.mp4`;
IMAGE.type = 'video';
IMAGE.meta = { prompt: 'waves roll in', steps: 4, sampler: 'Euler', cfgScale: 1, seed: 7 };
IMAGE.width = 1080;
IMAGE.height = 1920;
given.length = 0;
loaded.length = 0;
clearNotices();
await send();
check('an I2V model\'s video is pasted into img2img, not txt2img',
      [events.includes('paste:img2img'), events.includes('paste')], [true, false]);
check('and img2img is shown, on its img2img mode',
      [events.includes('tab:img2img'), events.includes('mode:img2img')], [true, true]);
check('with a denoising strength of 1', infotext().includes('Denoising strength: 1'), true);
check('its frames from the video\'s length, its size in Wan\'s steps',
      [infotext().includes('Batch size: 81'), infotext().includes('Size: 1088x1920')], [true, true]);
check('its first frame is loaded into img2img\'s image, as a PNG',
      [given.length, given[0]?.type, given[0]?.name], [1, 'image/png', 'civitai-1.png']);
check('drawn from the original, at full size', loaded.includes(`${C}/original=true/8c0dc66f.mp4`), true);
check('and nothing needs saying', document.querySelector('.mm-notice'), null);

IMAGE.url = `${C}/width=1080/8c0dc66f.mp4`;
loaded.length = 0;
await send();
check('whatever size the URL it came with asked for',
      loaded.includes(`${C}/original=true/8c0dc66f.mp4`), true);

decodes = (url) => !url.includes('original=true');
given.length = 0;
await send();
check('an original the browser cannot decode: the card\'s copy is used',
      [given.length, loaded.some((u) => u.includes('width=450'))], [1, true]);
check('and that it is small is said', document.querySelector('.mm-notice')?.textContent
      .includes('small preview copy'), true);
clearNotices();

decodes = () => false;
given.length = 0;
await send();
check('with no frame at all, the rest is still sent to img2img',
      [events.includes('paste:img2img'), given.length], [true, 0]);
check('and it says to drop an image in', Array.from(document.querySelectorAll('.mm-notice'))
      .some((n) => n.textContent.includes('drop an image into img2img')), true);
clearNotices();

decodes = () => true;
IMAGE.url = 'https://example.invalid/still.jpeg';
IMAGE.type = 'image';
given.length = 0;
await send();
check('a still in an I2V model\'s gallery starts from the still itself',
      [events.includes('paste:img2img'), given.length, given[0]?.type], [true, 1, 'image/jpeg']);

plan = { ...plan, video: 't2v' };
await send();
check('a text-to-video model still goes to txt2img',
      [events.includes('paste'), events.includes('paste:img2img'), events.includes('tab:txt2img')],
      [true, false, true]);
check('with no denoising strength of its own',
      promptBox.querySelector('textarea').value.includes('Denoising strength'), false);

// ---------------------------------------------------------- resource chips
// A send puts the image's LoRAs and embeddings under the negative prompt as
// chips. A click puts the tag in or takes it out; the chip is lit while a
// prompt holds it. Neo's paste splits the infotext into the two prompts.
const negRow = document.createElement('div');
negRow.id = 'txt2img_neg_prompt_row';
negRow.innerHTML = '<div id="txt2img_neg_prompt"><textarea></textarea></div>';
promptBox.after(negRow);
const positiveBox = promptBox.querySelector('textarea');
const negativeBox = negRow.querySelector('textarea');
paste.addEventListener('click', () => {
    const [prompt, rest = ''] = positiveBox.value.split('\nNegative prompt: ');
    positiveBox.value = prompt;
    negativeBox.value = rest.split('\n')[0];
});
const fetchBefore = globalThis.fetch;
const resourcesAsked = [];
const library = {
    versions: { 11: { version_id: 11, file_stem: 'add_detail', file_type: 'LORA' } },
    hashes: { aaaa: { version_id: 11, file_stem: 'add_detail', file_type: 'LORA' },
              bbbb: { version_id: 14, file_stem: 'easynegative', file_type: 'TextualInversion' } },
};
globalThis.fetch = async (url, ...rest) => {
    if (String(url).includes('/model-manager/image-resources')) {
        resourcesAsked.push(new URL(String(url), 'http://webui').searchParams);
        return { ok: true, json: async () => ({ success: true, ...structuredClone(library) }) };
    }
    const href = String(url);
    if (href.includes('/model-manager/civitai/download/progress')) {
        const id = Number(new URL(href, 'http://webui').searchParams.get('version_id'));
        return { ok: true, json: async () => ({ success: true, progress: chipProgress[id] || null }) };
    }
    if (href.includes('/model-manager/civitai/download')) {
        const form = new URLSearchParams(String(rest[0]?.body || ''));
        chipDownloads.push(Object.fromEntries(form));
        const id = Number(form.get('version_id'));
        return { ok: true, json: async () => ({ success: true, version_id: id, version_name: 'v1',
            substituted: false, progress: { version_id: id, percent: 0, status: 'pending' } }) };
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        return { ok: true, json: async () => ({ success: true, deferred: [],
            resolved: { cccc: { version_id: 98, model_id: 97 },
                        dddd: { version_id: null, model_id: null } } }) };
    }
    return fetchBefore(url, ...rest);
};
const chipDownloads = [];
const chipProgress = {};

plan = { success: true, preset: 'flux', manage_modules: false, select: [], missing: [] };
IMAGE.meta = {
    prompt: 'a cat, <lora:UploaderName_v2:0.8>', negativePrompt: 'easynegative, blurry',
    steps: 20, sampler: 'Euler', cfgScale: 3.5, seed: 1,
    civitaiResources: [{ type: 'lora', modelVersionId: 11, name: 'Detail Tweaker', weight: 0.8 },
                       { type: 'lora', modelVersionId: 99, name: 'Not Here' }],
    resources: [{ type: 'lora', name: 'UploaderName_v2', hash: 'AAAA', weight: 0.8 },
                { type: 'embed', name: 'easynegative', hash: 'bbbb' },
                { type: 'lora', name: 'hash_only', hash: 'cccc' },
                { type: 'lora', name: 'private_merge', hash: 'dddd' },
                { type: 'lora', name: 'no_hash' }],
};
await send();
const row = () => document.getElementById('mm_resource_chips_txt2img');
const chip = (name) => Array.from(row()?.querySelectorAll('[data-chip]') || [])
    .find((b) => b.querySelector('.mm-resource-chip-name')?.textContent.trim() === name);
const click = (element) => element.dispatchEvent(new window.Event('click', { bubbles: true }));

check('the image\'s resources are looked up by version id and hash',
      [resourcesAsked[0]?.get('version_ids'), resourcesAsked[0]?.get('hashes')], ['11,99', 'aaaa,bbbb,cccc,dddd']);
check('its chips sit under the negative prompt', negRow.nextElementSibling?.id, 'mm_resource_chips_txt2img');
check('one per LoRA and embedding, the gallery\'s own LoRA first',
      Array.from(row().querySelectorAll('.mm-resource-chip-name')).map((b) => b.textContent.trim()),
      ['flux', 'add_detail', 'Not Here', 'easynegative', 'hash_only', 'private_merge', 'no_hash']);
check('a LoRA the prompt named otherwise is pasted under the local file\'s name, weight kept',
      [positiveBox.value, positiveBox.value.includes('UploaderName')], ['a cat, <lora:add_detail:0.8>', false]);
check('what a prompt already holds is lit, the rest not',
      ['flux', 'add_detail', 'easynegative'].map((n) => chip(n).classList.contains('active')),
      [false, true, true]);
const note = (name) => chip(name)?.querySelector('.mm-resource-chip-note')?.textContent;
check('one with no file here says it is missing, and that a click downloads it',
      note('Not Here'), 'missing LoRA, click to download');
await waitFor('the hashes to be checked', () => note('private_merge') === 'not on Civitai');
check('one known by a hash Civitai has: downloadable too', note('hash_only'), 'missing LoRA, click to download');
check('one whose hash Civitai has never heard of says so, and offers nothing',
      [note('private_merge'), chip('private_merge').disabled], ['not on Civitai', true]);
check('nor one the image names with no hash or version at all',
      [note('no_hash'), chip('no_hash').disabled], ['no hash recorded', true]);

click(chip('flux'));
check('a click puts a LoRA in at the image\'s weight, else 0.5',
      [positiveBox.value, chip('flux').classList.contains('active')],
      ['a cat, <lora:add_detail:0.8>, <lora:flux:0.5>', true]);
click(chip('flux'));
check('a second takes it out', [positiveBox.value, chip('flux').classList.contains('active')],
      ['a cat, <lora:add_detail:0.8>', false]);
click(chip('easynegative'));
check('an embedding the negative prompt holds comes out of the negative prompt',
      [negativeBox.value, positiveBox.value], ['blurry', 'a cat, <lora:add_detail:0.8>']);
click(chip('easynegative'));
check('and goes back into it', negativeBox.value, 'blurry, easynegative');

positiveBox.value = 'a cat, <lora:flux:1.1>';
positiveBox.dispatchEvent(new window.Event('input', { bubbles: true }));
check('the chips follow the prompt as it is typed',
      [chip('flux').classList.contains('active'), chip('add_detail').classList.contains('active')],
      [true, false]);

// A missing chip downloads its resource when clicked - the version the image
// names, as the Resources dialog does - and adds nothing to the prompt.
const before = positiveBox.value;
chipProgress[99] = { version_id: 99, percent: 40.6, status: 'downloading', synced: false };
click(chip('Not Here'));
await waitFor('the download', () => chipDownloads.length === 1);
check('a click on a missing chip downloads the version the image names',
      [chipDownloads[0].version_id, chipDownloads[0].newer_if_gone], ['99', 'true']);
await waitFor('progress', () => chip('Not Here')?.textContent.includes('40%'), 4000);
check('the chip shows how it is going, and takes no clicks meanwhile',
      [chip('Not Here').querySelector('.mm-resource-chip-note')?.textContent, chip('Not Here').disabled],
      ['40%', true]);
library.versions[99] = { version_id: 99, file_stem: 'not_here', file_type: 'LORA' };
chipProgress[99] = { version_id: 99, percent: 100, status: 'complete', synced: true };
await waitFor('the chips to be looked up again', () => !!chip('not_here'), 5000);
check('once in the library it is a chip like any other, under the file\'s name',
      [chip('not_here')?.disabled, chip('not_here')?.classList.contains('missing'), !!chip('Not Here')],
      [false, false, false]);
check('and nothing was added to the prompt', positiveBox.value, before);

click(chip('hash_only'));
await waitFor('the hash to be looked up and downloaded', () => chipDownloads.length === 2);
check('a chip that knows only a hash is looked up first, then downloaded by version and model',
      [chipDownloads[1].version_id, chipDownloads[1].model_id], ['98', '97']);

click(row().querySelector('[data-chips-clear]'));
check('Clear takes the chips away', row(), null);
check('and leaves the prompts as they were', [positiveBox.value, negativeBox.value],
      ['a cat, <lora:flux:1.1>', 'blurry, easynegative']);

IMAGE.meta = { prompt: 'a lighthouse', steps: 20 };
MODEL.model_type = 'Checkpoint';
await send();
check('an image with nothing to chip shows no row', row(), null);

// ------------------------------------------------ the original Forge
// The extension runs in the original Forge too, whose UI preset is a row of
// radio buttons (sd, xl, flux, all) rather than Neo's dropdown. The send
// typed into it as if it were a dropdown, clearing the first radio's value.
preset.remove();
const radios = document.createElement('div');
radios.id = 'forge_ui_preset';
for (const value of ['sd', 'xl', 'flux', 'all']) {
    const label = document.createElement('label');
    label.innerHTML = `<input type="radio" name="forge-ui" value="${value}"${value === 'sd' ? ' checked' : ''}>`;
    const radio = label.querySelector('input');
    // A browser checks the one clicked and unchecks the rest; the harness does not.
    radio.click = () => {
        radios.querySelectorAll('input').forEach((r) => { r.checked = r === radio; });
        events.push(`preset:${value}`);
    };
    radios.appendChild(label);
}
document.body.appendChild(radios);
const radioValues = () => Array.from(radios.querySelectorAll('input')).map((r) => r.value);
const checkedPreset = () => radios.querySelector('input:checked')?.value;

plan = { success: true, preset: 'xl', manage_modules: false, select: [], missing: [] };
await send();
check('a radio preset control is switched by pressing the preset\'s own button',
      [checkedPreset(), events[0]], ['xl', 'preset:xl']);
check('without touching any button\'s value', radioValues(), ['sd', 'xl', 'flux', 'all']);
check('and the image is still sent after it', events.includes('paste'), true);

plan = { ...plan, preset: 'qwen' };
await send();
check('a preset the original Forge does not have is left alone',
      [checkedPreset(), radioValues(), events.some((e) => e.startsWith('preset'))],
      ['xl', ['sd', 'xl', 'flux', 'all'], false]);
check('and the send goes on without it', events.includes('paste'), true);

done();
