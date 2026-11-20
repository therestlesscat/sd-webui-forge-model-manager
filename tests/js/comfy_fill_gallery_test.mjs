// Civitai images filled from their ComfyUI workflows (#232): the Fill notice
// with the Civitai Images tab alone on - the repair follows it as it follows
// the Model Manager - on a page loaded while Fill already runs, pressed in
// another page: the settings window's line shows where it is with no press,
// and the note's Review opens the window on its progress. The rest of the
// page's side: comfy_fill_page_test.mjs.
import { bootPage, checker, mountTab, tabsAnswer, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_gallery.py');
const { check, waitFor, done } = checker();

globalThis.fetch = withGalleryPages(async (url) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [],
                       tabs: { ...tabsAnswer({}), gallery: { on: true, built: true } } });
    }
    if (path === '/model-manager/repairs') {
        return reply({ success: true, repairs: { comfy_fill: { count: 1, tab: 'comfy_fill',
                                                               tabs: ['model_manager', 'gallery'] } } });
    }
    if (path === '/model-manager/repairs/comfy-fill') {
        return reply({ success: true, needed: true, newer: false,
                       fill: { state: 'running', step: 'filling', done: 300, total: 5098, read: 290, gained: 31,
                               prompts: 3, levels: 0, covers: 0 } });
    }
    if (path === '/model-manager/notes') {
        return reply({ success: true, notes: [{ id: 'comfy-fill-0-81-6', version: '0.81.6', kind: 'action',
            tabs: ['model_manager', 'gallery'], title: 'Civitai images filled from their ComfyUI workflows', text: 't',
            action: { id: 'repair', label: 'Review', repair: 'comfy_fill' } }] });
    }
    return reply({ success: true, images: [], groups: [], total: 0 });
});

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the repair to start', () => globalThis.__mmOffered?.has('repairs.comfy_fill'));
check('the Civitai Images tab alone on: Fill\'s window offered', globalThis.__mmOffered?.has('repairs.comfy_fill'),
      true);
const slot = document.createElement('div');
slot.dataset.repairsSlot = '';
document.body.appendChild(slot);
window.dispatchEvent(new window.CustomEvent('mm-upkeep-drawn', { detail: { slot } }));
await waitFor('its line', () => slot.querySelector('.mm-upkeep-line')?.textContent.includes('300'));
check('a page loaded while Fill runs: the settings line shows where it is, no press made',
      slot.querySelector('.mm-upkeep-line')?.textContent, 'Filling Civitai images from their workflows: 300 of 5,098');
await waitFor('the note', () => document.querySelector('#gal_notes [data-note-action="repair"]'));
const noteButton = document.querySelector('#gal_notes [data-note-action="repair"]');
check('its note\'s Review, naming Fill', [noteButton?.textContent.trim(), noteButton?.dataset.noteRepair],
      ['Review', 'comfy_fill']);
noteButton?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the window', () => document.querySelector('dialog.mm-repair [data-repair-status]'));
check('Review opens Fill\'s window on its progress, Fill disabled',
      [document.querySelector('dialog.mm-repair h3')?.textContent,
       document.querySelector('dialog.mm-repair [data-repair-status]')?.textContent,
       document.querySelector('dialog.mm-repair [data-repair-fill]')?.disabled],
      ['Fill Civitai images from their workflows',
       'Reading 300 of 5,098 images that may hold a workflow. 31 images have changed so far.', true]);

done();
