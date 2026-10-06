// The Model Manager gallery's filter banner: one sentence, two switches.
//
//   4 images stored · 1 match the filters (1 shown) · 1 hidden due to NSFW filter,
//   1 hidden due to unusable prompt, 1 hidden due to both
//                                             [ ] Show NSFW (1)  [ ] Show unusable prompts (2)
//
// The hidden figures add up with what matches to the total, and an image both
// filters hide is counted once, apart - "due to both" - not credited to either:
// credited to the NSFW filter, its switch said 2 while hiding and 1 once
// ticked (#29). An unticked switch states the same number as its clause, which
// is what it alone hides: once ticked, its clause drops out and the switch says
// how many of its kind it now shows - the same number. The prompt switch says
// every image with an unusable prompt, however either switch is set: its
// clause says how many it alone hides.
//
// The switches read "Show ...", ticked to show, as they do everywhere - but the
// server is still asked whether to *hide* (hide_nsfw_images,
// hide_promptless_images), so each flip happens in exactly one place and the
// check that matters is what the request says, not only how the box looks.
//
// A gallery a filter has emptied must keep the banner, and with it the switch.
import { ROOT, act, call, checker, mountTab, startTab, tick, withGalleryPages } from './harness.mjs';

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
    const both = LIBRARY.filter((x) => !nsfwPass.includes(x) && !promptPass.includes(x)).length;
    return {
        shown,
        hidden_nsfw: LIBRARY.length - nsfwPass.length - both,
        hidden_promptless: nsfwPass.length - shown.length,
        hidden_both: both,
        nsfw_count: promptPass.filter((x) => x.nsfw).length,
        promptless_count: nsfwPass.filter((x) => !x.prompt).length,
        promptless_total: LIBRARY.filter((x) => !x.prompt).length,
    };
}

const asked = [];               // [hide_nsfw_images, hide_promptless_images] per request
let everyImageLacksAPrompt = false;
let everyImagePasses = false;

globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    if (href.includes('/ui-options')) {
        return { ok: true, json: async () => ({ success: true, samplers: [], schedulers: [],
            has_api_key: true, image_browsing: 'continuous' }) };
    }
    if (href.includes('/models/details')) {
        const params = new URL(href, 'http://webui').searchParams;
        const hideNsfw = params.get('hide_nsfw_images') !== 'false';
        const hidePromptless = params.get('hide_promptless_images') !== 'false';
        if (!params.has('via_page')) {
            asked.push([params.get('hide_nsfw_images'), params.get('hide_promptless_images')]);
        }

        if (everyImagePasses) {
            return { ok: true, json: async () => ({ success: true, model: { ...MODEL,
                images: [toImage(LIBRARY[0])],
                images_state: { version_id: 5001, total_count: 1, filtered_count: 1, hidden_nsfw: 0,
                                hidden_promptless: 0, nsfw_count: 0, promptless_count: 0,
                                hide_nsfw_images: true, hide_promptless_images: true } } }) };
        }
        if (everyImageLacksAPrompt) {
            return { ok: true, json: async () => ({ success: true, model: { ...MODEL, images: [],
                images_state: { version_id: 5001, total_count: 2, filtered_count: 0, hidden_nsfw: 0,
                                hidden_promptless: 2, nsfw_count: 0, promptless_count: 2, promptless_total: 2,
                                hide_nsfw_images: hideNsfw, hide_promptless_images: true } } }) };
        }
        const a = answer(hideNsfw, hidePromptless);
        return { ok: true, json: async () => ({ success: true, model: {
            ...MODEL, images: a.shown.map(toImage),
            images_state: { version_id: 5001, total_count: LIBRARY.length,
                            filtered_count: a.shown.length, hidden_nsfw: a.hidden_nsfw, hidden_promptless: a.hidden_promptless,
                            hidden_both: a.hidden_both, promptless_total: a.promptless_total,
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
});

const images = () => document.getElementById('mm_images');
const cards = () => images().querySelectorAll('.mm-image-card').length;
const banners = () => images().querySelectorAll('.mm-nsfw-warning');
const sentence = () => (banners()[0]?.querySelector('span')?.textContent || '').trim();
const switchLabel = (id) => (images().querySelector(`#${id}`)?.closest('label')?.textContent || '')
    .replace(/\s+/g, ' ').trim();
const ticked = (id) => images().querySelector(`#${id}`)?.checked;
const NSFW = 'mm_show_nsfw_images';
const PROMPT = 'mm_show_promptless_images';

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => cards() > 0);

// ------------------------------------------------------------- both hiding
check('there is one banner, not one per filter', banners().length, 1);
check('whose sentence adds up: shown plus each hidden figure is the total', sentence(),
      '4 images stored · 1 match the filters (1 shown) · 1 hidden due to NSFW filter, 1 hidden due to unusable prompt, '
      + '1 hidden due to both');
check('with both switches on its right: NSFW what it alone hides, prompts every unusable one',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (1)', 'Show unusable prompts (2)']);
check('the switches sit inside that one banner',
      banners()[0]?.querySelectorAll(`#${NSFW}, #${PROMPT}`).length, 2);
check('neither ticked while its filter hides', [ticked(NSFW), ticked(PROMPT)], [false, false]);
check('nothing says Hide any more', images().textContent.includes('Hide'), false);
check('the first request leaves both filters to the settings, so they are read at all',
      asked[0], [null, null]);

// ---------------------------------------------------------------- NSFW shown
asked.length = 0;
await tick('modelManager.showNsfwImages', true);
await waitFor('the reload', () => cards() === 2);
check('ticking NSFW asks the server not to hide them', asked, [['false', 'true']]);
check('its clause drops out, and the NSFW image without a prompt moves to the other',
      sentence(), '4 images stored · 2 match the filters (2 shown) · 2 hidden due to unusable prompt');
check('the ticked switch says how many NSFW it now shows - the number it said while hiding - '
      + 'and the prompt switch has not moved',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (1)', 'Show unusable prompts (2)']);
check('and is ticked', ticked(NSFW), true);

asked.length = 0;
await tick('modelManager.showNsfwImages', false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked, [['true', 'true']]);

// ------------------------------------------------------------- prompts shown
asked.length = 0;
await tick('modelManager.showPromptless', true);
await waitFor('the reload', () => cards() === 2);
check('ticking the prompt switch asks the server not to hide them', asked, [['true', 'false']]);
check('its clause drops out', sentence(), '4 images stored · 2 match the filters (2 shown) · 2 hidden due to NSFW filter');
check('and it still says every unusable one',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['Show NSFW (2)', 'Show unusable prompts (2)']);
check('ticked', ticked(PROMPT), true);

asked.length = 0;
await tick('modelManager.showPromptless', false);
await waitFor('the reload', () => cards() === 1);
check('unticking asks it to hide them again', asked, [['true', 'true']]);

// ------------------------------------------------- a gallery emptied by a filter
everyImageLacksAPrompt = true;
await tick('modelManager.showNsfwImages', false);
await waitFor('the emptied gallery', () => images().textContent.includes('Displaying 0 images'));
check('the banner stays, saying why', sentence(),
      '2 images stored · 0 match the filters (0 shown) · 2 hidden due to unusable prompt');
check('with the switch that can bring them back', switchLabel(PROMPT), 'Show unusable prompts (2)');
check('and the message blames neither filter in particular',
      images().querySelector('.mm-page-note')?.textContent,
      'Displaying 0 images for page 1 · 2 hidden due to unusable prompt · no more images on Civitai');
check('rather than telling you to untick an NSFW box', images().textContent.includes('Uncheck'), false);

// ------------------------------------------ the note under a page, likewise
{
    const { pageNoteHtml } = await import(`file:///${ROOT}/javascript/shared/gallery.mjs`);
    const note = pageNoteHtml({ number: 1, shown: 1, hidden_nsfw: 1, hidden_promptless: 1, hidden_both: 1, more: true });
    check('a page\'s note says what both filters hid, apart',
          note.replace(/<[^>]+>/g, ''),
          'Displaying 1 image for page 1 · 1 hidden due to NSFW filter · 1 hidden due to unusable prompt · '
          + '1 hidden due to both');
}

// --------------------------------------- a gallery the filters leave whole
// It used to have no banner at all, and so nowhere saying what is stored.
everyImageLacksAPrompt = false;
everyImagePasses = true;
// The gallery again, as a switch reloads it: the NSFW one, not drawn now.
await call('modelManager.showNsfwImages', {}, { checked: false });
await waitFor('the whole gallery', () => cards() === 1);
check('with nothing hidden, the banner is still drawn, with the counts', sentence(),
      '1 image stored · 1 match the filters (1 shown)');
check('and no switch, as neither has anything to hide or show',
      [switchLabel(NSFW), switchLabel(PROMPT)], ['', '']);

done();
