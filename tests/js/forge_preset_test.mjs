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
import { ROOT, act, checker, mountTab, sharedModule, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page's waits and polls, shortened: the fake server answers at once,
// and the same order of events happens ten times faster. See TIMING.
window.mmTiming = { poll: 100, scanPoll: 50, presetSettle: 60, presetQuiet: 40, presetMax: 3000, estimate: 10,
                    modulesCheck: 20, modulesCheckMax: 200 };
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
                    token.querySelector('.token-remove').addEventListener('click', () => {
                        token.remove();
                        events.push(`module-:${label}`);
                    });
                    root.querySelector('.wrap-inner').appendChild(token);
                    events.push(`module+:${label}`);
                } else {
                    input.value = label;
                    events.push(`preset:${label}`);
                    forgeAnswersPreset?.(label);
                }
                list.innerHTML = '';
            });
            list.appendChild(li);
        }
    });
    document.body.appendChild(root);
    return root;
}
// Forge's server side of a preset change, when a section wants one: see
// "a slow preset change" below.
let forgeAnswersPreset = null;
let forgeDelay = 0;
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
let generationPlan = null;               // a generation of your own's send plan
// What Forge's setting holds, asked after the modules are set: as a rule what
// the control shows. A section that wants Forge to disagree sets it.
let forgeHolds = () => selected();
globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    if (href.includes('/run/')) {
        await new Promise((r) => setTimeout(r, forgeDelay));
        return { ok: true, json: async () => ({ data: [] }) };
    }
    if (href.includes('/send-plan')) return { ok: true, json: async () => generationPlan };
    if (href.includes('/model-manager/forge-modules/current')) {
        return { ok: true, json: async () => ({ success: true, modules: [...forgeHolds()].sort() }) };
    }
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
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
// The last send's work after its paste, as the tab's copy of send.mjs keeps it.
const { sendInfotext, whenSendSettled } = await sharedModule('send.mjs');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card').length > 0);

async function send() {
    events.length = 0;
    planAsked.length = 0;
    await act('modelManager.sendImage', { index: 0 });
    await whenSendSettled();                        // the modules go in after the paste
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
       notices[0]?.includes('qwen_2.5_vl_7b_q4.gguf'),
       notices[0]?.includes('The settings (\u2699 at the top right of the tab, under "Send to txt2img')],
      [1, true, true, true]);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ------------------------------------ a checkpoint that brings its own
// An all-in-one checkpoint carries its text encoders and VAE, and gets none
// selected - Forge uses the checkpoint's. Said, as information: an empty
// "VAE / Text Encoder" read as a send that had failed.
const notices_ = () => Array.from(document.querySelectorAll('.mm-notice'));
plan = { success: true, preset: 'flux', manage_modules: true, source: 'file', select: [], target: [],
         missing: [], bundled: ['clip_l', 't5xxl', 'vae_ae'] };
await send();
check('a checkpoint that brings its own: nothing selected, and a notice saying so, as information',
      [selected(), notices_().map((n) => [n.className, n.textContent])],
      [[], [['mm-notice mm-notice-info', 'This checkpoint brings its own CLIP-L, T5-XXL and Flux VAE (ae): '
             + 'nothing is selected in "VAE / Text Encoder", and Forge uses the checkpoint\'s.']]]);
notices_().forEach((n) => n.remove());
plan = { ...plan, bundled: ['clip_l', 't5xxl'], select: [], target: [], missing: ['vae_ae'] };
await send();
check('with a problem too, one notice says both - the problem first',
      notices_().map((n) => [n.className, n.textContent]),
      [['mm-notice', 'This flux model also needs Flux VAE (ae), which is not installed. Add it to Forge\'s VAE '
        + 'or text_encoder folder, or select it in "VAE / Text Encoder". This checkpoint brings its own CLIP-L '
        + 'and T5-XXL: nothing is selected in "VAE / Text Encoder", and Forge uses the checkpoint\'s.']]);
notices_().forEach((n) => n.remove());

// ---------------------------------------------------------- an SDXL model
plan = { success: true, preset: 'xl', manage_modules: false, select: [], missing: [], target: [] };
await send();
check('an SDXL model switches the preset too', events[0], 'preset:xl');
check('and keeps the image\'s own VAE, as before - none named, none selected', selected(), []);

// ------------------------------------------- only what differs is changed
// Send makes the control hold exactly what the image needs, changing only
// what differs: each change is a request of Forge's, and after the old
// clear-and-reselect Neo sometimes loaded a model without its VAE.
const changes = () => events.filter((e) => e.startsWith('module'));
IMAGE.meta.VAE = 'sdxl_vae';
plan = { ...plan, target: ['sdxl_vae.safetensors'] };
await send();
check('the image\'s VAE is sent for the server to find', planAsked[0]?.get('vae'), 'sdxl_vae');
check('and the file it found is selected, in one change', [selected(), changes()],
      [['sdxl_vae.safetensors'], ['module+:sdxl_vae.safetensors']]);
await send();
check('a second image needing the same leaves the control untouched', changes(), []);

plan = { success: true, preset: 'flux', manage_modules: true, source: 'file',
         select: ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'],
         target: ['clip_l.safetensors', 't5xxl_fp16.safetensors', 'ae.safetensors'], missing: [] };
await send();
check('a model needing others takes out only what it does not need, and adds only what is missing',
      changes().sort(), ['module+:ae.safetensors', 'module+:clip_l.safetensors',
                         'module+:t5xxl_fp16.safetensors', 'module-:sdxl_vae.safetensors']);
plan = { ...plan, target: ['clip_l.safetensors', 't5xxl_fp16.safetensors'] };
await send();
check('and one needing one fewer takes that one out, and nothing else', changes(), ['module-:ae.safetensors']);
check('Forge holding what was sent, nothing is said', document.querySelector('.mm-notice'), null);

// Forge's setting is what it loads, whatever the control shows. When the two
// disagree after a send, that is said - only said, for now.
forgeHolds = () => ['clip_l.safetensors'];
await send();
const disagreed = document.querySelector('.mm-notice')?.textContent || '';
check('when Forge does not hold what the control shows, it is said, with what each is',
      [disagreed.startsWith('Forge did not take the VAE / Text Encoder change'),
       disagreed.includes('it holds clip_l.safetensors'),
       disagreed.includes('needs clip_l.safetensors, t5xxl_fp16.safetensors')], [true, true, true]);
forgeHolds = () => selected();
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
delete IMAGE.meta.VAE;

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

// The image's checkpoint, which a gallery that is not a checkpoint's never
// loaded (#134): selected by the name the server says Forge lists it under,
// after the preset - a preset change brings back the preset's own.
plan = { success: true, preset: 'qwen', manage_modules: true, select: [], target: [], missing: [],
         checkpoint: 'anima-preview2.safetensors [635cf338]', checkpoint_problem: null };
await send();
check('a LoRA\'s gallery selects the image\'s checkpoint, after the preset and before the paste',
      events.filter((e) => /^(preset|checkpoint|paste)/.test(e)),
      ['preset:qwen', 'checkpoint:anima-preview2.safetensors [635cf338]', 'paste']);
plan.preset = 'flux';

// One the library lacks is the one thing a send cannot go without: nothing
// is set, and the image's Resources open, saying why.
const resourcesNote = () => document.querySelector('.mm-resources-modal .mm-banner')?.textContent.replace(/^\s*!\s*/, '').trim();
const closeResources = () => document.querySelectorAll('.mm-modal-overlay').forEach((m) => m.remove());
plan = { ...plan, checkpoint: null, checkpoint_problem: { reason: 'missing', name: 'anima-preview2' } };
await send();
check('a checkpoint the library lacks: nothing is set or pasted',
      events.filter((e) => /^(preset|checkpoint|paste|module)/.test(e)), []);
check('and the Resources dialog says which, to download it there',
      resourcesNote(), 'The checkpoint this image was made with, anima-preview2, is not in your library. '
      + 'Download it here, then send the image again.');
closeResources();
plan = { ...plan, checkpoint_problem: { reason: 'elsewhere', name: 'anima.safetensors',
                                        path: 'D:/other-webui/models/Stable-diffusion/anima.safetensors' } };
await send();
check('one only in a folder this WebUI does not load: where it is, and nothing moved',
      [events.filter((e) => /^(preset|checkpoint|paste)/.test(e)), resourcesNote()],
      [[], 'The checkpoint this image was made with, anima.safetensors, is in your library at '
           + 'D:/other-webui/models/Stable-diffusion/anima.safetensors, a folder this WebUI does not load. '
           + 'Move it into this WebUI\'s models folder, or download it here; then send the image again.']);
closeResources();
plan = { ...plan, checkpoint_problem: { reason: 'not_checkpoint' } };
await send();
check('what it names as a checkpoint is not one: said so, nothing sent',
      [events.includes('paste'), resourcesNote()],
      [false, 'This image does not say which checkpoint it was made with: what it names as one is not a '
              + 'checkpoint, in your library or on Civitai.']);
closeResources();

// A VAE's or text encoder's gallery: its file is in the plan's target, which
// the send already holds the control to; one Forge does not list is said.
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
plan = { ...plan, checkpoint: null, checkpoint_problem: null, own_not_listed: 'ae_own.safetensors' };
await send();
check('a gallery\'s VAE Forge does not list is said, by name',
      document.querySelector('.mm-notice')?.textContent.includes('ae_own.safetensors'), true);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
delete plan.own_not_listed;

// A checkpoint's gallery loads its own, whatever the plan says of others.
MODEL.model_type = 'Checkpoint';
plan = { ...plan, checkpoint_problem: { reason: 'missing', name: 'anima-preview2' } };
await send();
check('a checkpoint\'s gallery is never stopped for the image\'s checkpoint',
      [events.includes('paste'), resourcesNote()], [true, undefined]);
MODEL.model_type = 'LORA';

// An image that names no checkpoint - no Model, no model hash, no checkpoint
// among its resources - cannot be sent from a gallery that is not a
// checkpoint's: its Send is disabled, saying why, before anything is asked.
const named = IMAGE.meta;
IMAGE.meta = { prompt: 'a lighthouse at dusk', steps: 20, sampler: 'Euler', cfgScale: 3.5, seed: 1,
               civitaiResources: [{ type: 'lora', modelVersionId: 5 }] };
const sendButton = async () => {
    await act('modelManager.selectModel', { index: 0 });
    await waitFor('the gallery', () => document.querySelector('#mm_images .mm-send-btn'));
    return document.querySelector('#mm_images .mm-send-btn');
};
let button = await sendButton();
check('a LoRA\'s gallery, an image naming no checkpoint: Send disabled, saying why',
      [button.disabled, button.getAttribute('title')],
      [true, 'This image does not say which checkpoint it was made with, which Send needs.']);
plan = { success: true, preset: 'flux', manage_modules: true, select: [], target: [], missing: [] };
await send();
check('and pressed anyway, nothing is asked or sent', [planAsked.length, events.includes('paste')], [0, false]);
MODEL.model_type = 'Checkpoint';
button = await sendButton();
check('a checkpoint\'s gallery sends it, its checkpoint the gallery\'s',
      [button.disabled, button.hasAttribute('title')], [false, false]);
MODEL.model_type = 'LORA';
IMAGE.meta = { ...IMAGE.meta, 'Model hash': 'aaaa111122' };
button = await sendButton();
check('an image naming its checkpoint by hash alone can be sent', button.disabled, false);
IMAGE.meta = named;
await sendButton();

// An upscaler's gallery: that upscaler goes in as Hires fix's, after the
// paste - which sets the image's own - by the name the server says Forge
// lists it under. Hires fix itself stays as the image had it.
const hires = document.createElement('div');
hires.id = 'txt2img_hr_upscaler';
hires.innerHTML = '<input>';
const hiresBox = document.createElement('div');
hiresBox.id = 'txt2img_hr-checkbox';
hiresBox.innerHTML = '<input type="checkbox">';
document.body.append(hires, hiresBox);
hiresBox.querySelector('input').checked = true;            // left on from the last generation
MODEL.model_type = 'Upscaler';
plan = { success: true, preset: 'flux', manage_modules: true, select: [], target: [], missing: [],
         checkpoint: 'anima-preview2.safetensors [635cf338]', upscaler: '4x-UltraSharp' };
await send();
check('an upscaler\'s gallery sets Hires fix\'s upscaler to it, and loads the image\'s checkpoint',
      [hires.querySelector('input').value, events.includes('checkpoint:anima-preview2.safetensors [635cf338]')],
      ['4x-UltraSharp', true]);
check('Hires fix stays as the image had it: off, as it used none', hiresBox.querySelector('input').checked, false);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
hires.querySelector('input').value = 'Latent';
plan = { ...plan, upscaler: null, upscaler_not_listed: '4x-UltraSharp.pth' };
await send();
check('one Forge does not list is said, and Hires fix\'s left as the paste set it',
      [document.querySelector('.mm-notice')?.textContent.includes('4x-UltraSharp.pth'),
       hires.querySelector('input').value], [true, 'Latent']);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
MODEL.model_type = 'LORA';
delete plan.upscaler_not_listed;
hires.remove();
hiresBox.remove();

// ------------------------------------------- an image-to-video model
// Sent to txt2img it failed in the sampler: an I2V model starts from an
// image, and txt2img has none to give. It goes to img2img instead, with the
// image - for a video its first frame, drawn onto a canvas - and a
// denoising strength of 1, which Neo asks of video models.
const tabs = document.createElement('div');
tabs.id = 'tabs';
for (const name of ['txt2img', 'img2img']) {
    const button = document.createElement('button');
    button.id = `tab_${name}-button`;
    button.addEventListener('click', () => events.push(`tab:${name}`));
    tabs.appendChild(button);
}
const mode = document.createElement('div');
mode.id = 'mode_img2img';
mode.innerHTML = '<button id="img2img_img2img_tab-button"></button>';
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
globalThis.fetch = withGalleryPages(async (url, ...rest) => {
    if (String(url).startsWith('https://example.invalid/')) {
        return { ok: true, blob: async () => new Blob(['jpeg'], { type: 'image/jpeg' }) };
    }
    return fetchServer(url, ...rest);
});
const infotext = () => i2iPrompt.querySelector('textarea').value;
const clearNotices = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

const C = 'https://image.civitai.com/acct/8c0dc66f';
plan = { success: true, preset: 'wan', manage_modules: true, select: [], missing: [], video: 'i2v' };
IMAGE.url = `${C}/original=true/8c0dc66f.mp4`;
IMAGE.type = 'video';
IMAGE.meta = { prompt: 'waves roll in', steps: 4, sampler: 'Euler', cfgScale: 1, seed: 7, Model: 'wan_i2v' };
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
// Forge's paste renames each LoRA "Lora hashes" lists to its own choice of
// name - the alias, with "Alias from file" - over the file names Send gives.
IMAGE.meta = { ...IMAGE.meta, 'Lora hashes': 'add_detail: 0123456789ab, other: ba9876543210' };
await send();
check('an image\'s Lora hashes are not pasted: Forge would rename its LoRAs by them',
      promptBox.querySelector('textarea').value.includes('Lora hashes'), false);
delete IMAGE.meta['Lora hashes'];

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
globalThis.fetch = withGalleryPages(async (url, ...rest) => {
    if (String(url).includes('/model-manager/image-resources')) {
        resourcesAsked.push(new URL(String(url), 'http://webui').searchParams);
        return { ok: true, json: async () => ({ success: true, ...structuredClone(library) }) };
    }
    const href = String(url);
    // The downloads list asks after every download at once; a chip's follows it there.
    if (href.includes('/model-manager/civitai/download/progress')) {
        return { ok: true, json: async () => ({ success: true, downloads: structuredClone(Object.values(chipProgress)) }) };
    }
    if (href.includes('/model-manager/civitai/download')) {
        // As every download is asked for (downloads().start): a form.
        const body = rest[0]?.body;
        const form = body instanceof FormData ? body : new URLSearchParams(String(body || ''));
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
});
const chipDownloads = [];
const chipProgress = {};

plan = { success: true, preset: 'flux', manage_modules: false, select: [], missing: [] };
IMAGE.meta = {
    prompt: 'a cat, <lora:UploaderName_v2:0.8>', negativePrompt: 'easynegative, blurry',
    steps: 20, sampler: 'Euler', cfgScale: 3.5, seed: 1, Model: 'a_checkpoint',
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
// (No answer here on what the missing ones are: see "missing resources" below.)
await waitFor('the missing chips', () => !row()?.querySelector('.mm-resource-chips-loading'));
check('one per LoRA and embedding, the gallery\'s own LoRA first, the missing after what the library has',
      Array.from(row().querySelectorAll('.mm-resource-chip-name')).map((b) => b.textContent.trim()),
      ['flux', 'add_detail', 'easynegative', 'Not Here', 'hash_only', 'private_merge', 'no_hash']);
check('a LoRA the prompt named otherwise is pasted under the local file\'s name, weight kept',
      [positiveBox.value, positiveBox.value.includes('UploaderName')], ['a cat, <lora:add_detail:0.8>', false]);
check('what a prompt already holds is lit, the rest not',
      ['flux', 'add_detail', 'easynegative'].map((n) => chip(n).classList.contains('active')),
      [false, true, true]);
// What a missing chip is doing is said in words on a line under the chips,
// never on the chip: a download used to rewrite the chip's own text five
// times, resizing it, and the chips after it moved under the pointer. The
// chip holds its mark and its name, and nothing else, in every state.
const note = (name) => {
    const index = chip(name)?.dataset.chip;
    const line = row()?.querySelector(`.mm-resource-chips-status [data-status-chip="${index}"]`);
    return line ? line.textContent.replace(`${name}: `, '') : null;
};
const parts = (name) => Array.from(chip(name)?.children || []).map((c) => c.className);
const onlyMarkAndName = (name) => parts(name).join() === 'mm-resource-chip-mark,mm-resource-chip-name';
check('one with no file here is marked to download, and says a click does it on hover, not on a line',
      [look_('Not Here'), chip('Not Here')?.title, note('Not Here')],
      ['↓', 'Not Here is not in the library: click to download it', null]);
await waitFor('the hashes to be checked', () => note('private_merge') === 'not on Civitai');
check('one known by a hash Civitai has: downloadable too', [look_('hash_only'), note('hash_only')], ['↓', null]);
check('every chip holds its mark and its name, and nothing else',
      ['flux', 'Not Here', 'hash_only', 'private_merge', 'no_hash'].every(onlyMarkAndName), true);

// Two things each chip says, told apart: whether it can be used - in the
// library, missing but downloadable, missing for good - by colour and a mark;
// whether a prompt holds it, by being filled (.active) rather than outlined.
function look_(name) {
    return chip(name)?.querySelector('.mm-resource-chip-mark')?.textContent;
}
const look = (name) => [chip(name)?.dataset.state, chip(name)?.querySelector('.mm-resource-chip-mark')?.textContent,
                        chip(name)?.classList.contains('active')];
check('in the library and in a prompt: ✓, filled', look('add_detail'), ['have', '✓', true]);
check('in the library, in no prompt: ✓, outlined', look('flux'), ['have', '✓', false]);
check('missing but downloadable: ↓', look('Not Here').slice(0, 2), ['download', '↓']);
check('missing, and nothing to download: ⊘', [look('no_hash').slice(0, 2), look('private_merge').slice(0, 2)],
      [['unavailable', '⊘'], ['unavailable', '⊘']]);
positiveBox.value += ', <lora:no_hash:0.5>';
positiveBox.dispatchEvent(new window.Event('input', { bubbles: true }));
await waitFor('the chips to be lit again', () => chip('no_hash')?.classList.contains('active'), 20);
check('a missing one a prompt names is filled too, in its own colour', look('no_hash'), ['unavailable', '⊘', true]);
positiveBox.value = positiveBox.value.replace(', <lora:no_hash:0.5>', '');
positiveBox.dispatchEvent(new window.Event('input', { bubbles: true }));
check('and a key says what the colours and filling mean',
      Array.from(row().querySelectorAll('.mm-resource-chips-key > span')).map((s) => s.textContent),
      ['✓ in library', '↓ click to download', '⊘ not available', 'filled: in the prompt']);
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
await waitFor('progress', () => note('Not Here')?.includes('40%'), 4000);
check('how it is going is said under the chips, and the chip takes no clicks meanwhile',
      [note('Not Here'), chip('Not Here').disabled], ['downloading, 40%', true]);
check('the chip fills as it goes, keeping its mark, its name and nothing else',
      [chip('Not Here').getAttribute('style'), look_('Not Here'), onlyMarkAndName('Not Here')],
      ['--mm-chip-progress: 40%', '↓', true]);
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

// A download that fails says why on the chip - it was only in the tooltip -
// and in the console.
const warned = [];
const warn = console.warn;
console.warn = (...args) => warned.push(args.join(' '));
chipProgress[98] = { version_id: 98, status: 'error', file_name: 'hash_only.safetensors',
                     error: 'File already exists: hash_only.safetensors, and Civitai lists no SHA-256 to compare it with' };
await waitFor('the failure', () => note('hash_only')?.includes('download failed'), 60);
console.warn = warn;
check('a failed download says why under the chips, cut short, and marks the chip !',
      [note('hash_only'), look_('hash_only'), onlyMarkAndName('hash_only'), chip('hash_only').disabled],
      [`download failed: ${'File already exists: hash_only.safetensors, and Civitai lists no SHA-256'.slice(0, 60)}..., click to retry`,
       '!', true, false]);
check('all of it in the tooltip', chip('hash_only')?.title.endsWith('lists no SHA-256 to compare it with'), true);
check('and in the console', warned.some((w) => w.includes('Download of hash_only.safetensors failed: File already exists')), true);

click(row().querySelector('[data-chips-clear]'));
check('Clear takes the chips away', row(), null);
check('and leaves the prompts as they were', [positiveBox.value, negativeBox.value],
      ['a cat, <lora:flux:1.1>', 'blurry, easynegative']);

// ------------------------------------------------------- missing resources
// What the library lacks is asked of Civitai after the send, which does not
// wait: until the answer, the row shows what the library has and says it is
// looking. Then the missing chips come after those, named as a download will
// name their files - so a download renames and moves nothing. A chip the
// infotext knows only by hash is its version: one chip with Civitai's list.
let releaseMissing;
let missingGate = null;
const missingAsked = [];
const missingAnswer = {
    success: true,
    versions: { 77: { file_stem: 'future_file', file_type: 'LORA', model_id: 76,
                      name: 'A Very Different Civitai Title', version_name: 'v3' } },
    hashes: { eeee: 77, ffff: null },
};
const fetchChips = globalThis.fetch;
globalThis.fetch = async (url, ...rest) => {
    if (String(url).includes('/model-manager/missing-resources')) {
        missingAsked.push(new URLSearchParams(String(rest[0]?.body || '')));
        await missingGate;
        return { ok: true, json: async () => structuredClone(missingAnswer) };
    }
    return fetchChips(url, ...rest);
};
const names = () => Array.from(row()?.querySelectorAll('.mm-resource-chip-name') || []).map((b) => b.textContent.trim());
const loading = () => row()?.querySelector('.mm-resource-chips-loading')?.textContent;
IMAGE.meta = {
    prompt: 'a cat, <lora:uploader_name:0.7>', steps: 20, Model: 'a_checkpoint',
    civitaiResources: [{ type: 'lora', modelVersionId: 11, name: 'Detail Tweaker', weight: 0.8 },
                       { type: 'lora', modelVersionId: 77, modelId: 76, name: 'A Very Different Civitai Title' }],
    resources: [{ type: 'lora', name: 'uploader_name', hash: 'eeee', weight: 0.7 },
                { type: 'lora', name: 'unknown_lora', hash: 'ffff' }],
};
missingGate = new Promise((resolve) => { releaseMissing = resolve; });
await send();
check('the send does not wait: the library\'s chips are there, and the row says it is looking for the rest',
      [names(), loading()], [['flux', 'add_detail'], 'Loading missing resources...']);
check('Civitai is asked about the missing ones: by version and model, and by hash',
      [JSON.parse(missingAsked.at(-1)?.get('versions') || '[]'), missingAsked.at(-1)?.get('hashes')],
      [[{ version_id: 77, model_id: 76 }], 'eeee,ffff']);
releaseMissing();
await waitFor('the answer', () => !loading());
check('then the missing come after them, named as a download will name the file, one chip per version',
      names(), ['flux', 'add_detail', 'future_file', 'unknown_lora']);
check('with Civitai\'s title on hover', chip('future_file')?.title.includes('A Very Different Civitai Title'), true);
check('and a hash Civitai does not know is said so, at once',
      [note('unknown_lora'), look_('unknown_lora')], ['not on Civitai', '⊘']);

// Downloaded: the same name, the same place.
chipProgress[77] = { version_id: 77, percent: 100, status: 'complete', synced: true };
library.versions[77] = { version_id: 77, file_stem: 'future_file', file_type: 'LORA' };
// The sync after a download stores the file's hashes: the image's finds it.
library.hashes.eeee = library.versions[77];
const promptLine = () => positiveBox.value.split('\n')[0];
check('before, the prompt names it as the image did', promptLine(), 'a cat, <lora:uploader_name:0.7>');
click(chip('future_file'));
await waitFor('the download to land', () => chip('future_file') && !chip('future_file').classList.contains('missing'), 5000);
check('once downloaded, the chip keeps its name and its place', names(), ['flux', 'add_detail', 'future_file', 'unknown_lora']);
// Send renames a LoRA it finds to its file; one found after, the same - or
// the prompt and its chip name one LoRA two ways.
check('and the prompt\'s tag for it is renamed to the file, weight kept, as Send would have',
      promptLine(), 'a cat, <lora:future_file:0.7>');
check('so its chip is lit', chip('future_file').classList.contains('active'), true);
delete library.versions[77];
delete library.hashes.eeee;

// An answer that comes after the row was cleared, or after another send, is dropped.
missingGate = new Promise((resolve) => { releaseMissing = resolve; });
IMAGE.meta.civitaiResources[1] = { type: 'lora', modelVersionId: 78, modelId: 76, name: 'Another' };
await send();
check('asked again for the next send', loading(), 'Loading missing resources...');
click(row().querySelector('[data-chips-clear]'));
releaseMissing();
await new Promise((resolve) => setTimeout(resolve, 50));
check('an answer after Clear draws nothing', row(), null);
globalThis.fetch = fetchChips;

IMAGE.meta = { prompt: 'a lighthouse', steps: 20 };
MODEL.model_type = 'Checkpoint';
await send();
check('an image with nothing to chip shows no row', row(), null);

// ------------------------------------------------ found by the file's name
// A file Scan Disk added and no sync has identified has no Civitai id and no
// stored hash; the server finds it by its name instead, and the chips say
// some were matched so.
IMAGE.meta = {
    prompt: 'a cat', negativePrompt: 'blurry', steps: 20,
    resources: [{ type: 'lora', name: 'add_detail_again', hash: 'AAAA' },
                { type: 'lora', name: 'Ghibli_v6', weight: 0.8 }],
    hashes: { 'lora:Ghibli_v6': '58549cc3d3' },
};
await send();
check('the image\'s LoRAs and embeddings are asked for by name too, with their hashes',
      JSON.parse(resourcesAsked[resourcesAsked.length - 1]?.get('names') || '[]'),
      [{ name: 'add_detail_again', hash: 'AAAA' }, { name: 'Ghibli_v6', hash: '58549cc3d3' }]);
check('and the hash the image keeps apart is asked for as a hash too',
      resourcesAsked[resourcesAsked.length - 1]?.get('hashes'), 'aaaa,58549cc3d3');
check('with every chip found by id or hash, no note', Boolean(row()?.querySelector('.mm-resource-chips-note')), false);
library.names = { ghibli_v6: { version_id: null, file_stem: 'Ghibli_v6', file_type: 'LORA' } };
await send();
await waitFor('the chips again', () => Boolean(chip('Ghibli_v6')));
check('one found by its name is a file you have: no missing note', note('Ghibli_v6') ?? null, null);
check('and a small note under the chips says some were matched by name',
      row()?.querySelector('.mm-resource-chips-note')?.textContent,
      'Some LoRAs and embeddings are matched by name, not by hash.');
delete library.names;
click(row().querySelector('[data-chips-clear]'));

// ------------------------------------------- one of your own generations
// Sent back set up as it was made with, from its record - the checkpoint's
// preset, the checkpoint, exactly the modules it loaded - the same for every
// kind of model. Pasting the infotext alone did none of it: Neo ignores an
// infotext's checkpoint and modules by default, so an SD 1.5 image sent after
// an Anima one kept the Anima model and its encoders.
async function sendGeneration(id, meta = {}) {
    events.length = 0;
    await sendInfotext({ infotext: 'a lighthouse at dusk\nSteps: 20', mode: 'txt2img', meta, generationId: id });
    await whenSendSettled();
}
const moduleChanges = () => events.filter((e) => e.startsWith('module'));
preset.querySelector('input').value = 'flux';
generationPlan = { success: true, preset: 'flux', checkpoint: '_Flux/flux1.safetensors [aa6ba2ab9f]',
                   checkpoint_missing: null, target: ['clip_l.safetensors', 'ae.safetensors'], modules_missing: [] };
await sendGeneration(299);
check('a generation is sent with the modules it loaded, exactly', selected().sort(),
      ['ae.safetensors', 'clip_l.safetensors']);
generationPlan = { success: true, preset: 'sd', checkpoint: '_SD_1.5/cyberrealistic.safetensors [bdfc5bafd3]',
                   checkpoint_missing: null, target: [], modules_missing: [] };
await sendGeneration(263);
check('one made with another model switches the preset, then the checkpoint, before the paste',
      events.filter((e) => /^(preset|checkpoint|paste)/.test(e)),
      ['preset:sd', 'checkpoint:_SD_1.5/cyberrealistic.safetensors [bdfc5bafd3]', 'paste']);
check('and one that loaded no modules takes out the ones left from before', [selected(), moduleChanges().length],
      [[], 2]);
check('Forge holding what was sent, nothing is said', document.querySelector('.mm-notice'), null);

generationPlan = { success: true, preset: null, checkpoint: null, checkpoint_missing: 'gone.safetensors',
                   target: [], modules_missing: ['qwen_image_vae.safetensors'] };
await sendGeneration(300);
const missingNote = document.querySelector('.mm-notice')?.textContent || '';
check('what was made with and is gone is said, by name, and the rest still sent',
      [missingNote.includes('gone.safetensors'), missingNote.includes('qwen_image_vae.safetensors'),
       events.includes('paste'), events.some((e) => e.startsWith('checkpoint'))], [true, true, true, false]);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// Its LoRAs and embeddings as chips, as a Civitai image's Send shows them:
// the server lists your images' resources as a Civitai image's, from the
// record - what Forge loaded, at its weight - and the infotext's hashes.
generationPlan = { success: true, preset: null, checkpoint: null, target: [], modules_missing: [] };
await sendGeneration(301, { prompt: 'a lighthouse <lora:add_detail:0.6>', resources: [
    { type: 'lora', name: 'add_detail', weight: 0.6, hash: 'aaaa' },
    { type: 'embedding', name: 'easynegative', weight: null, hash: 'bbbb' },
    { type: 'lora', name: 'gone_lora', weight: 0.8, hash: 'cccc' }] });
await waitFor('its chips', () => row() && chip('gone_lora')?.dataset.state === 'download');
check('a generation sent shows its LoRAs and embeddings as chips, found by their hashes',
      [look('add_detail').slice(0, 2), look('easynegative').slice(0, 2), look('gone_lora').slice(0, 2)],
      // gone_lora's hash is hash_only's, whose download failed above: marked so.
      [['have', '✓'], ['have', '✓'], ['download', '!']]);
await sendGeneration(302, {});
check('one that used none leaves none behind from the one before', row(), null);
generationPlan = null;

// ------------------------------------------------ the original Forge
// ------------------------------------------------- a slow preset change
// Forge answers a preset change from the server - its sampler, steps, size and
// CFG, then, chained on that, its checkpoint and modules - and each lands when
// the server is done. The send gave it a fixed 600 ms; a Krea model's took
// longer, and the preset's defaults landed on top of the image's settings.
forgeDelay = 300;
forgeAnswersPreset = () => {
    globalThis.fetch('/run/predict').then(() => {
        events.push('forge:defaults');
        return globalThis.fetch('/run/predict');
    }).then(() => events.push('forge:modules'));
};
preset.querySelector('input').value = 'sd';
plan = { success: true, preset: 'flux', manage_modules: false, select: [], missing: [] };
await send();
check('a slow preset change is waited out: its defaults and modules land before the image\'s settings',
      events.filter((e) => /^(preset|forge|paste)/.test(e)), ['preset:flux', 'forge:defaults', 'forge:modules', 'paste']);
forgeAnswersPreset = null;
forgeDelay = 0;

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

// ------------------------------------------------ a prompt wrapped in quotes
// Some tools give Civitai the prompt as a quoted string. Pasted as it is, a
// model reading prompts as instructions took the whole as one quotation and
// drew noise; the quotes around the whole go, and only those.
// (This DOM's textarea gives back only the first line; the infotext the
// paste writes - the one with a Steps line - is kept.)
let written = '';
Object.defineProperty(document.querySelector('#txt2img_prompt textarea'), 'value', {
    set: (text) => { if (String(text).includes('\nSteps:')) written = text; },
    get: () => written, configurable: true });
const sendPrompts = async (prompt, negativePrompt) => {
    IMAGE.meta = { prompt, negativePrompt, steps: 20 };
    written = '';
    await send();
    return written.split('\n').filter((line) => !line.startsWith('Steps:'));
};
check('a prompt and a negative prompt quoted whole are sent without the quotes',
      await sendPrompts(' "a lighthouse at dusk, (fog:1.2)" ', '"blurry"'),
      ['a lighthouse at dusk, (fog:1.2)', 'Negative prompt: blurry']);
check('a prompt with quotes of its own inside keeps every one',
      await sendPrompts('"a sign" reading "open"', 'text'),
      ['"a sign" reading "open"', 'Negative prompt: text']);
check('as does one quoted only in part',
      await sendPrompts('a sign reading "open"', ''), ['a sign reading "open"']);

done();
