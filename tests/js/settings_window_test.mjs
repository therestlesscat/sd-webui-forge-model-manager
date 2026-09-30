// The settings window: one window for both tabs, grouped, showing only what
// applies, saving only what changed - and telling the Settings page, whose
// Apply button would otherwise send back the values it loaded with.
import { readFileSync } from 'fs';
import { ROOT, checker, mountTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The Settings page's result line is watched for; linkedom has the observer,
// the harness does not make it global.
globalThis.MutationObserver = window.MutationObserver;
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
    model_manager_modules_flux: setting('text', 'old_t5.safetensors'),
    model_manager_modules_klein: setting('text', ''),
    model_manager_modules_lumina: setting('text', 'ae_fp8.safetensors'),
    model_manager_modules_zit: setting('text', ''),
    model_manager_modules_wan: setting('text', ''),
    model_manager_modules_qwen: setting('text', ''),
    model_manager_civitai_sfw_fill_page: setting('bool', false),
    model_manager_something_new: setting('bool', false, { label: 'A setting added later' }),
};
const ORDER = Object.keys(SETTINGS);
const posted = [];

// The text encoder and VAE table, as the server describes it: this WebUI has
// no Klein preset. Two copies of the Flux VAE are installed, and Lumina's
// setting names the fp8 one; Wan's VAE and Qwen-Image's are the same shape.
const cand = (label, precision = 'full') => ({ label, precision });
const AE = [cand('ae.safetensors'), cand('ae_fp8.safetensors', 'fp8')];
const WAN_SHAPE = [cand('qwen_image_vae.safetensors'), cand('qwen_image_vae_fp8.safetensors', 'fp8'),
                   cand('wan_2.1_vae.safetensors')];
// Kinds as classify() names them: shapes, which two files can share.
const KINDS = { ae: 'vae_ae', wan21_vae: 'vae_wan21', qwen_image_vae: 'vae_wan21' };
const fileRow = (file, label, candidates, automatic, selected = null, used_by = []) => ({
    file, label, kind: KINDS[file] || file, used_by, candidates, automatic, selected,
    links: [[`${file} download`, `https://example.invalid/${file}`]] });
const preset = (name, label, rows, kept = [], classes = [label]) => ({
    preset: name, label, note: '', setting: `model_manager_modules_${name}`, classes, rows, kept });
// The server's reading of a setting's text, as forge_modules.describe_presets
// does it: each name to the first row it is a candidate for, else kept.
function readInto(rows, text) {
    const kept = [];
    String(text || '').split(',').map((n) => n.trim()).filter(Boolean).forEach((name) => {
        const plain = (label) => label.replace(/\.safetensors$/, '');
        const row = rows.find((r) => !r.selected && r.candidates.some((c) => c.label === name || plain(c.label) === name));
        if (row) row.selected = row.candidates.find((c) => c.label === name || plain(c.label) === name).label;
        else kept.push({ name, why: 'not installed' });
    });
    return kept;
}
function describe(drafts = {}) {
    const text = (name) => drafts[name] ?? SETTINGS[`model_manager_modules_${name}`].value;
    const build = (name, label, rows, classes) => {
        const kept = readInto(rows, text(name));
        return preset(name, label, rows, kept, classes);
    };
    return [
        build('flux', 'Flux.1 / Chroma', [
            fileRow('clip_l', 'CLIP-L', [cand('clip_l.safetensors')], 'clip_l.safetensors', null, ['Flux.1']),
            fileRow('t5xxl', 'T5-XXL', [cand('t5xxl_fp16.safetensors'), cand('t5xxl_fp8.safetensors', 'fp8')],
                't5xxl_fp16.safetensors', null, ['Flux.1', 'Chroma']),
            fileRow('ae', 'Flux VAE (ae)', AE, 'ae.safetensors', null, ['Flux.1', 'Chroma']),
        ], ['Flux.1', 'Chroma']),
        build('lumina', 'Lumina Image 2.0', [
            fileRow('gemma2_2b', 'Gemma 2 2B', [], null),
            fileRow('ae', 'Flux VAE (ae)', AE, 'ae.safetensors'),
        ]),
        build('zit', 'Z-Image', [
            fileRow('qwen3_4b', 'Qwen3 4B', [cand('qwen_3_4b.safetensors')], 'qwen_3_4b.safetensors'),
            fileRow('ae', 'Flux VAE (ae)', AE, 'ae.safetensors'),
        ]),
        build('wan', 'Wan', [fileRow('wan21_vae', 'Wan 2.1 VAE', WAN_SHAPE, 'wan_2.1_vae.safetensors')]),
        build('qwen', 'Qwen-Image', [fileRow('qwen_image_vae', 'Qwen-Image VAE', WAN_SHAPE, 'qwen_image_vae.safetensors')]),
    ];
}
const tableAsked = [];
const keyTested = [];
// What the server says of judging stored images again, one answer per ask;
// the last is repeated. Nothing is running when the page loads.
let restampStates = [{ state: 'idle' }];
let keyAnswerReady = Promise.resolve();
const modelsAsked = [];
const libraryModel = (id) => ({ id, name: `M${id}`, display_name: `Model ${id}`, model_type: 'LORA',
                                file_path: `C:/m/${id}.safetensors`, has_civitai_data: true });
let settingsAsked = 0;

// Notes to the user, as the server lists them for "What's new": newest first.
const NOTES = [
    { id: 'b', version: '0.40.13', kind: 'feature', title: 'Pin the models you come back to',
      text: 'Pinned ones have a tab of their own.', dismissed: false },
    { id: 'a', version: '0.40.11', kind: 'action', title: 'Run Scan Disk once',
      text: 'With Re-evaluate file headers ticked.', dismissed: true },
];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/notes')) {
        return { ok: true, json: async () => ({ success: true, notes: NOTES }) };
    }
    if (href.includes('/model-manager/settings/nsfw-levels')) {
        const state = restampStates.length > 1 ? restampStates.shift() : restampStates[0];
        return { ok: true, json: async () => ({ success: true, ...state }) };
    }
    if (href.includes('/model-manager/settings/test-key')) {
        const body = JSON.parse(init.body);
        keyTested.push(body);
        await keyAnswerReady;
        const key = body.key ?? 'good-key';
        const result = key === 'good-key' ? { result: 'works', username: 'someone' }
            : key === '' ? { result: 'none' }
            : key === 'down-key' ? { result: 'unreachable', error: 'Connection error' }
            : { result: 'refused' };
        return { ok: true, json: async () => ({ success: true, which: 'key' in body ? 'typed' : 'saved', ...result }) };
    }
    if (href.includes('/model-manager/settings/modules')) {
        const drafts = new URL(href, 'http://webui').searchParams.get('drafts');
        tableAsked.push(drafts);
        return { ok: true, json: async () => ({ success: true, presets: describe(drafts ? JSON.parse(drafts) : {}) }) };
    }
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
    <button id="settings_submit">Apply settings</button><div id="settings_result"></div>
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
for (const [file, tab] of [['tab_model_manager.py', 'model_manager'], ['tab_civitai_browser.py', 'civitai_browser'],
                           ['header.py', 'TAB']]) {
    const markup = readFileSync(`${ROOT}/model_manager/ui/${file}`, 'utf8');
    check(`${file} has the gear, opening the one window, saying which tab it is in`,
          new RegExp(`class="mm-settings-btn"[^>]*onclick="window\\.mmOpenSettings && window\\.mmOpenSettings\\(\\{ tab: '${tab}' \\}\\)"`)
              .test(markup), true);
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
check('the text encoder and VAE table is asked for too', tableAsked.length, 1);
check('grouped into sections, in order, with a setting no section names under Other - What\'s new first',
      titles, ["What's new",
    'Civitai connection', 'Model Manager', 'Civitai Browser', 'Image gallery', 'NSFW detection',
    'Send to txt2img: text encoders and VAE', 'Advanced', 'Other']);
check('the text encoders collapsed', document.querySelectorAll('.mm-settings-section')[6].hasAttribute('open'), false);

// "What's new": every note that applies, dismissed ones too, by version -
// where a note dismissed in a tab can be read again. Collapsed.
const whatsNew = () => $('[data-whats-new]');
await waitFor('the notes', () => $('#mm_settings_notes')?.querySelector('[data-settings-note]'));
check('What\'s new lists the notes by version, newest first, dismissed ones too, collapsed',
      [whatsNew().hasAttribute('open'),
       Array.from($('#mm_settings_notes').querySelectorAll('.mm-settings-notes-version')).map((v) => v.textContent),
       Array.from($('#mm_settings_notes').querySelectorAll('[data-settings-note] strong')).map((t) => t.textContent)],
      [false, ['0.40.13', '0.40.11'], ['Pin the models you come back to', 'Run Scan Disk once']]);
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
check('at the size being set', [row().style.getPropertyValue('--mm-card-width'),
                                row().style.getPropertyValue('--mm-card-height')], ['160px', '224px']);
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
check('What\'s new is not a setting: a search leaves it out', whatsNew().hidden, true);
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

// ---------------------------------------------------------- testing the key
const keyField = () => field('model_manager_civitai_api_key');
const keyResult = () => [keyField().querySelector('#mm_settings_key_test').textContent,
                         keyField().querySelector('#mm_settings_key_test').dataset.tone];
async function testKey() {
    const before = keyTested.length;
    keyField().querySelector('[data-act="test-key"]').click();
    await waitFor('the key test', () => keyTested.length > before
        && !keyResult()[0].startsWith('Testing'));
}
await testKey();
check('with nothing typed, Test asks about the saved key', keyTested[keyTested.length - 1], {});
check('and says it works, and whose it is', keyResult(),
      ['The saved key works: signed in as someone.', 'good']);

type(keyField().querySelector('input'), 'wrong-key');
check('typing a new key clears what was said of the old one', keyResult()[0], '');
await testKey();
check('a typed key is tested before it is saved', keyTested[keyTested.length - 1], { key: 'wrong-key' });
check('and a refusal says so', keyResult(), ['Civitai refused the key typed here.', 'bad']);

type(keyField().querySelector('input'), 'down-key');
await testKey();
check('Civitai not answering is not a refused key', keyResult(), ['Could not reach Civitai: Connection error.', 'warn']);

// An answer for a key that has since been changed is not shown for the new one.
let release;
keyAnswerReady = new Promise((r) => { release = r; });
keyField().querySelector('[data-act="test-key"]').click();
check('while Civitai is asked, the window says so', keyResult()[0], 'Testing...');
type(keyField().querySelector('input'), 'good-key');
release();
await new Promise((r) => setTimeout(r, 50));
check('and an answer for a key since changed is dropped', keyResult()[0], '');
keyAnswerReady = Promise.resolve();

keyField().querySelector('[data-act="forget"]')?.click();
await testKey();
check('with the key removed, there is none to test', keyResult()[0], 'No key to test: type one, or save one first.');

// Leave the key as it was: close without saving, and open again.
confirmAnswer = true;
$('[data-act="cancel"]').click();
await window.mmOpenSettings();

// -------------------------------------------- text encoders and VAE table
const block = (name) => field(`model_manager_modules_${name}`);
const choice = (name, file) => block(name)?.querySelector(`select[data-file="${file}"]`);
function choose(name, file, value) {
    const select = choice(name, file);
    select.value = value;
    select.dispatchEvent(new window.Event('change', { bubbles: true }));
}
const said = (name) => block(name).querySelector('.mm-settings-extra').textContent.trim();
// What the window holds for a preset, read as a person would: Edit as text.
async function asText(name) {
    block(name).querySelector('[data-modules-text]').click();
    const value = block(name).querySelector(`input[data-key="model_manager_modules_${name}"]`).value;
    block(name).querySelector('[data-modules-text]').click();
    await waitFor('the table again', () => Boolean(block(name).querySelector('select')));
    return value;
}
const drafted = () => Object.fromEntries(['flux', 'lumina', 'zit', 'wan', 'qwen'].map((n) => [n,
    block(n).classList.contains('mm-settings-changed')]));

check('one block per preset this WebUI has, and none for one it lacks',
      ['flux', 'klein', 'lumina', 'zit', 'wan', 'qwen'].map((n) => Boolean(block(n))),
      [true, false, true, true, true, true]);
check('a row per file, choosing among the installed files of its kind, or Automatic',
      Array.from(choice('flux', 'ae').options).map((o) => o.textContent.trim()),
      ['Automatic: ae.safetensors', 'ae.safetensors (full)', 'ae_fp8.safetensors (fp8)']);
check('a preset of several models says which use each file',
      block('flux').querySelector('[data-file="t5xxl"] .mm-settings-module-for').textContent, 'Flux.1, Chroma');
check('a file nothing installed is gives its download links instead',
      block('lumina').querySelector('[data-file="gemma2_2b"] a')?.getAttribute('href'), 'https://example.invalid/gemma2_2b');
check('what the setting names is chosen', choice('lumina', 'ae').value, 'ae_fp8.safetensors');
check('and a name nothing installed matches is kept, and says why',
      block('flux').querySelector('.mm-settings-kept').textContent.replace(/\s+/g, ' ').trim(),
      'old_t5.safetensors not installed ×');

choose('flux', 'ae', 'ae.safetensors');
check('a row on Automatic that picks that file already stays on Automatic', choice('zit', 'ae').value, '');
check('a row set by hand keeps its own choice', choice('lumina', 'ae').value, 'ae_fp8.safetensors');
check('and the window says so', said('flux'), 'Lumina Image 2.0 (ae_fp8.safetensors) kept its own choice.');
check('the preset holds the chosen file, then the names it kept',
      await asText('flux'), 'ae.safetensors, old_t5.safetensors');

choose('flux', 'ae', 'ae_fp8.safetensors');
check('a row with nothing chosen that would pick another file is given this one',
      choice('zit', 'ae').value, 'ae_fp8.safetensors');
check('and the window says where', said('flux'), 'Also set for Z-Image.');
check('which is a change to that preset too', drafted(), { flux: true, lumina: false, zit: true, wan: false, qwen: false });

choose('wan', 'wan21_vae', 'qwen_image_vae_fp8.safetensors');
check('a file of the same shape but another file is not filled in: Qwen-Image\'s VAE is not Wan\'s',
      [choice('qwen', 'qwen_image_vae').value, said('wan')], ['', '']);
choose('wan', 'wan21_vae', '');
check('back to Automatic is no change', drafted().wan, false);

block('flux').querySelector('[data-kept-remove]').click();
check('a kept name can be removed', await asText('flux'), 'ae_fp8.safetensors');

block('zit').querySelector('.mm-settings-reset').click();
check('reset puts a preset back on Automatic', [choice('zit', 'ae').value, drafted().zit], ['', false]);

block('flux').querySelector('[data-modules-text]').click();
const text = block('flux').querySelector('input[data-key="model_manager_modules_flux"]');
check('a preset can be edited as text, the table\'s choices written out', text?.value, 'ae_fp8.safetensors');
type(text, 'ae_fp8.safetensors, t5xxl_fp8');
block('flux').querySelector('[data-modules-text]').click();
await waitFor('the table again', () => Boolean(choice('flux', 't5xxl')));
check('and back in the table, the server reads the text into it',
      [tableAsked[tableAsked.length - 1], choice('flux', 't5xxl').value],
      [JSON.stringify({ flux: 'ae_fp8.safetensors, t5xxl_fp8' }), 't5xxl_fp8.safetensors']);

$('#mm_settings_save').click();
await waitFor('the second save', () => saved.length === 2);
check('a save sends each preset\'s setting as text, as the Settings page holds it',
      posted[1], { model_manager_modules_flux: 'ae_fp8.safetensors, t5xxl_fp8' });

// ----------------------------------------- judging stored images again
// A save that changes how images are judged has the server judge every
// stored image again. A notice in the corner - the window has closed - shows
// how far it has got, then what changed.
const notice = () => document.querySelector('.mm-restamp');
const noticeText = () => notice()?.querySelector('.mm-restamp-text').textContent;
const n = (x) => Number(x).toLocaleString();
check('nothing is shown while nothing is running', notice(), null);

restampStates = [
    { state: 'running', judged: null, total: null },
    { state: 'running', judged: 50000, total: 100000 },
    { state: 'done', changed: 633, total: 100000 },
];
await window.mmOpenSettings();
pick(field('model_manager_nsfw_detection').querySelector('input[data-index="0"]'));
$('#mm_settings_save').click();
await waitFor('the notice', () => Boolean(notice()));
check('first, the images are being read: no share yet',
      [noticeText(), notice()?.classList.contains('mm-restamp-unknown')], ['Reading stored images...', true]);
await waitFor('the bar', () => noticeText()?.startsWith('Judging'));
check('then how many so far, as a bar', [noticeText(), notice()?.querySelector('.mm-restamp-fill').style.width],
      [`Judging stored images again... ${n(50000)} of ${n(100000)}`, '50%']);
await waitFor('the end', () => noticeText()?.startsWith('Done'));
check('then what changed', noticeText(), `Done: ${n(633)} of ${n(100000)} images changed level.`);

restampStates = [{ state: 'done', changed: 633, total: 100000 }];
const noticeShown = notice()?.style.display;
if (notice()) notice().style.display = 'none';
await window.mmOpenSettings();
type(field('model_manager_page_size').querySelector('input[type="number"]'), '40');
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 4);
await new Promise((r) => setTimeout(r, 400));
check('a save that changes nothing about judging shows no notice',
      [noticeShown, notice()?.style.display], ['', 'none']);

// ------------------------------------------- from the WebUI's Settings page
// Apply there saves through the same opts.set(), so the same pass runs. Its
// result line says what changed; the notice follows that. While Apply runs,
// Gradio puts its timer in the same element, beside the line the LAST Apply
// left - recorded on a real Settings page:
//   3.48s "0.0s   2 settings changed: model_manager_image_browsing, model_manager_nsfw_detection."
//   3.58s "1 settings changed: model_manager_nsfw_detection."
const { changedOnSettingsPage, restampNotice } = await import(`file:///${ROOT}/javascript/shared/settings.mjs?another-tab`);
check('the Settings page\'s result line is read for what it changed', [
    changedOnSettingsPage('2 settings changed: model_manager_nsfw_detection, sd_vae.'),
    changedOnSettingsPage('1 settings changed without save: model_manager_nsfw_prompt_words.'),
    changedOnSettingsPage('0 settings changed.'),
    changedOnSettingsPage('Unloaded all models'),
    changedOnSettingsPage('0.1s   1 settings changed: model_manager_nsfw_detection.'),
], [['model_manager_nsfw_detection', 'sd_vae'], ['model_manager_nsfw_prompt_words'], [], [], []]);

const apply = document.getElementById('settings_submit');
const result = document.getElementById('settings_result');
// Apply as Gradio does it: its timer beside the last line, then the new line.
function applied(line) {
    const before = result.textContent;
    apply.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    setTimeout(() => { result.innerHTML = `<span class="timer">0.0s</span>   ${before}`; }, 20);
    setTimeout(() => { result.querySelector('.timer').textContent = '0.1s'; }, 40);
    setTimeout(() => { result.textContent = line; }, 120);
}

notice().style.display = 'none';
result.textContent = '1 settings changed: sd_vae.';
restampStates = [{ state: 'running', judged: 1000, total: 100000 }, { state: 'done', changed: 12, total: 100000 }];
applied('2 settings changed: model_manager_nsfw_detection, sd_vae.');
await waitFor('the notice after Apply, within a second', () => noticeText()?.startsWith('Done: 12'), 20);
check('Apply that changes how images are judged shows the notice, though the last line did not name it',
      noticeText(), `Done: ${n(12)} of ${n(100000)} images changed level.`);

notice().style.display = 'none';
restampStates = [{ state: 'done', changed: 7, total: 100000 }];
applied('1 settings changed: sd_vae.');
await new Promise((r) => setTimeout(r, 600));
check('and Apply that changes something else does not, though the last line named it',
      notice().style.display, 'none');

// The same change again: the same line, arrived at through the timer.
result.textContent = '1 settings changed: model_manager_nsfw_prompt_words.';
applied('1 settings changed: model_manager_nsfw_prompt_words.');
await waitFor('the notice, the same line again', () => notice().style.display !== 'none', 20);
check('applying the same change again shows it too', noticeText(), `Done: ${n(7)} of ${n(100000)} images changed level.`);

// Every image judged, the changes being written.
notice().style.display = 'none';
restampStates = [{ state: 'running', judged: 100000, total: 100000 }, { state: 'running', judged: 100000, total: 100000 },
                 { state: 'done', changed: 3, total: 100000 }];
restampNotice().watch();
await waitFor('saving', () => noticeText() === 'Saving the new levels...', 20);
check('once every image is judged, it says the levels are being saved', noticeText(), 'Saving the new levels...');
await waitFor('done after saving', () => noticeText()?.startsWith('Done: 3'), 40);

// ------------------------------------------------- which sections are open
// Every section starts collapsed. Opened from a tab's gear, the ones that tab
// uses are open; from a note's button, only the one it is about, scrolled to.
const openSections = () => Array.from(document.querySelectorAll('.mm-settings-section[open]'))
    .map((s) => s.dataset.section);
const present = () => Array.from(document.querySelectorAll('.mm-settings-section[data-section]'))
    .map((s) => s.dataset.section);
const reopen = async (options) => {
    confirmAnswer = true;
    $('[data-act="cancel"]').click();
    await window.mmOpenSettings(options);
};
await reopen();
check('opened with nothing named, every section is collapsed', openSections(), []);
const TAB_SECTIONS = {
    model_manager: ['connection', 'model_manager', 'gallery', 'generations', 'nsfw', 'storage'],
    civitai_browser: ['connection', 'civitai_browser', 'gallery', 'nsfw', 'advanced'],
    generations: ['generations', 'nsfw'],
};
for (const [tab, sections] of Object.entries(TAB_SECTIONS)) {
    await reopen({ tab });
    check(`from the ${tab} tab's gear, its sections are open, the rest collapsed`,
          openSections(), present().filter((id) => sections.includes(id)));
}
check('What\'s new and the text encoder table never open from a gear',
      [$('[data-whats-new]').hasAttribute('open'), openSections().includes('modules')], [false, false]);
const scrolled = [];
window.HTMLElement.prototype.scrollIntoView = function() { scrolled.push(this.dataset.section); };
await reopen({ section: 'nsfw' });
check('from a note\'s button, only the section it is about, scrolled to', [openSections(), scrolled],
      [['nsfw'], ['nsfw']]);

done();
