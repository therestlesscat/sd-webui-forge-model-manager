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

done();
