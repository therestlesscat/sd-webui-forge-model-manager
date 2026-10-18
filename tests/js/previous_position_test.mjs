// Previous Position in the Model Manager (#250), now the shared module's
// (shared/previous_position.mjs), which the Generations and Civitai Images
// tabs use too. The Model Manager keeps its place in the browser's storage,
// under the keys it always used: a place saved before an update still shows
// its button. Its Send noted the place; now Show in Civitai Browser does too,
// as every tab's links out do.
import { act, checker, mountTab, press, startTab, tabEntries, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
const { check, waitFor, done } = checker();

const MODEL = {
    id: 5001, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};
globalThis.onAfterUiUpdate = () => {};
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/images/gallery-page')) {
        return reply({ success: true, images: [], page: { number: 1, size: 100, count: 0, shown: 0, more: false } });
    }
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: { ...MODEL, generations_count: 0 } });
    }
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 10, models: [MODEL] });
    }
    return reply({ success: true });
};

// A place saved before the update, as the Model Manager kept it.
localStorage.setItem('mm_scroll_position', '1500');
await startTab('modelManager');
await startTab('civitaiBrowser');
const shownInBrowser = [];
(await tabEntries('civitai_browser.mjs')).showModel = async (...args) => { shownInBrowser.push(args); };

const scrollY = (y) => Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
const scrolls = [];
window.scrollTo = (...args) => { scrolls.push(typeof args[0] === 'object' ? args[0].top : args[1]); };
const button = () => document.getElementById('mm_scroll_restore_btn');
const showing = () => Boolean(button()) && button().style.display !== 'none';
// No button, no press: a check fails rather than the suite.
const pressBack = () => {
    scrolls.length = 0;
    scrollY(0);
    if (button()) press(button());
    return scrolls[0] ?? null;
};

check('a place saved before the update shows Previous Position', showing(), true);
check('before Load Models, as it always was', button()?.nextElementSibling?.id, 'mm_load_btn');
check('still Previous Position: a card or a height, not a tile found (#264)', button()?.textContent, '↓ Previous Position');
check('pressed, the page goes back to it', pressBack(), 1500);
button()?.dispatchEvent(new window.Event('contextmenu', { bubbles: true, cancelable: true }));
check('a right-click clears it, from the browser\'s storage too',
      [showing(), localStorage.getItem('mm_scroll_position')], [false, null]);

// ------------------------------------------------------------ Show in Civitai Browser
document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });
await waitFor('the details', () => document.querySelector('[data-action="modelManager.showInCivitaiBrowser"]'));
scrollY(2222);
await press(document.querySelector('[data-action="modelManager.showInCivitaiBrowser"]'));
await waitFor('the Civitai Browser asked', () => shownInBrowser.length > 0);
check('Show in Civitai Browser notes the place, as Send does',
      [showing(), localStorage.getItem('mm_scroll_position')], [true, '2222']);
check('pressed, the page goes back there', pressBack(), 2222);

done();
