// View in the Resources dialog shows the model in the Civitai Browser tab (#260).
//
// It opened the version on civitai.com, in a new browser tab: out of the
// WebUI, where a download lands outside the library. It now closes the
// dialog, and the viewer under it, notes the tab's Previous Position, and
// opens the Civitai Browser at the model and the image's version - the model
// id asked of the server where the image's list leaves it out. A model
// Civitai answers 404 for loses View and Download to a red "Model deleted
// from Civitai". The website stays the way out where the Civitai Browser
// cannot help: off, or no model id to be had.
import { act, checker, mountTab, press, sharedModule, startTab, tabEntries, tabMarkup, withGalleryPages }
    from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_civitai_browser.py'));
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_gallery.py'));
globalThis.onAfterUiUpdate = globalThis.onAfterUiUpdate || (() => {});

const VERSION_ID = 5001;                  // the version whose gallery this is
const MODEL = {
    id: VERSION_ID, model_id: 4001, name: 'A Model', display_name: 'A Model',
    version_name: 'v1', base_model: 'SDXL 1.0', model_type: 'LORA',
    file_path: 'C:/models/a.safetensors', file_name: 'a.safetensors',
    file_size: 1e9, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 1, trained_words: [], tags: [],
};
const RESOURCES = [
    { type: 'LORA', name: 'Has Model Id', modelVersionId: 6001, modelId: 600 },
    // Civitai's list on an image sometimes names a version alone.
    { type: 'LORA', name: 'No Model Id', modelVersionId: 6002 },
    { type: 'LORA', name: 'Deleted Model', modelVersionId: 6003, modelId: 603 },
    { type: 'Checkpoint', name: 'Deleted But Held', modelVersionId: 6004, modelId: 604 },
    { type: 'LORA', name: 'Version Gone', modelVersionId: 6005, modelId: 605 },
    // Civitai could not be asked about it: no answer.
    { type: 'LORA', name: 'Not Answered', modelVersionId: 6006 },
];
const IMAGE = {
    id: 4242, url: 'https://example.invalid/4242.jpeg', browsingLevel: 1, mm_level: 1,
    meta: { prompt: 'a prompt long enough to read', civitaiResources: RESOURCES },
};
// The server's answer per version (resources.missing_files): a 404 for the
// model alone is gone; a model whose version is gone still has its model id.
const ANSWERS = {
    6001: { file_stem: 'has', file_type: 'LORA', model_id: 600, name: 'Has Model Id', version_name: 'v1' },
    6002: { file_stem: 'no_id', file_type: 'LORA', model_id: 602, name: 'No Model Id', version_name: 'v1' },
    6003: { gone: true },
    6004: { gone: true },
    6005: { version_gone: true, model_id: 605, name: 'Version Gone', file_type: 'LORA' },
};
const asked = [];                          // each missing-resources request's versions
let hold = null;                           // a promise the answer waits on: a slow Civitai
const opened = [];                         // what window.open was asked to open
window.open = (...args) => { opened.push(args[0]); return null; };

globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Simple'], has_api_key: true,
                       image_browsing: 'continuous', gallery_grid: 'Classic' });
    }
    if (href.includes('/model-manager/missing-resources')) {
        const versions = JSON.parse(new URLSearchParams(String(init.body || '')).get('versions') || '[]');
        asked.push(versions);
        if (hold) await hold;
        const answered = {};
        for (const { version_id: id } of versions) if (ANSWERS[id]) answered[id] = ANSWERS[id];
        return reply({ success: true, versions: answered, hashes: {} });
    }
    if (href.includes('/model-manager/image-resources')) {
        return reply({ success: true, versions: { 6004: { file_path: 'C:/models/held.safetensors' } } });
    }
    if (href.includes('/model-manager/gallery/browse')) {
        return reply({ success: true, seed: 1, more: false, state: { total: 1, filtered: 1 }, scope: { count: 1 },
            tiles: [{ kind: 'image', image: { ...IMAGE, width: 1024, height: 1536, mm_level_from_prompt: false },
                      model: { id: 40, name: 'A LoRA', civitai_type: 'LORA', model_type: 'LORA', base_model: 'SDXL 1.0' },
                      version: { id: 400, name: 'v1', file_path: 'C:/models/Lora/a.safetensors', file_type: 'LORA',
                                 base_model: 'SDXL 1.0' } }] });
    }
    if (href.includes('/model-manager/models/details')) {
        return reply({ success: true, model: {
            ...MODEL, images: [IMAGE],
            images_state: { version_id: VERSION_ID, next_cursor: null, sync_date: '2026-01-01T00:00:00Z',
                            total_count: 1, hidden_count: 0, hidden_nsfw: 0, hidden_promptless: 0,
                            hide_nsfw_images: false, hide_promptless_images: true },
        } });
    }
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions: [MODEL] });
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 10, models: [MODEL] });
    }
    return reply({ success: true });
});

await startTab('modelManager');
await startTab('civitaiBrowser');
// The Civitai Browser's entry, stood in for: what it was opened at.
const shown = [];
(await tabEntries('civitai_browser.mjs')).showModel = async (query) => { shown.push(query); };
document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

const panel = () => document.querySelector('.mm-resources-modal');
const row = (versionId) => panel()?.querySelector(`[data-res-name="${versionId}"]`)?.closest('tr') || null;
const view = (versionId) => row(versionId)?.querySelector('[data-action="resources.view"]') || null;
const actions = (versionId) => row(versionId)?.querySelector('.mm-res-actions')?.textContent.replace(/\s+/g, ' ').trim();
// No button, no press: a check fails rather than the suite.
const pressView = (versionId) => (view(versionId) ? press(view(versionId)) : null);
const restoreShowing = (id) => {
    const button = document.getElementById(id);
    return Boolean(button) && button.style.display !== 'none';
};

document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
await act('modelManager.selectModel', { index: 0 });
await waitFor('the gallery', () => document.querySelectorAll('#mm_images .mm-image-card').length > 0);

// ------------------------------------------------------------ the dialog asks
let release;
hold = new Promise((resolve) => { release = resolve; });
const opening = act('modelManager.showResources', { index: 0 });
await waitFor('the dialog', () => view(6001));
check('the dialog asks the server about every row, once, each with the model id it has',
      asked, [[{ version_id: 6001, model_id: 600 }, { version_id: 6002, model_id: null },
               { version_id: 6003, model_id: 603 }, { version_id: 6004, model_id: 604 },
               { version_id: 6005, model_id: 605 }, { version_id: 6006, model_id: null }]]);
check('View says where it goes: the Civitai Browser', view(6001)?.title, 'Show this model in the Civitai Browser tab');

// ------------------------------------------------------------ pressed before the answer
const viewing = pressView(6002);
await waitFor('looking up', () => view(6002)?.textContent.trim() === 'Looking up...');
check('a row with no model id, pressed before the answer: "Looking up...", disabled',
      [view(6002)?.textContent.trim(), view(6002)?.disabled], ['Looking up...', true]);
release();
hold = null;
await opening;
await viewing;
await waitFor('the Civitai Browser asked', () => shown.length === 1);
check('then the Civitai Browser, at the model id the answer gave and the image\'s version',
      shown, ['model:602 version:6002']);
check('nothing opened on the website, and the dialog closed', [opened, panel()], [[], null]);
check('the Model Manager noted its Previous Position, the image\'s card its target',
      [restoreShowing('mm_scroll_restore_btn'), localStorage.getItem('mm_scroll_target')],
      [true, '#mm_images .mm-image-card[data-index="0"]']);

// ------------------------------------------------------------ the rows, answered
await act('modelManager.showResources', { index: 0 });
await waitFor('the dialog again', () => view(6001));
await waitFor('the held version', () => actions(6004)?.includes('Installed'));
check('answers are kept: opened again, only the one Civitai could not answer is asked again',
      asked.slice(1), [[{ version_id: 6006, model_id: null }]]);
check('a model Civitai deleted: no View, no Download - the red message in their place',
      [view(6003), row(6003)?.querySelector('[data-action="resources.download"]') ?? null,
       actions(6003), !!row(6003)?.querySelector('.mm-res-state.error')],
      [null, null, 'Model deleted from Civitai', true]);
check('one the library holds keeps "Installed", beside the message',
      [view(6004), actions(6004)], [null, 'Model deleted from Civitai Installed']);
check('a model whose version alone is gone keeps its View', !!view(6005), true);

await pressView(6001);
await waitFor('the Civitai Browser asked again', () => shown.length === 2);
check('View on a row with its model id: the Civitai Browser at that model and version',
      shown[1], 'model:600 version:6001');

// ------------------------------------------------------------ no model id to be had
await act('modelManager.showResources', { index: 0 });
await waitFor('the dialog once more', () => view(6006));
await pressView(6006);
check('no model id, and Civitai could not answer for one: the website, the dialog left open',
      [opened, !!panel(), shown.length], [['https://civitai.com/model-versions/6006'], true, 2]);
opened.length = 0;

// ------------------------------------------------------------ the Civitai Images tab
// Its Resources is in the viewer: View closes both, and notes the tab's place.
document.querySelector('.mm-modal-close')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await startTab('gallery');
await waitFor('the tile', () => document.querySelectorAll('#gal_grid .gen-tile').length === 1);
await press(document.querySelector('#gal_grid [data-action="gallery.view"][data-tile="0"]'));
await waitFor('the viewer', () => document.querySelector('[data-gal-resources]'));
document.querySelector('[data-gal-resources]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('its dialog', () => view(6001));
// Scrolled down: a place at the top shows no Previous Position.
Object.defineProperty(window, 'scrollY', { value: 5000, configurable: true });
await pressView(6001);
await waitFor('the Civitai Browser asked from it', () => shown.length === 3);
check('from the viewer: the viewer closed with the dialog',
      [!!document.querySelector('[data-gal-resources]'), panel()], [false, null]);
check('and the Civitai Images tab noted its Previous Position', restoreShowing('gal_scroll_restore_btn'), true);

// ------------------------------------------------------------ the Civitai Browser off
const { stopTab } = await sharedModule('loading.mjs');
stopTab('civitaiBrowser');
await act('modelManager.showResources', { index: 0 });
await waitFor('the dialog, the Civitai Browser off', () => view(6001));
check('with the Civitai Browser off, View says it opens the website',
      view(6001)?.title, 'Open this version on Civitai');
await pressView(6001);
check('and does: the image\'s version on civitai.com', [opened, shown.length],
      [['https://civitai.com/model-versions/6001'], 3]);

done();
