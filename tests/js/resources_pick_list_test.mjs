// The Resources dialog's list of your checkpoints (#377), as R4's POC drew it
// (option A): a search box, then tabs - Suggested first, open as the dialog
// opens; a tab per family you hold, by name, its preset key in its tooltip;
// All - each with its count. Suggested holds the suggestions alone; a
// family's tab every checkpoint of it, suggested or not, the image's base
// model first under its own heading; All every one, under no heading. A row
// has two lines: the model and its version, the base model at the right; then
// why it is suggested, loaded now, its family where the tab does not say it,
// and its file. An image with no suggestions opens on its family, All where
// that is not known. A family this WebUI has no UI preset for is greyed,
// saying why - one Forge's detector could not tell, saying that; a file no
// sync has read says so, and not that Civitai lacks it. The search narrows every tab at
// once, and each tab's count follows. A pick redraws no row: the list keeps
// its scroll.
//
// And the dialog the Resources button opens (#377): its Send line's box
// starts from the image's checkpoint row - unticked where it says Installed,
// ticked where it does not, ticked with the setting on, read fresh - and
// opening it asks no send plan. Unticked, its Send sends the image's own. A
// row whose download cannot run says why (#377 case 6). A checkpoint Civitai
// does not know - a merge of your own - starts it unticked where the library
// holds its hash, and the line offers no download where none is drawn.
import { checker, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const row = (name, family, model, version, baseModel, extra = {}) => ({
    name, file: `${name.split(' ')[0]}`, family, read: true, supported: true, model, version, base_model: baseModel, ...extra });
const XL1 = row('animeMix_v12.safetensors [a1]', 'xl', 'Anime Mix', 'v12', 'Illustrious');
const XL2 = row('real_v2.safetensors [b2]', 'xl', 'Real', 'v2', 'SDXL 1.0');
const XL3 = row('toon_v1.safetensors [c3]', 'xl', 'Toon', 'v1', 'Illustrious');
const SD1 = row('dream_v8.safetensors [d4]', 'sd', 'Dream', 'v8', 'SD 1.5');
const QWEN = row('qwen_image.safetensors [e5]', 'qwen', 'Qwen Image', 'v1', 'Qwen', { supported: false });
const UNREAD = row('newMerge_test.safetensors [f6]', null, null, null, null, { read: false });
let list = { success: true, checkpoints: [XL1, XL2, XL3, SD1, QWEN, UNREAD],
             suggested: [{ name: XL1.name, why: ['same model'] }], picked: null,
             same_base: { base_model: 'Illustrious', names: [XL3.name] }, loaded: SD1.name, family: 'xl' };
const installed = new Set([8001]);
const heldHashes = new Set();
let settingOn = false;
let listHeld = null;
const asked = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/send/checkpoints')) {
        await listHeld;
        return reply(list);
    }
    if (href.includes('/model-manager/send/plan')) return reply({ success: false });
    if (href.includes('/image-resources')) {
        const params = new URL(href, 'http://x').searchParams;
        const ids = (params.get('version_ids') || '').split(',').filter(Boolean).map(Number);
        const hashes = (params.get('hashes') || '').split(',').filter((h) => heldHashes.has(h));
        return reply({ success: true, versions: Object.fromEntries(ids.filter((i) => installed.has(i)).map((i) => [i, { version_id: i }])),
                       hashes: Object.fromEntries(hashes.map((h) => [h, { version_id: null }])),
                       other_files: {}, names: {}, embeddings: [] });
    }
    // Civitai knows no hash here.
    if (href.includes('/resolve-hashes')) {
        const hashes = new URLSearchParams(String(init.body)).get('hashes').split(',');
        return reply({ success: true, deferred: [], resolved: Object.fromEntries(hashes.map((h) => [h, { version_id: null }])) });
    }
    if (href.includes('/missing-resources')) {
        const wanted = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(wanted.map(({ version_id: id }) => [id, { model_id: 81 }])) });
    }
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true, choose_checkpoint: settingOn,
                       family_names: { sd: 'SD 1.x', xl: 'SDXL', qwen: 'Qwen-Image' } });
    }
    return reply({ success: true });
};

const { showImageResources } = await sharedModule('resources.mjs');
const { gallerySendLine } = await sharedModule('send.mjs');
await (await sharedModule('ui_options.mjs')).uiOptions();
// No tab that downloads has started the downloads list here.
await startServices('core.mjs', 'calls.mjs', 'resources.mjs');

const modal = () => document.querySelector('.mm-resources-modal');
const box = () => modal()?.querySelector('[data-action="resources.chooseTick"]');
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const status = () => modal()?.querySelector('.mm-res-send-status')?.textContent || '';
const tabs = () => [...(modal()?.querySelectorAll('.mm-pick-tab') || [])].map((t) => t.textContent.trim());
const active = () => modal()?.querySelector('.mm-pick-tab.active')?.textContent.trim();
const heads = () => [...(modal()?.querySelectorAll('.mm-pick-head') || [])].map((h) => h.textContent);
const rows = () => [...(modal()?.querySelectorAll('.mm-pick-row') || [])];
const rowOf = (name) => rows().find((r) => r.querySelector('input')?.value === name);
const shownNames = () => rows().map((r) => r.querySelector('input')?.value);
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const search = (text) => {
    const input = modal()?.querySelector('.mm-pick-search');
    input.value = text;
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
};
const stopped = () => ({ opened: 'stop', ready: false, why: 'Not in your library yet.', reason: 'missing', waits: {},
                         check: null, run: () => {}, pick: () => {}, list: { version_ids: '8002' } });
const image = (versionId) => ({ id: 7000 + versionId, meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: versionId, modelId: 81, name: 'A Checkpoint', modelVersionName: 'v1' }] } });

// ------------------------------------------------------------- the list
const sub = (name) => rowOf(name)?.querySelector('.mm-pick-sub')?.textContent;
const pickTab = (family) => press(modal().querySelector(`[data-action="resources.pickTab"][data-family="${family}"]`));
let letListGo;
listHeld = new Promise((resolve) => { letListGo = resolve; });
await showImageResources(image(8002), null, { note: 'Not in your library.', send: stopped() });
await waitFor('the list asked', () => asked.some((h) => h.includes('/send/checkpoints')));
check('24. while the list is read: the search, a tab strip and the rows\' box already there, so its coming moves nothing',
      [modal()?.querySelector('.mm-pick-search')?.disabled, Boolean(modal()?.querySelector('.mm-pick-tabs .mm-pick-tab')),
       modal()?.querySelector('.mm-pick-rows .mm-pick-wait')?.textContent],
      [true, true, 'Reading your checkpoints…']);
letListGo();
listHeld = null;
await waitFor('the list', () => rows().length);
check('    tabs: Suggested first and open, a family each by name, All - each with its count',
      [tabs(), active()], [['Suggested 1', 'SDXL 3', 'SD 1.x 1', 'Qwen-Image 1', 'All 6'], 'Suggested 1']);
check('    the preset key in a family tab\'s tooltip',
      modal()?.querySelector('[data-family="xl"]')?.getAttribute('title'), 'Forge\'s UI preset: xl');
check('    Suggested: the suggestions alone, under no heading, each saying why, its family and its file',
      [heads(), shownNames(), sub(XL1.name)], [[], [XL1.name], 'Same model, other version · SDXL · animeMix_v12.safetensors']);
pickTab('xl');
check('    the image\'s family: every checkpoint of it, the suggested one too, the image\'s base model first',
      [heads(), shownNames()], [['Illustrious, like the image 2', 'Other SDXL 1'], [XL1.name, XL3.name, XL2.name]]);
check('    a row: the model and its version, the base model at the right, then its file - no family in its own tab',
      [rowOf(XL2.name)?.querySelector('.mm-pick-name')?.textContent, rowOf(XL2.name)?.querySelector('.mm-pick-base')?.textContent,
       sub(XL2.name)], ['Real v2', 'SDXL 1.0', 'real_v2.safetensors']);
check('    a suggested row in its family\'s tab still says why', sub(XL1.name), 'Same model, other version · animeMix_v12.safetensors');
search('toon');
check('    the search narrows every tab at once, the counts following',
      [tabs(), shownNames()], [['Suggested 0', 'SDXL 1', 'SD 1.x 0', 'Qwen-Image 0', 'All 1'], [XL3.name]]);
check('    and the box keeps what is typed', modal()?.querySelector('.mm-pick-search')?.value, 'toon');
search('');
pickTab('all');
check('    All: every checkpoint once, under no heading', [heads(), shownNames().filter((n) => n === XL1.name).length], [[], 1]);
// Never looked up, it is not known to be missing from Civitai (#377, the build's review).
check('    with each row\'s family, Forge\'s checkpoint said, a file no sync read said - not "Not on Civitai"',
      [sub(XL2.name), sub(SD1.name), sub(UNREAD.name)],
      ['SDXL · real_v2.safetensors', 'Loaded in Forge now · SD 1.x · dream_v8.safetensors', 'Not read by a sync yet']);
check('    a file Civitai does not know: its file on the first line',
      rowOf(UNREAD.name)?.querySelector('.mm-pick-name')?.textContent, 'newMerge_test.safetensors');
check('    a family with no UI preset here: greyed, saying why, not pickable',
      [rowOf(QWEN.name)?.classList.contains('mm-pick-greyed'), sub(QWEN.name), rowOf(QWEN.name)?.querySelector('input')?.disabled],
      [true, 'Qwen-Image · No UI preset for Qwen-Image in this WebUI · qwen_image.safetensors', true]);
const rowsBox = modal()?.querySelector('.mm-pick-rows');
const radio = rowOf(XL2.name)?.querySelector('input');
radio.checked = true;
press(radio);
check('    a pick redraws no row, so the list keeps its scroll; its row marked, Send saying it the short way',
      [modal()?.querySelector('.mm-pick-rows') === rowsBox, rowOf(XL2.name)?.classList.contains('picked'),
       rows().filter((r) => r.classList.contains('picked')).length, status()],
      [true, true, 1, 'Sends with Real v2. It will not come out exactly as made.']);
close();

list = { ...list, suggested: [] };
await showImageResources(image(8003), null, { send: stopped() });
await waitFor('the list', () => rows().length);
check('    an image with no suggestions: no Suggested tab, its family open first', [tabs()[0], active()], ['SDXL 3', 'SDXL 3']);
close();
list = { ...list, family: null };
await showImageResources(image(8003), null, { send: stopped() });
await waitFor('the list', () => rows().length);
check('    and its family not known: All open first', active(), 'All 6');
close();
list = { ...list, family: 'xl', suggested: [{ name: XL1.name, why: ['same model'] }] };
// A file a sync read whose model Forge's detector could not tell: no family, so no preset.
const UNTOLD = row('mystery_v1.safetensors [g7]', null, null, null, null, { supported: false });
list = { ...list, checkpoints: [...list.checkpoints, UNTOLD] };
await showImageResources(image(8003), null, { send: stopped() });
await waitFor('the list', () => rows().length);
pickTab('all');
check('    a checkpoint Forge could not tell: greyed, saying so - not "No UI preset for  in this WebUI"',
      [rowOf(UNTOLD.name)?.classList.contains('mm-pick-greyed'), sub(UNTOLD.name), rowOf(UNTOLD.name)?.title],
      [true, 'Not on Civitai · Forge could not tell what model this is',
       'Forge\'s model detector could not tell what model this checkpoint is, so Send could not set Forge up for it.']);
close();
list = { ...list, checkpoints: list.checkpoints.filter((c) => c !== UNTOLD) };

// ------------------------------------- the dialog the Resources button opens
const gallery = { id: 4001, base_model: 'SD 1.5', model_type: 'LORA' };
const shown = { id: 5001, file_path: 'C:/models/Lora/a_lora.safetensors', base_model: 'SD 1.5' };
asked.length = 0;
await showImageResources(image(8001), null, { send: gallerySendLine({ img: image(8001), model: gallery, version: shown }) });
check('    before the library has answered, nothing said yet', [box()?.checked, status()], [false, '']);
await waitFor('the box set', () => status());
check('25. the image\'s checkpoint row Installed: the box unticked, Send sends the image\'s own',
      [box()?.checked, sendButton()?.disabled, status(), rows().length],
      [false, false, 'Sends with the image\'s own checkpoint.', 0]);
check('36. the Send line sits at the dialog\'s foot, outside the rows that scroll (#377, R4)',
      [Boolean(modal()?.querySelector('.mm-resources-foot .mm-resources-send-wrap')),
       Boolean(modal()?.querySelector('.mm-modal-body .mm-resources-send-wrap'))], [true, false]);
check('    and opening it asked no send plan, nor the list',
      asked.filter((h) => h.includes('/send/plan') || h.includes('/send/checkpoints')), []);
check('    the setting read fresh as it opened', asked.some((h) => h.includes('/ui-options')), true);
press(sendButton());
await waitFor('the send', () => asked.some((h) => h.includes('/send/plan')));
const sentWith = new URL(asked.find((h) => h.includes('/send/plan')), 'http://x');
check('    pressed: sent as the tab\'s Send sends, with the image\'s own', sentWith.searchParams.has('use_checkpoint'), false);
document.querySelectorAll('.mm-notice').forEach((n) => n.remove());
close();

await showImageResources(image(8002), null, { send: gallerySendLine({ img: image(8002), model: gallery, version: shown }) });
await waitFor('the list', () => rows().length);
check('    the row not Installed: the box ticked, the list shown', [box()?.checked, rows().length > 0], [true, true]);
// Case 6: the downloads list runs with the Model Manager or the Civitai
// Browser alone, and neither runs here.
check('23. its row, downloads off: says which tabs they run with',
      modal()?.querySelector('[data-res-download="8002"]')?.textContent.trim(),
      'Not in the library - downloads run while the Model Manager or the Civitai Browser is on');
close();

settingOn = true;
await showImageResources(image(8001), null, { send: gallerySendLine({ img: image(8001), model: gallery, version: shown }) });
await waitFor('the list', () => rows().length);
check('    Installed, with the setting on: ticked', box()?.checked, true);
close();
settingOn = false;

// A merge of your own: the image names its checkpoint by a hash Civitai does
// not know, so its row is greyed, with no Download. The library holds it: the
// box started ticked, Send never enabled, and the line said to download it
// above (#377, the build's review).
const MERGE = 'abcdef1234';
heldHashes.add(MERGE);
const merge = { id: 7900, meta: { prompt: 'a lighthouse', resources: [{ type: 'model', name: 'my_merge_v3', hash: MERGE }] } };
await showImageResources(merge, null, { send: gallerySendLine({ img: merge, model: gallery, version: shown }) });
await waitFor('the box set', () => status());
check('    a checkpoint Civitai does not know, the library holding it: unticked, Send sends it',
      [box()?.checked, sendButton()?.disabled, status()], [false, false, 'Sends with the image\'s own checkpoint.']);
close();
// Another merge, not held (the page keeps what the library said it holds).
const other = { id: 7901, meta: { prompt: 'a lighthouse', resources: [{ type: 'model', name: 'my_merge_v4', hash: 'fedcba4321' }] } };
await showImageResources(other, null, { send: gallerySendLine({ img: other, model: gallery, version: shown }) });
await waitFor('the list', () => rows().length);
const tickedAtOpen = box()?.checked;
box().checked = false;
press(box());
check('    and not held: ticked; unticked, the line offers no download, as none is drawn',
      [tickedAtOpen, sendButton()?.disabled, status()], [true, true, 'The checkpoint is not in your library: pick one of yours.']);
close();

done();
