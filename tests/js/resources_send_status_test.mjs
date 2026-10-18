// A send stopped for its checkpoint opens the image's Resources dialog, whose
// own Send stays disabled until the server says Forge can load the
// checkpoint (#211). The reason was in Send's tooltip alone: a checkpoint
// downloaded from the dialog read "Downloaded" on its row while Send stayed
// grey, for a second or more, saying nothing.
//
// Now a line beside Send says what it waits for - the download, then Forge
// listing the file - and, once the dialog has stopped asking with the
// checkpoint still not ready, offers Check again. How Send finds out does not
// change: a check at once, then one each TIMING.sendRecheck for
// TIMING.sendRecheckMax.
import { checker, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
// The page's waits, shortened: the fake server answers at once.
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const CHECKPOINT = 111;
const GONE = 333;
const installed = new Set([222]);
let listed = [];                          // the downloads list, as the server keeps it
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => structuredClone(body) });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: listed });
    if (href.includes('/civitai/download')) {
        const versionId = Number(init.body.get('version_id'));
        listed = [{ version_id: versionId, status: 'pending', percent: 0, file_name: 'checkpoint.safetensors' }];
        return reply({ success: true, version_id: versionId, version_name: 'v1', progress: listed[0] });
    }
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: Object.fromEntries([...installed].map((id) => [id, { version_id: id }])),
                       hashes: {}, other_files: {}, names: {}, embeddings: [] });
    }
    if (href.includes('/missing-resources')) {
        const asked = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(asked.map(({ version_id: id, model_id: model }) =>
            [id, id === GONE ? { gone: true } : { model_id: model }])) });
    }
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    return reply({ success: true });
};

await sharedModule('downloads.mjs');
const { showImageResources } = await sharedModule('resources.mjs');
await startServices('core.mjs', 'calls.mjs', 'downloads.mjs', 'resources.mjs');

// What a stopped send hands the dialog (send.mjs): why it waits, as a reason
// and its sentence, and how to ask the server again - the reason, '' once
// the checkpoint can be loaded.
const WAITS = {
    missing: 'The checkpoint is not in your library yet.',
    elsewhere: 'The checkpoint is in a folder this WebUI does not load.',
    not_listed: 'Forge does not list the checkpoint yet.',
    not_checkpoint: 'The image names no checkpoint.',
};
let answer = 'missing';
let asks = 0;
// A server slow to answer: each check waits for this, while it is set.
let holding = null;
const sent = [];
const stoppedSend = (reason) => ({ why: WAITS[reason], reason, waits: WAITS, run: () => sent.push(reason),
                                   check: async () => { asks += 1; await holding; return answer; } });
const image = (checkpoint) => ({ meta: { civitaiResources: [
    { type: 'checkpoint', modelVersionId: checkpoint, modelId: 11, name: 'A Checkpoint', modelVersionName: 'v1' },
    { type: 'lora', modelVersionId: 222, modelId: 22, name: 'A LoRA', modelVersionName: 'v1' }] } });

const modal = () => document.querySelector('.mm-resources-modal');
const line = () => (modal()?.querySelector('.mm-res-send-status')?.textContent || '').replace(/\s+/g, ' ').trim();
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const checkAgain = () => modal()?.querySelector('[data-action="resources.checkAgain"]');
const download = () => modal()?.querySelector(`[data-action="resources.download"][data-version-id="${CHECKPOINT}"]`);
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());

// ------------------------------------- not in the library, Download offered
await showImageResources(image(CHECKPOINT), null, { note: 'The checkpoint is not in your library.',
                                                    send: stoppedSend('missing') });
await waitFor('the checkpoint\'s Download', () => download());
await waitFor('the line', () => line().includes('download it above'));
check('not in the library: the line says to download it above, and nothing to check again',
      [line(), Boolean(checkAgain())], ['The checkpoint is not in your library yet: download it above.', false]);
check('Send stays disabled, its tooltip as before',
      [sendButton()?.disabled, sendButton()?.getAttribute('title')], [true, WAITS.missing]);

// ---------------------------------------------------- its download on its way
if (download()) press(download());
await waitFor('the download listed', () => listed.length);
listed = [{ ...listed[0], status: 'downloading', percent: 40 }];
await waitFor('the download\'s line', () => line().includes('download to finish'));
check('its download on its way: the line says Send waits for it',
      line(), 'Waiting for the checkpoint\'s download to finish…');

// ------------------------------------------- landed, Forge not listing it yet
// Landed, the check it sets off still on its way: on 7880 the line said
// "not in your library yet" for 120 ms beside a row saying Downloaded.
let release;
holding = new Promise((resolve) => { release = resolve; });
answer = 'not_listed';
listed = [{ ...listed[0], status: 'complete', percent: 100, synced: true }];
await waitFor('the row to say Downloaded', () => (modal()?.querySelector(`[data-res-download="${CHECKPOINT}"]`)
    ?.textContent || '').includes('Downloaded'));
check('landed, the server not answered yet: the line already says Send waits for Forge',
      line(), 'Waiting for Forge to list the checkpoint…');
holding = null;
release();
await waitFor('the line about Forge', () => line().includes('Forge to list'));
check('landed, Forge not listing it yet: the line says Send waits for Forge',
      [line(), sendButton()?.disabled], ['Waiting for Forge to list the checkpoint…', true]);
answer = '';
await waitFor('Send', () => sendButton() && !sendButton().disabled);
check('once Forge lists it: Send works, and the line is gone',
      [sendButton()?.disabled, Boolean(modal()?.querySelector('.mm-res-send-status'))], [false, false]);
close();

// ------------------------- Forge still not listing it once the dialog stops
answer = 'not_listed';
await showImageResources(image(CHECKPOINT), null, { note: 'Forge does not list it yet.',
                                                    send: stoppedSend('not_listed'), recheck: true });
await waitFor('the line about Forge', () => line().includes('Forge to list'));
check('asking: the line says Send waits for Forge, nothing to check again',
      [line(), Boolean(checkAgain())], ['Waiting for Forge to list the checkpoint…', false]);
await waitFor('Check again', () => checkAgain());
check('stopped asking with Forge not listing it: the line says so, with Check again',
      [line(), Boolean(checkAgain()), sendButton()?.disabled],
      ['Forge does not list the checkpoint yet.', true, true]);
const before = asks;
answer = '';
if (checkAgain()) press(checkAgain());
await waitFor('Send after Check again', () => sendButton() && !sendButton().disabled);
check('Check again asks the server again, and Send works once it says so',
      [asks > before, sendButton()?.disabled, Boolean(checkAgain())], [true, false, false]);
close();

// --------------------- in the library by its row, still missing to the server
answer = 'missing';
await showImageResources(image(CHECKPOINT), null, { note: 'Not in your library.',
                                                    send: stoppedSend('missing'), recheck: true });
await waitFor('Check again', () => checkAgain());
check('stopped asking with the checkpoint still missing: the line, with Check again',
      [line(), Boolean(checkAgain())], ['The checkpoint is not in your library yet.', true]);
close();

// ------------------------------------------------- no Download to offer
answer = 'missing';
await showImageResources(image(GONE), null, { note: 'Not in your library.', send: stoppedSend('missing') });
await waitFor('the gone checkpoint\'s row', () => modal()?.querySelector(`[data-res-download="${GONE}"]`)
    && !modal().querySelector(`[data-res-download="${GONE}"]`).textContent.trim()
    && document.querySelectorAll('[data-res-download]').length === 2);
await waitFor('the line', () => line());
check('no Download offered for it: the line does not point at one',
      line(), 'The checkpoint is not in your library yet.');
close();

check('nothing was sent', sent, []);
done();
