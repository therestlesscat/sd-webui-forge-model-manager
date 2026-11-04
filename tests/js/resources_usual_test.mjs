// What a checkpoint picked in the Resources dialog is usually run with (#378):
// a block under the list, drawn once the server says the usual settings
// apply to the pick - not for one it says is as made - with each setting's
// usual value, how many of the uses give it, the image's own value and where
// they come from; a fifth row where the pick's preset takes one. It is asked
// once per pick (`send/usual`), filled in place - the list's rows, its
// scroll and the search box stay as they are - and an answer for an earlier
// pick, or after the dialog closed, draws nothing. Its tick starts ticked at
// each pick, or unticked with the setting off (ui-options' `usual_settings`,
// asked as the dialog opens); ticked, the dialog's Send hands the pick on
// with the usual settings, and Send's notice says what went.
import { checker, mountTab, press, sharedModule, startServices } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
window.mmTiming = { poll: 20, sendRecheck: 20, sendRecheckMax: 200, pasteMax: 50, frame: 5 };
const { check, waitFor, done } = checker();

// ------------------------------------------------------------- the server
const row = (name, model, version) => ({ name, file: name.split(' ')[0], family: 'xl', read: true, supported: true,
                                          model, version, base_model: 'SDXL 1.0' });
const MIX = row('animeMix_v12.safetensors [a1]', 'Anime Mix', 'v12');
const REAL = row('real_v2.safetensors [b2]', 'Real', 'v2');
const FLUX = row('fluxDev.safetensors [c3]', 'Flux Dev', 'fp8');
const OWN = row('own_v1.safetensors [d4]', 'Own', 'v1');
const LEAN = row('lean_v1.safetensors [e5]', 'Lean', 'v1');
const THIN = row('thin_v1.safetensors [f6]', 'Thin', 'v1');
const list = { success: true, checkpoints: [MIX, REAL, FLUX, OWN, LEAN, THIN], suggested: [{ name: OWN.name, why: ['the image\'s own'] }],
               picked: null, same_base: null, loaded: null, family: 'xl' };
const setting = (key, value, count, of, extra = {}) => ({ key, value, count, of, thin: false, missing: false, ...extra });
const IMAGE_OWN = { sampler: 'Euler a', schedule_type: 'Automatic', steps: 30, cfg: 5, distilled_cfg: null, shift: null,
                    hires: true };
const USUAL = {
    [MIX.name]: { success: true, applies: true, kind: 'model', source: 'yours', uses: 526, extra: null, image: IMAGE_OWN,
                  settings: [setting('sampler', 'DPM++ 2M', 349, 526), setting('schedule_type', 'Karras', 357, 526),
                             setting('steps', 20, 364, 526), setting('cfg', 7, 494, 526)] },
    [REAL.name]: { success: true, applies: true, kind: 'version', source: 'civitai', uses: 284, extra: null, image: IMAGE_OWN,
                   settings: [setting('sampler', 'Gone Sampler', 200, 284, { missing: true }),
                              setting('schedule_type', null, 0, 3, { thin: true }),
                              setting('steps', 25, 140, 284), setting('cfg', 4, 120, 284)] },
    [FLUX.name]: { success: true, applies: true, kind: 'model', source: 'civitai', uses: 40, extra: 'distilled', image: IMAGE_OWN,
                   settings: [setting('sampler', 'Euler', 40, 40), setting('schedule_type', 'Simple', 38, 40),
                              setting('steps', 28, 30, 40), setting('cfg', 1, 40, 40),
                              setting('distilled_cfg', 3.5, 22, 40)] },
    [OWN.name]: { success: true, applies: false, kind: 'own' },
    [LEAN.name]: { success: true, applies: true, kind: 'model', source: null, uses: 0, extra: null, image: IMAGE_OWN,
                   settings: [] },
    // A source, but every setting too thinly recorded, or this WebUI's lacking.
    [THIN.name]: { success: true, applies: true, kind: 'model', source: 'civitai', uses: 6, extra: null, image: IMAGE_OWN,
                   settings: [setting('sampler', 'Gone Sampler', 6, 6, { missing: true }),
                              setting('schedule_type', null, 0, 2, { thin: true }),
                              setting('steps', null, 0, 4, { thin: true }), setting('cfg', null, 0, 1, { thin: true })] },
};
const usualAsked = [];
const held = new Map();                  // a name whose answer waits
let failing = false;
let usualSetting = true;                 // ui-options' usual_settings
let optionsHeld = null;                  // ui-options' answer waits
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body, status = 200) => ({ ok: status === 200, status, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/send/usual')) {
        const params = new URL(href, 'http://x').searchParams;
        usualAsked.push(Object.fromEntries(params));
        const name = params.get('checkpoint');
        if (held.has(name)) await held.get(name).promise;
        if (failing) return reply({ success: false, error: 'the database is busy' }, 500);
        return reply(USUAL[name]);
    }
    if (href.includes('/model-manager/send/checkpoints')) return reply(list);
    if (href.includes('/model-manager/send/plan')) return reply({ success: false });
    if (href.includes('/image-resources')) {
        return reply({ success: true, versions: {}, hashes: {}, other_files: {}, names: {}, embeddings: [] });
    }
    if (href.includes('/resolve-hashes')) {
        const hashes = new URLSearchParams(String(init.body)).get('hashes').split(',');
        return reply({ success: true, deferred: [], resolved: Object.fromEntries(hashes.map((h) => [h, { version_id: null }])) });
    }
    if (href.includes('/missing-resources')) {
        const wanted = JSON.parse(new URLSearchParams(String(init.body)).get('versions'));
        return reply({ success: true, versions: Object.fromEntries(wanted.map(({ version_id: id }) => [id, { model_id: 81 }])) });
    }
    if (href.includes('/ui-options')) {
        if (optionsHeld) await optionsHeld;
        return reply({ success: true, samplers: [], schedulers: [], has_api_key: true, choose_checkpoint: false,
                       usual_settings: usualSetting, family_names: { xl: 'SDXL' } });
    }
    return reply({ success: true });
};

const { showImageResources } = await sharedModule('resources.mjs');
const send = await sharedModule('send.mjs');
await (await sharedModule('ui_options.mjs')).uiOptions();
await startServices('core.mjs', 'calls.mjs', 'resources.mjs');

const modal = () => document.querySelector('.mm-resources-modal');
const block = () => modal()?.querySelector('.mm-usual');
const blockText = () => (block()?.textContent || '').replace(/\s+/g, ' ').trim();
const usualTick = () => modal()?.querySelector('[data-action="resources.usualTick"]');
const sendButton = () => modal()?.querySelector('[data-action="resources.sendAgain"]');
const status = () => modal()?.querySelector('.mm-res-send-status')?.textContent || '';
const rowOf = (name) => [...(modal()?.querySelectorAll('.mm-pick-row') || [])].find((r) => r.querySelector('input')?.value === name);
const close = () => document.querySelectorAll('#mm_meta_modal').forEach((n) => n.close());
const values = () => [...(block()?.querySelectorAll('.mm-usual-value') || [])].map((v) => [v.dataset.usualKey, v.textContent.trim()]);
const pick = (name) => {
    const radio = rowOf(name)?.querySelector('input');
    if (!radio) return;
    radio.checked = true;
    press(radio);
};
const tickUsual = (on = true) => {
    const tick = usualTick();
    if (!tick) return;
    tick.checked = on;
    press(tick);
};
const sent = [];
const line = () => ({ opened: 'stop', ready: false, why: 'Not in your library yet.', reason: 'missing', waits: {},
                      check: null, run: () => {}, pick: (...args) => { sent.push(args); },
                      list: { version_ids: '8002' }, usualSource: { kind: 'civitai', image: 7002, version_ids: '8002', hashes: '' } });
const image = { id: 7002, meta: { prompt: 'a lighthouse', civitaiResources: [
    { type: 'checkpoint', modelVersionId: 8002, modelId: 81, name: 'A Checkpoint', modelVersionName: 'v1' }] } };
const open = async () => {
    await showImageResources(image, null, { note: 'Not in your library.', send: line() });
    await waitFor('the list', () => modal()?.querySelector('.mm-pick-row'));
    // Every checkpoint, not Suggested's alone.
    press(modal().querySelector('[data-action="resources.pickTab"][data-family="all"]'));
    await waitFor('every row', () => rowOf(MIX.name));
};

// --------------------------------------------- 17. drawn where it applies
await open();
check('17. nothing picked: no block, nothing asked', [blockText(), usualAsked.length], ['', 0]);
pick(MIX.name);
await waitFor('the answer drawn', () => values().length);
check('    a pick the server says they apply to: each setting\'s usual value, its count, the image\'s own',
      [values(), [...(block()?.querySelectorAll('.mm-usual-count') || [])].map((c) => c.textContent),
       [...(block()?.querySelectorAll('span.mm-usual-own') || [])].map((c) => c.textContent)],
      [[['sampler', 'DPM++ 2M'], ['schedule_type', 'Karras'], ['steps', '20'], ['cfg', '7']],
       ['349 of 526', '357 of 526', '364 of 526', '494 of 526'], ['The image has', 'Euler a', 'Automatic', '30', '5']]);
check('    headed by the pick\'s name, saying where they come from and that Hires fix keeps the image\'s',
      [block()?.querySelector('.mm-usual-head')?.textContent, block()?.querySelector('.mm-usual-from')?.textContent],
      ['Anime Mix v12 is usually run with', 'From 526 of your generations with it. Hires fix keeps the image\'s settings.']);
check('    asked with the pick\'s name and the image, as send/plan takes it',
      [usualAsked.length, usualAsked[0]?.checkpoint, usualAsked[0]?.kind, usualAsked[0]?.image, usualAsked[0]?.version_ids],
      [1, MIX.name, 'civitai', '7002', '8002']);
check('    the tick, on at first as the setting is, and Send\'s line says so',
      [Boolean(usualTick()), usualTick()?.checked, status().endsWith('With its usual settings.')], [true, true, true]);
tickUsual(false);
check('    unticked: Send\'s line without it', status().includes('usual settings'), false);
press(sendButton());
check('    Send unticked: the pick alone, no usual settings', sent.at(-1)?.slice(0, 1).concat([sent.at(-1)?.[2]]), [MIX.name, null]);
await open();
pick(MIX.name);
await waitFor('drawn again', () => usualTick());
check('    the answer kept while the dialog is open: asked once per pick... per dialog', usualAsked.length, 2);
tickUsual();
check('    ticked: Send\'s line says so', status().endsWith('With its usual settings.'), true);
press(sendButton());
check('    and the dialog\'s Send hands the pick on with them, by the pick\'s name as the list says it',
      sent.at(-1), [MIX.name, 81, { name: 'Anime Mix v12' }]);
await open();
pick(OWN.name);
await waitFor('own answered', () => usualAsked.length === 3);
await new Promise((r) => setTimeout(r, 10));
check('    one the server says is as made: no block, no tick', [blockText(), Boolean(usualTick())], ['', false]);

// ------------------------- 18. in place, and only for the pick still picked
const rowsBox = modal()?.querySelector('.mm-pick-rows');
const searchBox = modal()?.querySelector('.mm-pick-search');
searchBox.value = '';
rowsBox.scrollTop = 120;
searchBox.focus();
pick(MIX.name);
await waitFor('MIX drawn', () => values().length);
tickUsual(false);
check('18. the answer and the tick leave the list\'s rows, their scroll and the search box as they were',
      [modal()?.querySelector('.mm-pick-rows') === rowsBox, rowsBox.scrollTop,
       modal()?.querySelector('.mm-pick-search') === searchBox, document.activeElement === searchBox],
      [true, 120, true, true]);
pick(FLUX.name);
await waitFor('FLUX drawn', () => values().some(([k]) => k === 'distilled_cfg'));
check('    a new pick: the tick on again, as the setting says, Send\'s line with it',
      [usualTick()?.checked, status().includes('usual settings')], [true, true]);
let release;
held.set(REAL.name, { promise: new Promise((r) => { release = r; }) });
pick(REAL.name);
check('    while it asks: said where the rows go, no tick',
      [blockText(), Boolean(usualTick())], ['Reading what Real v2 is usually run with…', false]);
pick(MIX.name);
release();
await new Promise((r) => setTimeout(r, 20));
check('    an answer for an earlier pick draws nothing: the pick picked now stays',
      [block()?.querySelector('.mm-usual-head')?.textContent], ['Anime Mix v12 is usually run with']);
// A late answer for an earlier pick redraws nothing that did not change: the
// tick keeps its focus, and Esc stays in the dialog (#292).
held.set(THIN.name, { promise: new Promise((r) => { release = r; }) });
pick(THIN.name);
pick(MIX.name);
await waitFor('MIX again', () => usualTick());
const focused = usualTick();
focused?.focus();
release();
await new Promise((r) => setTimeout(r, 20));
check('    a late answer for an earlier pick leaves the focused tick where it is',
      [Boolean(focused) && usualTick() === focused, Boolean(focused) && document.activeElement === focused], [true, true]);
held.set(LEAN.name, { promise: new Promise((r) => { release = r; }) });
pick(LEAN.name);
close();
release();
await new Promise((r) => setTimeout(r, 20));
check('    nor one after the dialog closed: no block anywhere', [Boolean(modal()), document.querySelectorAll('.mm-usual').length],
      [false, 0]);

// ------------------------------- 19. nothing to go by, a failure, the notice
await open();
pick(LEAN.name);
await waitFor('lean drawn', () => blockText().startsWith('Not enough'));
check('19. nothing to go by: said, no tick, Send still enabled',
      [blockText(), Boolean(usualTick()), sendButton()?.disabled],
      ['Not enough to go by: fewer than 5 of your generations or Civitai\'s stored images use it.', false, false]);
failing = true;
pick(REAL.name);
await waitFor('failure drawn', () => blockText().startsWith('Could not'));
failing = false;
check('    a failed ask: said, no tick, Send still enabled',
      [blockText(), Boolean(usualTick()), sendButton()?.disabled],
      ['Could not read its usual settings: the database is busy.', false, false]);
const usualNotice = send.usualNotice || (() => 'missing');
check('    Send\'s notice names every setting that went, the fifth too',
      usualNotice({ name: 'Flux Dev fp8' }, { sampler: 'Euler', schedule_type: 'Simple', steps: 28, cfg: 1, distilled_cfg: 3.5 }),
      'Sent with Flux Dev fp8\'s usual settings: Euler, Simple, 28 steps, CFG 1, Distilled CFG Scale 3.5.');
check('    and that none went, where the Send found none to apply',
      usualNotice({ name: 'Real v2' }, undefined), 'Real v2\'s usual settings could not be applied: the image\'s own were sent.');

// ------------------------------------------- a thin or missing setting
close();
await open();
pick(REAL.name);
await waitFor('real drawn', () => values().length);
check('a setting this WebUI lacks, and one too few uses record: said, the image\'s kept for each',
      values().slice(0, 2), [['sampler', 'Gone Sampler · not in this WebUI'], ['schedule_type', 'Not recorded enough']]);
check('    from Civitai\'s images, said so', block()?.querySelector('.mm-usual-from')?.textContent,
      'From 284 Civitai images that name it. Hires fix keeps the image\'s settings.');

// ------------------------------------------------- 34. the fifth setting
pick(FLUX.name);
await waitFor('flux drawn', () => values().some(([k]) => k === 'distilled_cfg'));
check('34. an answer with a fifth row draws it, named', [values().at(-1), block()?.querySelectorAll('.mm-usual-name').length],
      [['distilled_cfg', '3.5'], 5]);
pick(MIX.name);
await waitFor('mix drawn', () => values().length === 4);
check('    one without draws none', [...(block()?.querySelectorAll('.mm-usual-name') || [])].map((n) => n.textContent),
      ['Sampler', 'Schedule type', 'Steps', 'CFG scale']);
const asks = usualAsked.length;
pick(FLUX.name);
pick(MIX.name);
await new Promise((r) => setTimeout(r, 10));
check('18. picked again in the same dialog: its answer kept, not asked again', usualAsked.length, asks);
pick(THIN.name);
await waitFor('thin drawn', () => values().length);
check('    an answer with nothing the tick would send - too few uses, or not in this WebUI: drawn, no tick',
      [values().length, Boolean(usualTick())], [4, false]);
close();

// ------------------------------------------ 35. the setting turned off
usualSetting = false;
await open();
pick(MIX.name);
await waitFor('mix drawn', () => usualTick());
check('35. the setting off: the tick starts unticked at a pick, Send\'s line without it',
      [usualTick()?.checked, status().includes('usual settings')], [false, false]);
tickUsual();
pick(FLUX.name);
await waitFor('flux drawn', () => values().some(([k]) => k === 'distilled_cfg'));
check('    ticked, then a new pick: unticked again', usualTick()?.checked, false);
press(sendButton());
check('    and Send so: the pick alone, no usual settings', sent.at(-1)?.[2], null);
// The setting's answer comes after a pick: the tick follows it, unless pressed meanwhile.
for (const pressed of [false, true]) {
    let releaseOptions;
    optionsHeld = new Promise((r) => { releaseOptions = r; });
    await open();
    pick(MIX.name);
    await waitFor('mix drawn', () => usualTick());
    const before = usualTick()?.checked;
    if (pressed) tickUsual(true);
    releaseOptions();
    optionsHeld = null;
    await new Promise((r) => setTimeout(r, 20));
    check(pressed ? '    pressed before the setting\'s answer came: kept as pressed'
                  : '    picked before the setting\'s answer came: ticked, then unticked as the setting says',
          [before, usualTick()?.checked, status().includes('usual settings')],
          pressed ? [true, true, true] : [true, false, false]);
    close();
}
usualSetting = true;

done();
