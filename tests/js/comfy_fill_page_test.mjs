// Civitai images filled from their ComfyUI workflows (#232): the Fill notice
// in the page. On a library from before 0.81.5 the server names the repair;
// its note's Review opens a window that says what Fill changes, Fill starts
// the server's job and shows where it is, Close leaves it running, and once
// done the window says what changed, and the note and the settings window's
// line go. A failure says why and offers Fill again. The repair follows two
// tabs, and stops only with the last. The server's side: repair_comfy_fill_test.py;
// the Civitai Images tab alone: comfy_fill_gallery_test.mjs.
import { bootPage, checker, mountTab, press, sharedModule, tabMarkup, tabsAnswer, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// The Civitai Images tab beside it: Fill follows both, and stops with the last.
document.body.insertAdjacentHTML('beforeend', tabMarkup('model_manager/ui/tab_gallery.py'));
const { check, waitFor, done } = checker();

// The server's Fill, as the suite moves it along.
let state = { state: 'idle' };
let needed = true;
let startAnswer = () => ({ success: true, fill: (state = { state: 'running', step: 'finding', done: 0, total: null,
                                                           read: 0, gained: 0, prompts: 0, levels: 0, covers: 0 }) });
const asked = [];
const started = [];
let heldGet = null;      // the next question about Fill, held until the suite lets it go
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [],
                       tabs: { ...tabsAnswer({ model_manager: true }), gallery: { on: true, built: true } } });
    }
    if (path === '/model-manager/repairs') {
        return reply({ success: true, repairs: { comfy_fill: { count: 1, tab: 'comfy_fill',
                                                               tabs: ['model_manager', 'gallery'] } } });
    }
    if (path === '/model-manager/repairs/comfy-fill') {
        if (heldGet) {
            const hold = heldGet;
            heldGet = null;
            await hold;
        }
        return reply({ success: true, needed, newer: false, fill: state });
    }
    if (path === '/model-manager/repairs/comfy-fill/start') {
        started.push(init.method);
        return reply(startAnswer());
    }
    if (path === '/model-manager/notes') {
        return reply({ success: true, notes: [{ id: 'comfy-fill-0-81-6', version: '0.81.6', kind: 'action',
            tabs: ['model_manager', 'gallery'], title: 'Civitai images filled from their ComfyUI workflows', text: 't',
            action: { id: 'repair', label: 'Review', repair: 'comfy_fill' } }] });
    }
    return reply({ success: true, models: [], images: [], total: 0 });
});

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const offered = () => globalThis.__mmOffered?.has('repairs.comfy_fill');
await waitFor('the repair to start', offered);
check('the Model Manager and the Civitai Images tab on: Fill\'s window offered, started once',
      [offered(), asked.filter((p) => p === '/model-manager/repairs').length], [true, 1]);
// Never started, nothing below can be pressed: the failure said, the suite ended.
if (!offered()) done();

// ------------------------------------------------------- the note's button
await waitFor('the note', () => document.querySelector('#mm_notes [data-note-action="repair"]'));
const noteButton = document.querySelector('#mm_notes [data-note-action="repair"]');
check('the note\'s Review, naming Fill', [noteButton?.textContent.trim(), noteButton?.dataset.noteRepair],
      ['Review', 'comfy_fill']);

// ----------------------------------------------- the settings window's place
const slot = document.createElement('div');
slot.dataset.repairsSlot = '';
document.body.appendChild(slot);
window.dispatchEvent(new window.CustomEvent('mm-upkeep-drawn', { detail: { slot } }));
const line = () => slot.querySelector('[data-repair="comfy_fill"]');
check('its line in the database box\'s place for repairs, with Review',
      [line()?.querySelector('.mm-upkeep-line')?.textContent, line()?.querySelector('button')?.dataset.action],
      ['Civitai images can be filled from their ComfyUI workflows', 'repairs.comfy_fill']);

// ------------------------------------------------------- the window, before
noteButton?.dispatchEvent(new window.Event('click', { bubbles: true }));
const dialog = () => document.querySelector('dialog.mm-repair');
await waitFor('the window', () => dialog()?.querySelector('[data-repair-fill]'));
const fillButton = () => dialog()?.querySelector('[data-repair-fill]');
const text = () => [...(dialog()?.querySelectorAll('.mm-question-message, .mm-question-note') || [])]
    .map((p) => p.textContent.replace(/\s+/g, ' ').trim());
check('before the press: what Fill does, in sentences; Fill and Close',
      [text()[0]?.startsWith('Some Civitai images hold the ComfyUI workflow'),
       text().some((t) => t.includes('which can hide it under a lower NSFW maximum')),
       text().some((t) => t.includes('nothing is deleted')),
       text().some((t) => t.startsWith('If two WebUIs share this database, update the extension in the other one first')),
       fillButton()?.textContent, fillButton()?.disabled, Boolean(dialog().querySelector('[data-repair-close]'))],
      [true, true, true, true, 'Fill', false, true]);
check('and no count: opening reads nothing whole', /\d/.test(text().join(' ')), false);

const closeWindow = () => dialog()?.querySelector('[data-repair-close]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
const note = () => document.querySelector('#mm_notes [data-note="comfy-fill-0-81-6"]');
const lineText = () => line()?.querySelector('.mm-upkeep-line')?.textContent;
closeWindow();

// ------------------------------------------------------- a run that failed
state = { state: 'failed', step: 'filling', error: 'database is locked.', done: 200, total: 5098 };
(await sharedModule('calls.mjs')).call('repairs.comfy_fill');
await waitFor('the failure', () => text()[0]?.startsWith('Fill stopped'));
check('a failed run: why, Fill offered again, the note and the line kept',
      [text()[0], fillButton()?.disabled, Boolean(note()), lineText()],
      ['Fill stopped: database is locked. What it filled is kept; press Fill to go on with the rest.', false, true,
       'Civitai images can be filled from their ComfyUI workflows']);

// ------------------------------------------------------- a press refused
startAnswer = () => ({ success: false, newer: true,
                       error: 'A newer copy of the extension sharing this database has filled it already. Update this copy.' });
fillButton()?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the refusal', () => text()[0]?.startsWith('Fill was not started'));
check('a press refused by a newer copy: why, in one sentence, and no Fill to press again',
      [text()[0], Boolean(fillButton())],
      ['Fill was not started: A newer copy of the extension sharing this database has filled it already. Update this copy.',
       false]);
closeWindow();

// ------------------------------------------------------- a press held at the server
// Closed and opened again while the press is out: the window's own question,
// read by the server before its job began, answers "idle" - which must not
// put Fill back to be pressed again.
state = { state: 'idle' };
(await sharedModule('calls.mjs')).call('repairs.comfy_fill');
await waitFor('the window', () => fillButton() && !fillButton().disabled);
let release;
const heldAnswer = new Promise((resolve) => { release = resolve; });
startAnswer = () => heldAnswer;
fillButton()?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the press', () => started.length === 2);
closeWindow();
const askedHeld = asked.length;
(await sharedModule('calls.mjs')).call('repairs.comfy_fill');
await waitFor('the window\'s own question answered', () => asked.slice(askedHeld).includes('/model-manager/repairs/comfy-fill'));
await new Promise((resolve) => setTimeout(resolve, 100));
check('a press still out: an older "idle" answer taken in the meantime does not offer Fill again',
      [text()[0], fillButton()?.disabled], ['Finding the images that hold a workflow...', true]);
release({ success: false, newer: false, error: 'held, then refused' });
await waitFor('the press\'s own answer', () => text()[0]?.startsWith('Fill was not started'));
closeWindow();

// ------------------------------------------------------- a press unanswered
state = { state: 'idle' };
(await sharedModule('calls.mjs')).call('repairs.comfy_fill');
await waitFor('the window', () => fillButton() && !fillButton().disabled);
startAnswer = () => {
    // The server took it and started, the answer lost on the way.
    state = { state: 'running', step: 'finding', done: 0, total: null, read: 0, gained: 0, prompts: 0, levels: 0, covers: 0 };
    throw new Error('Failed to fetch');
};
let letGo;
heldGet = new Promise((resolve) => { letGo = resolve; });
fillButton()?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the press', () => started.length === 3);
await waitFor('the lost answer said', () => text()[0]?.startsWith('The server did not answer'));
check('a press unanswered: said so - Fill may be running - not told as a failure', text()[0],
      'The server did not answer the press. Fill may be running: this window asks the server again.');
letGo();
await waitFor('the answer asked for again', () => lineText()?.endsWith('finding them...'));
check('a press unanswered: the server asked again, and its answer shown - Fill running, Fill disabled',
      [text()[0], fillButton()?.disabled], ['Finding the images that hold a workflow...', true]);
check('the settings window\'s line before Fill reads: no count yet', lineText(),
      'Filling Civitai images from their workflows: finding them...');

// ------------------------------------------------------- running
state = { state: 'running', step: 'filling', done: 1200, total: 5098, read: 1100, gained: 120, prompts: 12,
          levels: 0, covers: 0 };
await waitFor('its progress', () => text()[0]?.startsWith('Reading'));
check('while it fills: how far, and how many changed so far',
      text()[0], 'Reading 1,200 of 5,098 images that may hold a workflow. 120 images have changed so far.');
check('the settings window\'s line while it reads', lineText(), 'Filling Civitai images from their workflows: 1,200 of 5,098');
const closeButton = dialog().querySelector('[data-repair-close]');
state = { ...state, done: 1400 };
await waitFor('its next count', () => text()[0]?.startsWith('Reading 1,400'));
check('its count moves on, its buttons kept (the focus on Close not lost)',
      dialog().querySelector('[data-repair-close]') === closeButton, true);
closeWindow();
check('Close leaves it running: the window gone, nothing more posted', [dialog(), started.length], [null, 3]);
press(line().querySelector('button'));
await waitFor('the window again', () => text()[0]?.startsWith('Reading'));
check('opened again while it runs: on its progress, Fill disabled', [text()[0]?.startsWith('Reading 1,400'),
                                                                     fillButton()?.disabled], [true, true]);

// ------------------------------------------------------- done
state = { state: 'done', step: 'filling', done: 5098, total: 5098, read: 4879, gained: 531, prompts: 54, levels: 0,
          covers: 0 };
needed = false;
await waitFor('the end', () => text()[0]?.endsWith('None is judged at another NSFW level.'));
check('done: what changed, in sentences', text()[0],
      '531 images changed, 54 of them gaining a prompt from the workflow. None is judged at another NSFW level.');
check('the note and the settings window\'s line gone', [note(), line()], [null, null]);
const askedDone = asked.length;
await new Promise((resolve) => setTimeout(resolve, 1500));
check('and it stops asking where Fill is',
      asked.slice(askedDone).filter((p) => p === '/model-manager/repairs/comfy-fill').length, 0);
closeWindow();

// ------------------------------------------------------- filled elsewhere
// The other WebUI sharing the database filled it: nothing to report here, nothing to press.
state = { state: 'idle' };
(await sharedModule('calls.mjs')).call('repairs.comfy_fill');
await waitFor('the window', () => text()[0]?.includes('already'));
check('filled elsewhere: said so, and no Fill', [text()[0], Boolean(fillButton())],
      ['The stored images are filled from their workflows already.', false]);
closeWindow();

// ----------------------------------------------- stopped with the last of its tabs
const loading = await sharedModule('loading.mjs');
loading.stopTab('gallery');
check('the Civitai Images tab stopped, the Model Manager still running: Fill keeps running',
      [loading.available('gallery'), loading.available('modelManager'), offered()], [false, true, true]);
loading.stopTab('modelManager');
check('the last of its tabs stopped: Fill stops, its window no longer offered', offered(), false);

done();
