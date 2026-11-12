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
let listHold = null;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status === 200, status, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/send/usual')) {
        const params = new URL(href, 'http://x').searchParams;
        usualAsked.push(params.get('checkpoint'));
        return reply(USUAL[params.get('checkpoint')]);
    }
    if (href.includes('/model-manager/send/checkpoints')) {
        // Held by the check that reads the list's line while it is read (#415).
        const hold = listHold;
        listHold = null;
        if (hold) await hold;
        return reply(shownList);
    }
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
// What the usual-settings block says a ticked checkpoint runs with, found by the name its row shows.
const runs = (name) => {
    const label = rowOf(name)?.querySelector('.mm-pick-name')?.textContent.replace(/\s+/g, ' ').trim();
    const entry = [...(block()?.querySelectorAll('.mm-usual-each') || [])]
        .find((e) => e.querySelector('.mm-usual-each-name')?.firstChild?.textContent === label);
    return entry?.querySelector('.mm-usual-each-what')?.textContent || '';
};
const answered = (name) => Boolean(runs(name)) && !runs(name).startsWith('Reading');
// A row's lines: its box, its name, its base model, its second line - none added at a tick.
const rowParts = (name) => rowOf(name)?.children.length;
// The family note, first in the usual settings block.
const note = () => block()?.querySelector('[data-family-note]')?.textContent || '';
// Select several, beside Choose the checkpoint to send with: its box, and what it says.
const several = () => modal()?.querySelector('[data-action="resources.severalTick"]');
const severalSays = () => (several() ? [several().checked, several().disabled, several().closest('label')?.title] : null);
const pressSeveral = (on) => {
    if (!several()) return;
    several().checked = on;
    press(several());
};
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
      [usualTick()?.checked, status(), runs(MIX.name), rowParts(MIX.name), sendButton()?.disabled],
      [true, 'Sends with Anime Mix v12. It will not come out exactly as made. With its usual settings.', '', 4, false]);
usualTick().checked = false;
press(usualTick());
tick(REAL.name);
await waitFor('its answer', () => answered(REAL.name));
tick(REAL.name, false);
check('its usual tick, unticked, stays so while other rows are ticked and unticked',
      [usualTick()?.checked, status()], [false, 'Sends with Anime Mix v12. It will not come out exactly as made.']);

// ------------------------------------------------------- two and more
tick(REAL.name);
await waitFor('the block\'s entries', () => answered(REAL.name));
check('two ticked: the Send line sends with the first, then says Generate or Queue for 2 checkpoints queues them all',
      status(), 'Sends with Anime Mix v12, then Generate or Queue for 2 checkpoints in txt2img queues them all.');
check('no ticked row takes a line more: how each runs is the block\'s to say', [rowParts(MIX.name), rowParts(REAL.name)],
      [4, 4]);
check('the block lists what each runs with, with no tick; Hires fix following each run',
      [Boolean(usualTick()), block()?.querySelector('.mm-usual-head')?.textContent,
       [...block().querySelectorAll('.mm-usual-each')].map((e) => [e.querySelector('.mm-usual-each-name')?.textContent,
                                                                     e.querySelector('.mm-usual-each-what')?.textContent]),
       block().querySelector('.mm-usual-from')?.textContent],
      [false, 'What each runs with', [['Anime Mix v12', 'DPM++ 2M · Karras · Steps 20 · CFG scale 7'],
                                       ['Real v2', 'Steps 25 · CFG scale 4']],
       'A setting too few uses record, or one this WebUI lacks, stays as you set it. Hires fix follows each run\'s '
       + 'sampler, schedule type, CFG, and Distilled CFG or Shift.']);
for (const name of [OWN.name, LEAN.name, UNREAD.name]) tick(name);
await waitFor('their answers', () => answered(LEAN.name) && answered(UNREAD.name));
check('the image\'s own runs as made; one with too few uses, with yours; a file no sync read says its family is read then',
      [runs(OWN.name), runs(LEAN.name), runs(UNREAD.name)],
      ['Runs as made, with the image\'s settings.', 'Runs with your settings: too few uses record its own.',
       'Runs with your settings: too few uses record its own. Its family is read when you queue.']);
check('and the block says each the same way, in whole sentences',
      [...block().querySelectorAll('.mm-usual-each-what')].slice(2).map((e) => e.textContent),
      ['Runs as made, with the image\'s settings.', 'Runs with your settings: too few uses record its own.',
       'Runs with your settings: too few uses record its own. Its family is read when you queue.']);
check('and still no ticked row takes a line more', [OWN.name, LEAN.name, UNREAD.name].map(rowParts), [4, 4, 4]);
check('all of one family, or not known: nothing under the list', note(), '');
tick(FLUX.name);
await waitFor('its answer', () => answered(FLUX.name));
const familyNote = () => block()?.querySelector('[data-family-note]');
check('a checkpoint of another family than the first: a note in its own grey, after the entries, above the last line',
      [familyNote()?.matches('.mm-usual-note'), familyNote()?.previousElementSibling?.classList.contains('mm-usual-each'),
       familyNote()?.nextElementSibling?.classList.contains('mm-usual-from'),
       Boolean(modal()?.querySelector('.mm-pick-area > [data-family-note]'))], [true, true, true, false]);
check('it names the first ticked alone, whatever else is ticked, and says what stays yours',
      note(), 'Of another family than Anime Mix v12: the size, the prompt and its LoRAs, ADetailer, ControlNet and '
              + 'Diffusion in Low Bits stay as you set them.');
const marks = () => [...(block()?.querySelectorAll('.mm-usual-each') || [])]
    .map((e) => [e.querySelector('.mm-usual-each-name')?.firstChild?.textContent,
                 e.querySelector('.mm-usual-each-family')?.textContent || '']);
check('the entry of another family is marked after its name; the others are not',
      marks(), [['Anime Mix v12', ''], ['Real v2', ''], ['Own v1', ''], ['Lean v1', ''], ['newMerge.safetensors', ''],
                ['Flux Dev fp8', ' · another family']]);
check('every ticked one\'s usual settings asked once', usualAsked.slice().sort(),
      [MIX.name, REAL.name, FLUX.name, OWN.name, LEAN.name, UNREAD.name].sort());
for (const name of [MIX.name, REAL.name, OWN.name, LEAN.name, UNREAD.name]) tick(name, false);
tick(MIX.name);
check('the family judged against the first ticked, not the image\'s: Flux first, Anime Mix is the other family',
      [note(), marks()], ['Of another family than Flux Dev fp8: the size, the prompt and its LoRAs, ADetailer, ControlNet '
                          + 'and Diffusion in Low Bits stay as you set them.',
                          [['Flux Dev fp8', ''], ['Anime Mix v12', ' · another family']]]);
tick(FLUX.name, false);
tick(REAL.name);
check('back to two of one family: their notes and the line as they should be, the Send line counting two',
      [runs(FLUX.name), note(), status()], ['', '', 'Sends with Anime Mix v12, then Generate or Queue for 2 checkpoints in txt2img queues them all.']);

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
      [['checkbox'], 'Sends with Own v1, then Generate or Queue for 2 checkpoints in txt2img queues them all.']);
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
check('the Queue turned on since the WebUI started: round buttons, Select several greyed, its tooltip saying to restart',
      [kinds(), severalSays(), note()],
      [['radio'], [false, true, 'Restart the WebUI to tick several checkpoints here: the Queue was turned on since it started.'], '']);
close();
options.queueOn = false;
await open();
check('the Queue off: round buttons, Select several greyed, its tooltip saying to turn it on',
      [kinds(), severalSays(), note()],
      [['radio'], [false, true, 'Turn the Queue on to tick several checkpoints here and queue them.'], '']);
close();
options.queueOn = true;
options.built = true;
options.several = false;
await open();
check('the setting off, its default: round buttons, Select several unticked, nothing under the list',
      [kinds(), severalSays()?.slice(0, 2), note()], [['radio'], [false, false], '']);
close();
options.several = true;
options.choose = false;
await open();
check('the setting on, Choose the checkpoint at every Send off - nested under it, it does nothing: round buttons',
      [kinds(), note()], [['radio'], '']);
close();
options.choose = true;
await open('img2img');
check('a send into img2img: round buttons, no Select several, nothing under the list - it goes with the loaded checkpoint',
      [kinds(), Boolean(several()), note()], [['radio'], false, '']);
close();

// ------------------------------------------------------- Select several, pressed
// Last in the suite: a press lasts until the page is reloaded, over the setting.
options.several = false;
await open();
tick(OWN.name, false);
tick(REAL.name);
pressSeveral(true);
check('ticked: tick boxes, the one picked ticked, the Send line saying to tick',
      [kinds(), ticked(), severalSays()?.slice(0, 2), status()],
      [['checkbox'], [REAL.name], [true, false], 'Sends with Real v2. It will not come out exactly as made.']);
tick(MIX.name);
await waitFor('the block\'s entries', () => answered(MIX.name));
check('two ticked: the block says how each runs, the Send line queues both', [runs(REAL.name), status()],
      ['Steps 25 · CFG scale 4', 'Sends with Real v2, then Generate or Queue for 2 checkpoints in txt2img queues them all.']);
pressSeveral(false);
check('unticked: round buttons, the first ticked the one picked, no row notes, one sent',
      [kinds(), modal()?.querySelector('.mm-pick-row input:checked')?.value, runs(REAL.name), runs(MIX.name), status()],
      [['radio'], REAL.name, '', '', 'Sends with Real v2. It will not come out exactly as made. With its usual settings.']);
const severalBefore = sentSeveral.length;
press(sendButton());
await settle();
check('and Send sends that one alone, no several send', [sent.at(-1)?.[0], sentSeveral.length], [REAL.name, severalBefore]);
await open();
check('the next dialog starts as last pressed - unticked - though the setting is off too',
      [kinds(), severalSays()?.slice(0, 2)], [['radio'], [false, false]]);
pressSeveral(true);
close();
await open();
check('ticked last, the next dialog starts ticked though the setting is off', [kinds(), severalSays()?.slice(0, 2)],
      [['checkbox'], [true, false]]);
pressSeveral(false);
close();
options.several = true;
await open();
check('unticked last, the next starts unticked though the setting is on', [kinds(), severalSays()?.slice(0, 2)],
      [['radio'], [false, false]]);
const choose = modal()?.querySelector('[data-action="resources.chooseTick"]');
choose.checked = false;
press(choose);
check('Choose the checkpoint to send with unticked: no list, no Select several', Boolean(several()), false);
close();

// ------------------------------------------- Untick all and the Ticked tab (#415)
// With tick boxes: Untick all on the list's line, and a tab of the ticked, last, in the order they
// run - narrowed by the search, its count kept as each tick lands, the rows not drawn again. With
// round buttons, neither.
const untickAll = () => modal()?.querySelector('.mm-pick-line [data-action="resources.untickAll"]');
const tabNames = () => [...(modal()?.querySelectorAll('.mm-pick-tab:not(.mm-pick-tab-held)') || [])].map((b) => b.textContent.trim());
const heldTab = () => modal()?.querySelector('.mm-pick-tab.mm-pick-tab-held');
const activeTab = () => modal()?.querySelector('.mm-pick-tab.active')?.textContent.trim();
const rowNames = () => [...(modal()?.querySelectorAll('.mm-pick-row input') || [])].map((i) => i.value);
const pickTab = (family) => {
    const button = modal()?.querySelector(`[data-action="resources.pickTab"][data-family="${family}"]`);
    if (button) press(button);
};
const search = (text) => {
    const input = modal()?.querySelector('.mm-pick-search');
    if (!input) return;
    input.value = text;
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
};
// While the list is read: the line's controls there already, Untick all off, saying why.
await open();
pressSeveral(true);
close();
let releaseList;
listHold = new Promise((resolve) => { releaseList = resolve; });
await showImageResources(image, null, { note: 'Not in your library.', send: line() });
// Tick boxes come once the settings have answered; the list's answer is held till after.
await waitFor('the line in tick mode, the list held', () => untickAll() && modal()?.querySelector('.mm-pick-wait'));
check('#415: tick boxes, the list being read: Untick all there, off, saying so',
      [Boolean(untickAll()), untickAll()?.disabled, untickAll()?.title], [true, true, 'Your checkpoints are still being read.']);
releaseList();
await shown();
pressSeveral(false);
close();
await open();
check('#415: round buttons: no Untick all, no Ticked tab; its place held, last, unseen and out of reach, so tick boxes move no row',
      [Boolean(untickAll()), tabNames().some((n) => n.startsWith('Ticked')),
       [...(modal()?.querySelectorAll('.mm-pick-tab') || [])].at(-1) === heldTab(), heldTab()?.textContent.trim(),
       heldTab()?.disabled, heldTab()?.getAttribute('aria-hidden'), heldTab()?.getAttribute('tabindex')],
      [false, false, true, 'Ticked 0', true, 'true', '-1']);
pressSeveral(true);
tick(MIX.name);
tick(FLUX.name);
check('tick boxes: Untick all on the line, saying how many it unticks; a Ticked tab last, counting them',
      [untickAll()?.disabled, untickAll()?.title, tabNames().at(-1)], [false, 'Untick the 3 checkpoints ticked.', 'Ticked 3']);
pickTab('ticked');
check('    the Ticked tab: the ticked, in the order they run', rowNames(), [OWN.name, MIX.name, FLUX.name]);
search('flux');
check('    the search narrows it, and its count', [rowNames(), tabNames().at(-1)], [[FLUX.name], 'Ticked 1']);
search('');
const rowsBefore = modal()?.querySelector('.mm-pick-rows');
tick(MIX.name, false);
check('    unticked there: its row stays, unticked, the rows not drawn again; the count and Untick all follow',
      [rowNames(), ticked(), modal()?.querySelector('.mm-pick-rows') === rowsBefore, tabNames().at(-1), untickAll()?.title],
      [[OWN.name, MIX.name, FLUX.name], [OWN.name, FLUX.name], true, 'Ticked 2', 'Untick the 2 checkpoints ticked.']);
pickTab('ticked');
check('    drawn again - its tab pressed - the row is gone', rowNames(), [OWN.name, FLUX.name]);
// Pressed with the Ticked tab open: its rows stay, unticked, the rows not drawn again.
const rowsAtUntick = modal()?.querySelector('.mm-pick-rows');
// Pressed only where drawn: a build without it fails the checks after, not the suite.
if (untickAll()) press(untickAll());
check('Untick all, in the Ticked tab: its rows stay, unticked, the rows not drawn again',
      [rowNames(), modal()?.querySelector('.mm-pick-rows') === rowsAtUntick], [[OWN.name, FLUX.name], true]);
pickTab('all');
check('    no tick left; Send off, saying to tick one; Untick all off, saying nothing is ticked; Ticked 0',
      [ticked(), status(), sendButton()?.disabled, untickAll()?.disabled, untickAll()?.title, tabNames().at(-1)],
      [[], 'Tick a checkpoint to send with.', true, true, 'Nothing is ticked.', 'Ticked 0']);
pickTab('xl');
check('    none in a family\'s tab either', ticked(), []);
pickTab('ticked');
check('    and the Ticked tab says nothing is ticked', modal()?.querySelector('.mm-pick-rows')?.textContent.trim(), 'Nothing is ticked.');
pickTab('all');
tick(REAL.name);
check('    a tick: Untick all back, saying it', [untickAll()?.disabled, untickAll()?.title], [false, 'Untick the checkpoint ticked.']);
pickTab('ticked');
pressSeveral(false);
check('Select several off with the Ticked tab open: round buttons, All shown, no Ticked tab, no Untick all',
      [kinds(), activeTab()?.startsWith('All'), tabNames().some((n) => n.startsWith('Ticked')), Boolean(untickAll())],
      [['radio'], true, false, false]);
pressSeveral(true);
check('    on again: the Ticked tab back, open, the one picked ticked; no held place beside it', [activeTab(), ticked(), Boolean(heldTab())],
      ['Ticked 1', [REAL.name], false]);
pressSeveral(false);
close();

done();
