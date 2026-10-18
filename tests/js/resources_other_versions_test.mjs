// A send stopped for a checkpoint the library lacks opens the image's
// Resources dialog. With another file of the image's version held, a tick
// offered to send with that file (#233) - for your own generations only: a
// Civitai image's stopped Send handed the dialog no way to send with
// anything else. Another version of the same model held offered nothing.
//
// Now one way out at a time (#278): the file of the image's own version when
// the library holds one, otherwise the other versions of its model - a tick
// for one, a dropdown for several - from your generations and Civitai images
// alike.
import { checker, choose, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const CHECKPOINT = 111;        // the version the image names, which the library lacks
const MODEL = 11;
const HASH = 'abcdef0123';     // an AutoV2 of another file of CHECKPOINT
let versions = [];             // what /other-versions answers
let otherFiles = {};           // what /image-resources says of another file of the version
let plan = null;               // what /forge-modules answers
const asked = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/civitai/download/progress')) return reply({ success: true, downloads: [] });
    if (href.includes('/other-versions')) return reply({ success: true, versions });
    if (href.includes('/forge-modules')) return reply(plan);
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: { 222: { version_id: 222 } }, hashes: {}, other_files: otherFiles,
                       names: {}, embeddings: [] });
    }
    if (href.includes('/resolve-hashes')) {
        return reply({ success: true, deferred: [], resolved: { [HASH]: {
            version_id: CHECKPOINT, model_id: MODEL, name: 'A Checkpoint', version_name: 'v5', model_type: 'Checkpoint' } } });
    }
    if (href.includes('/missing-resources')) {
        const wanted = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(wanted.map(({ version_id: id }) => [id, { model_id: MODEL }])) });
    }
    if (href.includes('/ui-options')) return reply({ success: true, samplers: [], schedulers: [], has_api_key: true });
    return reply({ success: true });
};

await sharedModule('downloads.mjs');
const { showImageResources } = await sharedModule('resources.mjs');
const { sendGalleryImage } = await sharedModule('send.mjs');
await startServices('core.mjs', 'calls.mjs', 'downloads.mjs', 'resources.mjs');

const V16 = { version_id: 112, version_name: 'V16', base_model: 'SD 1.5', file_name: 'a_v16.safetensors' };
const XL = { version_id: 113, version_name: 'V2 XL', base_model: 'SDXL 1.0', file_name: 'a_xl.safetensors' };
const WAITS = { missing: 'The checkpoint is not in your library yet.' };
const used = [];
// Your generations' stopped send, as send.mjs hands it to the dialog.
const stoppedSend = () => ({ why: WAITS.missing, reason: 'missing', waits: WAITS, check: null, run: () => used.push('own'),
                             useInstalled: (versionId, kind) => used.push([versionId, kind]) });
const byId = { meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: CHECKPOINT, modelId: MODEL, name: 'A Checkpoint', modelVersionName: 'v5' },
    { type: 'lora', modelVersionId: 222, modelId: 22, name: 'A LoRA', modelVersionName: 'v1' }] } };
const byHash = { meta: { prompt: 'a lighthouse', resources: [{ type: 'model', name: 'a_checkpoint', hash: HASH }] } };

const modal = () => document.querySelector('.mm-resources-modal');
const tick = () => modal()?.querySelector('[data-action="resources.useInstalledTick"]');
const tickText = () => (tick()?.closest('label')?.textContent || '').replace(/\s+/g, ' ').trim();
const picker = () => modal()?.querySelector('[data-action="resources.chooseVersion"]');
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const note = () => modal()?.querySelector('[data-res-note]')?.textContent || '';
const versionsAsked = () => asked.filter((h) => h.includes('/other-versions'));
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const NOTE = 'The checkpoint this image was made with, A Checkpoint, is not in your library. Download it here, then press Send.';

// ------------------------------------------------- one other version held
versions = [V16];
await showImageResources(byId, null, { note: NOTE, send: stoppedSend() });
await waitFor('the tick', () => tick());
check('one other version of the model held: a tick naming it and its base model',
      tickText(), 'Use V16 (SD 1.5), the version I have, instead: the image may not come out exactly the same');
check('asked by the image\'s version and its model',
      versionsAsked().map((h) => [new URL(h, 'http://x').searchParams.get('version_id'),
                                  new URL(h, 'http://x').searchParams.get('model_id')]), [[String(CHECKPOINT), String(MODEL)]]);
check('the note offers the version you have',
      note(), 'The checkpoint this image was made with, A Checkpoint v5, is not in your library. '
              + 'Download it here, or send with the version of it you have.');
check('Send waits until it is ticked', sendButton()?.disabled, true);
if (tick()) { tick().checked = true; press(tick()); }
check('ticked, Send is on', sendButton()?.disabled, false);
if (sendButton() && !sendButton().disabled) press(sendButton());
check('and sends with that version, saying it is another version', used, [[112, 'version']]);
close();

// ------------------------------------------------ several versions held
used.length = 0;
asked.length = 0;
versions = [V16, XL];
await showImageResources(byId, null, { note: NOTE, send: stoppedSend() });
await waitFor('the dropdown', () => picker());
const options = () => [...(picker()?.querySelectorAll('option') || [])].map((o) => o.textContent);
check('two versions held: a dropdown, the image\'s own first, then each version with its base model',
      options(), ['The image\'s own checkpoint - download it above', 'V16 (SD 1.5)', 'V2 XL (SDXL 1.0)']);
check('no tick beside it', Boolean(tick()), false);
check('the image\'s own selected, and Send waits', [picker()?.value, sendButton()?.disabled], ['', true]);
if (picker()) choose('resources.chooseVersion', '113');
check('a version picked: Send is on, and the pick stays drawn', [sendButton()?.disabled, picker()?.value], [false, '113']);
if (picker()) choose('resources.chooseVersion', '');
check('the image\'s own picked again: Send waits again', sendButton()?.disabled, true);
if (picker()) choose('resources.chooseVersion', '112');
if (sendButton() && !sendButton().disabled) press(sendButton());
check('Send goes with the version picked', used, [[112, 'version']]);
close();

// ------------------------------- another file of the image's version too
used.length = 0;
asked.length = 0;
versions = [V16];
otherFiles = { [HASH]: { name: 'a_v5_fp16.safetensors', fp: 'fp16', size: 'pruned', file_size: 2132651338 } };
await showImageResources(byHash, null, { note: NOTE, send: stoppedSend() });
await waitFor('the tick', () => tick());
await new Promise((r) => setTimeout(r, 100));
check('another file of the image\'s own version held: its tick alone, as before (#233)',
      [tickText().startsWith('Use the fp16 pruned'), Boolean(picker())], [true, false]);
check('and the other versions are not asked for', versionsAsked(), []);
close();
otherFiles = {};

// ------------------------------------------------- nothing of it held
asked.length = 0;
versions = [];
await showImageResources(byId, null, { note: NOTE, send: stoppedSend() });
await waitFor('the question', () => versionsAsked().length);
await new Promise((r) => setTimeout(r, 50));
check('nothing of the model held: nothing offered, asked once',
      [Boolean(tick()), Boolean(picker()), versionsAsked().length], [false, false, 1]);
close();

// ---------------------------------------------- a Civitai image's Send
// It stops for the checkpoint; the dialog offers the version held; ticked,
// Send asks the server again with use_version, and says what it sent with.
asked.length = 0;
versions = [V16];
const gallery = { id: 4001, base_model: 'SD 1.5', model_type: 'LORA' };
const shown = { id: 5001, file_path: 'C:/models/Lora/a_lora.safetensors', base_model: 'SD 1.5' };
plan = { success: true, preset: null, checkpoint: null,
         checkpoint_problem: { reason: 'missing', name: 'A Checkpoint' } };
await sendGalleryImage({ img: byId, model: gallery, version: shown });
await waitFor('the tick, from a Civitai image', () => tick());
check('a Civitai image\'s stopped Send offers the version held too',
      tickText(), 'Use V16 (SD 1.5), the version I have, instead: the image may not come out exactly the same');
plan = { success: true, preset: null, checkpoint: 'a_v16.safetensors [1234]', checkpoint_problem: null,
         instead: 'a_v16.safetensors' };
if (tick()) { tick().checked = true; press(tick()); }
if (sendButton() && !sendButton().disabled) press(sendButton());
await waitFor('the send with it', () => asked.filter((h) => h.includes('use_version=')).length);
const withVersion = asked.find((h) => h.includes('use_version='));
check('ticked and sent: the server is asked with that version',
      withVersion && new URL(withVersion, 'http://x').searchParams.get('use_version'), '112');
await waitFor('the notice', () => document.querySelector('.mm-notice'));
check('and the notice says it was another version of the model',
      (document.querySelector('.mm-notice')?.textContent || '').includes(
          'Sent with a_v16.safetensors, another version of the model this image was made with'), true);

done();
