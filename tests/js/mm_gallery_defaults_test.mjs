// Each model the Model Manager opens starts its gallery as the settings say,
// and the switches then last while that model is open - as in the Civitai
// Browser (cb_gallery_defaults_test.mjs), which has to behave the same.
//
// The page used to send its own "hide" on the first request, so the server's
// fall-back to the settings never ran and neither setting was read at all;
// and a switch ticked on one model stayed ticked for every model after it.
import { ROOT, act, checker, mountTab, tick, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const model = (id) => ({
    id, model_id: id + 1000, name: `Model ${id}`, display_name: `Model ${id}`,
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: `C:/models/${id}.safetensors`, file_name: `${id}.safetensors`,
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [],
});
const MODELS = [model(1), model(2)];
// Safe with a prompt, explicit with a prompt, safe without one.
const LIBRARY = [{ id: 1, nsfw: false, prompt: true }, { id: 2, nsfw: true, prompt: true },
                 { id: 3, nsfw: false, prompt: false }];
const settings = { hide_nsfw_images: true, hide_promptless_images: true };

globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    if (href.includes('/models/details')) {
        const params = new URL(href, 'http://webui').searchParams;
        // What api/models.py does: the request's value, else the setting.
        const said = (name) => (params.has(name) ? params.get(name) !== 'false' : settings[name]);
        const hideNsfw = said('hide_nsfw_images');
        const hidePromptless = said('hide_promptless_images');
        // Counted as images_ops.get_image_counts counts them.
        const nsfwPass = LIBRARY.filter((x) => !hideNsfw || !x.nsfw);
        const promptPass = LIBRARY.filter((x) => !hidePromptless || x.prompt);
        const shown = nsfwPass.filter((x) => promptPass.includes(x));
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODELS[0], images: shown.map((x) => ({ id: x.id, url: `https://example.invalid/${x.id}.jpeg`,
                browsingLevel: x.nsfw ? 8 : 1, meta: x.prompt ? { prompt: 'a lighthouse by the sea' } : null })),
            images_state: { version_id: 5001, total_count: LIBRARY.length,
                            hidden_nsfw: LIBRARY.length - nsfwPass.length,
                            hidden_promptless: nsfwPass.length - shown.length,
                            nsfw_count: promptPass.filter((x) => x.nsfw).length,
                            promptless_count: nsfwPass.filter((x) => !x.prompt).length,
                            hide_nsfw_images: hideNsfw, hide_promptless_images: hidePromptless } } }) };
    }
    if (href.includes('/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 2, page: 1,
            page_size: 10, models: MODELS }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 1);

const shown = () => Array.from(document.querySelectorAll('#mm_images .mm-image-card img'))
    .map((img) => (img.getAttribute('data-src') || img.getAttribute('src') || '').split('/').pop());
const ticked = () => ['mm_show_nsfw_images', 'mm_show_promptless_images']
    .map((id) => document.getElementById(id)?.checked ?? null);

async function open(index) {
    document.getElementById('mm_images').innerHTML = '';
    await act('modelManager.selectModel', { index: index });
    await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card').length > 0);
}

await open(0);
check('hiding both, the gallery opens with only the safe image with a prompt',
      [shown(), ticked()], [['1.jpeg'], [false, false]]);

await tick('modelManager.showNsfwImages', true);
await tick('modelManager.showPromptless', true);
check('the switches show everything for this model', shown(), ['1.jpeg', '2.jpeg', '3.jpeg']);

await open(1);
check('the next model starts from the settings again, not from the switches',
      [shown(), ticked()], [['1.jpeg'], [false, false]]);

settings.hide_nsfw_images = false;
settings.hide_promptless_images = false;
await open(0);
check('a change to the settings reaches the next model opened, without a reload',
      [shown(), ticked()], [['1.jpeg', '2.jpeg', '3.jpeg'], [true, true]]);

settings.hide_nsfw_images = true;
await open(1);
check('each setting on its own', [shown(), ticked()], [['1.jpeg', '3.jpeg'], [false, true]]);

done();
