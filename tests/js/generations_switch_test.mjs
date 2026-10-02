// "Your generations" off (#27): every tab of them goes at once, without a
// restart - the Generations tab's button is hidden, the page leaving it for
// the Model Manager if it was showing, and each model's gallery shows only
// its Civitai images - and comes back when it is on again. Known from
// ui-options, and again when the setting is saved: in the settings window
// (its answer carries the value) or on the Settings page (only which keys
// changed, so the page asks). The server's side: generations_switch_test.py.
import { ROOT, checker, mountTab, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// Forge's tab bar, as far as the switch looks at it.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_generations_tab-button" class="selected" aria-selected="true">Generations</button>
        <button id="tab_model_manager_tab-button">Model Manager</button>
        <button id="tab_civitai_browser_tab-button">Civitai Browser</button>
    </div>`);
const tabButton = (label) => Array.from(document.querySelectorAll('#tabs button')).find((b) => b.textContent === label);
const clicked = [];
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => clicked.push(b.textContent)));

let serverSays = false;
const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: 'v1',
    base_model: 'SDXL 1.0', model_type: 'LORA', file_path: 'C:/m/a.safetensors', file_name: 'a.safetensors',
    file_size: 1, nsfw_level: 1, has_civitai_data: true, local_version_count: 1, trained_words: [], tags: [],
};
globalThis.fetch = withGalleryPages(async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true,
                       generations_enabled: serverSays });
    }
    if (href.includes('/models/details')) {
        return reply({ success: true, model: { ...MODEL, images: [], generations_count: 3,
            images_state: { version_id: 5001, total_count: 0, filtered_count: 0, offset: 0 } } });
    }
    if (href.includes('/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [MODEL] });
    }
    return reply({ success: true, generations: [], total: 0 });
});

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

await waitFor('the switch', () => tabButton('Generations').style.display === 'none');
check('off: the Generations tab\'s button is hidden at once', tabButton('Generations').style.display, 'none');
check('and, as it was showing, the page goes to the Model Manager', clicked, ['Model Manager']);

document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelector('#mm_grid .model-card'));
await window.mmSelectModel(0);
await waitFor('the gallery', () => document.querySelector('#mm_images .mm-images-header'));
const galleryTabs = () => Array.from(document.querySelectorAll('#mm_images .mm-gallery-tab')).map((t) => t.textContent.trim());
check('a model\'s gallery has only its Civitai images', galleryTabs(), ['Civitai images']);

// Turned on in the settings window: its answer says the new value.
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', { detail: { changed: ['model_manager_record_generations'],
    settings: { model_manager_record_generations: { value: true } } } }));
check('on again, from the settings window: the button is back', tabButton('Generations').style.display, '');
check('and the gallery\'s Your generations', galleryTabs(), ['Civitai images', 'Your generations (3)']);

await window.mmShowGalleryTab('generations');
check('which opens', document.querySelector('#mm_images .mm-gallery-tab.active')?.textContent.trim(),
      'Your generations (3)');

// Turned off on the Settings page: which keys changed is all it says, so the
// page asks the server.
serverSays = false;
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied',
    { detail: { changed: ['model_manager_record_generations'] } }));
await waitFor('the page to ask', () => tabButton('Generations').style.display === 'none');
check('off again, from the Settings page: the button hidden', tabButton('Generations').style.display, 'none');
check('and the gallery leaves Your generations for the Civitai images',
      [galleryTabs(), document.querySelector('#mm_images .mm-gallery-tab.active')?.textContent.trim()],
      [['Civitai images'], 'Civitai images']);

// Another setting applied there changes nothing.
serverSays = true;
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied', { detail: { changed: ['model_manager_page_size'] } }));
await new Promise((resolve) => setTimeout(resolve, 50));
check('another setting applied asks nothing, and changes nothing', tabButton('Generations').style.display, 'none');

done();
