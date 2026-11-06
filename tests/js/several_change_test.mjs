// Change, in txt2img's several mode (#400, shared/several.mjs): your
// checkpoint list in a window of its own - the Resources dialog's list, its
// search and family tabs (shared/resources.mjs) - each row a tick box, ticked
// as the mode holds it, asked of the server once. A tick changes the window
// alone; Use these, with two or more ticked, makes them the mode's list, in
// the order they were ticked, named as the list names them, from where the
// list came from as before - and sends nothing: no plan asked, no loader
// pressed, the prompt as it was. Cancel changes nothing. The mode ended -
// the setting turned off - closes the window.
import { act, bootPage, checker, escape, mountTab, press, sendLoaders, sharedModule, tabsAnswer } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_queue.py');
const { check, waitFor, done } = checker();

// Forge's tabs and txt2img's Generate box, as scheduler/capture.py makes it.
document.body.insertAdjacentHTML('afterbegin', `
    <div id="tabs">
        <button id="tab_txt2img-button" class="selected">txt2img</button>
        <button id="tab_img2img-button">img2img</button>
        <button id="tab_queue_tab-button">Queue</button>
    </div>
    <div id="txt2img_prompt"><textarea>a red apple</textarea></div>
    <div id="txt2img_generate_box" class="generate-box">
        <button id="txt2img_interrupt" style="display: none">Interrupt</button>
        <button id="txt2img_generate">Generate</button>
        <button id="txt2img_queue">Queue</button>
        <button id="txt2img_queue_several">Queue for checkpoints</button>
    </div>`);
const loaderAsks = [];
sendLoaders(document, { onAsk: (tab, request) => loaderAsks.push({ tab, ...request }),
                        answer: () => ({ mode: 0, skipped: [], notes: [] }) });
const byId = (id) => document.getElementById(id);
const queued = [];
byId('txt2img_queue_several').addEventListener('click', () => queued.push('pressed'));
const generated = [];

// The server: the setting on, a task of three checkpoints by Forge's names -
// and one holding a checkpoint gone since and one of a family this WebUI has
// no UI preset for - and the list of your checkpoints, five, as
// send.your_checkpoints answers with no image: the one loaded in Forge
// suggested.
let settingOn = true;
const ANIME = 'sdxl\\anime_v12.safetensors [0123abcd]';
const PHOTO = 'photo_v5.safetensors';
const FLUX = 'flux_dev.safetensors';
const DREAM = 'dream_v8.safetensors';
const QWEN = 'qwen_image.safetensors';
const GONE = 'gone_v1.safetensors';
const TASKS = { 30: [ANIME, PHOTO, FLUX], 32: [ANIME, GONE, QWEN] };
const row = (name, family, model, version, extra = {}) => ({
    name, file: name.split('\\').pop().split(' ')[0], family, read: true, supported: true, model, version,
    base_model: family, ...extra });
const CHECKPOINTS = [row(ANIME, 'xl', 'Anime Mix', 'v12'), row(PHOTO, 'xl', 'Real Photo', 'v5'),
                     row(FLUX, 'flux', 'Flux Dev', 'fp8'), row(DREAM, 'sd', 'Dream', 'v8'),
                     row(QWEN, 'qwen', 'Qwen Image', 'v1', { supported: false })];
let listFails = false;
const asked = [];
globalThis.fetch = async (url) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/ui-options')) {
        return reply({ success: true, samplers: [], schedulers: [], queue_enabled: true, queue_ask_above: 0,
                       queue_several: settingOn, tabs: tabsAnswer({ queue: true }),
                       family_names: { xl: 'SDXL', flux: 'Flux', sd: 'SD 1.x', qwen: 'Qwen-Image' } });
    }
    if (href.includes('/send/plan')) {
        const task = new URL(href, 'http://webui').searchParams.get('task');
        return reply({ success: true, kind: 'task', mode: 'txt2img', preset: null, checkpoint: ANIME, target: [],
                       modules_missing: [], checkpoints: TASKS[task] });
    }
    if (href.includes('/send/checkpoints')) {
        if (listFails) return reply({ success: false, error: 'the library is busy' });
        return reply({ success: true, checkpoints: CHECKPOINTS, suggested: [{ name: PHOTO, why: ['loaded now'] }],
                       picked: null, same_base: null, loaded: PHOTO, family: null });
    }
    if (href.includes('/asset-version')) return reply({ success: true, version: '1' });
    return reply({ success: true, notes: [], tasks: [], total: 0, page: 1, pages: 1, running: false, counts: {} });
};
globalThis.selectCheckpoint = () => {};

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
await waitFor('the Queue tab, and several mode with it', () => globalThis.__mmOffered?.has('several.change'));
// Forge's own listener on Generate, after ours on the document (this DOM has no capture phase).
document.addEventListener('click', (event) => {
    if (event.target.closest?.('#txt2img_generate')) generated.push('generate');
});
const { loadTask } = await sharedModule('send.mjs');
const { severalList } = await sharedModule('several.mjs');

const strip = () => byId('mm_several_strip');
const win = () => document.querySelector('dialog.mm-several-change');
const inputs = () => [...(win()?.querySelectorAll('.mm-pick-row input') || [])];
const ticked = () => inputs().filter((i) => i.checked).map((i) => i.value);
const inputOf = (name) => inputs().find((i) => i.value === name);
const tickedText = () => win()?.querySelector('[data-several-ticked]')?.textContent;
const use = () => win()?.querySelector('[data-several-use]');
/** A tick box ticked or unticked, as a click on it. */
function tick(name, on) {
    const input = inputOf(name);
    if (!input) return false;
    input.checked = on;
    press(input);
    return true;
}
const search = (text) => {
    const box = win()?.querySelector('.mm-pick-search');
    if (!box) return;
    box.value = text;
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
};
const listAsks = () => asked.filter((h) => h.includes('/send/checkpoints')).length;

await loadTask(30);
check('in several mode with the task\'s three', severalList()?.names, [ANIME, PHOTO, FLUX]);
check('the strip offers Change, then Leave',
      [...(strip()?.querySelectorAll('button') || [])].map((b) => b.textContent.trim()), ['Change', 'Leave']);

// ------------------------------------------------------- the window opens
act('several.change');
await waitFor('the list in the window', () => inputs().length);
check('Change: a window of its own, the list asked of the server once',
      [Boolean(win()?.open), win()?.querySelector('h3')?.textContent.trim(), listAsks()],
      [true, 'Checkpoints to queue with', 1]);
check('each row a tick box, ticked as the mode holds it, three ticked; no round buttons',
      [inputs().every((i) => i.type === 'checkbox'), ticked(), tickedText(), use()?.disabled],
      [true, [ANIME, PHOTO, FLUX], '3 ticked', false]);
check('its tabs open on All, every ticked row in it, though one is suggested; the loaded one said; the ticked rows marked',
      [[...win().querySelectorAll('.mm-pick-tab')].map((t) => t.textContent.trim()),
       win()?.querySelector('.mm-pick-tab.active')?.textContent.trim(),
       inputOf(PHOTO)?.closest('.mm-pick-row')?.querySelector('.mm-pick-loaded')?.textContent,
       [...win().querySelectorAll('.mm-pick-row.picked')].map((r) => r.querySelector('input')?.value)],
      [['Suggested 1', 'SDXL 2', 'Flux 1', 'SD 1.x 1', 'Qwen-Image 1', 'All 5'], 'All 5', 'Loaded in Forge now',
       [ANIME, PHOTO, FLUX]]);
check('focus starts on Cancel, the safe button, as every window\'s does',
      document.activeElement === win()?.querySelector('[data-several-cancel]'), true);
check('a family this WebUI cannot run: greyed, its box off, saying a queued run could not load it',
      [inputOf(QWEN)?.disabled, inputOf(QWEN)?.closest('.mm-pick-row')?.title],
      [true, 'This WebUI has no UI preset for this checkpoint\'s family, so a queued run could not load it.']);

// -------------------------------------------------------------- ticking
tick(PHOTO, false);
tick(DREAM, true);
const marked = () => [...win().querySelectorAll('.mm-pick-row.picked')].map((r) => r.querySelector('input')?.value);
check('a tick changes the window alone, its row marked with it: the mode keeps its list until Use these',
      [ticked(), marked(), tickedText(), severalList()?.names],
      [[ANIME, FLUX, DREAM], [ANIME, FLUX, DREAM], '3 ticked', [ANIME, PHOTO, FLUX]]);
search('flux');
check('its search narrows its rows', inputs().map((i) => i.value), [FLUX]);
search('');
check('and the ticks stay as they were', ticked(), [ANIME, FLUX, DREAM]);
tick(ANIME, false);
tick(FLUX, false);
check('one ticked: Use these off, saying why', [tickedText(), use()?.disabled, use()?.title],
      ['1 ticked', true, 'Tick two checkpoints or more. To generate with one, press Leave and use Generate.']);
tick(FLUX, true);
// Ctrl+Enter with the window open: Forge presses Generate, and nothing happens.
document.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Enter', ctrlKey: true }));
byId('txt2img_generate').dispatchEvent(new window.Event('click', { bubbles: true, cancelable: true }));
check('Ctrl+Enter while the window is open: nothing queued, nothing generated, the window as it was',
      [queued, generated, Boolean(win()), ticked()], [[], [], true, [FLUX, DREAM]]);

// -------------------------------------------------------------- Use these
const plansBefore = asked.filter((h) => h.includes('/send/plan')).length;
const loadsBefore = loaderAsks.length;
const prompt = () => document.querySelector('#txt2img_prompt textarea').value;
use()?.click();
check('Use these: the window closed, the mode holds the ticks in the order ticked, from where it came as before',
      [win(), severalList()], [null, { names: [DREAM, FLUX], source: { task: 30 } }]);
check('the button and the strip say them, named as the list names them',
      [byId('txt2img_queue_several').textContent, strip()?.querySelector('.mm-several-names')?.textContent,
       JSON.parse(strip()?.dataset.checkpoints || 'null')],
      ['Queue for 2 checkpoints', 'Queues with Dream v8 and Flux Dev fp8', { names: [DREAM, FLUX], source: { task: 30 } }]);
check('and nothing is sent: no plan asked, no loader pressed, nothing queued, the prompt as it was',
      [asked.filter((h) => h.includes('/send/plan')).length - plansBefore, loaderAsks.length - loadsBefore, queued,
       prompt()], [0, 0, [], 'a red apple']);

// ---------------------------------------------------------------- Cancel
act('several.change');
act('several.change');
await waitFor('the list in the window', () => inputs().length);
check('opened again - pressed twice, one window - ticked as the mode holds it now, the list asked afresh once',
      [document.querySelectorAll('dialog.mm-several-change').length, ticked(), listAsks()], [1, [FLUX, DREAM], 2]);
tick(FLUX, false);
tick(ANIME, true);
win()?.querySelector('[data-several-cancel]')?.click();
check('Cancel: the window closed, the mode as it was', [win(), severalList()?.names], [null, [DREAM, FLUX]]);
for (const [how, close] of [['Esc', () => escape()],
                            ['a click beside it', () => win()?.dispatchEvent(new window.Event('click', { bubbles: true }))]]) {
    act('several.change');
    await waitFor('the list in the window', () => inputs().length);
    tick(FLUX, false);
    close();
    check(`${how}: the window closed, the mode as it was`, [win(), severalList()?.names], [null, [DREAM, FLUX]]);
}

// ---------------------------------------- the list failing, the mode ending
listFails = true;
act('several.change');
await waitFor('the answer', () => win()?.querySelector('.mm-pick-wait')?.textContent.includes('Could not'));
check('the list failing says so in the window',
      win()?.querySelector('.mm-pick-wait')?.textContent, 'Could not read your checkpoints: the library is busy');
use()?.click();
check('and its ticks stay as the mode holds them: Use these keeps the list', [win(), severalList()?.names],
      [null, [DREAM, FLUX]]);
listFails = false;
act('several.change');
await waitFor('the list in the window', () => inputs().length);
settingOn = false;
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_queue_several'], settings: { model_manager_queue_several: { value: false } } } }));
await new Promise((resolve) => setTimeout(resolve, 20));
check('the setting turned off with the window open - it only starts the Resources dialog\'s box: the window stays, '
      + 'the mode holds', [Boolean(win()), severalList()?.names], [true, [DREAM, FLUX]]);
use()?.click();
// The setting stays off from here: Load to UI enters the mode all the same.
// ---------------- a name Forge does not list, a family this WebUI cannot run
await loadTask(32);
check('the setting off: Load to UI of a task of several enters the mode all the same', severalList()?.names.length, 3);
// Pressed only where the strip offers it: a mode not entered fails the checks after, not the suite.
if (strip()) act('several.change');
await waitFor('the list in the window', () => inputs().length);
const subOf = (name) => inputOf(name)?.closest('.mm-pick-row')?.querySelector('.mm-pick-sub')?.textContent;
check('a ticked name Forge does not list: a row of its own, first, ticked, saying so, open to untick',
      [inputs()[0]?.value, inputOf(GONE)?.checked, subOf(GONE), inputOf(GONE)?.disabled], [GONE, true, 'Forge does not list it', false]);
check('a ticked row of a family this WebUI cannot run: greyed, ticked, open to untick',
      [inputOf(QWEN)?.closest('.mm-pick-row')?.classList.contains('mm-pick-greyed'), inputOf(QWEN)?.checked,
       inputOf(QWEN)?.disabled], [true, true, false]);
tick(GONE, false);
tick(QWEN, false);
tick(DREAM, true);
use()?.click();
check('both let go, the list is what is ticked', severalList()?.names, [ANIME, DREAM]);

// ------------------------------------- Several checkpoints…, outside the mode
const entry = () => byId('mm_several_entry');
check('in the mode: no Several checkpoints…, the strip in its place', [entry(), Boolean(strip())], [null, true]);
if (strip()) act('several.leave');
check('out of the mode: Several checkpoints… right under Generate\'s box, the strip gone',
      [strip(), entry()?.previousElementSibling?.id, entry()?.querySelector('button')?.textContent],
      [null, 'txt2img_generate_box', 'Several checkpoints…']);
const entryAsks = listAsks();
const entryLoads = loaderAsks.length;
const entryPlans = asked.filter((h) => h.includes('/send/plan')).length;
// Pressed only where drawn: a break that never draws it fails the checks after, not the suite.
if (entry()) act('several.change');
await waitFor('the list in the window', () => inputs().length);
check('it opens Change\'s window, the list asked once, Forge\'s loaded checkpoint ticked, Use these waiting for a second',
      [Boolean(win()?.open), listAsks() - entryAsks, ticked(), tickedText(), use()?.disabled, use()?.title],
      [true, 1, [PHOTO], '1 ticked', true, 'Tick two checkpoints or more. To generate with one, use Generate.']);
tick(ANIME, true);
use()?.click();
check('Use these enters the mode with them, in the order ticked, no image or task behind them',
      [severalList(), JSON.parse(strip()?.dataset.checkpoints || 'null'), entry()],
      [{ names: [PHOTO, ANIME], source: null }, { names: [PHOTO, ANIME], source: null }, null]);
check('and sends nothing: no plan asked, no loader pressed, the prompt as it was',
      [asked.filter((h) => h.includes('/send/plan')).length - entryPlans, loaderAsks.length - entryLoads,
       document.querySelector('#txt2img_prompt textarea').value], [0, 0, 'a red apple']);
if (strip()) act('several.leave');
if (entry()) act('several.change');
await waitFor('the list in the window', () => inputs().length);
tick(DREAM, true);
win()?.querySelector('[data-several-cancel]')?.click();
check('Cancel outside the mode changes nothing: no mode, Several checkpoints… still there',
      [Boolean(win()), severalList(), Boolean(entry())], [false, null, true]);

await loadTask(30);
if (strip()) act('several.change');
await waitFor('the list in the window', () => inputs().length);
window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed: ['model_manager_queue_enabled'], settings: { model_manager_queue_enabled: { value: false } } } }));
await waitFor('the window to close', () => !win());
check('the Queue switched off with the window open: the window closed, the mode ended', [win(), severalList()],
      [null, null]);
check('and Several checkpoints… is not drawn again: the mode\'s service has stopped', entry(), null);

done();
