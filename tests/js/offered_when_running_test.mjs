// What is offered only while what it needs runs (#182).
//
// A download, while the downloads list runs: the Model Manager and the
// Civitai Browser start it, and a tab without them - Generations, the Queue -
// sends without it. The Resources dialog and the chips then offer no Download.
// A note's Sync button, while the sync's dialog is offered: the Model Manager
// starts it, and the notes in every tab no longer import it.
import { checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();
document.body.insertAdjacentHTML('beforeend', `
    <div id="txt2img_neg_prompt_row"></div>
    <div id="notes_before"></div><div id="notes_after"></div>`);

const SYNC_NOTE = { id: 'a-sync-note', version: '0.1.0', kind: 'action', title: 'Sync again', text: 't',
                    action: { id: 'sync', label: 'Sync' } };
globalThis.fetch = async (url) => {
    const body = String(url).includes('/model-manager/notes')
        ? { success: true, notes: [SYNC_NOTE] }
        : { success: true, versions: {}, hashes: {}, downloads: [], resources: {} };
    return { ok: true, status: 200, json: async () => body };
};

// As the Generations tab starts them: Send, and with it the Resources dialog
// and the chips - not the downloads list.
for (const name of ['core.mjs', 'calls.mjs', 'notes.mjs', 'send.mjs']) (await sharedModule(name)).start?.();
const resources = await sharedModule('resources.mjs');
const chips = await sharedModule('chips.mjs');
const { start: startDownloads } = await sharedModule('downloads.mjs');

// ------------------------------------------------------------ a download
const IMAGE = { id: 1, meta: { prompt: 'a prompt',
    civitaiResources: [{ type: 'LORA', name: 'Some LoRA', modelVersionId: 6001, modelId: 4001 }] } };
const CHIP = { kind: 'lora', name: 'some_lora', title: 'Some LoRA', weight: 1, versionId: 6001, modelId: 4001,
               installed: false };
const cell = () => document.querySelector('.mm-resources-modal [data-res-download="6001"]')?.innerHTML || '';
const chip = () => document.querySelector('#mm_resource_chips_txt2img [data-chip="0"]');

await resources.showImageResources(IMAGE, null);
await waitFor('the Resources dialog', () => cell());
check('downloads off: the dialog says it is not in the library, and offers no Download',
      [cell().includes('Not in the library'), cell().includes('resources.download')], [true, false]);
chips.showResourceChips('txt2img', [{ ...CHIP }]);
check('nor does its chip: it cannot be pressed, and says it is not available',
      [chip()?.disabled, chip()?.dataset.state], [true, 'unavailable']);
let asked = 0;
const realFetch = globalThis.fetch;
globalThis.fetch = (url) => { if (String(url).includes('/civitai/download')) asked += 1; return realFetch(url); };
await resources.downloadResource(6001, 4001);
check('and a download asked for all the same asks for nothing', asked, 0);

startDownloads?.();              // as the Model Manager or the Civitai Browser starts it
await resources.showImageResources(IMAGE, null);
await waitFor('the dialog again', () => cell().includes('resources.download'));
check('downloads on: the dialog offers Download', cell().includes('data-action="resources.download"'), true);
chips.showResourceChips('txt2img', [{ ...CHIP }]);
check('and so does the chip', [chip()?.disabled, chip()?.dataset.state], [false, 'download']);

// --------------------------------------------------------- a note's Sync
const { showNotes } = await sharedModule('notes.mjs');
const button = (id) => document.querySelector(`#${id} [data-note-action="sync"]`);
showNotes('before', 'notes_before');
await waitFor('the first notes', () => document.querySelector('#notes_before [data-note]'));
check('the sync\'s dialog not offered: the note has no Sync button', button('notes_before'), null);

(await sharedModule('jobs.mjs')).start?.();     // as the Model Manager starts it
const opened = [];
globalThis.__mmOffered.set('sync.showDialog', (options) => opened.push(options ?? null));
showNotes('after', 'notes_after');
await waitFor('the second notes', () => document.querySelector('#notes_after [data-note]'));
check('offered: the note has one', Boolean(button('notes_after')), true);
button('notes_after')?.dispatchEvent(new window.Event('click', { bubbles: true }));
check('and it opens the dialog by name', opened, [null]);

done();
