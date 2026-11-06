// Several checkpoints ticked in the Resources dialog (#400): while the setting
// Queue a generation with several checkpoints is on, the Queue is on and was
// built at this start, and the send goes into txt2img, each row of the list
// of your checkpoints is a tick box, the image's own ticked as it opens. One
// ticked works as one pick did: its usual settings, their tick, its Send.
// Two or more: the Send line says it sends with the first, then queues them;
// each ticked row says how it runs - with its usual settings, with yours, or
// as made - and a file no sync read that its family is read when you queue;
// a line under the list says what stays yours for a checkpoint of another
// family than the first; the usual settings block lists each, with no tick.
// Send hands the line's several send the names, the image they came from,
// how each is named and what the list was asked with. A ticked name the
// list asked again no longer holds stays in sight. With the Queue off, or on
// since the last start, the rows keep their round buttons and the line says
// what to do; with the setting off, or a send into img2img, they keep them.
import { call, checker, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const row = (name, family, model, version, extra = {}) => ({ name, file: name.split(' ')[0], family, read: true,
                                                              supported: true, model, version, base_model: 'SDXL 1.0',
                                                              ...extra });
const MIX = row('animeMix_v12.safetensors [a1]', 'xl', 'Anime Mix', 'v12');
const REAL = row('real_v2.safetensors [b2]', 'xl', 'Real', 'v2');
const FLUX = row('fluxDev.safetensors [c3]', 'flux', 'Flux Dev', 'fp8', { base_model: 'Flux.1 D' });
const OWN = row('own_v1.safetensors [d4]', 'xl', 'Own', 'v1');
const LEAN = row('lean_v1.safetensors [e5]', 'xl', 'Lean', 'v1');
const UNREAD = row('newMerge.safetensors', null, null, null, { read: false, base_model: null });
const GREY = row('qwen_image.safetensors [f6]', 'qwen', 'Qwen Image', 'v1', { supported: false, base_model: 'Qwen' });
// As send.your_checkpoints answers: the image's own suggested and picked first, the one Forge has loaded suggested.
const list = { success: true, checkpoints: [MIX, REAL, FLUX, OWN, LEAN, UNREAD, GREY],
               suggested: [{ name: OWN.name, why: ['the image\'s own'] }, { name: LEAN.name, why: ['loaded now'] }],
               picked: OWN.name, same_base: null, loaded: LEAN.name, family: 'xl' };
let shownList = list;
const setting = (key, value, count, of, extra = {}) => ({ key, value, count, of, thin: false, missing: false, ...extra });
const IMAGE_OWN = { sampler: 'Euler a', schedule_type: 'Automatic', steps: 30, cfg: 5, hires: false };
const USUAL = {
    [MIX.name]: { success: true, applies: true, kind: 'model', source: 'yours', uses: 526, image: IMAGE_OWN,
                  settings: [setting('sampler', 'DPM++ 2M', 349, 526), setting('schedule_type', 'Karras', 357, 526),
                             setting('steps', 20, 364, 526), setting('cfg', 7, 494, 526)] },
    [REAL.name]: { success: true, applies: true, kind: 'version', source: 'civitai', uses: 284, image: IMAGE_OWN,
                   settings: [setting('steps', 25, 140, 284), setting('cfg', 4, 120, 284)] },
    [FLUX.name]: { success: true, applies: true, kind: 'model', source: 'civitai', uses: 40, image: IMAGE_OWN,
                   settings: [setting('cfg', 1, 40, 40), setting('distilled_cfg', 3.5, 22, 40)] },
    [OWN.name]: { success: true, applies: false, kind: 'own' },
    [LEAN.name]: { success: true, applies: true, kind: 'model', source: null, uses: 0, image: IMAGE_OWN, settings: [] },
    [UNREAD.name]: { success: true, applies: true, kind: 'file', source: null, uses: 0, image: IMAGE_OWN, settings: [] },
};
const usualAsked = [];
// ui-options as the server says them: the setting, the Queue's switch, and whether this start built it.
const options = { several: true, queueOn: true, built: true, choose: true };
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status === 200, status, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/send/usual')) {
        const params = new URL(href, 'http://x').searchParams;
        usualAsked.push(params.get('checkpoint'));
        return reply(USUAL[params.get('checkpoint')]);
    }
    if (href.includes('/model-manager/send/checkpoints')) return reply(shownList);
    // A gallery Send's plan, asked before its dialog opens: the image's checkpoint can be sent.
    if (href.includes('/model-manager/send/plan')) {
        return reply({ success: true, preset: null, checkpoint: null, target: [], modules_missing: [] });
    }
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: {}, hashes: {}, other_files: {}, names: {}, embeddings: [] });
    }
    if (href.includes('/missing-resources')) {
        const wanted = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(wanted.map(({ version_id: id }) => [id, { model_id: 81 }])) });
    }
    if (href.includes('/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true, choose_checkpoint: options.choose,
                       usual_settings: true, family_names: { xl: 'SDXL', flux: 'Flux', qwen: 'Qwen-Image' },
                       queue_several: options.several, queue_enabled: options.queueOn,
                       tabs: { queue: { on: options.queueOn, built: options.built } } });
    }
    return reply({ success: true });
};

const { showImageResources } = await sharedModule('resources.mjs');
const send = await sharedModule('send.mjs');
await (await sharedModule('ui_options.mjs')).uiOptions();
await startServices('core.mjs', 'calls.mjs', 'resources.mjs');

const modal = () => document.querySelector('.mm-resources-modal');
const block = () => modal()?.querySelector('.mm-usual');
const status = () => modal()?.querySelector('.mm-res-send-status')?.textContent || '';
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const usualTick = () => block()?.querySelector('[data-action="resources.usualTick"]');
const rowOf = (name) => [...(modal()?.querySelectorAll('.mm-pick-row') || [])].find((r) => r.querySelector('input')?.value === name);
const runs = (name) => rowOf(name)?.querySelector('.mm-pick-runs')?.textContent || '';
const note = () => modal()?.querySelector('.mm-pick-note')?.textContent || '';
const kinds = () => [...new Set([...(modal()?.querySelectorAll('.mm-pick-row input') || [])].map((i) => i.type))];
const ticked = () => [...(modal()?.querySelectorAll('.mm-pick-row input') || [])].filter((i) => i.checked).map((i) => i.value);
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const tick = (name, on = true) => {
    const input = rowOf(name)?.querySelector('input');
    if (!input) return;
    input.checked = on;
    press(input);
};
const sent = [];
const sentSeveral = [];
const line = (tab = 'txt2img', extra = {}) => ({
    opened: 'stop', ready: false, why: 'Not in your library yet.', reason: 'missing', waits: {}, check: null, tab,
    run: () => {}, pick: async (...args) => { sent.push(args); return true; },
    pickSeveral: async (...args) => { sentSeveral.push(args); return true; },
    list: { version_ids: '8002' }, usualSource: { kind: 'civitai', image: 7002, version_ids: '8002', hashes: '' },
    ...extra });
const image = { id: 7002, url: 'https://image.civitai.com/x/a.jpeg', meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 8002, modelId: 81, name: 'A Checkpoint', modelVersionName: 'v1' }] } };
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
async function shown() {
    await waitFor('the list', () => modal()?.querySelector('.mm-pick-row'));
    await settle();
    // Pressed only where drawn: a dialog that did not open fails the checks after, not the suite.
    const all = modal()?.querySelector('[data-action="resources.pickTab"][data-family="all"]');
    if (all) press(all);
    await waitFor('every row', () => rowOf(MIX.name));
}
async function open(tab = 'txt2img', extra = {}) {
    await showImageResources(image, null, { note: 'Not in your library.', send: line(tab, extra) });
    await shown();
}

// ------------------------------------------------- tick boxes, as it opens
await open();
check('the setting on, the Queue on and built, into txt2img: a tick box on every row, the image\'s own ticked',
      [kinds(), ticked(), status(), note()],
      [['checkbox'], [OWN.name], 'Sends with Own v1. The image comes out as made.', '']);
check('a row this WebUI cannot run says Send or a queued run could not load it',
      rowOf(GREY.name)?.title, 'This WebUI has no UI preset for this checkpoint\'s family, so Send or a queued run '
                               + 'could not load it.');
tick(OWN.name, false);
check('none ticked: Send off, saying to tick one', [status(), sendButton()?.disabled, sendButton()?.title],
      ['Tick a checkpoint to send with.', true, 'Tick a checkpoint to send with.']);

// --------------------------------------------------------------- one ticked
tick(MIX.name);
await waitFor('its usual settings', () => usualTick());
check('one ticked works as one pick: its usual settings, their tick, its Send line, no note on its row',
      [usualTick()?.checked, status(), runs(MIX.name), sendButton()?.disabled],
      [true, 'Sends with Anime Mix v12. It will not come out exactly as made. With its usual settings.', '', false]);
usualTick().checked = false;
press(usualTick());
tick(REAL.name);
await waitFor('its answer', () => runs(REAL.name).startsWith('Runs'));
tick(REAL.name, false);
check('its usual tick, unticked, stays so while other rows are ticked and unticked',
      [usualTick()?.checked, status()], [false, 'Sends with Anime Mix v12. It will not come out exactly as made.']);

// ------------------------------------------------------- two and more
tick(REAL.name);
await waitFor('the notes', () => runs(REAL.name).startsWith('Runs'));
check('two ticked: the Send line sends with the first, then says Queue for 2 checkpoints queues them all',
      status(), 'Sends with Anime Mix v12, then Queue for 2 checkpoints in txt2img queues them all.');
check('each ticked row says it runs with its usual settings',
      [runs(MIX.name), runs(REAL.name)], ['Runs with its usual settings.', 'Runs with its usual settings.']);
check('the block lists what each runs with, with no tick; Hires fix following each run',
      [Boolean(usualTick()), block()?.querySelector('.mm-usual-head')?.textContent,
       [...block().querySelectorAll('.mm-usual-each')].map((e) => [e.querySelector('.mm-usual-each-name')?.textContent,
                                                                     e.querySelector('.mm-usual-each-what')?.textContent]),
       block().querySelector('.mm-usual-from')?.textContent],
      [false, 'What each runs with', [['Anime Mix v12', 'Sampler DPM++ 2M · Schedule type Karras · Steps 20 · CFG scale 7'],
                                       ['Real v2', 'Steps 25 · CFG scale 4']],
       'A setting too few uses record, or one this WebUI lacks, stays as you set it. Hires fix follows each run\'s '
       + 'sampler, schedule type, CFG, and Distilled CFG or Shift.']);
for (const name of [OWN.name, LEAN.name, UNREAD.name]) tick(name);
await waitFor('their answers', () => runs(LEAN.name).startsWith('Runs') && runs(UNREAD.name).startsWith('Runs'));
check('the image\'s own runs as made; one with too few uses, with yours; a file no sync read says its family is read then',
      [runs(OWN.name), runs(LEAN.name), runs(UNREAD.name)],
      ['Runs as made, with the image\'s settings.', 'Runs with your settings: too few uses record its own.',
       'Runs with your settings: too few uses record its own. Its family is read when you queue.']);
check('and the block says each the same way, in whole sentences',
      [...block().querySelectorAll('.mm-usual-each-what')].slice(2).map((e) => e.textContent),
      ['Runs as made, with the image\'s settings.', 'Runs with your settings: too few uses record its own.',
       'Runs with your settings: too few uses record its own.']);
check('all of one family, or not known: nothing under the list', note(), '');
tick(FLUX.name);
await waitFor('its answer', () => runs(FLUX.name).startsWith('Runs'));
check('a checkpoint of another family than the first: the line under the list says what stays yours for it',
      note(), 'The size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them '
              + 'for Flux Dev fp8, of another family than Anime Mix v12.');
check('every ticked one\'s usual settings asked once', usualAsked.slice().sort(),
      [MIX.name, REAL.name, FLUX.name, OWN.name, LEAN.name, UNREAD.name].sort());
for (const name of [MIX.name, REAL.name, OWN.name, LEAN.name, UNREAD.name]) tick(name, false);
tick(MIX.name);
check('the family judged against the first ticked, not the image\'s: Flux first, Anime Mix is the other family',
      note(), 'The size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them '
              + 'for Anime Mix v12, of another family than Flux Dev fp8.');
tick(FLUX.name, false);
tick(REAL.name);
check('back to two of one family: their notes and the line as they should be, the Send line counting two',
      [runs(FLUX.name), note(), status()], ['', '', 'Sends with Anime Mix v12, then Queue for 2 checkpoints in txt2img queues them all.']);

// -------------------------------------------------------------- Send
press(sendButton());
await waitFor('the several send', () => sentSeveral.length);
check('Send hands the line\'s several send the names, the image\'s model, where they came from, their names and the list\'s',
      sentSeveral.at(-1), [[MIX.name, REAL.name], 81,
                           { source: { image: { kind: 'civitai', image: 7002, version_ids: '8002', hashes: '', image_model: 81 } },
                             labels: { [MIX.name]: 'Anime Mix v12', [REAL.name]: 'Real v2' },
                             listParams: { version_ids: '8002', model_id: 81, base_model: '', same_file: '' } }]);
await open();
tick(OWN.name, false);
tick(REAL.name);
await waitFor('its answer', () => usualTick());
press(sendButton());
await settle();
check('one ticked: Send as one pick, with its usual settings, and no several send', [sent.at(-1), sentSeveral.length],
      [[REAL.name, 81, { name: 'Real v2' }], 1]);

// -------------------------------------- a ticked name the list asked again drops
let ready = false;
await open('txt2img', { check: async () => (ready ? '' : 'missing') });
tick(REAL.name);
shownList = { ...list, checkpoints: list.checkpoints.filter((c) => c !== REAL) };
ready = true;
call('resources.checkAgain');
await waitFor('the list asked again', () => rowOf(REAL.name)?.querySelector('.mm-pick-sub')?.textContent === 'Forge does not list it');
check('a ticked checkpoint the list asked again no longer holds: a row of its own, first, still ticked, saying so',
      [modal()?.querySelector('.mm-pick-row input')?.value, rowOf(REAL.name)?.querySelector('input')?.checked,
       ticked()], [REAL.name, true, [REAL.name, OWN.name]]);
shownList = list;
close();

// A dialog open keeps what it started with: the setting turned off since changes nothing in it.
await open();
options.several = false;
tick(MIX.name);
check('the setting turned off with the dialog open: its tick boxes stay', [kinds(), status()],
      [['checkbox'], 'Sends with Own v1, then Queue for 2 checkpoints in txt2img queues them all.']);
close();
options.several = true;

// ---------------------------------------- the Send lines as Send makes them
// A LoRA's gallery, whose image names its checkpoint.
const gallery = { id: 90, type: 'LORA', base_model: 'SDXL 1.0' };
const shownVersion = { id: 9002, base_model: 'SDXL 1.0', file_path: 'F:\\models\\Lora\\style.safetensors' };
await send.sendGalleryImage({ img: image, model: gallery, version: shownVersion, choose: true });
await shown();
check('a Civitai image\'s own Send, asked to choose, into txt2img: tick boxes', kinds(), ['checkbox']);
close();
await send.sendGalleryImage({ img: image, model: gallery, version: shownVersion, into: { mode: 0 }, choose: true });
await shown();
check('and into img2img: round buttons', kinds(), ['radio']);
close();

// --------------------------------------------------- where it cannot tick
options.built = false;
await open();
check('the Queue turned on since the WebUI started: round buttons, and the line says to restart',
      [kinds(), note()], [['radio'], 'Restart the WebUI to tick several checkpoints here: the Queue was turned on since it started.']);
close();
options.queueOn = false;
await open();
check('the Queue off: round buttons, and the line says to turn it on',
      [kinds(), note()], [['radio'], 'Turn the Queue on to tick several checkpoints here and queue them.']);
close();
options.queueOn = true;
options.built = true;
options.several = false;
await open();
check('the setting off, its default: round buttons, nothing under the list, as before', [kinds(), note()], [['radio'], '']);
close();
options.several = true;
options.choose = false;
await open();
check('the setting on, Choose the checkpoint at every Send off - nested under it, it does nothing: round buttons',
      [kinds(), note()], [['radio'], '']);
close();
options.choose = true;
await open('img2img');
check('a send into img2img: round buttons, nothing under the list - it goes with the loaded checkpoint',
      [kinds(), note()], [['radio'], '']);
close();

done();
