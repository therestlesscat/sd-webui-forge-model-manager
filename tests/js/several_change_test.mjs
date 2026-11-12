// Change, in txt2img's several mode (#400, shared/several.mjs): your
// checkpoint list in a window of its own - the Resources dialog's list, its
// search and family tabs (shared/resources.mjs) - each row a tick box, ticked
// as the mode holds it, asked of the server once. A tick changes the window
// alone; Use these, with two or more ticked, makes them the mode's list, in
// the order they were ticked, named as the list names them, from where the
// list came from as before - and sends nothing: no plan asked, no loader
// pressed, the prompt as it was. Cancel changes nothing. The mode ended -
// the setting turned off - closes the window. Beside the list, what each
// ticked one runs with (#406): asked of the server for the whole ticked list
// at each tick, with the press's own {names, source}, an older answer dropped,
// a failure shown and asked again at the next tick, each line as the plan says
// it - and the rows, their scroll and the search box left as they are.
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
// Each with its size (#415), not in name order: Largest first is Flux, Real Photo, Qwen, Anime, Dream.
const CHECKPOINTS = [row(ANIME, 'xl', 'Anime Mix', 'v12', { size: 2 }), row(PHOTO, 'xl', 'Real Photo', 'v5', { size: 5 }),
                     row(FLUX, 'flux', 'Flux Dev', 'fp8', { size: 9 }), row(DREAM, 'sd', 'Dream', 'v8', { size: 1 }),
                     row(QWEN, 'qwen', 'Qwen Image', 'v1', { supported: false, size: 3 })];
let listFails = false;
const asked = [];
// What each runs with (several.runs_preview), as the server answers it: only
// the names asked, each from RUN or as a plain usual-settings line, with what
// ANSWER says beside them. `holdNext` holds the next answer until released.
const RUN = {};
let ANSWER = {};
let runsFail = false;
let holdNext = null;
let holdList = null;                    // holds the next answer of your checkpoints' list until released
const runsAsked = [];
const plainRun = { how: 'usual', usual: { steps: 20 }, family: 'xl', family_state: 'read', another_family: false,
                   problem: null };
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    asked.push(href);
    const reply = (body) => ({ ok: true, status: 200, json: async () => structuredClone(body) });
    if (href.includes('/model-manager/queue/several/runs')) {
        const body = JSON.parse(init.body || '{}');
        runsAsked.push(body);
        // Worked out as asked, then held: a held answer says what was so when it was asked.
        const answer = runsFail ? { success: false, error: 'the library is busy' }
            : { success: true, runs: Object.fromEntries(body.names.map((n) => [n, RUN[n] || plainRun])),
                selected: { name: PHOTO, state: 'read' }, gone_task: null, ...ANSWER };
        const hold = holdNext;
        holdNext = null;
        if (hold) await hold;
        return reply(answer);
    }
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
        const hold = holdList;
        holdList = null;
        if (hold) await hold;
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
const column = () => win()?.querySelector('.mm-pick-area > [data-several-runs]');
/** Each line of the column: the name, whether marked another family, what it runs with. */
const lines = () => [...(column()?.querySelectorAll('.mm-usual-each') || [])].map((e) => [
    e.querySelector('.mm-usual-each-name')?.firstChild?.textContent, Boolean(e.querySelector('.mm-usual-each-family')),
    e.querySelector('.mm-usual-each-what')?.textContent]);
const under = () => [...(column()?.querySelectorAll('.mm-usual-note:not([data-family-note])') || [])].map((e) => e.textContent);
const familyNote = () => column()?.querySelector('[data-family-note]')?.textContent ?? null;
const settled = () => lines().length > 0 && !lines().some(([, , what]) => what.startsWith('Reading'));
const STAY = 'the size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them.';
/** The answer as given, asked afresh by a tick and its untick: the last answer is the one drawn. */
async function answered(runs, extra = {}) {
    Object.assign(RUN, runs);
    ANSWER = extra;
    tick(DREAM, true);
    tick(DREAM, false);
    await waitFor('the column answered afresh', () => settled() && lines().length === 3);
}
RUN[ANIME] = { ...plainRun, how: 'held', usual: { steps: 12 } };
RUN[PHOTO] = { ...plainRun, how: 'held', usual: null };
RUN[FLUX] = { ...plainRun, how: 'usual', usual: { sampler: 'Euler', schedule_type: 'Simple', steps: 20, distilled_cfg: 3.5 },
              family: 'flux', another_family: true };

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
      [true, [ANIME, FLUX, PHOTO], '3 ticked', false]);
check('its tabs open on All, every ticked row in it, though one is suggested; the loaded one said; the ticked rows marked',
      [[...win().querySelectorAll('.mm-pick-tab')].map((t) => t.textContent.trim()),
       win()?.querySelector('.mm-pick-tab.active')?.textContent.trim(),
       inputOf(PHOTO)?.closest('.mm-pick-row')?.querySelector('.mm-pick-loaded')?.textContent,
       [...win().querySelectorAll('.mm-pick-row.picked')].map((r) => r.querySelector('input')?.value)],
      [['Suggested 1', 'Flux 1', 'Qwen-Image 1', 'SD 1.x 1', 'SDXL 2', 'All 5', 'Ticked 3'], 'All 5', 'Loaded in Forge now',
       [ANIME, FLUX, PHOTO]]);
check('focus starts on Cancel, the safe button, as every window\'s does',
      document.activeElement === win()?.querySelector('[data-several-cancel]'), true);
check('a family this WebUI cannot run: greyed, its box off, saying a queued run could not load it',
      [inputOf(QWEN)?.disabled, inputOf(QWEN)?.closest('.mm-pick-row')?.title],
      [true, 'This WebUI has no UI preset for this checkpoint\'s family, so a queued run could not load it.']);

// ------------------------------------------- what each runs with (#406)
check('the window\'s message: the prompt stays, what each runs with is shown with the list; Change says so too',
      [win()?.querySelector('.mm-question-message')?.textContent.replace(/\s+/g, ' ').trim(),
       strip()?.querySelector('[data-action="several.change"]')?.title],
      ['Tick each checkpoint to make your generation with; they run in the order you tick them. Your prompt stays as '
       + 'it is; what each one runs with is shown with the list.',
       'Tick the checkpoints to queue with, and see what each runs with.']);
await waitFor('the column\'s answer', settled);
check('asked once, with the press\'s own names and source, the ticks in the mode\'s order', runsAsked,
      [{ names: [ANIME, PHOTO, FLUX], source: { task: 30 } }]);
check('a line per ticked checkpoint, in tick order, named as the list names them, from the answer', lines(),
      [['Anime Mix v12', false, 'Steps 12 · as in task #30'],
       ['Real Photo v5', false, 'Runs with your settings, as in task #30.'],
       ['Flux Dev fp8', true, 'Euler · Simple · Steps 20 · Distilled CFG Scale 3.5']]);
check('the family note names Forge\'s selected checkpoint', familyNote(),
      `Of another family than Forge's selected checkpoint, Real Photo v5: ${STAY}`);

// A tick: the whole list asked once; the rows and the search box left as they are.
const rowsBefore = [...win().querySelectorAll('.mm-pick-row')];
const searchBox = win().querySelector('.mm-pick-search');
searchBox.focus();
runsAsked.length = 0;
tick(DREAM, true);
await waitFor('the four lines', () => settled() && lines().length === 4);
check('a tick asks once, for the whole ticked list, in tick order', runsAsked.map((b) => b.names),
      [[ANIME, PHOTO, FLUX, DREAM]]);
const rowsAfter = [...win().querySelectorAll('.mm-pick-row')];
check('the rows are the same elements, and the search box keeps its focus',
      [rowsBefore.length > 0, rowsAfter.length === rowsBefore.length, rowsAfter.every((r, i) => r === rowsBefore[i]),
       document.activeElement === searchBox], [true, true, true, true]);
// An older answer arriving after a newer one is dropped.
let release;
holdNext = new Promise((resolve) => { release = resolve; });
const heldAnime = RUN[ANIME];
const heldPhoto = RUN[PHOTO];
RUN[ANIME] = { ...plainRun, how: 'thin', usual: null };
tick(DREAM, false);
RUN[ANIME] = heldAnime;
// The newer answer says something of its own, so the wait for it cannot be met by an older one.
RUN[PHOTO] = { ...plainRun, how: 'plain', usual: null };
tick(FLUX, false);
await waitFor('the newer answer', () => settled() && lines().length === 2 && lines()[1][2] === 'Runs with your settings.');
RUN[PHOTO] = heldPhoto;
// While a newer answer is asked, the lines drawn stay, and the new name reads as being asked.
let releaseNext;
holdNext = new Promise((resolve) => { releaseNext = resolve; });
tick(DREAM, true);
await waitFor('the new name asked', () => lines().length === 3);
check('while asked: the lines drawn stay, the new name reads as being asked', lines().map(([name, , what]) => [name, what]),
      [['Anime Mix v12', 'Steps 12 · as in task #30'], ['Real Photo v5', 'Runs with your settings.'],
       ['Dream v8', 'Reading its usual settings…']]);
releaseNext();
await waitFor('its line', settled);
tick(DREAM, false);
await waitFor('two again', () => settled() && lines().length === 2
                                 && lines()[1][2] === 'Runs with your settings, as in task #30.');
release();
await new Promise((resolve) => setTimeout(resolve, 30));
check('an older answer arriving last is dropped: the newer one stays drawn',
      lines().map(([name, , what]) => [name, what]),
      [['Anime Mix v12', 'Steps 12 · as in task #30'], ['Real Photo v5', 'Runs with your settings, as in task #30.']]);
// A failure is shown, not kept: the next tick asks again.
runsFail = true;
tick(FLUX, true);
await waitFor('the failure', () => lines().some(([, , what]) => what.startsWith('Could not')));
check('a failure is shown on each line', lines().map(([, , what]) => what),
      Array(3).fill('Could not read what it runs with: the library is busy.'));
runsFail = false;
runsAsked.length = 0;
await answered({});
check('and the next tick asks again', [runsAsked.length > 0, lines().map(([, , what]) => what)[0]],
      [true, 'Steps 12 · as in task #30']);
// Each line, as the plan says it, and the lines under them.
await answered({ [ANIME]: { ...plainRun, how: 'yours', usual: null },
                 [PHOTO]: { ...plainRun, how: 'as_made', usual: null },
                 [FLUX]: { ...plainRun, how: 'error', usual: null, family: null, family_state: 'not_read',
                           another_family: null } },
               { selected: { name: PHOTO, state: 'not_read' }, gone_task: 30 });
check('yours, as made, unreadable and a family read when you queue; a task gone; the selected one not read',
      [lines().map(([, mark, what]) => [mark, what]), under(), familyNote()],
      [[[false, 'Runs with your settings: Forge\'s selected checkpoint.'],
        [false, 'Runs as made, with the image\'s settings.'],
        [false, 'Could not read its usual settings: it runs with your settings. Its family is read when you queue.']],
       ['Task #30 is gone: each takes its usual settings.',
        'Forge\'s selected checkpoint is not read yet: a checkpoint of another family is told when you queue.'], null]);
await answered({ [ANIME]: { ...plainRun, how: 'thin', usual: null },
                 [PHOTO]: { ...plainRun, how: 'plain', usual: null, family: null, family_state: 'unrecognised',
                            another_family: true },
                 [FLUX]: { ...plainRun, how: null, usual: null, family: 'flux', another_family: true,
                           problem: `${FLUX} needs T5-XXL, which this WebUI does not have.` } },
               { selected: { name: null, state: null } });
check('too few uses, none applying and a family not recognised, a refusal; none selected',
      [lines().map(([, mark, what]) => [mark, what]), under(), familyNote()],
      [[[false, 'Runs with your settings: too few uses record its own.'],
        [true, 'Runs with your settings. Its family was not recognised when last read: it is read again when you queue.'],
        [true, `Queuing stops on it: ${FLUX} needs T5-XXL, which this WebUI does not have.`]],
       [], `Forge has no checkpoint selected that it lists, so each is of another family: ${STAY}`]);
await answered({}, { selected: { name: PHOTO, state: 'unrecognised' } });
check('the selected one not recognised when last read: said under the lines', under(),
      ['Forge\'s selected checkpoint was not recognised when last read: a checkpoint of another family is told when '
       + 'you queue.']);
tick(ANIME, false);
tick(PHOTO, false);
tick(FLUX, false);
await waitFor('the hint', () => !lines().length);
check('nothing ticked: the column says what it is for, with nothing to ask', [under(), lines()],
      [['Tick a checkpoint to see what it runs with.'], []]);
for (const name of [ANIME, PHOTO, FLUX]) tick(name, true);
for (const name of [ANIME, PHOTO, FLUX]) delete RUN[name];
ANSWER = {};
await waitFor('the three again', () => settled() && lines().length === 3);
// The list's answer coming after the column's: each line named by its file, then as the list names it.
win()?.querySelector('[data-several-cancel]')?.click();
let releaseList;
holdList = new Promise((resolve) => { releaseList = resolve; });
act('several.change');
await waitFor('the column answered, the list still asked', () => win() && settled());
check('with the list not come yet, each line is named by its file', lines().map(([name]) => name),
      ['anime_v12', 'photo_v5', 'flux_dev']);
const untickWhileRead = win()?.querySelector('.mm-pick-line [data-action="resources.untickAll"]');
check('#415: three ticked, the list not come yet: Untick all there, off until it is, saying why',
      [untickWhileRead?.disabled, untickWhileRead?.title], [true, 'Your checkpoints are still being read.']);
releaseList();
await waitFor('the list in the window', () => inputs().length);
await waitFor('the lines named again', () => lines()[0]?.[0] === 'Anime Mix v12');
check('and once it comes, as the list names them', lines().map(([name]) => name),
      ['Anime Mix v12', 'Real Photo v5', 'Flux Dev fp8']);

// -------------------------------------------------------------- ticking
tick(PHOTO, false);
tick(DREAM, true);
const marked = () => [...win().querySelectorAll('.mm-pick-row.picked')].map((r) => r.querySelector('input')?.value);
check('a tick changes the window alone, its row marked with it: the mode keeps its list until Use these',
      [ticked(), marked(), tickedText(), severalList()?.names],
      [[ANIME, DREAM, FLUX], [ANIME, DREAM, FLUX], '3 ticked', [ANIME, PHOTO, FLUX]]);
search('flux');
check('its search narrows its rows', inputs().map((i) => i.value), [FLUX]);
search('');
check('and the ticks stay as they were', ticked(), [ANIME, DREAM, FLUX]);
tick(ANIME, false);
tick(FLUX, false);
check('one ticked: Use these off, saying why', [tickedText(), use()?.disabled, use()?.title],
      ['1 ticked', true, 'Tick two checkpoints or more. To generate with one, press Leave and use Generate.']);
tick(FLUX, true);
// Ctrl+Enter with the window open: Forge presses Generate, and nothing happens.
document.dispatchEvent(Object.assign(new window.Event('keydown', { bubbles: true }), { key: 'Enter', ctrlKey: true }));
byId('txt2img_generate').dispatchEvent(new window.Event('click', { bubbles: true, cancelable: true }));
check('Ctrl+Enter while the window is open: nothing queued, nothing generated, the window as it was',
      [queued, generated, Boolean(win()), ticked()], [[], [], true, [DREAM, FLUX]]);

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
      [document.querySelectorAll('dialog.mm-several-change').length, ticked(), listAsks()], [1, [DREAM, FLUX], 3]);
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
const untickFailed = win()?.querySelector('.mm-pick-line [data-action="resources.untickAll"]');
check('#415: and Untick all, off, says the list could not be read - not that it is still being read',
      [untickFailed?.disabled, untickFailed?.title], [true, 'Your checkpoints could not be read.']);
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
// #415: the Sort box as the Resources dialog left it in the browser - one key for both windows.
localStorage.setItem('mm-pick-sort', 'base');
// Pressed only where the strip offers it: a mode not entered fails the checks after, not the suite.
if (strip()) act('several.change');
await waitFor('the list in the window', () => inputs().length);
const subOf = (name) => inputOf(name)?.closest('.mm-pick-row')?.querySelector('.mm-pick-sub')?.textContent;
check('a ticked name Forge does not list: a row of its own, first, ticked, saying so, open to untick',
      [inputs()[0]?.value, inputOf(GONE)?.checked, subOf(GONE), inputOf(GONE)?.disabled], [GONE, true, 'Forge does not list it', false]);
check('a ticked row of a family this WebUI cannot run: greyed, ticked, open to untick',
      [inputOf(QWEN)?.closest('.mm-pick-row')?.classList.contains('mm-pick-greyed'), inputOf(QWEN)?.checked,
       inputOf(QWEN)?.disabled], [true, true, false]);
const sortBox = () => win()?.querySelector('.mm-pick-line [data-action="resources.pickSort"]');
/** The Sort box set, as a person picks an order: its change. */
function sortTo(value) {
    const box = sortBox();
    if (!box) return false;
    box.value = value;
    press(box);
    return true;
}
const activeTab = () => win()?.querySelector('.mm-pick-tab.active')?.textContent.trim();
check('#415: the window opens on the order the dialog kept - by base model, the name Forge does not list still first',
      [sortBox()?.value, sortBox()?.disabled, inputs().map((i) => i.value)],
      ['base', false, [GONE, FLUX, QWEN, DREAM, ANIME, PHOTO]]);
search('dev');
sortTo('file');
check('    another order chosen here: kept for both, the search, the tab and the ticks as they were',
      [localStorage.getItem('mm-pick-sort'), win()?.querySelector('.mm-pick-search')?.value, activeTab(),
       inputs().map((i) => i.value)], ['file', 'dev', 'All 1', [FLUX]]);
search('');
sortTo('size');
check('    Largest first: the name Forge does not list, which has no size, still first',
      inputs().map((i) => i.value), [GONE, FLUX, PHOTO, QWEN, ANIME, DREAM]);
sortTo('file');
check('    the rows by file name, the ticks on the same rows', [inputs().map((i) => i.value), ticked()],
      [[GONE, ANIME, DREAM, FLUX, PHOTO, QWEN], [GONE, ANIME, QWEN]]);
// Untick all (#415): every tick gone, the greyed row's box disabled again as a full draw draws it,
// Use these off, and the column asks nothing with nothing ticked.
const untickHere = () => win()?.querySelector('.mm-pick-line [data-action="resources.untickAll"]');
const runsBeforeUntick = runsAsked.length;
const rowsBeforeUntick = win()?.querySelector('.mm-pick-rows');
if (untickHere()) press(untickHere());
await new Promise((resolve) => setTimeout(resolve, 20));
check('#415: Untick all: no tick left, the rows not drawn again, the greyed row\'s box disabled again; 0 ticked, '
      + 'Use these off saying why, nothing asked; Untick all off, the Ticked tab at 0',
      [ticked(), win()?.querySelector('.mm-pick-rows') === rowsBeforeUntick, inputOf(QWEN)?.disabled, tickedText(),
       use()?.disabled, use()?.title, runsAsked.length - runsBeforeUntick, untickHere()?.disabled,
       win()?.querySelector('.mm-pick-tab[data-family="ticked"]')?.textContent.trim()],
      [[], true, true, '0 ticked', true, 'Tick two checkpoints or more. To generate with one, press Leave and use Generate.',
       0, true, 'Ticked 0']);
// Select all (#415): All's rows by file name, but not the name Forge does not list - unticked, it is
// there only to be let go - nor the greyed one; the column asked once, with all of them.
const selectHere = () => win()?.querySelector('.mm-pick-line [data-action="resources.pickAll"]');
const runsBeforeAll = runsAsked.length;
if (selectHere()) press(selectHere());
await waitFor('the column asked', () => runsAsked.length > runsBeforeAll);
check('#415: Select all in All: every row it can tick, by file name; not the one Forge does not list, not the greyed; '
      + 'the column asked once, with them; Use these on', [ticked(), runsAsked.length - runsBeforeAll, runsAsked.at(-1)?.names,
       tickedText(), use()?.disabled], [[ANIME, DREAM, FLUX, PHOTO], 1, [ANIME, DREAM, FLUX, PHOTO], '4 ticked', false]);
if (untickHere()) press(untickHere());
tick(ANIME, true);
// By base model again, Dream shows before Anime: the run order below is the ticks', not the rows'.
sortTo('base');
tick(GONE, false);
tick(QWEN, false);
tick(DREAM, true);
use()?.click();
check('both let go, the list is what is ticked', severalList()?.names, [ANIME, DREAM]);
localStorage.removeItem('mm-pick-sort');

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
await waitFor('its line', settled);
check('outside the mode, what the loaded one runs with is asked once the list has ticked it, with no source',
      [runsAsked.at(-1), lines().length], [{ names: [PHOTO], source: null }, 1]);
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
