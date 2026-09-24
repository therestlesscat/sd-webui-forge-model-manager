// The Model Manager gallery's filter banner: one sentence, two switches.
//
//   Showing 1 of 4 images (2 hidden due to NSFW filter, 1 hidden due to unusable prompt)
//                                             [ ] Show NSFW (2)  [ ] Show unusable prompts (1)
//
// The hidden figures add up with what is shown to the total, so an image both
// filters hide is counted once - by the NSFW filter, which filters first. An
// unticked switch states the same number as its clause. Once ticked, its
// clause drops out and the switch says how many of its kind it now shows.
//
// The switches read "Show ...", ticked to show, as they do everywhere - but the
// server is still asked whether to *hide* (hide_nsfw_images,
// hide_promptless_images), so each flip happens in exactly one place and the
// check that matters is what the request says, not only how the box looks.
//
// A gallery a filter has emptied must keep the banner, and with it the switch.
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1,
    trained_words: [], tags: [],
};

// One image of each kind: plain, NSFW, no prompt, and NSFW with no prompt.
const LIBRARY = [
    { id: 1, nsfw: false, prompt: true },
    { id: 2, nsfw: true, prompt: true },
    { id: 3, nsfw: false, prompt: false },
    { id: 4, nsfw: true, prompt: false },
];
const toImage = (x) => ({
    id: x.id, url: `https://example.invalid/${x.id}.jpeg`, browsingLevel: x.nsfw ? 8 : 1,
    meta: x.prompt ? { prompt: 'a prompt long enough', steps: 20, sampler: 'Euler', cfgScale: 7 } : null,
});

// The server's side of it, as images_ops.get_image_counts works it out.
function answer(hideNsfw, hidePromptless) {
    const nsfwPass = LIBRARY.filter((x) => !hideNsfw || !x.nsfw);
    const promptPass = LIBRARY.filter((x) => !hidePromptless || x.prompt);
    const shown = nsfwPass.filter((x) => promptPass.includes(x));
    return {
        shown,
        hidden_nsfw: LIBRARY.length - nsfwPass.length,
        hidden_promptless: nsfwPass.length - shown.length,
        nsfw_count: promptPass.filter((x) => x.nsfw).length,
        promptless_count: nsfwPass.filter((x) => !x.prompt).length,
    };
}

const asked = [];               // [hide_nsfw_images, hide_promptless_images] per request
let everyImageLacksAPrompt = false;

globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/ui-options')) {
        return { ok: true, json: async () => ({ success: true, samplers: [], schedulers: [],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/models/details')) {
        const params = new URL(href, 'http://webui').searchParams;
        const hideNsfw = params.get('hide_nsfw_images') !== 'false';
        const hidePromptless = params.get('hide_promptless_images') !== 'false';
        asked.push([params.get('hide_nsfw_images'), params.get('hide_promptless_images')]);

        if (everyImageLacksAPrompt) {
            return { ok: true, json: async () => ({ success: true, model: { ...MODEL, images: [],
                images_state: { version_id: 5001, total_count: 2, hidden_nsfw: 0,
                                hidden_promptless: 2, nsfw_count: 0, promptless_count: 2,
                                hide_nsfw_images: hideNsfw, hide_promptless_images: true } } }) };
        }
        const a = answer(hideNsfw, hidePromptless);
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL, images: a.shown.map(toImage),
            images_state: { version_id: 5001, total_count: LIBRARY.length,
                            hidden_nsfw: a.hidden_nsfw, hidden_promptless: a.hidden_promptless,
                            nsfw_count: a.nsfw_count, promptless_count: a.promptless_count,
                            hide_nsfw_images: hideNsfw,
                            hide_promptless_images: hidePromptless } } }) };
    }
    if (href.includes('/models/versions')) {
        return { ok: true, json: async () => ({ success: true, versions: [MODEL] }) };
    }
    if (href.includes('/model-manager/models')) {
        return { ok: true, json: async () => ({ success: true, total: 1, page: 1,
            page_size: 10, models: [MODEL] }) };
    }
    return { ok: true, json: async () => ({ success: true }) };
};

const images = () => document.getElementById('mm_images');
const cards = () => images().querySelectorAll('.mm-image-card').length;
const banners = () => images().querySelectorAll('.mm-nsfw-warning');
const sentence = () => (banners()[0]?.querySelector('span')?.textContent || '').trim();
const switchLabel = (id) => (images().querySelector(`#${id}`)?.closest('label')?.textContent || '')
    .replace(/\s+/g, ' ').trim();
const ticked = (id) => images().querySelector(`#${id}`)?.checked;
const NSFW = 'mm_show_nsfw_images';
const PROMPT = 'mm_show_promptless_images';

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => cards() > 0);

// ------------------------------------------------------------- both hiding
check('there is one banner, not one per filter', banners().length, 1);
check('whose sentence adds up: shown plus each hidden figure is the total', sentence(),
      'Showing 1 of 4 images (2 hidden due to NSFW filter, 1 hidden due to unusable prompt)');
check('with both switches on its right, each stating its clause\'s number',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (2)', 'Show unusable prompts (1)']);
check('the switches sit inside that one banner',
      banners()[0]?.querySelectorAll(`#${NSFW}, #${PROMPT}`).length, 2);
check('neither ticked while its filter hides', [ticked(NSFW), ticked(PROMPT)], [false, false]);
check('nothing says Hide any more', images().textContent.includes('Hide'), false);

// ---------------------------------------------------------------- NSFW shown
asked.length = 0;
await window.mmToggleShowNsfwImages(true);
await waitFor('the reload', () => cards() === 2);
check('ticking NSFW asks the server not to hide them', asked, [['false', 'true']]);
check('its clause drops out, and the NSFW image without a prompt moves to the other',
      sentence(), 'Showing 2 of 4 images (2 hidden due to unusable prompt)');
check('the ticked switch says how many NSFW it now shows',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (1)', 'Show unusable prompts (2)']);
check('and is ticked', ticked(NSFW), true);

asked.length = 0;
await window.mmToggleShowNsfwImages(false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked, [['true', 'true']]);

// ------------------------------------------------------------- prompts shown
asked.length = 0;
await window.mmToggleShowPromptless(true);
await waitFor('the reload', () => cards() === 2);
check('ticking the prompt switch asks the server not to hide them', asked, [['true', 'false']]);
check('its clause drops out', sentence(), 'Showing 2 of 4 images (2 hidden due to NSFW filter)');
check('and it says how many it now shows',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (2)', 'Show unusable prompts (1)']);
check('ticked', ticked(PROMPT), true);

asked.length = 0;
await window.mmToggleShowPromptless(false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked, [['true', 'true']]);

// ------------------------------------------------- a gallery emptied by a filter
everyImageLacksAPrompt = true;
await window.mmToggleShowNsfwImages(false);
await waitFor('the emptied gallery', () => images().textContent.includes('No images to show'));
check('the banner stays, saying why', sentence(),
      'Showing 0 of 2 images (2 hidden due to unusable prompt)');
check('with the switch that can bring them back', switchLabel(PROMPT), 'Show unusable prompts (2)');
check('and the message blames neither filter in particular',
      images().textContent.includes('No images to show with the filters above.'), true);
check('rather than telling you to untick an NSFW box', images().textContent.includes('Uncheck'), false);

done();
