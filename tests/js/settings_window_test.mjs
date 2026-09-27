// The settings window: one window for both tabs, grouped, showing only what
// applies, saving only what changed - and telling the Settings page, whose
// Apply button would otherwise send back the values it loaded with.
import { readFileSync } from 'fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// ------------------------------------------------ the server's settings
const setting = (kind, value, extra = {}) => ({ label: extra.label || 'A setting', info: '',
                                                 kind, value, default: value, ...extra });
const SETTINGS = {
    model_manager_civitai_api_key: { label: 'Civitai API Key', info: '', kind: 'secret',
                                     default: '', has_value: false },
    model_manager_civitai_requests_per_second: setting('number', 6, { minimum: 1, maximum: 10, step: 1 }),
    model_manager_page_size: setting('number', 20, { minimum: 5, maximum: 50, step: 5,
                                                     label: 'Model Manager: Models per page' }),
    model_manager_card_size: setting('text', '200x280'),
    model_manager_preview_least_nsfw: setting('bool', true),
    model_manager_gallery_hide_nsfw: setting('bool', true),
    model_manager_nsfw_detection: setting('choice', 'words', { default: 'model', choices: [
        ['Trained model', 'model'], ['Word list', 'words']] }),
    model_manager_nsfw_prompt_model_percent: setting('number', 2, { minimum: 0, maximum: 20, step: 0.25 }),
    model_manager_nsfw_prompt_words: setting('text', '', { lines: 2 }),
    model_manager_civitai_folder_template: setting('text', '_{baseModel}/{modelName}'),
    model_manager_modules_flux: setting('text', ''),
    model_manager_civitai_sfw_fill_page: setting('bool', false),
    model_manager_something_new: setting('bool', false, { label: 'A setting added later' }),
};
const ORDER = Object.keys(SETTINGS);
const posted = [];
const modelsAsked = [];
const libraryModel = (id) => ({ id, name: `M${id}`, display_name: `Model ${id}`, model_type: 'LORA',
                                file_path: `C:/m/${id}.safetensors`, has_civitai_data: true });
let settingsAsked = 0;

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/settings/folder-example')) {
        return { ok: true, json: async () => ({ success: true, subfolder: '_SDXL_1.0/Example_Model',
                                                unknown: [] }) };
    }
    if (href.includes('/model-manager/settings')) {
        if (init.method === 'POST') {
            const { values } = JSON.parse(init.body);
            posted.push(values);
            const changed = Object.keys(values);
            changed.forEach((key) => {
                if (SETTINGS[key].kind === 'secret') SETTINGS[key].has_value = Boolean(values[key]);
                else SETTINGS[key].value = values[key];
            });
            return { ok: true, json: async () => ({ success: true, settings: SETTINGS, order: ORDER,
                                                    changed, database_in_use: 'C:/models.db' }) };
        }
        settingsAsked += 1;
        return { ok: true, json: async () => ({ success: true, settings: SETTINGS, order: ORDER,
                                                database_in_use: 'C:/models.db', bundled_nsfw_words: 99 }) };
    }
    if (href.includes('/model-manager/models?') && href.includes('page_size=')) {
        const n = Number(new URL(href, 'http://webui').searchParams.get('page_size'));
        modelsAsked.push(String(n));
        return { ok: true, json: async () => ({ success: true, total: 40, page: 1, page_size: n,
            models: Array.from({ length: n }, (_, i) => libraryModel(i + 1)) }) };
    }
    return { ok: true, json: async () => ({ success: true, models: [], total: 0 }) };
};

// The Settings page's own fields, as Gradio draws them.
const page = document.createElement('div');
page.innerHTML = `
    <div id="setting_model_manager_page_size"><input type="number" value="20"><input type="range" value="20"></div>
    <div id="setting_model_manager_gallery_hide_nsfw"><input type="checkbox" checked></div>
    <div id="setting_model_manager_nsfw_detection">
        <input type="radio" name="d" value="model"><input type="radio" name="d" value="words" checked></div>`;
document.body.appendChild(page);
const heard = [];
['input', 'change'].forEach((type) => page.addEventListener(type, (e) => heard.push(`${type}:${e.target.closest('[id]').id}`)));

let confirmAnswer = true;
window.confirm = () => confirmAnswer;
const saved = [];
window.addEventListener('mm-settings-saved', (e) => saved.push(e.detail.changed));

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// -------------------------------------------------------------- the gear
for (const tab of ['tab_model_manager.py', 'tab_civitai_browser.py']) {
    const markup = readFileSync(`${ROOT}/model_manager/ui/${tab}`, 'utf8');
    check(`${tab} has the gear, opening the one window`,
          /class="mm-settings-btn"[^>]*onclick="window\.mmOpenSettings/.test(markup), true);
}
check('the gear is in the header', Boolean(document.querySelector('.model-manager-header .mm-settings-btn')), true);

// --------------------------------------------------------------- opening
const $ = (sel) => document.querySelector(sel);
const field = (key) => $(`.mm-settings-field[data-key="${key}"]`);
const shown = (key) => Boolean(field(key)) && !field(key).hidden;
const status = () => $('#mm_settings_status').textContent;
function type(el, value) {
    el.value = value;
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
}
function pick(el) {
    el.checked = true;
    el.dispatchEvent(new window.Event('change', { bubbles: true }));
}

await window.mmOpenSettings();
check('it opens', $('#mm_settings')?.style.display, 'flex');
check('on the page body, outside anything Gradio redraws', $('#mm_settings')?.parentElement, document.body);
check('asking the server, each time it opens', settingsAsked, 1);

const titles = Array.from(document.querySelectorAll('.mm-settings-section > summary')).map((s) => s.textContent);
check('grouped into sections, in order, with a setting no section names under Other', titles, [
    'Civitai connection', 'Model Manager', 'Civitai Browser', 'Image gallery', 'NSFW detection',
    'Send to txt2img: text encoders and VAE', 'Advanced', 'Other']);
check('the text encoders collapsed', document.querySelectorAll('.mm-settings-section')[5].hasAttribute('open'), false);
check('with a short label', field('model_manager_page_size').querySelector('.mm-settings-label').textContent,
      'Models per page');

// -------------------------------------------------------- what is shown
check('requests per second is hidden without an API key',
      shown('model_manager_civitai_requests_per_second'), false);
type(field('model_manager_civitai_api_key').querySelector('input'), 'a-new-key');
check('and shown once one is typed', shown('model_manager_civitai_requests_per_second'), true);

check('with the word list, the trained model\'s share is hidden',
      shown('model_manager_nsfw_prompt_model_percent'), false);
check('the words are shown', shown('model_manager_nsfw_prompt_words'), true);
pick(field('model_manager_nsfw_detection').querySelector('input[data-index="0"]'));
check('with the trained model, its share is shown', shown('model_manager_nsfw_prompt_model_percent'), true);
check('and the words still, since they apply with it too', shown('model_manager_nsfw_prompt_words'), true);

// -------------------------------------------------------------- changes
check('two changes so far, counted', status(), '2 unsaved changes');
check('each marked', ['model_manager_civitai_api_key', 'model_manager_nsfw_detection']
    .every((k) => field(k).classList.contains('mm-settings-changed')), true);
type(field('model_manager_nsfw_prompt_model_percent').querySelector('input[type="number"]'), '3');
pick(field('model_manager_nsfw_detection').querySelector('input[data-index="1"]'));
check('a hidden setting\'s change still counts', status(), '2 unsaved changes');
check('as it would: it is hidden, and changed',
      [shown('model_manager_nsfw_prompt_model_percent'),
       field('model_manager_nsfw_prompt_model_percent').classList.contains('mm-settings-changed')], [false, true]);

const size = field('model_manager_page_size');
type(size.querySelector('input[type="range"]'), '30');
check('the slider and its box say the same', size.querySelector('input[type="number"]').value, '30');
check('three changes', status(), '3 unsaved changes');

size.querySelector('.mm-settings-reset').click();
check('reset puts back the default', field('model_manager_page_size').querySelector('input[type="number"]').value, '20');
check('which is no change', status(), '2 unsaved changes');
type(field('model_manager_page_size').querySelector('input[type="number"]'), '30');

field('model_manager_card_size').querySelector('[data-w="160"]').click();
check('a card size preset sets both sides',
      Array.from(field('model_manager_card_size').querySelectorAll('input')).map((i) => i.value), ['160', '224']);
// ------------------------------------------------------------ card preview
// One row of the tab's own cards at the size being set: as many as fit, and
// only as many models asked for as that.
const row = () => field('model_manager_card_size').querySelector('.mm-settings-card-row');
const cardCount = () => row().querySelectorAll('.model-card').length;
const settle = () => new Promise((r) => setTimeout(r, 400));
check('there is no preview until asked for', [row().hidden, cardCount()], [true, 0]);
const rowWidth = 700;       // what the dialog gives the row; linkedom lays nothing out
Object.defineProperty(Object.getPrototypeOf(row()), 'clientWidth', {
    configurable: true,
    get() { return this.classList?.contains('mm-settings-card-row') ? rowWidth : 0; },
});
modelsAsked.length = 0;
field('model_manager_card_size').querySelector('[data-card-show]').click();
await waitFor('the preview', () => cardCount() > 0);
check('Show preview draws the tab\'s own cards', row().hidden, false);
check('as many as fit in one row: 700px holds four 160px cards and their gaps', cardCount(), 4);
check('at the size being set', [row().style.getPropertyValue('--mm-preview-card-width'),
                                row().style.getPropertyValue('--mm-preview-card-height')], ['160px', '224px']);
check('asking the library for exactly that many, the tab having none loaded', modelsAsked, ['4']);

const [width] = field('model_manager_card_size').querySelectorAll('input');
type(width, '300');
await settle();
check('a wider card fits fewer', cardCount(), 2);
check('and needs no more models', modelsAsked, ['4']);
type(width, '100');
await settle();
check('a narrower one fits more: 700px holds six 100px cards', cardCount(), 6);
check('asking only for the difference\'s worth - six, once', modelsAsked, ['4', '6']);
type(width, '4');
await settle();
check('a size passed through while typing is not drawn',
      [cardCount(), field('model_manager_card_size').querySelector('.mm-settings-card-note').textContent
          .startsWith('Too small to preview')], [0, true]);
field('model_manager_card_size').querySelector('[data-card-show]').click();
check('Hide preview hides it', row().hidden, true);
field('model_manager_card_size').querySelector('[data-w="160"]').click();

// --------------------------------------------------------------- search
type($('#mm_settings_search'), 'thumbnail');
check('searching shows only what matches',
      ORDER.filter(shown), ['model_manager_preview_least_nsfw']);
type($('#mm_settings_search'), '');

// ------------------------------------------------------ closing, saving
confirmAnswer = false;
$('[data-act="cancel"]').click();
check('closing with changes asks, and stays open when told to', $('#mm_settings').style.display, 'flex');

heard.length = 0;
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 1);
check('a save sends what changed, and only that', posted[0], {
    model_manager_civitai_api_key: 'a-new-key',
    model_manager_page_size: 30,
    model_manager_card_size: '160x224',
    model_manager_nsfw_prompt_model_percent: 3,
});
check('the window closes', $('#mm_settings').style.display, 'none');
check('and the tabs are told what changed', saved[0].sort(), Object.keys(posted[0]).sort());
check('the Settings page\'s own fields are set to what was saved',
      Array.from(document.querySelectorAll('#setting_model_manager_page_size input')).map((i) => i.value), ['30', '30']);
check('as if typed there, so Gradio takes them',
      heard.includes('input:setting_model_manager_page_size'), true);

// ------------------------------------------------ one window, both tabs
const before = window.mmSettingsWindow;
await import(`file:///${ROOT}/javascript/shared/settings.mjs?another-tab`);
check('a second copy of the module - the other tab\'s - uses the same window',
      window.mmSettingsWindow, before);
await window.mmOpenSettings();
check('which is drawn once', document.querySelectorAll('#mm_settings').length, 1);
check('and opens with what the server has now', field('model_manager_page_size')
    .querySelector('input[type="number"]').value, '30');
check('with nothing changed', status(), '');

done();
