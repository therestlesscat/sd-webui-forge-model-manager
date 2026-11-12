// A model whose file is not there, in the details panel (#418).
//
// Since #389 a sync keeps the row of a file whose drive or folder cannot be
// seen. The panel asked its details and got "Model file not found": no
// description, no gallery, and Delete and Sync pressable for nothing. The
// details now answer from the library, saying which files are not there -
// "unseen", their drive or folder away, or "gone", deleted and not yet
// forgotten - and the panel follows: a line under the header, the Files
// list's tags, Delete and Sync greyed with why where none of their files is
// there, and a delete of some files that leaves the rest by name.
import { act, checker, forgeRefreshButtons, mountTab, press, startTab } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const version = (id, name, file = name) => ({
    id, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: name,
    base_model: 'SDXL 1.0', model_type: 'LORA', file_path: `X:/loras/${file}.safetensors`,
    file_name: `${file}.safetensors`, file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 2, trained_words: [], tags: [],
});
let versions = [version(501, 'v1')];
// The details route's word on each file, by path: "unseen", "gone", or there.
let away = {};
let loadsHere = true;
// A path whose details answer fails.
let failDetails = null;
const deleted = [];
let syncAnswer = null;

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/models/delete')) {
        const path = new URLSearchParams(String(init.body || '')).get('path');
        deleted.push(path);
        return reply({ success: true, deleted: [path] });
    }
    if (href.includes('/model-manager/models/force-sync')) return reply(syncAnswer);
    if (href.includes('/model-manager/sync/estimate')) {
        return reply({ success: true, estimate: { image_options: { page: 100, kept: {}, first: {} } } });
    }
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions });
    if (href.includes('/model-manager/models/details')) {
        // As the route answers (#418): the shown file's own word, the rest in files_absent.
        const path = new URL(href, 'http://webui').searchParams.get('path');
        if (path === failDetails) return reply({ success: false, error: 'Database is locked' });
        const model = { civitai_model: { description: 'From the library' },
                        images_state: { version_id: 501, total_count: 0 } };
        if (away[path]) Object.assign(model, { absent: away[path], loads_here: loadsHere });
        const others = Object.fromEntries(Object.entries(away).filter(([p]) => p !== path));
        if (Object.keys(others).length) model.files_absent = others;
        return reply({ success: true, model });
    }
    if (href.includes('/model-manager/models')) {
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [versions[0]] });
    }
    return reply({ success: true });
};
forgeRefreshButtons(document, window);
// The Delete question, answered Delete as it opens; its words kept.
let confirmText = '';
const elementProto = Object.getPrototypeOf(Object.getPrototypeOf(document.createElement('div')));
const showModal = elementProto.showModal;
elementProto.showModal = function answer() {
    showModal.call(this);
    const yes = '[data-value="true"]';
    if (this.classList.contains('mm-model-delete-dialog')) confirmText = this.textContent.replace(/\s+/g, ' ');
    setTimeout(() => this.querySelector(yes)?.dispatchEvent(new window.Event('click', { bubbles: true })), 0);
};

await startTab('modelManager');
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const open = async () => {
    document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
    await act('modelManager.selectModel', { index: 0 });
};
const header = () => document.querySelector('#mm_details .detail-header');
const button = (label) => Array.from(header().querySelectorAll('button')).find((b) => b.textContent.trim() === label);
const note = () => document.getElementById('mm_absent_note');
const noteText = () => (note()?.hidden ? null : note()?.querySelector('.mm-absent-text')?.textContent);
const greyed = (label) => [button(label)?.disabled, button(label)?.title];
const statusText = () => document.getElementById('mm_status')?.textContent.trim();

// ---------------------------------------------------- one file, its drive away
away = { 'X:/loras/v1.safetensors': 'unseen' };
await open();
check('the line says the drive or folder is not there, with the path',
      noteText(), 'The drive or folder this file was in is not there now: X:/loras/v1.safetensors. What is shown '
                  + 'is what the library kept. Connect the drive, and everything works again.');
check('the description comes, from the library',
      document.querySelector('#mm_details .mm-description')?.textContent.trim(), 'From the library');
const FORGET = 'To forget it, tick "Also forget files whose drive or folder is not there" in the Sync dialog; '
               + 'a sync that finds no file at all forgets nothing.';
check('Delete greyed, saying why and where to forget it', greyed('Delete Model'),
      [true, `This file's drive or folder is not there: nothing to delete. ${FORGET}`]);
check('Sync greyed, titled as Delete', greyed('Sync'),
      [true, `This model's drive or folder is not there: nothing to sync. ${FORGET}`]);

// The other WebUI's file, sharing the database: no drive to connect here.
loadsHere = false;
await open();
check('the other WebUI\'s file: no "connect the drive"',
      [noteText()?.includes('Connect the drive'), noteText()?.includes('a folder this WebUI does not load')], [false, true]);
loadsHere = true;

// ------------------------------------------------------- deleted by hand
away = { 'X:/loras/v1.safetensors': 'gone' };
await open();
check('a file deleted: the line says the next sync forgets it',
      noteText(), 'This file is no longer on disk: X:/loras/v1.safetensors. The next sync from the dialog forgets it.');
check('Delete greyed, the next sync forgets it', greyed('Delete Model'),
      [true, 'This file is no longer on disk: nothing to delete. The next sync from the dialog forgets it.']);
check('Sync greyed too', greyed('Sync'),
      [true, 'This model\'s files are no longer on disk: nothing to sync. The next sync from the dialog forgets them.']);

// ------------------------------------------------------- the file there
away = {};
await open();
check('a file there: no line, Delete and Sync as drawn',
      [noteText(), greyed('Delete Model'), greyed('Sync')],
      [null, [false, 'Delete this model, and its files'], [false, 'Force sync this model']]);

// --------------------------------------- two versions, a switch between them
versions = [version(501, 'v1'), version(502, 'v2')];
away = { 'X:/loras/v2.safetensors': 'unseen' };
await open();
check('v1 shown, there: no line; Delete Current pressable, Delete All too - v1 is there',
      [noteText(), button('Delete Current Model Version')?.disabled, button('Delete All Model Versions')?.disabled,
       button('Sync')?.disabled], [null, false, false, false]);
await act('modelManager.selectPill', { index: 1 });
await waitFor('the line for v2', () => noteText() !== null);
check('v2 shown, away: the line, and Delete Current greyed', [noteText()?.startsWith('The drive or folder'),
      button('Delete Current Model Version')?.disabled], [true, true]);
await act('modelManager.selectPill', { index: 0 });
await waitFor('the line gone for v1', () => noteText() === null);
check('back to v1: Delete Current pressable again', button('Delete Current Model Version')?.disabled, false);

// A switch whose details answer fails: the line and buttons follow the
// version all the same - the last answer named every file.
await act('modelManager.selectPill', { index: 1 });
await waitFor('the line for v2 again', () => noteText() !== null);
failDetails = 'X:/loras/v1.safetensors';
await act('modelManager.selectPill', { index: 0 });
check('back to v1, its details failing: no line, Delete Current pressable',
      [noteText(), button('Delete Current Model Version')?.disabled], [null, false]);
failDetails = null;

// Delete All with v2 away: v1 alone is sent, v2 named as left, not failed.
deleted.length = 0;
await press(button('Delete All Model Versions'));
check('Delete All sends only the file there', deleted, ['X:/loras/v1.safetensors']);
check('the question asks of the file it deletes, lists it, and names the one left, and why',
      [confirmText.includes('Are you sure you want to delete the file v1.safetensors of "A Model"?'),
       confirmText.includes('all 2 versions'),
       confirmText.includes('Left as they are, not there to delete: v2.safetensors - its drive or folder is not there now')],
      [true, false, true]);
check('the end line says what went, and the one left as information, not as a failure',
      [statusText(), document.getElementById('mm_status')?.classList.contains('error')],
      ['Deleted v1.safetensors of A Model. Left v2.safetensors: its drive or folder is not there now', false]);

// The model's Sync with v2 away: v1 synced, v2 left by name, not "failed".
syncAnswer = { success: true, synced_count: 1, total_versions: 2,
               errors: ['X:/loras/v2.safetensors: its drive or folder is not there now'] };
await open();
await press(button('Sync'));
await waitFor('the sync\'s line', () => (statusText() || '').startsWith('Synced'));
check('Sync counts the file there, and names the one left',
      statusText(), 'Synced 1 of 1 files from Civitai; left as they are: X:/loras/v2.safetensors: its drive or folder '
                    + 'is not there now');

// ---------------------------------------------- one version, two files, one away
versions = [version(501, 'v1'), version(501, 'v1', 'v1_fp32')];
away = { 'X:/loras/v1_fp32.safetensors': 'gone' };
await open();
const fileRows = () => Array.from(document.querySelectorAll('#mm_details .mm-files-slot tbody tr'));
check('the Files list tags the file not there, and greys its own delete',
      fileRows().map((tr) => [tr.querySelector('.mm-absent-tag')?.textContent || null,
                              tr.querySelector('[data-action="modelManager.deleteFile"]')?.disabled]),
      [[null, false], ['Not on disk', true]]);
check('its own delete titled why', fileRows()[1].querySelector('[data-action="modelManager.deleteFile"]')?.title,
      'This file is no longer on disk: nothing to delete. The next sync from the dialog forgets it.');

// Its sibling deleted from the Files list: the file not there is the one
// shown now, and the panel says so at once.
deleted.length = 0;
await press(fileRows()[0].querySelector('[data-action="modelManager.deleteFile"]'));
check('the file there deleted alone', deleted, ['X:/loras/v1.safetensors']);
check('the file left, not there, is shown with its line, Delete greyed',
      [noteText(), button('Delete Model')?.disabled],
      ['This file is no longer on disk: X:/loras/v1_fp32.safetensors. The next sync from the dialog forgets it.', true]);

done();
