// Saying which judges NSFW, while a trained model does.
//
// Settings -> Model Manager -> NSFW detection picks a trained model (the
// default) or the word list alone. The model is sometimes wrong in ways
// nobody can point at, so while it decides what the filters hide, the page
// says so and where to switch: above the results while "Only Show Models with
// SFW images" is ticked, and in the gallery's filter banner. The word list
// needs no note; sfw_filter_test.mjs checks the Civitai Browser says none.
import { ROOT, checker, mountTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'SDXL 1.0', model_type: 'LORA', file_path: 'C:/models/a.safetensors',
    file_name: 'a.safetensors', file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};
const IMAGE = { id: 1, url: 'https://example.invalid/1.jpeg', browsingLevel: 1, mm_level: 1,
    meta: { prompt: 'a lighthouse at dusk', steps: 20, sampler: 'Euler', cfgScale: 7 } };

globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Simple'], has_api_key: true,
                       image_browsing: 'continuous', nsfw_detection: 'model' });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: [IMAGE],
            images_state: { version_id: 5001, total_count: 3, hidden_nsfw: 2, nsfw_count: 2,
                            hidden_promptless: 0 } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL], civitai_versions: [] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true });
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const $ = (id) => document.getElementById(id);
const NOTE = 'NSFW is judged by a trained model';

await waitFor('the page to know which judges', () => $('mm_sfw_only_banner_model')?.textContent.includes(NOTE));
check('1. with the SFW filter off, no banner', $('mm_sfw_only_banner').style.display, 'none');
$('mm_sfw_only').checked = true;
$('mm_sfw_only').dispatchEvent(new window.Event('change', { bubbles: true }));
check('   ticked, a banner says a trained model decides, and where to switch',
      [$('mm_sfw_only_banner').style.display,
       $('mm_sfw_only_banner').textContent.includes('Settings \u2192 Model Manager \u2192 NSFW detection')],
      ['flex', true]);
$('mm_sfw_only').checked = false;
$('mm_sfw_only').dispatchEvent(new window.Event('change', { bubbles: true }));
check('   and it goes when the box is unticked', $('mm_sfw_only_banner').style.display, 'none');

$('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-nsfw-warning'));
const banner = document.querySelector('#mm_images .mm-nsfw-warning');
check('2. the gallery\'s filter banner says it too, under the count',
      [banner?.textContent.includes('2 hidden due to NSFW filter'),
       banner?.querySelector('.filter-banner-note')?.textContent.includes(NOTE)], [true, true]);

done();
