// Several checkpoints ticked in the Resources dialog (#400): while the setting
// Queue a generation with several checkpoints is on, the Queue is on and was
// built at this start, and the send goes into txt2img, each row of the list
// of your checkpoints is a tick box, the image's own ticked as it opens. One
// ticked works as one pick did: its usual settings, their tick, its Send.
// Two or more: the Send line says it sends with the first, then queues them;
// the usual settings block lists each, with no tick - as the press will decide
// it, asked of the server for the whole list at once (#407): its usual
// settings, yours, as made, or what stops the press, with what stays yours
// for a checkpoint of another family than the first. One ask out at a time,
// for the newest list (#433); an older list's answer draws nothing.
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
// Holds the next answer of one pick's usual settings until it resolves.
let usualHold = null;
// What each runs with, as the server answers the route (several.runs_preview, #407): for each name
// asked, its usual settings above and its family against the first's, with what RUN and ANSWER say
// over them. `runsHold` holds the next answer until it resolves; `runsRefuse` is what is answered instead.
const RUN = {};
let ANSWER = {};
let runsHold = null;
let runsRefuse = null;
const runsAsked = [];
const rowNamed = (name) => [...list.checkpoints, ...(shownList.checkpoints || [])].find((c) => c.name === name);
function runEntry(name, against) {
    const [mine, first] = [rowNamed(name), rowNamed(against)];
    const values = Object.fromEntries((USUAL[name]?.settings || []).map((s) => [s.key, s.value]));
    const some = Object.keys(values).length > 0;
    return { how: !USUAL[name]?.applies ? 'as_made' : some ? 'usual' : 'thin', usual: some ? values : null,
             family: mine?.family ?? null, family_state: mine?.read ? 'read' : 'not_read', problem: null,
             another_family: mine?.read && first?.read ? mine.family !== first.family : null, ...RUN[name] };
}
// ui-options as the server says them: the setting, the Queue's switch, and whether this start built it.
const options = { several: true, queueOn: true, built: true, choose: true, usual: true };
let listHold = null;
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status === 200, status, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/send/usual')) {
        const params = new URL(href, 'http://x').searchParams;
        usualAsked.push(params.get('checkpoint'));
        const hold = usualHold;
        usualHold = null;
        if (hold) await hold;
        return reply(USUAL[params.get('checkpoint')]);
    }
    if (href.includes('/model-manager/queue/several/runs')) {
        const body = JSON.parse(init.body || '{}');
        runsAsked.push(body);
        // Worked out as asked, then held: a held answer says what was so when it was asked.
        const answer = { success: true, runs: Object.fromEntries(body.names.map((n) => [n, runEntry(n, body.against)])),
                         selected: { name: body.against, state: rowNamed(body.against)?.read ? 'read' : 'not_read' },
                         gone_task: null, ...ANSWER };
        const refuse = runsRefuse;
        const hold = runsHold;
        runsHold = null;
        if (hold) await hold;
        return refuse ? reply(refuse.body, refuse.status) : reply(answer);
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
                       usual_settings: options.usual, family_names: { xl: 'SDXL', flux: 'Flux', qwen: 'Qwen-Image' },
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
const search = (text) => {
    const input = modal()?.querySelector('.mm-pick-search');
    if (!input) return;
    input.value = text;
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
};
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
// Pressed only where drawn: the check above fails without it, not the suite.
const usualBox = usualTick();
if (usualBox) {
    usualBox.checked = false;
    press(usualBox);
}
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
await waitFor('its answer', () => answered(FLUX.name) && note());
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
check('#407: the usual settings of the first ticked alone asked of send/usual, and of the one picked as it opened',
      usualAsked, [OWN.name, MIX.name]);
check('    what each runs with asked for the whole list at once, in tick order, from the image as Send hands it to the '
      + 'press, against the first ticked', runsAsked.at(-1),
      { names: [MIX.name, REAL.name, OWN.name, LEAN.name, UNREAD.name, FLUX.name],
        source: { image: { kind: 'civitai', image: 7002, version_ids: '8002', hashes: '', image_model: 81 } }, against: MIX.name });
for (const name of [MIX.name, REAL.name, OWN.name, LEAN.name, UNREAD.name]) tick(name, false);
tick(MIX.name);
await waitFor('its mark', () => note());
check('the family judged against the first ticked, not the image\'s: Flux first, Anime Mix is the other family',
      [note(), marks()], ['Of another family than Flux Dev fp8: the size, the prompt and its LoRAs, ADetailer, ControlNet '
                          + 'and Diffusion in Low Bits stay as you set them.',
                          [['Flux Dev fp8', ''], ['Anime Mix v12', ' · another family']]]);
tick(FLUX.name, false);
tick(REAL.name);
await waitFor('their answers', () => answered(MIX.name) && answered(REAL.name));
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

// ------------------------------- what each runs with, as the press decides it (#407)
const whats = () => [...(block()?.querySelectorAll('.mm-usual-each') || [])].map((e) => e.querySelector('.mm-usual-each-what')?.textContent);
const under = () => [...(block()?.querySelectorAll('.mm-usual-note:not([data-family-note])') || [])].map((e) => e.textContent);
const settled = () => whats().length > 0 && !whats().some((w) => w.startsWith('Reading'));
/** A dialog with these ticked, and what each runs with said. */
async function ticking(names, extra = {}) {
    await open('txt2img', extra);
    tick(OWN.name, false);
    for (const name of names) tick(name);
    if (names.length === 1) return settle();
    await waitFor('what each runs with', settled);
    // Never said, every wait after would run its whole length, past the runner's limit: the failures so far, now.
    return settled() ? undefined : done();
}
// Pressed only where drawn: on the code before, a Send that waits has closed the dialog at once.
const pressSend = () => { if (sendButton()) press(sendButton()); };
const hold = () => { let go; const held = new Promise((resolve) => { go = resolve; }); return [held, go]; };
// Every way an answer reads, as the press would do it.
RUN[MIX.name] = { how: 'error', usual: null };
RUN[REAL.name] = { how: 'plain', usual: null };
RUN[FLUX.name] = { how: null, usual: null, problem: `${FLUX.name} needs T5-XXL, which this WebUI does not have.` };
RUN[OWN.name] = { how: 'usual', usual: { steps: 12 } };
RUN[LEAN.name] = { family_state: 'unrecognised', family: null, another_family: null };
RUN[UNREAD.name] = { how: 'as_made', usual: null };
await ticking([MIX.name, REAL.name, FLUX.name, OWN.name, LEAN.name, UNREAD.name]);
check('#407: unreadable; none applying; one the press would refuse; one the list says is as made and the press does not; '
      + 'not recognised; as made with its family not read', whats(),
      ['Could not read its usual settings: it runs with your settings.', 'Runs with your settings.',
       `Queuing stops on it: ${FLUX.name} needs T5-XXL, which this WebUI does not have.`, 'Steps 12',
       'Runs with your settings: too few uses record its own. Its family was not recognised when last read: it is read '
       + 'again when you queue.', 'Runs as made, with the image\'s settings. Its family is read when you queue.']);
for (const name of Object.keys(RUN)) delete RUN[name];
close();
// The first ticked is what families are compared with: not read, not recognised, or no longer listed.
await ticking([UNREAD.name, FLUX.name]);
check('the first not read: no marks, and said under the lines by its own name', [marks().map(([, m]) => m), note(), under()],
      [['', ''], '', ['newMerge.safetensors is not read yet: a checkpoint of another family is told when you queue.']]);
close();
ANSWER = { selected: { name: MIX.name, state: 'unrecognised' } };
RUN[FLUX.name] = { another_family: null };
await ticking([MIX.name, FLUX.name]);
check('the first read and not recognised: no marks, and said so', [marks().map(([, m]) => m), note(), under()],
      [['', ''], '', ['Anime Mix v12 was not recognised when last read: a checkpoint of another family is told when you queue.']]);
close();
ANSWER = { selected: { name: MIX.name, state: 'not_listed' } };
RUN[MIX.name] = { how: null, usual: null, family_state: null,
                  problem: `Forge does not list the checkpoint ${MIX.name}: refresh its list, or pick another.` };
await ticking([MIX.name, FLUX.name]);
check('the first no longer listed by Forge: its line says queuing stops, no marks, nothing more said',
      [whats()[0], marks().map(([, m]) => m), note(), under()],
      [`Queuing stops on it: Forge does not list the checkpoint ${MIX.name}: refresh its list, or pick another.`, ['', ''], '', []]);
close();
ANSWER = {};
for (const name of Object.keys(RUN)) delete RUN[name];
// The route refused - the Queue turned off with the dialog open - or failing: said on each line, the next tick asks again.
await ticking([MIX.name, REAL.name]);
runsRefuse = { status: 403, body: { success: false, error: 'The Queue is turned off.' } };
tick(LEAN.name);
await waitFor('the refusal', () => whats()[0]?.startsWith('Could not'));
check('the Queue turned off with the dialog open: said on each line, in the server\'s words', whats(),
      Array(3).fill('Could not read what it runs with: The Queue is turned off.'));
runsRefuse = null;
tick(LEAN.name, false);
await waitFor('answered again', () => settled() && !whats()[0].startsWith('Could not'));
check('    and the next tick asks again', whats(), ['DPM++ 2M · Karras · Steps 20 · CFG scale 7', 'Steps 25 · CFG scale 4']);
// One out at a time, for the newest list.
let [held, go] = hold();
runsHold = held;
const before = runsAsked.length;
tick(FLUX.name);
for (let n = 0; n < 5; n += 1) {
    tick(LEAN.name);
    tick(LEAN.name, false);
}
check('#433: ten ticks while an ask is out: none asked beside it', runsAsked.length - before, 1);
check('    the lines drawn stay, the new name reads as being asked', whats(),
      ['DPM++ 2M · Karras · Steps 20 · CFG scale 7', 'Steps 25 · CFG scale 4', 'Reading its usual settings…']);
go();
await waitFor('the newest list\'s answer', settled);
check('    then one, for the newest list', runsAsked.slice(before).map((b) => b.names),
      Array(2).fill([MIX.name, REAL.name, FLUX.name]));
// A new first ticked: nothing of the old one's answer is drawn against it.
[held, go] = hold();
runsHold = held;
tick(MIX.name, false);
tick(REAL.name, false);
tick(MIX.name);
check('#407: a new first ticked: no mark, note or line from the old first\'s answer', [marks(), note(), whats()],
      [[['Flux Dev fp8', ''], ['Anime Mix v12', '']], '', Array(2).fill('Reading its usual settings…')]);
go();
await waitFor('its answer', settled);
check('    then as against it', [marks(), note().startsWith('Of another family than Flux Dev fp8: ')],
      [[['Flux Dev fp8', ''], ['Anime Mix v12', ' · another family']], true]);
// An answer out as the ticks go to one, to none: dropped.
for (const [label, left] of [['one', [FLUX.name]], ['none', []]]) {
    if (!ticked().includes(MIX.name)) tick(MIX.name);
    if (!ticked().includes(FLUX.name)) tick(FLUX.name);
    await waitFor('both', settled);
    [held, go] = hold();
    runsHold = held;
    tick(LEAN.name);
    for (const name of [MIX.name, FLUX.name, LEAN.name]) if (!left.includes(name)) tick(name, false);
    await settle();
    const html = block()?.innerHTML;
    const asks = runsAsked.length;
    go();
    await settle();
    check(`an answer out as the ticks go to ${label}: not drawn, and nothing asked after it`, [block()?.innerHTML === html,
          Boolean(block()?.querySelector('.mm-usual-each')), runsAsked.length - asks], [true, false, 0]);
}
close();
// The dialog closed, another opened: the first's answer draws nothing there.
await ticking([MIX.name, REAL.name]);
[held, go] = hold();
runsHold = held;
tick(FLUX.name);
tick(LEAN.name);
close();
await ticking([MIX.name, LEAN.name]);
const inSecond = whats();
const asksThen = runsAsked.length;
go();
await settle();
check('an answer for a dialog since closed draws nothing in the one open, and that dialog\'s newest list is not asked',
      [whats(), runsAsked.length - asksThen], [inSecond, 0]);
close();
// Back to one: its usual settings are there for Send, or waited for.
await open();
tick(OWN.name, false);
tick(MIX.name);
tick(REAL.name);
tick(REAL.name, false);
await settle();
pressSend();
await settle();
check('#407: the second unticked again: Send goes with the first\'s usual settings', sent.at(-1), [MIX.name, 81, { name: 'Anime Mix v12' }]);
await open();
tick(OWN.name, false);
tick(MIX.name);
tick(REAL.name);
[held, go] = hold();
usualHold = held;
const sentBefore = sent.length;
tick(MIX.name, false);
pressSend();
pressSend();
check('the first unticked, the one left never asked: Send waits for its usual settings', [sent.length, Boolean(modal())],
      [sentBefore, true]);
go();
await waitFor('the send', () => sent.length > sentBefore);
await settle();
check('    and goes with them, once though pressed twice', [sent.length - sentBefore, sent.at(-1), Boolean(modal())],
      [1, [REAL.name, 81, { name: 'Real v2' }], false]);
await open();
tick(OWN.name, false);
tick(MIX.name);
tick(REAL.name);
[held, go] = hold();
usualHold = held;
tick(MIX.name, false);
pressSend();
close();
go();
await settle();
check('    closed while it waits: nothing is sent', sent.length, sentBefore + 1);
await open();
tick(OWN.name, false);
tick(MIX.name);
tick(REAL.name);
[held, go] = hold();
usualHold = held;
tick(MIX.name, false);
pressSend();
close();
await open();
go();
await settle();
check('    closed while it waits, another dialog opened: nothing is sent, and it stays open', [sent.length, Boolean(modal())],
      [sentBefore + 1, true]);
close();
// The list asked again - a download landed - asks what each runs with again.
let listReady = false;
await ticking([MIX.name, REAL.name], { check: async () => (listReady ? '' : 'missing') });
const askedBefore = runsAsked.length;
RUN[REAL.name] = { how: 'thin', usual: null };
const LANDED = row('landed_v1.safetensors [h8]', 'xl', 'Landed', 'v1');
shownList = { ...list, checkpoints: [...list.checkpoints, LANDED] };
listReady = true;
call('resources.checkAgain');
await waitFor('asked again', () => whats()[1]?.startsWith('Runs with your settings'));
check('the list asked again with several ticked: what each runs with asked again, the new list drawn',
      [runsAsked.length - askedBefore, Boolean(rowOf(LANDED.name))], [1, true]);
delete RUN[REAL.name];
shownList = list;
close();
let failReady = false;
await ticking([MIX.name, REAL.name], { check: async () => (failReady ? '' : 'missing') });
const askedOk = runsAsked.length;
shownList = { success: false, error: 'the library is busy' };
failReady = true;
call('resources.checkAgain');
await waitFor('the list failing', () => modal()?.querySelector('.mm-pick-wait')?.textContent.includes('busy'));
await settle();
check('    asked again and failing: nothing asked of it', runsAsked.length - askedOk, 0);
shownList = list;
close();
// An answer draws the block alone: the rows as they are, the focused tick focused.
await ticking([MIX.name]);
[held, go] = hold();
runsHold = held;
tick(REAL.name);
const tickBox = rowOf(REAL.name)?.querySelector('input');
const rowsThen = modal()?.querySelector('.mm-pick-rows');
tickBox?.focus();
go();
await waitFor('the two lines', () => settled() && whats().length === 2);
check('an answer keeps the focused tick and the rows as drawn (#292)',
      [Boolean(tickBox), document.activeElement === tickBox, modal()?.querySelector('.mm-pick-rows') === rowsThen], [true, true, true]);
close();

// Select all over many (#433): one ask, the Send bar's markup built for each of its two answers and no more.
const MANY = Array.from({ length: 300 }, (_, n) => row(`many_${n}.safetensors`, 'xl', `Many ${n}`, 'v1'));
for (const c of MANY) USUAL[c.name] = USUAL[MIX.name];
shownList = { ...list, checkpoints: [...list.checkpoints, ...MANY] };
await open();
tick(OWN.name, false);
search('many');
const [usualBefore, runsBefore] = [usualAsked.length, runsAsked.length];
const realSort = Array.prototype.sort;
let sorts = 0;
Array.prototype.sort = function counted(...args) { if (this.length >= 300) sorts += 1; return realSort.apply(this, args); };
[held, go] = hold();
runsHold = held;
const [usualHeld, goUsual] = hold();
usualHold = usualHeld;
const all = modal()?.querySelector('.mm-pick-line [data-action="resources.pickAll"]');
if (all) press(all);
await settle();
const atTick = sorts;
goUsual();
await settle();
const atUsual = sorts;
go();
await waitFor('the 300 lines', settled);
await settle();
Array.prototype.sort = realSort;
check('#433: Select all over 300: one ask of what each runs with, one of usual settings',
      [runsAsked.length - runsBefore, usualAsked.length - usualBefore, whats().length], [1, 1, 300]);
// Building the bar's markup sorts the rows twice: for Select all's state, and for the rows.
check('    the Send bar\'s markup built once at each of the two answers, not once a checkpoint', [atUsual - atTick, sorts - atUsual],
      [2, 2]);
close();
shownList = list;

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
const selectAllWhileRead = modal()?.querySelector('.mm-pick-line [data-action="resources.pickAll"]');
check('    and Select all, off, saying so', [selectAllWhileRead?.disabled, selectAllWhileRead?.title],
      [true, 'Your checkpoints are still being read.']);
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

// ------------------------------------------------------------- Select all (#415)
// What the open tab and the search show and can be ticked - not greyed - top to bottom, after the
// ticks there are; in the dialog the first ticked is what Send loads. Its state follows a search,
// a tick and a tab press; in the Ticked tab, and once nothing shown is left, it is off.
const selectAll = () => modal()?.querySelector('.mm-pick-line [data-action="resources.pickAll"]');
const lineActions = () => [...(modal()?.querySelectorAll('.mm-pick-line [data-action]') || [])].map((e) => e.dataset.action);
await open();
const askedFrom = usualAsked.length;
const runsFrom = runsAsked.length;
check('#415: round buttons: no Select all', Boolean(selectAll()), false);
pressSeveral(true);
check('tick boxes: Select all on the line, before Untick all, saying how many it ticks - not the greyed, not the ticked',
      [lineActions(), selectAll()?.disabled, selectAll()?.title],
      [['resources.pickSort', 'resources.pickAll', 'resources.untickAll'], false, 'Tick the 5 checkpoints shown.']);
if (untickAll()) press(untickAll());
search('v1');
check('    after a search: what it shows - Anime Mix v12, Lean v1, Own v1; Qwen, greyed, not counted',
      [rowNames(), selectAll()?.title], [[MIX.name, LEAN.name, OWN.name, GREY.name], 'Tick the 3 checkpoints shown.']);
const rowsAtSelect = modal()?.querySelector('.mm-pick-rows');
if (selectAll()) press(selectAll());
await waitFor('what they run with', () => answered(MIX.name) && answered(LEAN.name));
const askedHere = usualAsked.slice(askedFrom);
check('    pressed, nothing ticked before: those three, top to bottom, the top one what Send loads; the rows not drawn again',
      [ticked(), status(), modal()?.querySelector('.mm-pick-rows') === rowsAtSelect],
      [[MIX.name, LEAN.name, OWN.name], 'Sends with Anime Mix v12, then Generate or Queue for 3 checkpoints in txt2img queues them all.',
       true]);
check('    what the three run with asked once, together; the usual settings of the first alone',
      [runsAsked.slice(runsFrom).map((b) => b.names), askedHere.filter((n) => n !== OWN.name)],
      [[[MIX.name, LEAN.name, OWN.name]], [MIX.name]]);
check('    then off: nothing shown is left to tick', [selectAll()?.disabled, selectAll()?.title],
      [true, 'Every checkpoint shown that can be ticked is ticked.']);
search('');
check('    the search cleared: the rest of All', [selectAll()?.disabled, selectAll()?.title], [false, 'Tick the 3 checkpoints shown.']);
tick(FLUX.name);
check('    one of them ticked by hand: one fewer', selectAll()?.title, 'Tick the 2 checkpoints shown.');
pickTab('flux');
check('    Flux\'s tab, its one checkpoint ticked: off', [selectAll()?.disabled, selectAll()?.title],
      [true, 'Every checkpoint shown that can be ticked is ticked.']);
pickTab('ticked');
check('    the Ticked tab: off, saying to open another', [selectAll()?.disabled, selectAll()?.title],
      [true, 'Open another tab to tick what it shows.']);
pickTab('all');
if (selectAll()) press(selectAll());
pickTab('ticked');
check('    All\'s rest ticked after the ticks there were - the run order; the greyed one never',
      [rowNames(), ticked().includes(GREY.name)], [[MIX.name, LEAN.name, OWN.name, FLUX.name, UNREAD.name, REAL.name], false]);
[held, go] = hold();
runsHold = held;
tick(REAL.name, false);
tick(UNREAD.name, false);
pressSeveral(false);
const asksOff = runsAsked.length;
check('#407: Select several off, the first never ticked alone: its usual settings are there for Send', status(),
      'Sends with Anime Mix v12. It will not come out exactly as made. With its usual settings.');
const oneView = block()?.innerHTML;
go();
await settle();
check('    and an answer out for the ticks draws nothing over it, nothing asked after it',
      [Boolean(oneView), block()?.innerHTML === oneView, runsAsked.length - asksOff], [true, true, 0]);
close();

// A family's tab in two parts - the image's base model first - ticked top to bottom across them:
// not by name, which would put Anime Mix first.
shownList = { ...list, checkpoints: list.checkpoints.map((c) => (c === MIX ? { ...MIX, base_model: 'Pony' } : c)),
              same_base: { base_model: 'SDXL 1.0', names: [LEAN.name, OWN.name, REAL.name] } };
await open();
pressSeveral(true);
if (untickAll()) press(untickAll());
pickTab('flux');
check('#415: one row to tick: Select all says it the short way', selectAll()?.title, 'Tick the checkpoint shown.');
pickTab('xl');
check('    a family\'s tab in two parts', modal()?.querySelectorAll('.mm-pick-head').length, 2);
if (selectAll()) press(selectAll());
pickTab('ticked');
check('    Select all there: the image\'s base model\'s part, then the other, each top to bottom', rowNames(),
      [LEAN.name, OWN.name, REAL.name, MIX.name]);
pressSeveral(false);
close();
shownList = list;

// The list asked again, failing (a download landed, a recheck): it keeps its last answer and shows
// the error alone - Select all and Untick all off, saying the list could not be read.
let readyAgain = false;
await open('txt2img', { check: async () => (readyAgain ? '' : 'missing') });
pressSeveral(true);
tick(MIX.name);
shownList = { success: false, error: 'the library is busy' };
readyAgain = true;
call('resources.checkAgain');
await waitFor('the list asked again, failing', () => modal()?.querySelector('.mm-pick-wait')?.textContent.includes('busy'));
check('#415: the list asked again, failing: Select all and Untick all off, saying it could not be read',
      [selectAll()?.disabled, selectAll()?.title, untickAll()?.disabled, untickAll()?.title],
      [true, 'Your checkpoints could not be read.', true, 'Your checkpoints could not be read.']);
shownList = list;
pressSeveral(false);
close();

// --------------------- ticks taken back stay so when the list is asked again (#417)
// The list is asked again while the dialog is open - Send's check finding the
// image's checkpoint ready, a download landing - and its answer names a pick.
// The pick is the dialog's to fill only while the person has not set the ticks:
// taken back, by hand or by Untick all, they stay taken back. Each check opens
// a dialog of its own: once its check finds the checkpoint ready, it asks no more.
const EXTRA = row('extra_v1.safetensors [g7]', 'xl', 'Extra', 'v1');
// The list asked again: as before, with a row only this answer has, so a wait can tell it came.
const askedAgain = { ...list, checkpoints: [...list.checkpoints, EXTRA] };
let readyAgain417 = false;
const recheckable417 = () => ({ check: async () => (readyAgain417 ? '' : 'missing') });
async function open417(first = list) {
    shownList = first;
    readyAgain417 = false;
    await open('txt2img', recheckable417());
}
async function askAgain417() {
    shownList = askedAgain;
    readyAgain417 = true;
    call('resources.checkAgain');
    await waitFor('the list asked again', () => rowOf(EXTRA.name));
    await settle();
}

await open417();
pressSeveral(true);
check('#417: tick boxes, the image\'s own ticked as it opens', [kinds(), ticked()], [['checkbox'], [OWN.name]]);
if (untickAll()) press(untickAll());
check('    Untick all: nothing ticked', ticked(), []);
await askAgain417();
check('1. Untick all, then the list asked again naming a pick: nothing ticked, Send waits for a tick',
      [ticked(), sendButton()?.disabled, status()], [[], true, 'Tick a checkpoint to send with.']);
pressSeveral(false);
close();

await open417();
pressSeveral(true);
tick(OWN.name, false);
check('#417: the one tick taken off by hand: nothing ticked', ticked(), []);
await askAgain417();
check('2. a tick taken off by hand, then the list asked again naming a pick: nothing ticked, Send waits for a tick',
      [ticked(), sendButton()?.disabled, status()], [[], true, 'Tick a checkpoint to send with.']);
pressSeveral(false);
close();

await open417();
pressSeveral(true);
if (untickAll()) press(untickAll());
pressSeveral(false);
check('#417: Untick all, then round buttons again: nothing picked', [kinds(), ticked(), status()],
      [['radio'], [], 'Pick a checkpoint to send with.']);
await askAgain417();
check('3. round buttons after Untick all, then the list asked again naming a pick: nothing picked, Send waits',
      [ticked(), sendButton()?.disabled, status()], [[], true, 'Pick a checkpoint to send with.']);
close();

// The guard: a dialog whose first read picked nothing, untouched - the list asked
// again once Send's check finds the image's checkpoint ready picks it, the stop's way back.
await open417({ ...list, picked: null });
check('#417 guard: round buttons, nothing picked at the first read', [kinds(), ticked(), status()],
      [['radio'], [], 'Pick a checkpoint to send with.']);
await askAgain417();
check('5. untouched, the list asked again once the checkpoint is ready: its pick is picked, Send on',
      [ticked(), sendButton()?.disabled, status()], [[OWN.name], false, 'Sends with Own v1. The image comes out as made.']);
close();
shownList = list;

// ------------------------------------ a Send of the one left of several waits (#407)
/** Anime Mix and Real ticked, Anime Mix unticked: Real alone, its usual settings asked and held; its release. */
async function leftAlone() {
    await open();
    tick(OWN.name, false);
    tick(MIX.name);
    tick(REAL.name);
    const [answer, release] = hold();
    usualHold = answer;
    tick(MIX.name, false);
    return release;
}
/** Select several on or off for the dialogs opened after: a press lasts until the page is reloaded. */
async function severalFrom(on) {
    await open();
    pressSeveral(on);
    close();
}
await severalFrom(true);
const sentOff = sent.length;
go = await leftAlone();
pressSeveral(false);
pressSend();
go();
await settle();
check('Select several turned off before it is answered: Send goes with its usual settings all the same', sent.at(-1),
      [REAL.name, 81, { name: 'Real v2' }]);
check('    once', sent.length - sentOff, 1);
await severalFrom(true);
for (const [label, change] of [
    ['another ticked beside it', () => tick(LEAN.name)],
    ['another ticked in its place', () => { tick(REAL.name, false); tick(LEAN.name); }],
    ['Choose the checkpoint to send with unticked', () => {
        const choose = modal()?.querySelector('[data-action="resources.chooseTick"]');
        if (choose) { choose.checked = false; press(choose); }
    }]]) {
    const count = sent.length;
    go = await leftAlone();
    pressSend();
    change();
    go();
    await settle();
    check(`    ${label} while it waits: nothing is sent`, [sent.length - count, Boolean(modal())], [0, true]);
    close();
}
// One pick that was never among several goes at once, as it always has: ticked alone, the image's own, a round button.
for (const [label, several_, pick] of [['one ticked alone', true, () => { tick(OWN.name, false); tick(MIX.name); }],
                                       ['the image\'s own, as it opens', true, () => {}],
                                       ['a round button', false, () => tick(MIX.name)]]) {
    const count = sent.length;
    await severalFrom(several_);
    const [answer, release] = hold();
    if (label.startsWith('the image')) usualHold = answer;
    await open();
    if (!label.startsWith('the image')) usualHold = answer;
    pick();
    pressSend();
    check(`${label}, its usual settings asked: Send goes at once`, sent.length - count, 1);
    release();
    usualHold = null;
    await settle();
    close();
}
await severalFrom(true);
// Its usual settings not sent - the tick's setting off: nothing to wait for.
options.usual = false;
const countOff = sent.length;
go = await leftAlone();
pressSend();
check('Send with usual settings off: the one left of several goes at once', [sent.length - countOff, sent.at(-1)?.[2]], [1, null]);
go();
await settle();
options.usual = true;
close();

done();
