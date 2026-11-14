// A send stopped for a checkpoint the library lacks opens the image's
// Resources dialog. With another file of the image's version held, a tick
// offered to send with that file (#233); another version of the same model,
// a tick for one and a dropdown for several (#278); the same file held under
// another model, Send at once (#304). When none of those was held, the
// dialog's Send stayed grey for ever.
//
// Now one list of your checkpoints (#377): the stop opens with its box,
// "Choose the checkpoint to send with", ticked, and the list under it -
// asked once the dialog's missing-resources lookup has answered, with what it
// said of the image's checkpoint. What suits the image comes first, each with
// a chip saying why: another version of its model is suggested, not picked;
// the same file under another model is picked first, and the image comes out
// as made. Every pick is sent one way, by Forge's name for it.
import { checker, FORGE_REFRESH_EVENTS, forgeRefreshButtons, mountTab, press, sharedModule, startServices, tick } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const CHECKPOINT = 111;        // the version the image names, which the library lacks
const MODEL = 11;
let plan = null;               // what the send plan answers
let sameFile = null;           // what /missing-resources says of the checkpoint's file, held under another model
let list = null;               // what /send/checkpoints answers
let progress = [];             // what the downloads list answers
let listAfter = null;          // what /send/checkpoints answers once Forge's list is refreshed
let refreshes = [];            // Forge's refreshes pressed, from the stand-in buttons below
let forgeAnswered = false;     // whether Forge has answered its checkpoint refresh
const asked = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: progress });
    if (href.includes('/civitai/download')) {
        return reply({ success: true, version_id: CHECKPOINT, version_name: 'v5', file_id: 1111,
                       progress: { version_id: CHECKPOINT, file_id: 1111, status: 'pending', percent: 0 } });
    }
    // After a download, the new file is in Forge's list only once its refresh is answered.
    if (href.includes('/model-manager/send/checkpoints')) return reply(listAfter && forgeAnswered ? listAfter : list);
    // Forge's answer to its checkpoint refresh: only now does it list the new file.
    if (href.includes('/run/predict')) {
        forgeAnswered = refreshes.includes('checkpoints');
        return reply({});
    }
    if (href.includes('/queue/join')) return reply({});
    if (href.includes('/model-manager/send/plan')) return reply(plan);
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: { 222: { version_id: 222 } }, hashes: {}, other_files: {},
                       names: {}, embeddings: [] });
    }
    if (href.includes('/missing-resources')) {
        const wanted = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(wanted.map(({ version_id: id }) => [id, {
            model_id: MODEL, base_model: 'SD 1.5', ...(sameFile ? { same_file: sameFile } : {}) }])) });
    }
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true,
                       family_names: { sd: 'SD 1.x', xl: 'SDXL' } });
    }
    return reply({ success: true });
};

await sharedModule('downloads.mjs');
const { showImageResources } = await sharedModule('resources.mjs');
const { sendGalleryImage } = await sharedModule('send.mjs');
await (await sharedModule('ui_options.mjs')).uiOptions();
await startServices('core.mjs', 'calls.mjs', 'forge.mjs', 'downloads.mjs', 'resources.mjs');

const V16 = { name: '_SD\\a_v16.safetensors [1234]', file: 'a_v16.safetensors', family: 'sd', read: true, supported: true,
              model: 'A Checkpoint', version: 'V16', base_model: 'SD 1.5' };
const OTHER = { name: 'other.safetensors [9999]', file: 'other.safetensors', family: 'sd', read: true, supported: true,
                model: 'Another', version: 'v1', base_model: 'SD 1.5' };
const REUP = { name: 'reup.safetensors [5678]', file: 'reup.safetensors', family: 'sd', read: true, supported: true,
               model: 'A Re-upload', version: 'fp8', base_model: 'SD 1.5' };
const answer = (checkpoints, suggested, picked = null) => ({ success: true, checkpoints, suggested, picked,
    same_base: { base_model: 'SD 1.5', names: [] }, loaded: null, family: 'sd' });
const WAITS = { missing: 'The checkpoint is not in your library yet.' };
const picked = [];
// A stopped send, as send.mjs hands it to the dialog.
const stoppedSend = () => ({ opened: 'stop', ready: false, why: WAITS.missing, reason: 'missing', waits: WAITS, check: null,
                             run: () => picked.push('own'), pick: (name, model) => picked.push([name, model]),
                             button: 'Send to txt2img', list: { generation: 7 } });
const byId = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: CHECKPOINT, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v5' },
    { type: 'lora', modelVersionId: 222, modelId: 22, name: 'A LoRA', modelVersionName: 'v1' }] } };

const modal = () => document.querySelector('.mm-resources-modal');
const box = () => modal()?.querySelector('[data-action="resources.chooseTick"]');
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const status = () => modal()?.querySelector('.mm-res-send-status')?.textContent || '';
const rows = () => [...(modal()?.querySelectorAll('.mm-pick-row') || [])];
const rowOf = (name) => rows().find((r) => r.querySelector('input')?.value === name);
const whys = (row) => [...(row?.querySelectorAll('.mm-pick-why') || [])].map((c) => c.textContent);
const sub = (row) => row?.querySelector('.mm-pick-sub')?.textContent;
const active = () => modal()?.querySelector('.mm-pick-tab.active')?.textContent;
const heads = () => [...(modal()?.querySelectorAll('.mm-pick-head') || [])].map((h) => h.textContent);
const listAsked = () => asked.filter((h) => h.includes('/send/checkpoints'));
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const pickRow = (name) => {
    const radio = rowOf(name)?.querySelector('input');
    if (radio) { radio.checked = true; press(radio); }
};

// ------------------------------- another version of the model held (#278)
list = answer([V16, OTHER], [{ name: V16.name, why: ['same model'] }]);
await showImageResources(byId, null, { note: 'Not in your library.', send: stoppedSend() });
await waitFor('the list', () => rows().length);
check('a stop opens with its box ticked and the list under it, on Suggested', [box()?.checked, rows().length], [true, 1]);
const listUrl = new URL(listAsked()[0] || 'http://x/', 'http://x');
check('the list is asked after the missing-resources lookup, with what it said of the image\'s checkpoint',
      [asked.findIndex((h) => h.includes('/missing-resources')) < asked.findIndex((h) => h.includes('/send/checkpoints')),
       listUrl.searchParams.get('generation'), listUrl.searchParams.get('model_id'),
       listUrl.searchParams.get('base_model')],
      [true, '7', String(MODEL), 'SD 1.5']);
check('another version of the model: under Suggested, open first, saying why, its family and its file',
      [active(), heads(), sub(rowOf(V16.name))], ['Suggested 1', [], 'Same model, other version · SD 1.x · a_v16.safetensors']);
check('nothing picked: Send waits for a pick, saying so', [sendButton()?.disabled, status()], [true, 'Pick a checkpoint to send with.']);
pickRow(V16.name);
check('picked: Send is on, and says what it sends with',
      [sendButton()?.disabled, status()],
      [false, 'Sends with A Checkpoint V16. It will not come out exactly as made.']);
if (sendButton() && !sendButton().disabled) press(sendButton());
check('pressed: the dialog closes and the pick is sent by Forge\'s name, with the image\'s model',
      [Boolean(modal()), picked], [false, [[V16.name, MODEL]]]);
close();

// ------------------------------------------------- unticked: the image's own
picked.length = 0;
await showImageResources(byId, null, { note: 'Not in your library.', send: stoppedSend() });
await waitFor('the list', () => rows().length);
await tick('resources.chooseTick', false);
check('unticked: the list goes, and Send waits for the image\'s own, as before',
      [rows().length, sendButton()?.disabled, sendButton()?.getAttribute('title')], [0, true, WAITS.missing]);
close();

// ------------------------- the same file, held under another model (#304)
// One checkpoint uploaded twice: the server matched the missing version's
// file to the library's by its hash, and suggests it, picked first.
picked.length = 0;
asked.length = 0;
sameFile = { version_id: 333, file_name: 'reup.safetensors', model_name: 'A Re-upload', version_name: 'fp8' };
list = answer([OTHER, REUP], [{ name: REUP.name, why: ['same file'] }], REUP.name);
// Another image, its checkpoint another version: the page keeps each version's answer.
const reuploaded = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 3072332, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v1.0' }] } };
await showImageResources(reuploaded, null, { note: 'Not in your library.', send: stoppedSend() });
await waitFor('Send on', () => sendButton() && !sendButton().disabled);
check('the list was told of the same file, by its version',
      new URL(listAsked()[0] || 'http://x/', 'http://x').searchParams.get('same_file'), '333');
check('the same file under another model: suggested, picked first, Send on at once - the image comes out as made',
      [sub(rowOf(REUP.name)), rowOf(REUP.name)?.querySelector('input')?.checked, status()],
      ['Same file · SD 1.x · reup.safetensors', true, 'Sends with A Re-upload fp8. The image comes out as made.']);
if (sendButton() && !sendButton().disabled) press(sendButton());
check('and sends with it', picked, [[REUP.name, MODEL]]);
close();
sameFile = null;

// --------------------------------------- a download lands from the dialog
// A deleted version's newest, or the image's own: once it is in the library,
// the list is asked again, and shows it (#372, #377).
picked.length = 0;
asked.length = 0;
const NEWEST = { name: 'a_v6.safetensors [6666]', file: 'a_v6.safetensors', family: 'sd', read: true, supported: true,
                 model: 'A Checkpoint', version: 'v6', base_model: 'SD 1.5' };
list = answer([OTHER], []);
const landing = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: CHECKPOINT, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v5' }] } };
await showImageResources(landing, null, { note: 'Not in your library.', send: stoppedSend() });
await waitFor('the list', () => rows().length);
const download = modal()?.querySelector(`[data-action="resources.download"][data-version-id="${CHECKPOINT}"]`);
check('the checkpoint\'s row offers its Download', Boolean(download), true);
const listsBefore = listAsked().length;
// Forge lists the new file only once its refresh is answered: asked before
// then, the list would not hold it.
refreshes = forgeRefreshButtons(document, window);
listAfter = answer([OTHER, NEWEST], [{ name: NEWEST.name, why: ['same model'] }]);
if (download) press(download);
progress = [{ version_id: CHECKPOINT, file_id: 1111, status: 'complete', percent: 100, synced: true }];
await waitFor('the list asked again', () => listAsked().length > listsBefore && rowOf(NEWEST.name), 100);
check('20. once it lands and Forge has listed it, the list is asked again, the download in it, suggested',
      [listAsked().length > listsBefore, whys(rowOf(NEWEST.name))[0]], [true, 'Same model, other version']);
progress = [];
listAfter = null;
forgeAnswered = false;
close();

// ------------------- the list is not asked while Forge's refreshes run (#425)
// Each of Forge's two refreshes rebuilds its checkpoint list from nothing
// (`list_models`): asked meanwhile, the list comes back empty. The re-check
// finds the image's checkpoint ready once the first refresh has listed it,
// while the second - the extra networks' - still runs.
picked.length = 0;
list = answer([OTHER], []);
let rebuilding = false;        // between the extra networks refresh's press and the step Forge chains after it
const askedRebuilding = [];
const listWas = list;
listAfter = answer([OTHER, NEWEST], []);
const plain = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/queue/join')) {
        const fn = JSON.parse(String(init.body || '{}')).fn_index;
        if (fn === FORGE_REFRESH_EVENTS.extraNetworks) rebuilding = true;
        if (fn === FORGE_REFRESH_EVENTS.chained) rebuilding = false;
    }
    if (href.includes('/civitai/download') && !href.includes('progress')) {
        return { ok: true, status: 200, json: async () => ({ success: true, version_id: 113, version_name: 'v7', file_id: 1113,
            progress: { version_id: 113, file_id: 1113, status: 'pending', percent: 0 } }) };
    }
    if (href.includes('/model-manager/send/checkpoints')) {
        askedRebuilding.push(rebuilding);
        if (rebuilding) return { ok: true, status: 200, json: async () => answer([], []) };
    }
    return plain(url, init);
};
document.querySelectorAll('#forge_refresh_checkpoint, #txt2img_lora_extra_refresh_internal').forEach((b) => b.remove());
refreshes = forgeRefreshButtons(document, window, { delay: 120 });
const recheckable = { ...stoppedSend(), check: async () => (forgeAnswered ? null : 'missing') };
const landing2 = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 113, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v7' }] } };
await showImageResources(landing2, null, { note: 'Not in your library.', send: recheckable });
await waitFor('the list', () => rows().length);
const listsAt = askedRebuilding.length;
const download2 = modal()?.querySelector('[data-action="resources.download"][data-version-id="113"]');
if (download2) press(download2);
progress = [{ version_id: 113, file_id: 1113, status: 'complete', percent: 100, synced: true }];
await waitFor('both refreshes done and the list asked after them',
              () => refreshes.includes('extra networks') && !rebuilding && rowOf(NEWEST.name), 100);
check('21. a download lands: the list is never asked while Forge rebuilds its own, and ends with the download in it',
      [askedRebuilding.slice(listsAt).filter(Boolean).length, Boolean(rowOf(NEWEST.name)), Boolean(rowOf(OTHER.name))],
      [0, true, true]);
// Both asks still go: the re-check's, once the checkpoint can be loaded, and the one after downloads.
await waitFor('two asks after the rebuild', () => askedRebuilding.slice(listsAt).filter((r) => !r).length >= 2, 40);
check('    the re-check still asks for the list, after the rebuild, as does the ask after downloads',
      askedRebuilding.slice(listsAt).filter((r) => !r).length, 2);
globalThis.fetch = plain;
progress = [];
listAfter = null;
list = listWas;
forgeAnswered = false;
close();

// ------- a stop for a checkpoint Forge has not listed yet: Send presses its refresh first (#425)
// Send presses Forge's checkpoint refresh and opens the dialog at once (send.mjs, `not_listed`).
// The dialog's first ask must wait for that refresh: asked during it, the list is empty.
list = answer([OTHER, NEWEST], []);
let checkpointRefreshing = false;
const asked22 = [];
const plain22 = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/run/predict')) checkpointRefreshing = false;
    if (href.includes('/model-manager/send/checkpoints')) {
        asked22.push(checkpointRefreshing);
        if (checkpointRefreshing) return { ok: true, status: 200, json: async () => answer([], []) };
    }
    return plain22(url, init);
};
document.querySelectorAll('#forge_refresh_checkpoint, #txt2img_lora_extra_refresh_internal').forEach((b) => b.remove());
refreshes = forgeRefreshButtons(document, window, { delay: 120 });
document.querySelector('#forge_refresh_checkpoint')?.addEventListener('click', () => { checkpointRefreshing = true; });
const { refreshWebUiModelList } = await sharedModule('forge.mjs');
const notListed = { ...stoppedSend(), reason: 'not_listed', check: null };
refreshWebUiModelList();
await showImageResources(landing, null, { note: 'Not listed yet.', send: notListed, recheck: true });
await waitFor('the list after Send\'s refresh', () => rows().length && !checkpointRefreshing, 100);
check('22. Send presses Forge\'s refresh and opens the dialog: its first ask waits for the refresh, the list full',
      [asked22.filter(Boolean).length, asked22.length > 0, Boolean(rowOf(NEWEST.name)), Boolean(rowOf(OTHER.name))],
      [0, true, true, true]);
close();

// Opened for another image while its first ask waits: that ask never goes - the new dialog's does.
asked22.length = 0;
const askedFor = [];
const plain22b = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.includes('/model-manager/send/checkpoints')) askedFor.push(new URL(href, 'http://x').searchParams.get('generation'));
    return plain22b(url, init);
};
refreshWebUiModelList();
await showImageResources(landing, null, { note: 'Not listed yet.', send: notListed, recheck: true });
const other = { ...stoppedSend(), reason: 'not_listed', check: null, list: { generation: 8 } };
await showImageResources(landing, null, { note: 'Not listed yet.', send: other, recheck: true });
await waitFor('the second dialog\'s list', () => rows().length && askedFor.length, 100);
check('    opened for another image during the wait: the first dialog never asks, the second asks once',
      askedFor, ['8']);
globalThis.fetch = plain22;
list = listWas;
forgeAnswered = false;
close();
document.querySelectorAll('#forge_refresh_checkpoint, #txt2img_lora_extra_refresh_internal').forEach((b) => b.remove());
refreshes = forgeRefreshButtons(document, window);

// The Resources button's dialog, its box unticked by hand: a download of the
// image's checkpoint landing enables its Send, the image's own.
const { gallerySendLine } = await sharedModule('send.mjs');
const OWN_DOWNLOAD = 115;
const fresh = { id: 7115, meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: OWN_DOWNLOAD, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v9' }] } };
list = answer([OTHER], []);
await showImageResources(fresh, null, { send: gallerySendLine({ img: fresh, model: { id: 4001, base_model: 'SD 1.5' },
                                                                version: { id: 5001, file_path: 'C:/models/Lora/a.safetensors' } }) });
await waitFor('the box set', () => box()?.checked === true);
await tick('resources.chooseTick', false);
check('the Resources button\'s dialog, its checkpoint not here, unticked: Send waits for it', sendButton()?.disabled, true);
const ownDownload = modal()?.querySelector(`[data-action="resources.download"][data-version-id="${OWN_DOWNLOAD}"]`);
if (ownDownload) press(ownDownload);
progress = [{ version_id: OWN_DOWNLOAD, file_id: 1111, status: 'complete', percent: 100, synced: true }];
await waitFor('Send on once it lands', () => sendButton() && !sendButton().disabled, 100);
check('    its download landed: Send sends the image\'s own, the box left as pressed',
      [sendButton()?.disabled, status(), box()?.checked], [false, 'Sends with the image\'s own checkpoint.', false]);
progress = [];
close();

// ---------------------------------------------- a Civitai image's Send
// It stops for the checkpoint; a pick goes to the server as use_checkpoint,
// with the image's model, and the notice says what it was to the image.
asked.length = 0;
list = answer([V16, OTHER], [{ name: V16.name, why: ['same model'] }]);
const gallery = { id: 4001, base_model: 'SD 1.5', model_type: 'LORA' };
const shown = { id: 5001, file_path: 'C:/models/Lora/a_lora.safetensors', base_model: 'SD 1.5' };
plan = { success: true, preset: null, checkpoint: null, checkpoint_problem: { reason: 'missing', name: 'A Checkpoint' } };
await sendGalleryImage({ img: byId, model: gallery, version: shown });
await waitFor('the list, from a Civitai image', () => rows().length);
const civitaiUrl = new URL(listAsked()[0] || 'http://x/', 'http://x');
check('a Civitai image\'s list is asked with its checkpoint and its gallery',
      [civitaiUrl.searchParams.get('version_ids'), civitaiUrl.searchParams.get('gallery_file'),
       civitaiUrl.searchParams.get('gallery_base_model')],
      [String(CHECKPOINT), shown.file_path, 'SD 1.5']);
plan = { success: true, preset: null, checkpoint: V16.name, checkpoint_problem: null,
         instead: 'a_v16.safetensors', pick: 'version' };
pickRow(V16.name);
if (sendButton() && !sendButton().disabled) press(sendButton());
await waitFor('the send with it', () => asked.filter((h) => h.includes('use_checkpoint=')).length);
const withPick = new URL(asked.find((h) => h.includes('use_checkpoint=')), 'http://x');
check('picked and sent: the server is asked with Forge\'s name for it and the image\'s model',
      [withPick.searchParams.get('use_checkpoint'), withPick.searchParams.get('image_model'),
       withPick.searchParams.has('use_version')], [V16.name, String(MODEL), false]);
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('and the notice says it was another version of the model',
      (document.querySelector('.mm-notice')?.textContent || '').includes(
          'Sent with a_v16.safetensors, another version of the model this image was made with'), true);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
close();

// A Civitai image whose checkpoint the library holds under another model
// (#304): sent with it, and said to be the image's own - no caution.
asked.length = 0;
sameFile = { version_id: 334, file_name: 'reup.safetensors', model_name: 'A Re-upload', version_name: 'fp8' };
list = answer([OTHER, REUP], [{ name: REUP.name, why: ['same file'] }], REUP.name);
plan = { success: true, preset: null, checkpoint: null, checkpoint_problem: { reason: 'missing', name: 'A Checkpoint' } };
const ownFile = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 3072333, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v1.1' }] } };
await sendGalleryImage({ img: ownFile, model: gallery, version: shown });
await waitFor('Send on, from a Civitai image', () => sendButton() && !sendButton().disabled);
plan = { success: true, preset: null, checkpoint: REUP.name, checkpoint_problem: null, instead: 'reup.safetensors', pick: 'same' };
if (sendButton() && !sendButton().disabled) press(sendButton());
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('sent with the same file, and said to be the image\'s own checkpoint',
      [new URL(asked.find((h) => h.includes('use_checkpoint=')) || 'http://x/', 'http://x').searchParams.get('use_checkpoint'),
       document.querySelector('.mm-notice')?.textContent],
      [REUP.name, 'Sent with reup.safetensors: the checkpoint this image was made with, held in your library under another Civitai model.']);

done();
