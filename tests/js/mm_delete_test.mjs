// Deleting a model, from the details panel's header.
//
// Delete sat at the foot of the panel and deleted the grid card's version,
// which after picking another version in the panel was not the file on
// screen. It is now in the header, beside "Show in Civitai Browser": "Delete
// Model" for a model with one version here, and for one with several,
// "Delete Current Model Version" - the version shown - and "Delete All Model
// Versions".
import { ROOT, act, checker, mountTab, press } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

const version = (id, name) => ({
    id, model_id: 4001, name: 'A Model', display_name: 'A Model', version_name: name,
    base_model: 'SDXL 1.0', model_type: 'LORA', file_path: `C:/models/${name}.safetensors`,
    file_name: `${name}.safetensors`, file_size: 1, nsfw_level: 1, has_civitai_data: true,
    local_version_count: 2, trained_words: [], tags: [],
});
let versions = [version(501, 'v1'), version(502, 'v2')];
const deleted = [];
let refuse = null;
let gridAsked = 0;

globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    // A copy, as an answer off the network is: the page changes what it is given.
    const reply = (body) => ({ ok: true, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/models/delete')) {
        const path = new URLSearchParams(String(init.body || '')).get('path');
        if (path === refuse) return reply({ success: false, error: 'Not a model in the library' });
        deleted.push(path);
        return reply({ success: true, deleted: [path] });
    }
    if (href.includes('/model-manager/models/versions')) return reply({ success: true, versions });
    if (href.includes('/model-manager/models/details')) return reply({ success: true, model: { images: [] } });
    if (href.includes('/model-manager/models')) {
        gridAsked++;
        return reply({ success: true, total: 1, page: 1, page_size: 20, models: [versions[0]] });
    }
    return reply({ success: true });
};
let confirmText = '';
window.confirm = globalThis.confirm = (text) => { confirmText = text; return true; };

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const open = async () => {
    document.getElementById('mm_load_btn').dispatchEvent(new window.Event('click', { bubbles: true }));
    await waitFor('the grid', () => document.querySelectorAll('#mm_grid .model-card').length > 0);
    await act('modelManager.selectModel', { index: 0 });
};
const header = () => document.querySelector('#mm_details .detail-header');
const buttons = () => Array.from(header()?.querySelectorAll('button.danger') || []).map((b) => b.textContent.trim());
// A click on the button, and its promise returned, so a check waits for
// every delete it starts.
const pressLabelled = (label) => press(Array.from(header().querySelectorAll('button'))
    .find((b) => b.textContent.trim() === label));

// ------------------------------------------------------ several versions
await open();
check('with several versions, the header offers the version shown, and all of them',
      buttons(), ['Delete Current Model Version', 'Delete All Model Versions']);
const order = Array.from(header().querySelectorAll('button')).map((b) => b.textContent.trim());
check('beside "Sync", before the close button',
      order.slice(order.indexOf('Sync'), order.indexOf('Sync') + 4),
      ['Sync', 'Delete Current Model Version', 'Delete All Model Versions', '×']);
check('and nothing is left at the foot of the panel',
      !!document.querySelector('#mm_details .detail-actions [data-action="modelManager.deleteModel"]'), false);

await act('modelManager.selectPill', { index: 1 });
await pressLabelled('Delete Current Model Version');
check('"current" deletes the version on screen - not the grid card\'s', deleted, ['C:/models/v2.safetensors']);
check('having named it in the confirmation', confirmText.includes('version "v2"'), true);

deleted.length = 0;
await open();
await pressLabelled('Delete All Model Versions');
check('"all" deletes every version here', deleted, ['C:/models/v1.safetensors', 'C:/models/v2.safetensors']);
check('having listed them in the confirmation',
      [confirmText.includes('all 2 versions'), confirmText.includes('v1.safetensors'),
       confirmText.includes('v2.safetensors')], [true, true, true]);

deleted.length = 0;
refuse = 'C:/models/v1.safetensors';
await open();
await pressLabelled('Delete All Model Versions');
check('one that fails does not stop the rest', deleted, ['C:/models/v2.safetensors']);
check('and is said', document.getElementById('mm_status')?.textContent.includes('v1: Not a model in the library'),
      true);
refuse = null;

// ------------------------------------------------------- one version
versions = [version(501, 'v1')];
deleted.length = 0;
await open();
check('with one version, one button: Delete Model', buttons(), ['Delete Model']);
await pressLabelled('Delete Model');
check('deleting that version', deleted, ['C:/models/v1.safetensors']);

// ------------------------------------------------- one version, two files
// An fp16 and an fp32 of one version (#133): one model, one version - and
// either file can go alone, from the version's Files list.
versions = [version(501, 'v1'), { ...version(501, 'v1'), file_path: 'C:/models/v1_fp32.safetensors',
                                  file_name: 'v1_fp32.safetensors' }];
deleted.length = 0;
await open();
check('with one version of two files, the header deletes the model', buttons(), ['Delete Model']);
const fileBins = () => Array.from(document.querySelectorAll('#mm_details .mm-files-slot [data-action="modelManager.deleteFile"]'));
check('and each file has its own delete in the Files list', fileBins().length, 2);
const askedBefore = gridAsked;
await press(fileBins()[1]);
check('that file, alone', deleted, ['C:/models/v1_fp32.safetensors']);
check('named as a file', confirmText.includes('the file v1_fp32.safetensors'), true);
check('its row goes, and nothing else: the panel stays open, the grid is not asked again',
      [!!header(), fileBins().length, gridAsked - askedBefore], [true, 0, 0]);
check('the one file left is shown as a version of one',
      [document.querySelector('#mm_details .file-path-cell')?.textContent.trim(),
       Array.from(document.querySelectorAll('#mm_details .mm-file-fact')).map((tr) => tr.style.display)],
      ['C:/models/v1.safetensors', ['', '', '']]);
await open();
await press(fileBins()[0]);
check('deleting the file shown shows the other, the panel still open',
      [!!header(), document.querySelector('#mm_details .file-path-cell')?.textContent.trim()],
      [true, 'C:/models/v1_fp32.safetensors']);
deleted.length = 0;
await open();
await pressLabelled('Delete Model');
check('the model, both its files', deleted, ['C:/models/v1.safetensors', 'C:/models/v1_fp32.safetensors']);

done();
