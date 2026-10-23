// The settings window: one window for both tabs, grouped, showing only what
// applies, saving only what changed - and telling the Settings page, whose
// Apply button would otherwise send back the values it loaded with.
import { readFileSync } from 'fs';
import { ROOT, answerQuestions, call, checker, mountTab, sharedModule, startTab, tabMarkup } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The page's waits, shortened (TIMING): the preview's, the restamp's poll, a redraw's.
// The restamp's poll stays slower than waitFor's look (50 ms), which reads each state it passes through.
window.mmTiming = { previewWait: 30, restampPoll: 120, drawRetry: 25 };
// The Settings page's result line is watched for; linkedom has the observer,
// the harness does not make it global.
globalThis.MutationObserver = window.MutationObserver;
const { check, waitFor, done } = checker();

// ------------------------------------------------ the server's settings
// As the server describes them (#320): the registry's answer at every default
// (settings_answer.json, written by tools/settings_answer.py and held to the
// registry by settings_registry_test.py), with the values this suite starts
// from: the word list chosen, and two presets naming files.
const ANSWER = JSON.parse(readFileSync(`${ROOT}/tests/js/settings_answer.json`, 'utf8'));
const SETTINGS = structuredClone(ANSWER.settings);
SETTINGS.model_manager_nsfw_detection.value = 'words';
SETTINGS.model_manager_modules_flux.value = 'old_t5.safetensors';
SETTINGS.model_manager_modules_lumina.value = 'ae_fp8.safetensors';
const ORDER = [...ANSWER.order];
const PLACING = { groups: ANSWER.groups, tag_labels: ANSWER.tag_labels, badge_labels: ANSWER.badge_labels };
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
            return { ok: true, json: async () => ({ success: true, settings: SETTINGS, order: ORDER, ...PLACING,
                                                    changed, database_in_use: 'C:/models.db' }) };
        }
        settingsAsked += 1;
        return { ok: true, json: async () => ({ success: true, settings: SETTINGS, order: ORDER, ...PLACING,
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

// Each question answered as confirmAnswer says (#292): Discard, or Keep editing.
let confirmAnswer = true;
answerQuestions(() => String(confirmAnswer));
const saved = [];
window.addEventListener('mm-settings-saved', (e) => saved.push(e.detail.changed));

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

// -------------------------------------------------------------- the gear
// The tab as drawn, not the template: the template's placeholder once
// changed its quotes, and the Generations tab's gear said "TAB" (0.44.21).
for (const [file, tab] of [['tab_model_manager.py', 'model_manager'], ['tab_civitai_browser.py', 'civitai_browser'],
                           ['tab_generations.py', 'generations']]) {
    const markup = tabMarkup(`model_manager/ui/${file}`);
    check(`${file} has the gear, opening the one window, saying which tab it is in`,
          new RegExp(`class="mm-settings-btn"[^>]*data-action="settings\\.open" data-tab="${tab}"`)
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

await call('settings.open');
check('it opens', $('#mm_settings')?.open, true);
check('on the page body, outside anything Gradio redraws', $('#mm_settings')?.parentElement, document.body);
check('asking the server, each time it opens', settingsAsked, 1);

const titles = Array.from(document.querySelectorAll('#mm_settings_nav [data-act="group"] > span:first-child'))
    .map((s) => s.textContent);
check('the text encoder and VAE table is asked for too', tableAsked.length, 1);
check('grouped as the registry groups them, in its order - What\'s new first, then Tabs (#320)',
      titles, ["What's new", 'Tabs', 'Civitai account', 'Downloads', 'Pages and cards', 'What is hidden', 'Send',
               'Generations', 'Files and folders', 'Sync and queue', 'Updates']);
check('no group title above the list: the left pane says which group shows (#344)',
      document.querySelectorAll('.mm-settings-group-title, #mm_settings_body h4').length, 0);
// The window as the proof of concept drew it (#320): the groups on the left,
// each with its count, What's new first; one group on the right (#344).
const navEntries = () => Array.from(document.querySelectorAll('#mm_settings_nav [data-act="group"]'))
    .map((b) => [b.querySelector('span')?.textContent, b.querySelector('.mm-settings-count')?.textContent ?? null,
                 b.getAttribute('aria-current')]);
const shownSections = () => Array.from(document.querySelectorAll('.mm-settings-section[data-section]'))
    .filter((s) => !s.hidden).map((s) => s.dataset.section);
const countOf = (id) => Array.from(document.querySelectorAll(`.mm-settings-section[data-section="${id}"] .mm-settings-field`))
    .filter((f) => !f.hidden).length;
const labelOf = (id) => ANSWER.groups.find((g) => g.id === id)?.label;
check('two panes: the groups on the left, What\'s new first, each group with the count it shows; the first picked',
      [Boolean($('.mm-settings-panes #mm_settings_nav')), navEntries()],
      [true, [["What's new", null, 'false'], ...Array.from(document.querySelectorAll('.mm-settings-section[data-section]'))
          .map((s) => [labelOf(s.dataset.section), String(countOf(s.dataset.section)),
                       String(s.dataset.section === 'tabs')])]]);
check('opened with nothing named: the first group alone on the right, not every group (#344)',
      [shownSections(), $('[data-whats-new]')?.hidden], [['tabs'], true]);
const pressGroup = (id) => $(`#mm_settings_nav [data-group="${id}"]`)?.click();
pressGroup('pages_and_cards');
check('a group pressed: it alone, marked current', [shownSections(), navEntries().find(([, , c]) => c === 'true')?.[0]],
      [['pages_and_cards'], 'Pages and cards']);
pressGroup('pages_and_cards');
check('pressed again: it stays, not every group (#344)', shownSections(), ['pages_and_cards']);
// A row: name, badges and tags, the description under it, the control on
// the right - or, too wide for that, across the row.
const inCtl = (key, sel) => Boolean(field(key)?.querySelector(`.mm-settings-ctl ${sel}`));
const inWide = (key, sel) => Boolean(field(key)?.querySelector(`.mm-settings-wide-ctl ${sel}`));
check('a switch, a number, a choice and a folder path on the right; card size, the download folder and the key across',
      [inCtl('model_manager_preview_least_nsfw', 'input[type="checkbox"]'), inCtl('model_manager_page_size', 'input[type="range"]'),
       inCtl('model_manager_page_size', 'input[type="number"]'), inCtl('model_manager_generations_grid', '.mm-settings-seg input[type="radio"]'),
       inCtl('model_manager_queue_inputs_dir', 'input[type="text"]'),
       inWide('model_manager_card_size', '.mm-settings-cardsize'), inWide('model_manager_civitai_folder_template', 'input'),
       inWide('model_manager_civitai_api_key', 'input[type="password"]')],
      [true, true, true, true, true, true, true, true]);
check('the description under the name, on the left',
      field('model_manager_page_size')?.querySelector(':scope > .mm-settings-name + .mm-settings-ctl + .mm-settings-help') !== null,
      true);
// Each setting in one group, and none left over: a setting the registry has
// no group for cannot be declared (settings_registry_test).
check('every setting drawn once, in a group', ORDER.filter((k) => !k.startsWith('model_manager_modules_'))
    .every((k) => document.querySelectorAll(`.mm-settings-section .mm-settings-field[data-key="${k}"]`).length === 1), true);

// ------------------------------------------------------------- the tabs
// Each tab's switch, in one group, first, in the WebUI's tab order (#185),
// named "X Tab" (#320).
const TAB_KEYS = ['model_manager_queue_enabled', 'model_manager_record_generations', 'model_manager_gallery_tab',
                  'model_manager_model_manager_enabled', 'model_manager_civitai_browser_enabled'];
const nameOf = (key) => field(key)?.querySelector('.mm-settings-label')?.textContent;
check('Tabs holds the five switches, in the order of the tabs, each named "X Tab"',
      [Array.from(document.querySelectorAll('.mm-settings-section[data-section="tabs"] .mm-settings-field'))
          .map((f) => f.dataset.key), TAB_KEYS.map(nameOf)],
      [TAB_KEYS, ['Queue Tab', 'Generations Tab', 'Civitai Images Tab', 'Model Manager Tab', 'Civitai Browser Tab']]);
// A setting shows while a tab it needs is on, and a group while one of its
// settings does: switched off in the window, they go at once; the rest stay.
// A group with a setting shown, as the left pane counts it: one alone is on the right.
const sectionShown = (id) => Number($(`#mm_settings_nav [data-group="${id}"] .mm-settings-count`)?.textContent) > 0;
const SECTION_IDS = ANSWER.groups.map((g) => g.id);
const tickTab = (key, on) => {
    const box = field(key).querySelector('input[type="checkbox"]');
    box.checked = on;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};
tickTab('model_manager_model_manager_enabled', false);
tickTab('model_manager_civitai_browser_enabled', false);
check('the Model Manager and the Civitai Browser off: every group stays, for Generations, the Queue and Send',
      SECTION_IDS.filter(sectionShown), SECTION_IDS);
check('but their own settings go', shown('model_manager_page_size'), false);
// Only a sync started in the Model Manager hashes several files at once;
// every download's sync keeps a version's images, Send's too (#320, R6).
check('Files hashed at once goes with the Model Manager; Images kept per version stays, for every download',
      [shown('model_manager_hash_threads'), shown('model_manager_sync_images_per_version')], [false, true]);
tickTab('model_manager_record_generations', false);
check('Generations off too: the groups with nothing left go',
      SECTION_IDS.filter(sectionShown), ['tabs', 'civitai_account', 'downloads', 'send', 'files', 'sync_and_queue', 'updates']);
check('the picked group, Pages and cards, emptied: the first with a setting shown instead (#344)',
      [shownSections(), navEntries().find(([, , c]) => c === 'true')?.[0]], [['tabs'], 'Tabs']);
tickTab('model_manager_gallery_tab', true);
check('the Civitai Images tab on: its pages, cards and hidden images come back, and how many of its images load at once',
      [SECTION_IDS.filter(sectionShown).includes('pages_and_cards'), SECTION_IDS.filter(sectionShown).includes('hidden'),
       shown('model_manager_civitai_images_at_once')], [true, true, true]);
TAB_KEYS.forEach((key) => tickTab(key, true));
check('all on again: every group', SECTION_IDS.filter(sectionShown), SECTION_IDS);
// The Gallery's switch back to off, as it was: the counts below are of other changes.
tickTab('model_manager_gallery_tab', false);

// "What's new": every note that applies, dismissed ones too, by version -
// where a note dismissed in a tab can be read again. Collapsed.
const whatsNew = () => $('[data-whats-new]');
await waitFor('the notes', () => $('#mm_settings_notes')?.querySelector('[data-settings-note]'));
check('What\'s new lists the notes by version, newest first, dismissed ones too - shown only when pressed',
      [!whatsNew().hidden,
       Array.from($('#mm_settings_notes').querySelectorAll('.mm-settings-notes-version')).map((v) => v.textContent),
       Array.from($('#mm_settings_notes').querySelectorAll('[data-settings-note] strong')).map((t) => t.textContent)],
      [false, ['0.40.13', '0.40.11'], ['Pin the models you come back to', 'Run Scan Disk once']]);
check('with its window name, not Forge\'s', nameOf('model_manager_page_size'), 'Models per page');

// Tab headings inside a group (#320): settings for several tabs first, then
// each tab's; a row's tag that repeats its heading is left out.
const headingOf = (key) => {
    let at = field(key)?.previousElementSibling;
    while (at && !at.classList.contains('mm-settings-subheading')) at = at.previousElementSibling;
    return at?.textContent ?? null;
};
const tagsOf = (key) => Array.from(field(key)?.querySelectorAll('.mm-settings-tag') || []).map((t) => t.textContent);
const subheadings = (id) => Array.from(document.querySelectorAll(
    `.mm-settings-section[data-section="${id}"] .mm-settings-subheading`)).map((h) => h.textContent);
check('Pages and cards: shared across tabs first, then each tab in the WebUI\'s order',
      subheadings('pages_and_cards'),
      ['Shared across tabs', 'Generations Tab', 'Civitai Images Tab', 'Model Manager Tab', 'Civitai Browser Tab']);
check('the two "Models per page" under their tabs\' headings, no tag repeating it',
      [headingOf('model_manager_page_size'), headingOf('model_manager_civitai_page_size'),
       tagsOf('model_manager_page_size'), tagsOf('model_manager_civitai_page_size')],
      ['Model Manager Tab', 'Civitai Browser Tab', [], []]);
check('a shared setting says the tabs it acts in', tagsOf('model_manager_card_videos_play'),
      ['Model Manager Tab', 'Civitai Browser Tab']);
check('no headings where every setting falls under one, nor in Tabs', [subheadings('downloads'), subheadings('tabs')], [[], []]);
check('a state is a badge, not part of the name',
      [nameOf('model_manager_civitai_sfw_fill_page'),
       field('model_manager_civitai_sfw_fill_page')?.querySelector('.mm-settings-badge')?.textContent],
      ['Fill pages while hiding NSFW models', 'Not recommended']);

// How many of Civitai's images load at once (#213): in the account group,
// shown with or without a key, a box with no slider.
const AT_ONCE = 'model_manager_civitai_images_at_once';
const greyed = (key) => Boolean(field(key)?.classList.contains('mm-settings-off'));
const why = (key) => field(key)?.querySelector('.mm-settings-under')?.textContent ?? '';
check('Civitai images at once: in Civitai account, with its name, shown without a key',
      [field(AT_ONCE)?.closest('.mm-settings-section')?.dataset.section, nameOf(AT_ONCE), shown(AT_ONCE), greyed(AT_ONCE)],
      ['civitai_account', 'Images loading at once', true, false]);
check('a number box, no slider', [!!field(AT_ONCE)?.querySelector('input[type="number"]'),
                                  !!field(AT_ONCE)?.querySelector('input[type="range"]')], [true, false]);

// How many downloads run at once (#279): first in Downloads, shown without a
// key - a download needs none - a slider.
const DOWNLOADS = 'model_manager_downloads_at_once';
const groupKeys = (id) => Array.from(document.querySelectorAll(
    `.mm-settings-section[data-section="${id}"] .mm-settings-field`)).map((f) => f.dataset.key);
check('Downloads at once: first in Downloads, with its name, shown without a key',
      [groupKeys('downloads')[0], nameOf(DOWNLOADS), shown(DOWNLOADS)], [DOWNLOADS, 'Downloads at once', true]);
check('a slider from 1 to 10', ['min', 'max'].map((a) => field(DOWNLOADS)?.querySelector('input[type="range"]')?.getAttribute(a)),
      ['1', '10']);

// A file in parts (#282): the switch after Downloads at once, then how many
// connections, under it - a slider from 2, the switch being the only off -
// greyed while the switch is off, saying why, its value kept (#320).
const IN_PARTS = 'model_manager_download_in_parts';
const CONNECTIONS = 'model_manager_connections_per_file';
check('in parts: after Downloads at once, the switch, then the connections under it, with their names',
      [groupKeys('downloads').slice(1, 3), [IN_PARTS, CONNECTIONS].map(nameOf),
       field(CONNECTIONS)?.classList.contains('mm-settings-child')],
      [[IN_PARTS, CONNECTIONS], ['Download large files in parts', 'Connections per file'], true]);
const connectionsSlider = () => field(CONNECTIONS)?.querySelector('input[type="range"]');
check('the connections: a slider from 2 to 16, at 4, live while the switch is on',
      [connectionsSlider()?.getAttribute('min'), connectionsSlider()?.getAttribute('max'), connectionsSlider()?.value,
       shown(CONNECTIONS), greyed(CONNECTIONS), why(CONNECTIONS)], ['2', '16', '4', true, false, '']);
tickTab(IN_PARTS, false);
check('the switch off: the connections greyed, not hidden, saying why, their value kept',
      [shown(CONNECTIONS), greyed(CONNECTIONS), why(CONNECTIONS), connectionsSlider()?.value],
      [true, true, 'Applies while “Download large files in parts” is on.', '4']);
tickTab(IN_PARTS, true);
check('on again: live', [greyed(CONNECTIONS), why(CONNECTIONS)], [false, '']);

// Send's highest clip skip (#339): under its switch, greyed while Send takes
// no clip skip, its value kept.
const CLIP_SKIP = 'model_manager_send_clip_skip';
const CLIP_SKIP_MAX = 'model_manager_send_clip_skip_max';
const highestSlider = () => field(CLIP_SKIP_MAX)?.querySelector('input[type="range"]');
check('the highest clip skip: a slider from 1 to 12, at 6, live while Send takes the image\'s',
      [highestSlider()?.getAttribute('min'), highestSlider()?.getAttribute('max'), highestSlider()?.value,
       shown(CLIP_SKIP_MAX), greyed(CLIP_SKIP_MAX)], ['1', '12', '6', true, false]);
tickTab(CLIP_SKIP, false);
check('the switch off: greyed, its value kept', [shown(CLIP_SKIP_MAX), greyed(CLIP_SKIP_MAX), highestSlider()?.value],
      [true, true, '6']);
tickTab(CLIP_SKIP, true);
check('on again: live', greyed(CLIP_SKIP_MAX), false);

// The tile reading, a choice of two saved as words, drawn as a switch.
const READING = 'model_manager_generations_reading';
check('reading tiles: a switch, on for Single pass, with its Alpha badge',
      [field(READING)?.querySelector('input[type="checkbox"]')?.checked, nameOf(READING),
       field(READING)?.querySelector('.mm-settings-badge')?.textContent], [true, 'Read tiles in one pass', 'Alpha']);

// -------------------------------------------------------- what is shown
check('requests per second is greyed without an API key, saying why',
      [shown('model_manager_civitai_requests_per_second'), greyed('model_manager_civitai_requests_per_second'),
       why('model_manager_civitai_requests_per_second')], [true, true, 'Applies once an API key is set.']);
type(field('model_manager_civitai_api_key').querySelector('input'), 'a-new-key');
check('and live once one is typed', greyed('model_manager_civitai_requests_per_second'), false);

check('with the word list, the trained model\'s share is greyed, saying for what',
      [greyed('model_manager_nsfw_prompt_model_percent'), why('model_manager_nsfw_prompt_model_percent')],
      [true, 'Applies while “Find explicit PG images with” is Trained model.']);
check('the words are live', [shown('model_manager_nsfw_prompt_words'), greyed('model_manager_nsfw_prompt_words')],
      [true, false]);
pick(field('model_manager_nsfw_detection').querySelector('input[data-index="0"]'));
check('with the trained model, its share is live', greyed('model_manager_nsfw_prompt_model_percent'), false);
check('and the words still, since they apply with it too', greyed('model_manager_nsfw_prompt_words'), false);

// The Generations tab's own explicit-images setting, in What is hidden under
// its tab's heading - shown only while generations are recorded, there being
// no tab otherwise.
const GEN_NSFW = 'model_manager_generations_hide_nsfw';
const recording = () => field('model_manager_record_generations').querySelector('input[type="checkbox"]');
check('the Generations tab\'s setting is in What is hidden, under its tab, with its name',
      [field(GEN_NSFW)?.closest('.mm-settings-section')?.dataset.section, headingOf(GEN_NSFW), nameOf(GEN_NSFW)],
      ['hidden', 'Generations Tab', 'Hide explicit images by default']);
check('shown while generations are recorded', shown(GEN_NSFW), true);
// Whether a delete takes the files too, to begin with (#107): in
// Generations, shared by the Generations tab and a model's Your generations.
const GEN_DELETE = 'model_manager_generations_delete_files';
check('the delete setting is in Generations, shared across tabs, with its name and tabs',
      [field(GEN_DELETE)?.closest('.mm-settings-section')?.dataset.section, headingOf(GEN_DELETE), nameOf(GEN_DELETE),
       tagsOf(GEN_DELETE)],
      ['your_generations', 'Shared across tabs', 'Tick "also delete the files"', ['Generations Tab', 'Model Manager Tab']]);
check('shown while generations are recorded, too', shown(GEN_DELETE), true);

// Images as uploaded, not resized (#192): both in Pages and cards, shared.
check('the two image-size settings are in Pages and cards, shared, with their names',
      ['model_manager_gallery_originals', 'model_manager_card_originals'].map((key) =>
          [field(key)?.closest('.mm-settings-section')?.dataset.section, headingOf(key), nameOf(key)]),
      [['pages_and_cards', 'Shared across tabs', 'Full-size images in galleries'],
       ['pages_and_cards', 'Shared across tabs', 'Full-size images on model cards']]);
recording().checked = false;
recording().dispatchEvent(new window.Event('change', { bubbles: true }));
check('hidden when they are not', shown(GEN_NSFW), false);
check('and the delete setting with it', shown(GEN_DELETE), false);
recording().checked = true;
recording().dispatchEvent(new window.Event('change', { bubbles: true }));

// -------------------------------------------------------------- changes
check('two changes so far, counted', status(), '2 unsaved changes');
check('each marked', ['model_manager_civitai_api_key', 'model_manager_nsfw_detection']
    .every((k) => field(k).classList.contains('mm-settings-changed')), true);
type(field('model_manager_nsfw_prompt_model_percent').querySelector('input[type="number"]'), '3');
pick(field('model_manager_nsfw_detection').querySelector('input[data-index="1"]'));
check('a greyed setting\'s change still counts', status(), '2 unsaved changes');
check('as it would: it is greyed, and changed',
      [greyed('model_manager_nsfw_prompt_model_percent'),
       field('model_manager_nsfw_prompt_model_percent').classList.contains('mm-settings-changed')], [true, true]);

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
const settle = () => new Promise((r) => setTimeout(r, 80));     // the preview's wait, and a margin
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
type($('#mm_settings_search'), 'least explicit');
check('What\'s new is not a setting: a search leaves it out', whatsNew().hidden, true);
check('searching shows only what matches', ORDER.filter(shown), ['model_manager_preview_least_nsfw']);
// A tab's name finds the settings that act in it, by their tags (#320).
type($('#mm_settings_search'), 'queue tab');
// Word by word, two more hold both words apart: Images loading at once
// ("queues the rest", "its tab's setting"), and Downloads at once ("in the
// queue", and "Tab" in its tags).
check('a tab\'s name finds what acts in it', ORDER.filter(shown),
      ['model_manager_queue_enabled', 'model_manager_civitai_images_at_once', 'model_manager_downloads_at_once',
       'model_manager_database_path', 'model_manager_queue_inputs_dir', 'model_manager_queue_ask_above',
       'model_manager_check_updates']);
// Every word typed, in any order (#320): as one piece, "queue folder" found nothing.
type($('#mm_settings_search'), 'queue folder');
check('every word typed, in any order, finds a setting holding them apart', ORDER.filter(shown),
      ['model_manager_database_path', 'model_manager_queue_inputs_dir']);
type($('#mm_settings_search'), 'folder queue');
check('in either order', ORDER.filter(shown), ['model_manager_database_path', 'model_manager_queue_inputs_dir']);
type($('#mm_settings_search'), '');
// Send's presets under a heading of their own, its explanation under it
// (#320); both go with the presets, the Clip skip settings left.
const sendHeading = () => $('[data-section="send"] .mm-settings-subheading');
const sendIntro = () => $('[data-section="send"] .mm-settings-intro');
const sendRows = () => Array.from($('[data-section="send"] .mm-settings-fields')?.children || []);
check('Send\'s presets under their heading, the explanation under it, after Clip skip',
      [sendHeading()?.textContent, sendHeading()?.nextElementSibling === sendIntro(), sendHeading()?.hidden,
       sendIntro()?.hidden, sendRows().indexOf(field('model_manager_send_clip_skip_max')) < sendRows().indexOf(sendHeading())],
      ['Text encoders and VAE', true, false, false, true]);
type($('#mm_settings_search'), 'highest clip skip');
check('a search leaving Clip skip alone hides the presets\' heading and explanation too',
      [shown('model_manager_send_clip_skip_max'), sendHeading()?.hidden, sendIntro()?.hidden], [true, true, true]);
type($('#mm_settings_search'), '');

// ------------------------------------------------------ closing, saving
confirmAnswer = false;
$('[data-act="cancel"]').click();
check('closing with changes asks, and stays open when told to', $('#mm_settings').open, true);

heard.length = 0;
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 1);
check('a save sends what changed, and only that', posted[0], {
    model_manager_civitai_api_key: 'a-new-key',
    model_manager_page_size: 30,
    model_manager_card_size: '160x224',
    model_manager_nsfw_prompt_model_percent: 3,
});
check('the window closes', $('#mm_settings').open, false);
check('and the tabs are told what changed', saved[0].sort(), Object.keys(posted[0]).sort());
check('the Settings page\'s own fields are set to what was saved',
      Array.from(document.querySelectorAll('#setting_model_manager_page_size input')).map((i) => i.value), ['30', '30']);
check('as if typed there, so Gradio takes them',
      heard.includes('input:setting_model_manager_page_size'), true);

// ------------------------------------------------ one window, both tabs
// The tabs share the module's one copy (#53), so one window.
const before = (await sharedModule('settings.mjs')).settingsWindow();
check('the other tab, importing the module too, gets the same window',
      (await sharedModule('settings.mjs')).settingsWindow(), before);
await call('settings.open');
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
await call('settings.open');

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
await call('settings.open');
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
await call('settings.open');
type(field('model_manager_page_size').querySelector('input[type="number"]'), '40');
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 4);
await new Promise((r) => setTimeout(r, 250));          // two restamp polls: none would come
check('a save that changes nothing about judging shows no notice',
      [noticeShown, notice()?.style.display], ['', 'none']);

// The delete setting, ticked and saved like any other (#107).
await call('settings.open');
const deleteFiles = field(GEN_DELETE)?.querySelector('input[type="checkbox"]');
if (deleteFiles) {
    deleteFiles.checked = true;
    deleteFiles.dispatchEvent(new window.Event('change', { bubbles: true }));
}
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 5);
check('ticked and saved, the delete setting is sent by its key', posted.at(-1),
      { model_manager_generations_delete_files: true });

// Downloads at once, slid to 4 and saved (#279).
await call('settings.open');
const downloadsSlider = field(DOWNLOADS)?.querySelector('input[type="range"]');
if (downloadsSlider) type(downloadsSlider, '4');
$('#mm_settings_save').click();
await waitFor('the save', () => saved.length === 6);
check('Downloads at once, saved as a number by its key', posted.at(-1), { model_manager_downloads_at_once: 4 });

// ------------------------------------------- from the WebUI's Settings page
// Apply there saves through the same opts.set(), so the same pass runs. Its
// result line says what changed; the notice follows that. While Apply runs,
// Gradio puts its timer in the same element, beside the line the LAST Apply
// left - recorded on a real Settings page:
//   3.48s "0.0s   2 settings changed: model_manager_image_browsing, model_manager_nsfw_detection."
//   3.58s "1 settings changed: model_manager_nsfw_detection."
const { changedOnSettingsPage, restampNotice } = await sharedModule('settings.mjs');
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
await new Promise((r) => setTimeout(r, 300));          // over two restamp polls: none would come
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
const present = () => Array.from(document.querySelectorAll('.mm-settings-section[data-section]'))
    .map((s) => s.dataset.section);
const reopen = async (options) => {
    confirmAnswer = true;
    $('[data-act="cancel"]').click();
    await call('settings.open', options);
};
await reopen();
const band = () => $('#mm_settings_band');
const bandButtons = () => Array.from(band()?.querySelectorAll('[data-act="band"]') || [])
    .map((b) => [b.textContent.trim(), b.getAttribute('aria-pressed')]);
check('opened with nothing named, the first group, and no band', [shownSections(), band()?.hidden], [['tabs'], true]);
// A tab's gear (#320): the band, on that tab's settings - those tagged with
// it - their groups open; All settings beside it, with each count.
const drawn = () => ORDER.filter((k) => field(k));
const taggedWith = (tab) => drawn().filter((k) => (ANSWER.settings[k].tags || []).includes(tab));
const groupsOf = (keys) => present().filter((id) => keys.some((k) => ANSWER.settings[k].group === id));
// The Civitai Images tab is off here (above): its own setting shows with no band.
const byTabs = () => drawn().filter((k) => k !== 'model_manager_gallery_grid');
for (const [tab, label] of [['model_manager', 'Model Manager Tab'], ['civitai_browser', 'Civitai Browser Tab'],
                            ['generations', 'Generations Tab'], ['queue', 'Queue Tab']]) {
    await reopen({ tab });
    check(`from the ${tab} tab's gear: its settings alone, the first of their groups shown, the band on it`,
          [drawn().filter(shown), shownSections(), band()?.hidden, bandButtons()],
          [taggedWith(tab), groupsOf(taggedWith(tab)).slice(0, 1), false,
           [[`${label} settings ${taggedWith(tab).length}`, 'true'], [`All settings ${byTabs().length}`, 'false']]]);
}
check('the Queue Tab\'s: its switch, its two settings, the database file and the update check',
      taggedWith('queue'), ['model_manager_queue_enabled', 'model_manager_database_path',
                            'model_manager_queue_inputs_dir', 'model_manager_queue_ask_above',
                            'model_manager_check_updates']);
check('What\'s new and Send, with the text encoder table, never open from a gear',
      [$('[data-whats-new]').hidden, shownSections().includes('send')], [true, false]);
band()?.querySelector('[data-band="all"]')?.click();
check('All settings: every setting, the same group still shown, All pressed',
      [drawn().filter(shown), shownSections(), bandButtons().map(([, on]) => on)], [byTabs(), ['tabs'], ['false', 'true']]);
type($('#mm_settings_search'), 'folder');
check('a search keeps the band', [band()?.hidden, drawn().filter(shown).length > 1], [false, true]);
check('and, none matching in Tabs, shows the first group that has (#344)',
      [shownSections(), groupsOf(drawn().filter(shown)).length > 1], [groupsOf(drawn().filter(shown)).slice(0, 1), true]);
band()?.querySelector('[data-band="tab"]')?.click();
check('and narrows the tab\'s settings: its folder, and the database file\'s', drawn().filter(shown),
      ['model_manager_database_path', 'model_manager_queue_inputs_dir']);
type($('#mm_settings_search'), '');
check('back on the tab: its settings again', drawn().filter(shown), taggedWith('queue'));

// Changed (#320): only the settings off their default, beside the search -
// saved so earlier in this suite, or changed now and not saved.
await reopen();
const changedButton = () => $('#mm_settings_changed');
const SAVED_OFF = ['model_manager_civitai_api_key', 'model_manager_downloads_at_once', 'model_manager_page_size',
                   'model_manager_card_size', 'model_manager_nsfw_prompt_model_percent', 'model_manager_modules_flux',
                   'model_manager_modules_lumina', 'model_manager_generations_delete_files'];
check('Changed counts the settings off their default', [changedButton()?.textContent,
      changedButton()?.getAttribute('aria-pressed')], [`Changed (${SAVED_OFF.length})`, 'false']);
type(field('model_manager_hash_threads').querySelector('input[type="number"]'), '5');
changedButton()?.click();
const offNow = ORDER.filter((k) => [...SAVED_OFF, 'model_manager_hash_threads'].includes(k));
check('pressed: only those, the unsaved one too, the first of their groups shown, What\'s new hidden',
      [drawn().filter(shown), shownSections(), whatsNew().hidden, changedButton()?.textContent,
       changedButton()?.getAttribute('aria-pressed')],
      [offNow, groupsOf(offNow).slice(0, 1), true, `Changed (${offNow.length})`, 'true']);
field('model_manager_hash_threads')?.querySelector('[data-reset]')?.click();
check('reset to its default, it goes', [shown('model_manager_hash_threads'), changedButton()?.textContent],
      [false, `Changed (${SAVED_OFF.length})`]);
$('#mm_settings_all')?.click();
check('All: everything back', [drawn().filter(shown), changedButton()?.getAttribute('aria-pressed')], [byTabs(), 'false']);
// The Changed badge, and Reset, on a setting off its default alone.
const badgeShown = (key) => field(key)?.querySelector('.mm-settings-badge-changed')?.hidden === false;
const resetShown = (key) => field(key)?.querySelector('[data-reset]')?.hidden === false;
check('a setting off its default: the Changed badge and Reset; one at it, neither',
      [badgeShown('model_manager_page_size'), resetShown('model_manager_page_size'),
       badgeShown('model_manager_hash_threads'), resetShown('model_manager_hash_threads')], [true, true, false, false]);
// Nothing matches: said so.
type($('#mm_settings_search'), 'zzzz nothing');
check('nothing matches: said, every group hidden', [$('#mm_settings_empty')?.hidden, shownSections()], [false, []]);
type($('#mm_settings_search'), '');
check('cleared: the line goes', $('#mm_settings_empty')?.hidden, true);
// What's new, pressed on the left: it alone.
pressGroup('whats-new');
check('What\'s new pressed: it alone', [whatsNew()?.hidden, shownSections()], [false, []]);
pressGroup('whats-new');
check('pressed again: it stays (#344)', [whatsNew()?.hidden, shownSections()], [false, []]);
type($('#mm_settings_search'), 'folder');
check('a search there: the first group that has a match, as What\'s new holds no setting (#344)',
      [whatsNew()?.hidden, shownSections()], [true, groupsOf(drawn().filter(shown)).slice(0, 1)]);
type($('#mm_settings_search'), '');

// A link to a setting (#320): no band, its group open, scrolled to, marked.
const scrolled = [];
window.HTMLElement.prototype.scrollIntoView = function() { scrolled.push(this.dataset.section || this.dataset.key); };
await reopen({ focus: 'model_manager_send_clip_skip_max' });
check('a link: no band, its group alone, scrolled to it, marked',
      [band()?.hidden, shownSections(), scrolled, field('model_manager_send_clip_skip_max')?.classList.contains('mm-settings-marked')],
      [true, ['send'], ['model_manager_send_clip_skip_max'], true]);
scrolled.length = 0;
await reopen({ section: 'hidden' });
check('from a note\'s button, only the group it is about, scrolled to', [shownSections(), scrolled],
      [['hidden'], ['hidden']]);

// Thumbnails (#5): where and how many, under the switch that makes them; the
// folder under keeping them in one - greyed while that is not so, saying why
// (#320), and none of them while nothing is recorded.
const THUMBS = ['model_manager_thumbnails', 'model_manager_thumbnails_place', 'model_manager_thumbnails_folder',
                'model_manager_thumbnail_threads'];
await reopen({ tab: 'generations' });
const tickThumbs = (on) => {
    const box = field('model_manager_thumbnails').querySelector('input[type="checkbox"]');
    box.checked = on;
    box.dispatchEvent(new window.Event('change', { bubbles: true }));
};
check('making thumbnails, in a folder: all four shown, none greyed', [THUMBS.map(shown), THUMBS.map(greyed)],
      [[true, true, true, true], [false, false, false, false]]);
pick(field('model_manager_thumbnails_place').querySelector('input[data-index="1"]'));
check('beside each image: the folder greyed, saying why', [THUMBS.map(greyed), why('model_manager_thumbnails_folder')],
      [[false, false, true, false], 'Applies while \u201cWhere thumbnails are kept\u201d is In a folder.']);
pick(field('model_manager_thumbnails_place').querySelector('input[data-index="0"]'));
tickThumbs(false);
check('not making them: the three under it greyed, the folder saying the switch is why',
      [THUMBS.map(greyed), why('model_manager_thumbnails_folder')],
      [[false, true, true, true], 'Applies while \u201cMake thumbnails\u201d is on.']);
tickThumbs(true);
check('ticked again: all four live', THUMBS.map(greyed), [false, false, false, false]);
tickTab('model_manager_record_generations', false);
check('nothing recorded: none of the four', THUMBS.map(shown), [false, false, false, false]);
tickTab('model_manager_record_generations', true);

// "Your generations" is a model's section in the Model Manager. The settings
// for the Generations tab and the recorder say "Generations", in the window
// and on the WebUI's own Settings page.
const sectionTitle = $('#mm_settings_nav [data-group="your_generations"] > span')?.textContent.trim();
const recordLabel = $('[data-key="model_manager_record_generations"]')?.textContent.replace(/\s+/g, ' ').trim();
// Forge's names are the registry's page names now (#320).
const forgeLabels = Object.values(ANSWER.settings).map((s) => s.label);
check('the window names the section and its first setting "Generations"',
      [sectionTitle?.startsWith('Generations'), recordLabel?.startsWith('Generations')], [true, true]);
check('no label on the Settings page says "Your generations"',
      forgeLabels.filter((label) => label.startsWith('Your generations')), []);

done();
