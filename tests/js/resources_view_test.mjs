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
//
// The same answer from the server holds each version's base model and family,
// and a checkpoint's row says them, beside its kind (#439).
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
// What a hash is of (resources.resolve_hashes).
const HASHES = { abcdef1234: { version_id: 7201, model_id: 720, name: 'Found by hash', version_name: 'v1',
                               model_type: 'Checkpoint' },
                 ffff000001: { version_id: null } };
const asked = [];                          // each missing-resources request's versions
let hold = null;                           // a promise the answer waits on: a slow Civitai
const opened = [];                         // what window.open was asked to open
window.open = (...args) => { opened.push(args[0]); return null; };

globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: ['Euler'], schedulers: ['Simple'], has_api_key: true,
                       image_browsing: 'continuous', gallery_grid: 'Classic',
                       family_names: { sd: 'SD 1.x', xl: 'SDXL', anima: 'Anima' } });
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
        const held = { 6004: { version_id: 6004 }, 7102: { version_id: 7102 } };
        const ids = (new URL(href, 'http://webui').searchParams.get('version_ids') || '').split(',');
        return reply({ success: true, versions: Object.fromEntries(ids.filter(id => held[id]).map(id => [id, held[id]])) });
    }
    if (href.includes('/model-manager/resolve-hashes')) {
        const hashes = (new URLSearchParams(String(init.body || '')).get('hashes') || '').split(',');
        return reply({ success: true, resolved: Object.fromEntries(hashes.filter(h => HASHES[h]).map(h => [h, HASHES[h]])), deferred: [] });
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
                            nsfw_images: 'all', hide_promptless_images: true },
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
const row = (versionId) => panel()?.querySelector(`[data-res-name="${versionId}"]`)?.closest('.mm-res-row') || null;
const view = (versionId) => row(versionId)?.querySelector('[data-action="resources.view"]') || null;
// View's own button, in the cell after the Download cell (#377, R4); the name above does the same.
const viewButton = (versionId) => row(versionId)?.querySelector('.mm-res-open [data-action="resources.view"]') || null;
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
check('View is a button again, in a cell of its own at the row\'s right, after the Download cell (#377, R4)',
      [viewButton(6001)?.textContent.trim(), viewButton(6001)?.title,
       Array.from(row(6001)?.children || []).map((cell) => cell.className)],
      ['View', 'Show this model in the Civitai Browser tab', ['mm-res-name', 'mm-res-actions', 'mm-res-open']]);

// ------------------------------------------------------------ pressed before the answer
const viewing = pressView(6002);
const looking = (versionId) => row(versionId)?.querySelector('.mm-res-looking')?.textContent.trim();
await waitFor('looking up', () => looking(6002) === 'Looking up...');
check('a row with no model id, pressed before the answer: "Looking up..." under its name, the name disabled',
      [looking(6002), view(6002)?.disabled], ['Looking up...', true]);
// "Looking up..." in it would widen View's column under the reader.
check('    and its View button disabled too, keeping its word',
      [viewButton(6002)?.textContent.trim(), viewButton(6002)?.disabled], ['View', true]);
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
check('a model Civitai deleted: its name opens nothing, no Download - the red message under the name (#377, R4)',
      [view(6003), row(6003)?.querySelector('[data-action="resources.download"]') ?? null,
       actions(6003), row(6003)?.querySelector('.mm-res-sub .mm-res-state.error')?.textContent],
      [null, null, '', 'Model deleted from Civitai']);
check('one the library holds keeps "Installed", the message under its name',
      [view(6004), actions(6004), !!row(6004)?.querySelector('.mm-res-sub .mm-res-state.error')], [null, 'Installed', true]);
check('a model whose version alone is gone keeps its View', !!view(6005), true);
check('    View\'s button too; a model Civitai deleted has an empty cell where it would be',
      [!!viewButton(6005), viewButton(6003), row(6003)?.querySelector('.mm-res-open')?.innerHTML.trim()], [true, null, '']);

const viewPressed = viewButton(6001);
if (viewPressed) await press(viewPressed);
await waitFor('the Civitai Browser asked again', () => shown.length === 2);
check('View\'s button on a row with its model id: the Civitai Browser at that model and version',
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

// The base model belongs to the image's version, even if its model has other versions (#439).
document.querySelector('#mm_meta_modal').close();
const { showImageResources } = await sharedModule('resources.mjs');
const checkpoints = { meta: { civitaiResources: [
    { type: 'Checkpoint', name: 'Example', modelId: 710, modelVersionId: 7101 },
    { type: 'model', name: 'Example', modelId: 710, modelVersionId: 7102 },
    { type: 'Checkpoint', name: 'Example', modelId: 710, modelVersionId: 7103 },
    { type: 'LORA', name: 'Example style', modelId: 711, modelVersionId: 7111 },
    { type: 'Checkpoint', name: 'Deleted model', modelId: 712, modelVersionId: 7121 },
    { type: 'Checkpoint', name: 'Unanswered', modelVersionId: 7131 },
] } };
Object.assign(ANSWERS, {
    7101: { model_id: 710, base_model: 'Illustrious', family: 'xl' },
    7102: { model_id: 710, base_model: 'SDXL <i>1.0</i>', family: 'xl' },
    7103: { model_id: 710, version_gone: true, newest: { version_id: 7101, version_name: 'v3', file_stem: 'example' } },
    7111: { model_id: 711, base_model: 'Pony', family: 'xl' },
    7121: { gone: true },
});
const notes = id => row(id)?.querySelector('.mm-res-sub')?.textContent.trim();
const labels = ['Checkpoint · SDXL · Illustrious', 'Checkpoint · SDXL · SDXL <i>1.0</i>'];
const requestsBefore = asked.length;
hold = new Promise(resolve => { release = resolve; });
await showImageResources(checkpoints, 7102);
check('before the version lookup answers, both checkpoints show their kind',
      [notes(7101), notes(7102)], ['Checkpoint', 'Checkpoint']);
release();
hold = null;
await waitFor('the version lookup to redraw the open rows', () => row(7121)?.querySelector('.mm-res-state.error'));
check('each checkpoint shows its family and its own base model, the installed one in its own gallery too',
      [notes(7101), notes(7102), actions(7101), actions(7102)], [...labels, 'Download', 'Installed']);
check('markup in the base model appears as literal text',
      [notes(7102), !!row(7102)?.querySelector('.mm-res-sub i')], [labels[1], false]);
check('a deleted version keeps its explanation beside a replacement row with its own base model',
      [notes(7103), actions(7103), notes(7101)],
      ['Checkpoint · this version is deleted from Civitai', 'Download v3, the newest', labels[0]]);
check('a LoRA, a deleted model and an unanswered checkpoint keep their notes without an extra separator',
      [notes(7111), notes(7121), notes(7131)], ['LoRA', 'Checkpoint · Model deleted from Civitai', 'Checkpoint']);

document.querySelector('#mm_meta_modal').close();
const reopened = showImageResources(checkpoints, 7102);
check('the first draw on reopening shows both cached labels', [notes(7101), notes(7102)], labels);
await reopened;
check('one batch when opened, then only the unanswered version when reopened',
      asked.slice(requestsBefore).map(batch => batch.map(item => item.version_id)),
      [[7101, 7102, 7103, 7111, 7121, 7131], [7131]]);
document.querySelector('#mm_meta_modal').close();
await showImageResources({ meta: { civitaiResources: [
    { type: 'Checkpoint', name: 'Example', modelId: 710, modelVersionId: '7101' },
] } }, null);
check('a version ID recorded as text reads the same cached label', notes(7101), labels[0]);

// An image with infotext and no Civitai list: its checkpoint's version is found by the hash it gives.
ANSWERS[7201] = { model_id: 720, base_model: 'SDXL 1.0', family: 'sd' };
document.querySelector('#mm_meta_modal').close();
await showImageResources({ meta: { resources: [{ type: 'model', name: 'Named by hash', hash: 'ABCDEF1234' }] } }, null);
await waitFor('the version lookup to answer', () => asked.at(-1)[0].version_id === 7201 && /·/.test(notes(7201) || ''));
check('a checkpoint found by its hash shows its family and base model', notes(7201), 'Checkpoint · SD 1.x · SDXL 1.0');

// What the server says of the family is said as it is: the library's file can be of another than
// Civitai's base model is (above), and one Civitai deleted still has it.
Object.assign(ANSWERS, {
    7301: { model_id: 730, version_gone: true, family: 'xl' },
    7302: { gone: true, family: 'sd' },
    7303: { model_id: 730, base_model: 'Anima', family: 'anima' },
    7304: { model_id: 730, base_model: 'HiDream' },
    7305: { model_id: 730, base_model: 'Something New', family: 'new' },
    7306: { model_id: 730, family: 'xl' },
});
const others = { meta: { civitaiResources: [7301, 7302, 7303, 7304, 7305, 7306].map(id => (
    { type: 'Checkpoint', name: 'Example', modelId: 730, modelVersionId: id })) } };
document.querySelector('#mm_meta_modal').close();
await showImageResources(others, null);
await waitFor('the lookup of the others', () => row(7302)?.querySelector('.mm-res-state.error'));
check('a deleted version and a deleted model: the family before their note', [notes(7301), notes(7302)],
      ['Checkpoint · SDXL · this version is deleted from Civitai', 'Checkpoint · SD 1.x · Model deleted from Civitai']);
check('a family named as the base model is said once; no family, the base model alone; no base model, the family',
      [notes(7303), notes(7304), notes(7306)], ['Checkpoint · Anima', 'Checkpoint · HiDream', 'Checkpoint · SDXL']);
check('a family with no name shows its preset\'s, as its tab does', notes(7305), 'Checkpoint · new · Something New');

// Another dialog opened while an answer is out: the late answer draws the rows showing, as they are there.
ANSWERS[7401] = { model_id: 740, base_model: 'Pony', family: 'xl' };
const one = id => ({ meta: { civitaiResources: [{ type: 'Checkpoint', name: 'Example', modelId: 740, modelVersionId: id }] } });
hold = new Promise(resolve => { release = resolve; });
document.querySelector('#mm_meta_modal').close();
await showImageResources(one(7401), null);
document.querySelector('#mm_meta_modal').close();
const second = one(7401);
second.meta.civitaiResources[0].modelVersionName = 'v9';
second.meta.civitaiResources.push(one(7303).meta.civitaiResources[0]);
await showImageResources(second, null);
const requestsOut = asked.length;
release();
hold = null;
await new Promise(resolve => setTimeout(resolve, 20));
check('a dialog replaced while its answer is out: the one showing draws its own rows',
      [notes(7303), notes(7401), row(7401)?.querySelector('.mm-res-version')?.textContent],
      ['Checkpoint · Anima', 'Checkpoint · SDXL · Pony', 'v9']);
document.querySelector('#mm_meta_modal').close();
const again = showImageResources(one(7401), null);
check('    and the first, opened again, its own, the late answer kept', [notes(7401), asked.length],
      ['Checkpoint · SDXL · Pony', requestsOut]);
await again;

for (const [resource, reason] of [[{ type: 'lora', name: 'Style' }, 'Named only by its name'],
                                  [{ type: 'model', name: 'Example' }, 'No hash recorded'],
                                  [{ type: 'model', name: 'Example', hash: 'ffff000001' }, 'Not on Civitai']]) {
    document.querySelector('#mm_meta_modal').close();
    await showImageResources({ meta: { Model: 'Example', resources: [resource] } }, null);
    const unresolved = panel()?.querySelector('.mm-res-unresolved');
    check('an unresolved checkpoint keeps its explanation: ' + reason,
          [unresolved?.querySelector('.mm-res-sub')?.textContent.trim(), unresolved?.querySelector('.mm-res-no-hash')?.textContent],
          ['Checkpoint', reason]);
}

done();
