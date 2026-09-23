// The Model Manager gallery's two switches, and what an emptied gallery says.
//
// Every NSFW and prompt switch in both tabs reads "Show ..." with a count,
// ticked to show what the filter would hide. These two read "Hide ...", ticked
// to hide. They now read the same way as the rest - but the server is still
// asked whether to *hide* (hide_nsfw_images, hide_promptless_images), so each
// flip has to happen in exactly one place, and the check that matters is what
// the request says, not only how the box looks.
//
// The (n) is how many of the model's images are of that kind, whichever way
// the switch is set, so it comes from the server: once a switch shows
// everything, nothing on the page could say how many it had been hiding.
//
// A gallery a filter has emptied must keep that filter's switch on screen.
// It kept the NSFW one and lost the prompt one, telling you to untick a box
// that was not the reason, with no way to show the images that were.
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
const image = (id, level, prompt = 'a prompt long enough') => ({
    id, url: `https://example.invalid/${id}.jpeg`, browsingLevel: level,
    meta: prompt ? { prompt, steps: 20, sampler: 'Euler', cfgScale: 7 } : null,
});

// The version has three images: one plain, one NSFW, one with no prompt.
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
                                hidden_promptless: 2, nsfw_total: 0, promptless_total: 2,
                                hide_nsfw_images: hideNsfw, hide_promptless_images: true } } }) };
        }
        const shown = [image(1, 1)];
        if (!hideNsfw) shown.push(image(2, 8));
        if (!hidePromptless) shown.push(image(3, 1, null));
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL, images: shown,
            images_state: { version_id: 5001, total_count: 3,
                            hidden_nsfw: hideNsfw ? 1 : 0,
                            hidden_promptless: hidePromptless ? 1 : 0,
                            nsfw_total: 1, promptless_total: 1,
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

const cards = () => document.querySelectorAll('#mm_images .mm-image-card').length;
const nsfwSwitch = () => document.querySelector('.mm-nsfw-warning #mm_show_nsfw_images');
const promptSwitch = () => document.querySelector('.mm-nsfw-warning #mm_show_promptless_images');
const label = (box) => (box?.closest('label')?.textContent || '').trim();
const images = () => document.getElementById('mm_images');

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => cards() > 0);

// --------------------------------------------------------------- the wording
check('the NSFW switch reads Show NSFW, with a count', label(nsfwSwitch()), 'Show NSFW (1)');
check('the prompt switch reads the same way, with a count',
      label(promptSwitch()), 'Show images without prompts (1)');
check('nothing in the gallery says Hide any more', images().textContent.includes('Hide'), false);
check('while NSFW images are hidden, their switch is not ticked', nsfwSwitch()?.checked, false);
check('nor, while they are hidden, the prompt one', promptSwitch()?.checked, false);

// -------------------------------------------------- the NSFW request underneath
asked.length = 0;
await window.mmToggleShowNsfwImages(true);
await waitFor('the reload', () => cards() === 2);
check('ticking NSFW asks the server not to hide them', asked.map((a) => a[0]), ['false']);
check('and they appear', cards(), 2);
check('with the switch now ticked', nsfwSwitch()?.checked, true);
check('and the same count, since it counts the model rather than the page',
      label(nsfwSwitch()), 'Show NSFW (1)');

asked.length = 0;
await window.mmToggleShowNsfwImages(false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked.map((a) => a[0]), ['true']);
check('with the switch unticked', nsfwSwitch()?.checked, false);

// ------------------------------------------------ the prompt request underneath
asked.length = 0;
await window.mmToggleShowPromptless(true);
await waitFor('the reload', () => cards() === 2);
check('ticking the prompt switch asks the server not to hide them',
      asked.map((a) => a[1]), ['false']);
check('without touching the NSFW one', asked.map((a) => a[0]), ['true']);
check('with the switch now ticked', promptSwitch()?.checked, true);
check('saying what it is showing', images().textContent.includes('Showing 1 with no prompt to read'), true);
check('and keeping its count', label(promptSwitch()), 'Show images without prompts (1)');

asked.length = 0;
await window.mmToggleShowPromptless(false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked.map((a) => a[1]), ['true']);

// ------------------------------------------------- a gallery emptied by a filter
everyImageLacksAPrompt = true;
await window.mmToggleShowNsfwImages(false);
await waitFor('the emptied gallery', () => images().textContent.includes('No images to show'));
check("the prompt filter's switch stays, so the hidden images can be shown",
      !!document.querySelector('#mm_images #mm_show_promptless_images'), true);
check('with how many it is holding back', images().textContent.includes('2 hidden - no prompt to read'), true);
check('and its count', label(document.querySelector('#mm_images #mm_show_promptless_images')),
      'Show images without prompts (2)');
check('and the message blames neither filter in particular',
      images().textContent.includes('No images to show with the filters above.'), true);
check('rather than telling you to untick an NSFW box', images().textContent.includes('Uncheck'), false);

done();
