// txt2img's several mode (#400, shared/several.mjs): Load to UI of a task of
// several checkpoints enters it while the setting Queue a generation with
// several checkpoints is on. Generate is hidden, Queue for N checkpoints
// stands in its place, and a strip under them names the list - where the
// press's page code reads it, with where it came from. With the setting off,
// Load to UI sets up the first checkpoint and says so.
//
// In the mode a press of Generate the person makes, or the one Forge's
// Ctrl+Enter makes for them, becomes Queue for N checkpoints - never while a
// generation runs, nor in img2img - and the large-batch question never comes
// to offer Generate. A click Generate forever makes passes. Leave, a plain
// Send (Load to UI of a task of one), the setting turned off from the
// settings window or Forge's Settings page, and the Queue switched off each
// end it: Generate back.
import { readFileSync } from 'node:fs';
import { ROOT, act, bootPage, checker, mountTab, sendLoaders, sharedModule, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// Forge's tabs, txt2img's Generate box - Interrupt, Skip and Interrupting
// over it, Generate, the Queue button and Queue for N checkpoints beside it,
// as scheduler/capture.py makes them - img2img's Generate, and the batch
// sliders the large-batch question reads.
const sliders = (tab) => `
    <div id="${tab}_batch_count"><input type="number" value="1"></div>
    <div id="${tab}_batch_size"><input type="number" value="1"></div>`;
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_queue_tab-button">Queue</button>
    </div>
    <div id="txt2img_prompt"><textarea></textarea></div>
    <div id="txt2img_toprow">
        <div id="txt2img_generate_box" class="generate-box">
            <button id="txt2img_interrupt" style="display: none">Interrupt</button>
            <button id="txt2img_skip" style="display: none">Skip</button>
            <button id="txt2img_interrupting" style="display: none">Interrupting...</button>
            <button id="txt2img_generate">Generate</button>
            <button id="txt2img_queue">Queue</button>
            <button id="txt2img_queue_several">Queue for checkpoints</button>
            <button id="txt2img_generate_several">Generate for checkpoints</button>
        </div>
        <div id="txt2img_tools"></div>
    </div>
    ${sliders('txt2img')}
    <button id="img2img_generate">Generate</button>
    <button id="img2img_queue">Queue</button>
    ${sliders('img2img')}`);
sendLoaders(document, { answer: () => ({ mode: 0, skipped: [], notes: [] }) });
const byId = (id) => document.getElementById(id);
const pressed = [];
for (const id of ['txt2img_queue', 'txt2img_queue_several', 'txt2img_generate_several', 'img2img_queue']) {
    byId(id).addEventListener('click', () => pressed.push(id));
}

// The server: the setting as said, a task of three checkpoints - by Forge's
// names, a folder and a hash in one - and a task of one.
let settingOn = true;
const NAMES = ['sdxl\\anime_v12.safetensors [0123abcd]', 'photo_v5.safetensors', 'flux_dev.safetensors'];
const PLANS = { 30: NAMES, 31: ['photo_v5.safetensors'] };
globalThis.fetch = async (url) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], queue_enabled: true, queue_ask_above: 4,
                       queue_several: settingOn, tabs: tabsAnswer({ queue: true }) });
    }
    const plan = href.includes('/send/plan') && new URL(href, 'http://webui').searchParams.get('task');
    if (plan) {
        // As the server answers: its first checkpoint set up, every one named (send.task_plan).
        return reply({ success: true, kind: 'task', mode: 'txt2img', preset: null, checkpoint: PLANS[plan][0],
                       target: [], modules_missing: [], checkpoints: PLANS[plan] });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, running: false, counts: {} });
};

// Forge's checkpoint box, as Load to UI sets it.
const selected = [];
globalThis.selectCheckpoint = (name) => selected.push(name);
// The WebUI's onAfterUiUpdate keeps each callback; the suite runs several mode's.
const updates = [];
globalThis.onAfterUiUpdate = (callback) => updates.push(callback);
const redraw = () => updates.filter((callback) => callback.name === 'draw').forEach((callback) => callback());
// Each listener on the document, with whether it hears on the way down.
const listening = [];
const addListener = document.addEventListener.bind(document);
document.addEventListener = (type, listener, options) => {
    listening.push({ type, name: listener?.name, capture: Boolean(typeof options === 'object' ? options?.capture : options) });
    return addListener(type, listener, options);
};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab, and several mode with it', () => globalThis.__mmOffered?.has('queue.start')
                                                                && globalThis.__mmOffered?.has('several.enter'));
// Forge's own listeners: on Generate, and its Ctrl+Enter, which clicks the
// shown tab's Generate. A browser runs the page's capture listeners before
// them; this DOM has no capture phase, so they stand after ours on the document.
document.addEventListener('click', (event) => {
    const generate = event.target.closest?.('#txt2img_generate, #img2img_generate');
    if (generate) pressed.push(generate.id);
});
const showing = (tab) => ['txt2img', 'img2img'].forEach((t) => byId(`tab_${t}-button`).classList.toggle('selected', t === tab));
function ctrlEnter() {
    document.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Enter', ctrlKey: true }));
    const tab = byId('tab_img2img-button').classList.contains('selected') ? 'img2img' : 'txt2img';
    byId(`${tab}_generate`).dispatchEvent(new window.Event('click', { bubbles: true, cancelable: true }));
}
/** A press of Generate: the person's own, or - not trusted - a script's, as Generate forever's. */
function click(person) {
    const event = new window.Event('click', { bubbles: true, cancelable: true });
    if (person) Object.defineProperty(event, 'isTrusted', { value: true });
    byId('txt2img_generate').dispatchEvent(event);
}
const { loadTask } = await sharedModule('send.mjs');
const { severalList } = await sharedModule('several.mjs');
const strip = () => byId('mm_several_strip');
const inMode = () => document.body.classList.contains('mm-several');
const notices = () => [...document.querySelectorAll('.mm-notice')].map((n) => n.textContent.trim());
const clearNotices = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ---------------------------------------------------- entered by Load to UI
const words = () => [byId('txt2img_generate_several').textContent, byId('txt2img_queue_several').textContent];
check('before: no mode, no strip, the buttons as made', [inMode(), strip(), words()],
      [false, null, ['Generate for checkpoints', 'Queue for checkpoints']]);
await loadTask(30);
check('Load to UI of a task of three, the setting on: several mode, with its list and the task it came from',
      [inMode(), severalList()], [true, { names: NAMES, source: { task: 30 } }]);
check('the buttons read how many', words(), ['Generate for 3 checkpoints', 'Queue for 3 checkpoints']);
check('Generate for N says it runs next and resumes nothing', byId('txt2img_generate_several').title,
      'Queue one task that makes this generation with each checkpoint in turn, and run it next: after the task the '
      + 'queue is on, if any. The queue does not resume.');
check('a strip right under Generate\'s box names each, short; in full on hover',
      [strip()?.previousElementSibling?.id, strip()?.querySelector('.mm-several-names')?.textContent,
       strip()?.querySelector('.mm-several-names')?.title],
      ['txt2img_generate_box', 'Queues with anime_v12, photo_v5 and flux_dev', NAMES.join('\n')]);
check('nothing said; the first checkpoint set up in Forge', [notices(), selected], [[], [NAMES[0]]]);
check('Generate\'s click and Ctrl+Enter are heard on the way down, before Forge\'s listeners and the Queue tab\'s',
      ['click', 'keydown'].map((type) => listening.filter((l) => l.type === type
                                                             && ['onGenerate', 'onKeys'].includes(l.name))
          .map((l) => l.capture)), [[true], [true]]);

// Gradio redraws: each update the mode writes only what differs, and puts
// back what a redraw took.
const Observer = window.MutationObserver;
const written = [];
const watcher = new Observer((records) => written.push(...records));
watcher.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
redraw();
redraw();
await new Promise((resolve) => setTimeout(resolve, 10));
watcher.disconnect();
check('an update with nothing changed writes nothing', written.length, 0);
strip()?.remove();
byId('txt2img_queue_several').textContent = 'Queue for checkpoints';
byId('txt2img_generate_several').textContent = 'Generate for checkpoints';
redraw();
check('an update after a redraw took the strip and the words puts both back',
      [words(), strip()?.previousElementSibling?.id, JSON.parse(strip()?.dataset.checkpoints || 'null')],
      [['Generate for 3 checkpoints', 'Queue for 3 checkpoints'], 'txt2img_generate_box',
       { names: NAMES, source: { task: 30 } }]);

// The press's page code, as the server hands it to Gradio (capture._READ_SEVERAL),
// puts the strip's list in its last input.
const capture = readFileSync(`${ROOT}/model_manager/scheduler/capture.py`, 'utf8');
const readSeveral = (0, eval)(capture.match(/_READ_SEVERAL = """([\s\S]*?)"""/)?.[1] || 'null');
check('the press reads the list and where it came from off the strip',
      typeof readSeveral === 'function' ? JSON.parse(readSeveral('a red apple', 20, '').at(-1) || 'null') : null,
      { names: NAMES, source: { task: 30 } });

// The stylesheet is what hides Generate and Queue: linkedom has no cascade, so
// its rule is read. Interrupt and Skip are named nowhere in it.
const css = readFileSync(`${ROOT}/style.css`, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const rule = css.match(/([^{}]*)\{\s*display:\s*none\s*!important;\s*\}/g)
    ?.find((r) => r.includes('#txt2img_queue_several'));
// Made after the Queue button: the box puts Generate for N first, in Generate's
// place; Queue for N, made right after Queue, stands where Queue was.
const own = (id) => css.match(new RegExp(`(?:^|})\\s*#${id}\\s*\\{([^}]*)\\}`))?.[1] || '';
check('the stylesheet puts Generate for N first in Generate\'s box, as tall as Generate',
      [/(^|;|\s)order:\s*-1\s*;/.test(own('txt2img_generate_several')),
       /min-height:\s*4\.5em/.test(own('txt2img_generate_several'))], [true, true]);
check('and leaves Queue for N where it is made, as Queue is', own('txt2img_queue_several'), '');
check('the stylesheet hides Generate and Queue in the mode, and both buttons outside it',
      rule?.split('{')[0].split(',').map((s) => s.trim()).sort(),
      ['body.mm-several #txt2img_generate', 'body.mm-several #txt2img_queue',
       'body:not(.mm-several) #txt2img_generate_several', 'body:not(.mm-several) #txt2img_queue_several']);

// ------------------------------------------------------ Generate's presses
pressed.length = 0;
ctrlEnter();
check('Ctrl+Enter presses Generate for N checkpoints, never Generate', pressed, ['txt2img_generate_several']);
pressed.length = 0;
click(true);
check('so does a click of the person\'s on Generate', pressed, ['txt2img_generate_several']);
pressed.length = 0;
click(false);
check('Generate forever\'s click, no keys before it, passes to Generate', pressed, ['txt2img_generate']);
pressed.length = 0;
document.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Enter', ctrlKey: true }));
const realNow = Date.now;
Date.now = () => realNow() + 1500;
click(false);
Date.now = realNow;
check('nor a click that comes over a second after Ctrl+Enter', pressed, ['txt2img_generate']);

pressed.length = 0;
byId('txt2img_interrupt').style.display = 'block';
ctrlEnter();
byId('txt2img_interrupt').style.display = 'none';
check('while a generation runs, Ctrl+Enter is Forge\'s, as ever', pressed, ['txt2img_generate']);

pressed.length = 0;
showing('img2img');
ctrlEnter();
showing('txt2img');
check('in img2img, Ctrl+Enter is Forge\'s, as ever', pressed, ['img2img_generate']);

// Above the large-batch setting (4), Generate asks first - but not in the mode.
const dialog = () => document.querySelector('dialog.queue-dialog[open]');
byId('txt2img_batch_count').querySelector('input').value = '5';
pressed.length = 0;
ctrlEnter();
await new Promise((resolve) => setTimeout(resolve, 20));
check('a large batch in the mode: Generate for N checkpoints, and no question offering Generate',
      [pressed, Boolean(dialog())], [['txt2img_generate_several'], false]);

// --------------------------------------------------------------- Leave
// Pressed only where drawn: a break that never draws it fails the checks before, not the suite.
if (strip()) act('several.leave');
check('Leave: Generate back, the strip gone, nothing held', [inMode(), strip(), severalList()], [false, null, null]);
pressed.length = 0;
ctrlEnter();
await waitFor('the question', () => dialog());
check('out of the mode, the same batch asks again, Generate pressed by Forge as ever',
      [Boolean(dialog()), pressed], [true, []]);
[...(dialog()?.querySelectorAll('button') || [])].find((b) => b.textContent.trim() === 'Cancel')?.click();
await new Promise((resolve) => setTimeout(resolve, 10));
byId('txt2img_batch_count').querySelector('input').value = '1';

// ------------------------------------------------------- a plain Send
await loadTask(30);
await loadTask(31);
check('Load to UI of a task of one, a plain Send: the mode ends', [inMode(), strip(), severalList()], [false, null, null]);

// ------------------------------------------------------------- the setting
// It only starts the Resources dialog's box: turned off, the mode holds, and Load to UI enters it.
await loadTask(30);
settingOn = false;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_queue_several'], settings: { model_manager_queue_several: { value: false } } } }));
await new Promise((resolve) => setTimeout(resolve, 20));
check('the setting turned off in the settings window: the mode holds', [inMode(), severalList()?.names], [true, NAMES]);
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied', { detail: { changed: ['model_manager_queue_several'] } }));
await new Promise((resolve) => setTimeout(resolve, 20));
check('and turned off on Forge\'s Settings page: the mode holds', inMode(), true);
await loadTask(31);
clearNotices();
await loadTask(30);
check('with it off, Load to UI of a task of several enters the mode, and says nothing of the setting',
      [inMode(), severalList()?.names, notices()], [true, NAMES, []]);
await loadTask(31);

// With the setting on but no Queue for N checkpoints made at this start, the
// mode cannot hold: the first is set up, and the notice names no setting.
settingOn = true;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_queue_several'], settings: { model_manager_queue_several: { value: true } } } }));
const made = byId('txt2img_queue_several');
const box = made.parentNode;
made.remove();
clearNotices();
await loadTask(30);
box.append(made);
check('no button made: no mode, and the notice does not ask for the setting, which is on',
      [inMode(), notices()], [false, ['Task #30 holds 3 checkpoints. Load to UI set up the first.']]);

// ----------------------------------------------------- the Queue switched off
await loadTask(30);
check('in the mode again', inMode(), true);
// Switched off in the settings window: the loading module stops the tab, and its services with it.
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_queue_enabled'], settings: { model_manager_queue_enabled: { value: false } } } }));
await waitFor('the mode to end', () => !inMode());
check('the Queue switched off: Generate back, the strip gone', [inMode(), strip()], [false, null]);
pressed.length = 0;
click(true);
check('and Generate generates', pressed, ['txt2img_generate']);

done();
