// A repair in the page (#241): the loading module asks which repairs the
// library needs once the tabs have started, imports a repair's script only
// when the server names it, and stops it with its tab. Generations recorded
// twice: its line in the settings window's place for repairs, the note's
// Review, and its window - every early copy ticked to begin with, Remove
// sending only the ticked ones, Cancel nothing. The server's side:
// generations_review_test.py; a library that needs none: repairs_none_test.mjs.
import { bootPage, checker, escape, mountTab, press, sharedModule, tabsAnswer, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const ROWS = [
    { id: 41, kept: 42, created_at: '2026-10-22T12:24:09', mode: 'txt2img', batch_count: 2, images: 2,
      kept_images: 4, same_press: 1, prompt: 'a lighthouse', image_id: 7, hidden_level: null },
    { id: 31, kept: 33, created_at: '2026-10-22T12:20:00', mode: 'txt2img', batch_count: 3, images: 2,
      kept_images: 6, same_press: 2, prompt: null, image_id: null, hidden_level: 'X' },
];
let listed = ROWS;
// LoRA weights saved as 1 (#392): the second repair, its own window.
const LORA_ROWS = [
    { id: 51, created_at: '2026-11-09T21:14:00', mode: 'txt2img', batch_count: 2, images: 4, prompt: 'a portrait',
      image_id: 9, hidden_level: null, changes: [{ name: 'example_style', from: 1, te: 0.7, unet: 0.7 },
                                                { name: 'scheduled', from: 1, te: null, unet: null }] },
    { id: 52, created_at: '2026-11-08T10:02:00', mode: 'txt2img', batch_count: 1, images: 1, prompt: null,
      image_id: null, hidden_level: 'X', changes: [{ name: 'detail', from: 1, te: 1, unet: 0.4 }] },
    { id: 53, created_at: '2026-11-07T09:00:00', mode: 'img2img', batch_count: 1, images: 2,
      prompt: 'a <b data-mm-marker>bold</b> prompt',
      image_id: 10, hidden_level: null, changes: [{ name: '<i data-mm-marker></i>', from: 1, te: 0.5, unet: 0.5 }] },
];
let loraListed = LORA_ROWS;
const corrections = [];
// Correct's answer: held until the suite lets it go, or answered at once.
let correctAnswer = () => ({ success: true, corrected: [51], skipped: [{ id: 53, why: 'it is already gone' }] });
let held = null;
const asked = [];
const posted = [];
const browsed = [];      // the Generations tab's searches, as it asked for them
globalThis.fetch = withGalleryPages(async (url, init = {}) => {
    const href = String(url);
    const path = href.replace(/^https?:\/\/[^/]+/, '').replace(/\?.*/, '');
    asked.push(path);
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (path === '/model-manager/ui-options') {
        return reply({ success: true, samplers: [], schedulers: [], tabs: tabsAnswer({ generations: true }) });
    }
    if (path === '/model-manager/repairs') {
        return reply({ success: true, repairs: { recorded_twice: { count: 2, tab: 'generations' },
                                                 lora_weights: { count: 3, tab: 'generations' } } });
    }
    if (path === '/model-manager/repairs/recorded-twice') return reply({ success: true, early: listed });
    if (path === '/model-manager/repairs/recorded-twice/remove') {
        const ids = new URLSearchParams(init.body).get('ids');
        posted.push(ids);
        return reply({ success: true, removed: ids.split(',').map(Number), skipped: [] });
    }
    if (path === '/model-manager/repairs/lora-weights') return reply({ success: true, generations: loraListed });
    if (path === '/model-manager/repairs/lora-weights/correct') {
        const ids = new URLSearchParams(init.body).get('ids');
        corrections.push(ids);
        if (held) {
            const wait = held;
            held = null;
            const answer = await wait;
            if (answer instanceof Error) throw answer;
            return reply(answer);
        }
        return reply(correctAnswer());
    }
    if (path === '/model-manager/generations/browse') browsed.push(new URL(href).searchParams.get('search'));
    if (path === '/model-manager/notes') {
        return reply({ success: true, notes: [{ id: 'recorded-twice-0-70-5', version: '0.70.5', kind: 'action',
            tabs: ['generations'], title: 'Some generations were recorded twice', text: 't',
            action: { id: 'repair', label: 'Review', repair: 'recorded_twice' } },
            { id: 'lora-weights-0-78-10', version: '0.78.10', kind: 'action', tabs: ['generations'],
              title: 'LoRA weights saved as 1', text: 't',
              action: { id: 'repair', label: 'Review', repair: 'lora_weights' } }] });
    }
    return reply({ success: true, generations: [], images: [], total: 0 });
});

await bootPage();
document.dispatchEvent(new window.Event('DOMContentLoaded'));
const offered = () => globalThis.__mmOffered?.has('repairs.recorded_twice');
await waitFor('the repair to start', offered);
check('the page asked which repairs the library needs, once the tab had started',
      asked.filter((p) => p === '/model-manager/repairs').length, 1);
check('and started the one named: its window offered', offered(), true);

// ------------------------------------------------------- the note's button
await waitFor('the note', () => document.querySelector('#gen_notes [data-note-action="repair"]'));
const noteButton = document.querySelector('#gen_notes [data-note-action="repair"]');
check('the note\'s Review is drawn once the repair has started, naming it',
      [noteButton?.textContent.trim(), noteButton?.dataset.noteRepair], ['Review', 'recorded_twice']);

// ----------------------------------------------- the settings window's place
const slot = document.createElement('div');
slot.dataset.repairsSlot = '';
document.body.appendChild(slot);
window.dispatchEvent(new window.CustomEvent('mm-upkeep-drawn', { detail: { slot } }));
const line = () => slot.querySelector('[data-repair="recorded_twice"]');
check('its line in the database box\'s place for repairs',
      [line()?.querySelector('.mm-upkeep-line')?.textContent, line()?.querySelector('button')?.dataset.action],
      ['Recorded twice: 2 generations', 'repairs.recorded_twice']);

// ------------------------------------------------------------- the window
noteButton.dispatchEvent(new window.Event('click', { bubbles: true }));
const dialog = () => document.querySelector('dialog.mm-repair');
await waitFor('the list', () => dialog()?.querySelectorAll('[data-repair-id]').length === 2);
const boxes = () => [...dialog().querySelectorAll('[data-repair-id]')];
const remove = () => dialog().querySelector('[data-repair-remove]');
const all = () => dialog().querySelector('[data-repair-all]');
check('the note\'s Review opens the window: every early copy, ticked to begin with',
      boxes().map((b) => [b.dataset.repairId, b.checked]), [['41', true], ['31', true]]);
check('Remove says how many, Select all ticked',
      [remove().textContent, remove().disabled, all().checked, all().indeterminate], ['Remove 2', false, true, false]);
const rows = [...dialog().querySelectorAll('.mm-repair-row')];
check('a row: a preview of its first image, when, its prompt, its images and the kept generation\'s',
      [rows[0].querySelector('img')?.getAttribute('src'), rows[0].querySelector('.mm-repair-prompt')?.textContent,
       rows[0].querySelector('.mm-repair-text > span:last-child')?.textContent],
      ['/model-manager/generations/images/7/thumb', 'a lighthouse', '2 images, all in the generation after it, which has 4']);
check('one the Generations tab would hide: its level in the picture\'s place, its prompt hidden too',
      [rows[1].querySelector('img'), rows[1].querySelector('.mm-repair-hidden')?.textContent,
       rows[1].querySelector('.mm-repair-prompt')?.textContent],
      [null, 'X', 'Rated X: hidden, as the Generations tab hides it']);
check('one of a chain says so, with its batch count',
      [rows[1].querySelector('.mm-repair-when')?.textContent.includes('batch count 3'),
       rows[1].querySelector('.mm-repair-text > span:last-child')?.textContent],
      [true, '2 images, all in the last generation of the press, which has 6']);

const untick = (box) => { box.checked = false; box.dispatchEvent(new window.Event('change', { bubbles: true })); };
untick(boxes()[1]);
check('one unticked: the count, Remove\'s number, Select all half',
      [dialog().querySelector('[data-repair-count]').textContent, remove().textContent, all().indeterminate],
      ['1 of 2 ticked', 'Remove 1', true]);
untick(boxes()[0]);
check('none ticked: Remove greyed, saying why', [remove().disabled, remove().title], [true, 'Nothing ticked']);
all().checked = true;
all().dispatchEvent(new window.Event('change', { bubbles: true }));
check('Select all ticks every row', boxes().map((b) => b.checked), [true, true]);
untick(boxes()[1]);

remove().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the answer', () => dialog()?.querySelector('[data-repair-close]'));
check('Remove sends only the ticked one', posted, ['41']);
check('and says what happened', dialog().querySelector('.mm-question-message')?.textContent, 'Removed 1.');
check('the line counts what is left', line()?.querySelector('.mm-upkeep-line')?.textContent,
      'Recorded twice: 1 generation');
dialog().querySelector('[data-repair-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('Close closes it', dialog(), null);

// -------------------------------------------------- Cancel removes nothing
listed = ROWS.slice(1);
press(line().querySelector('button'));
await waitFor('the list again', () => dialog()?.querySelectorAll('[data-repair-id]').length === 1);
dialog().querySelector('[data-repair-cancel]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('opened from its line, then Cancel: closed, nothing sent', [dialog(), posted], [null, ['41']]);

// -------------------------- View all: the Generations tab, searching them all
listed = ROWS;
press(line().querySelector('button'));
await waitFor('the list for View all', () => dialog()?.querySelectorAll('[data-repair-id]').length === 2);
untick(boxes()[0]);
browsed.length = 0;
dialog().querySelector('[data-repair-view]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the search', () => browsed.length);
check('View all, one unticked: the window closes, the Generations tab searches every one listed and each kept',
      [dialog(), document.getElementById('gen_search')?.value, browsed.at(-1)],
      [null, 'generation:31,33,41,42', 'generation:31,33,41,42']);
check('and nothing was removed', posted, ['41']);

// ---------------------------- the server's counts, drawn as numbers (S2)
// A marker shows a fault: an element, or an attribute added. Nothing runs.
const ODD = '2" data-mm-marker="1 <i data-mm-marker></i>';
listed = [{ ...ROWS[1], batch_count: ODD, images: ODD, kept_images: ODD }];
press(line().querySelector('button'));
await waitFor('the odd row', () => dialog()?.querySelectorAll('[data-repair-id]').length === 1);
check('a row\'s counts that are not numbers draw nothing as markup',
      dialog().querySelectorAll('[data-mm-marker]').length, 0);
dialog().querySelector('[data-repair-cancel]').dispatchEvent(new window.Event('click', { bubbles: true }));

// ------------------------------------------- LoRA weights saved as 1 (#392)
const loraOffered = () => globalThis.__mmOffered?.has('repairs.lora_weights');
check('the second repair named is started too: its window offered', loraOffered(), true);
// The notes are a pile, one shown at a time: its note is the second.
document.querySelector('#gen_notes [data-note-step="1"]')?.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('its note', () => document.querySelector('#gen_notes [data-note-repair="lora_weights"]'));
const loraNote = document.querySelector('#gen_notes [data-note-repair="lora_weights"]');
check('its note\'s Review', loraNote?.textContent.trim(), 'Review');
const loraLine = () => slot.querySelector('[data-repair="lora_weights"]');
window.dispatchEvent(new window.CustomEvent('mm-upkeep-drawn', { detail: { slot } }));
check('its line in the database box\'s place for repairs, beside the other',
      [loraLine()?.querySelector('.mm-upkeep-line')?.textContent, loraLine()?.querySelector('button')?.dataset.action],
      ['LoRA weights saved as 1: 3 generations', 'repairs.lora_weights']);
loraNote.dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('its list', () => dialog()?.querySelectorAll('[data-repair-id]').length === 3);
const correctButton = () => dialog().querySelector('[data-repair-correct]');
const loraStatus = () => dialog()?.querySelector('[data-repair-status]');
check('the note\'s Review opens its window: every one ticked, Correct counting them',
      [boxes().map((b) => b.checked), correctButton().textContent, dialog().querySelector('h3')?.textContent],
      [[true, true, true], 'Correct 3', 'LoRA weights saved as 1']);
const loraRows = [...dialog().querySelectorAll('.mm-repair-row')];
check('a row: its first image, when and in which tab, its prompt, its images and each LoRA\'s change',
      [loraRows[0].querySelector('img')?.getAttribute('src'),
       loraRows[0].querySelector('.mm-repair-when')?.textContent.includes('txt2img, batch count 2'),
       loraRows[0].querySelector('.mm-repair-prompt')?.textContent,
       loraRows[0].querySelector('.mm-repair-text > span:last-child')?.textContent],
      ['/model-manager/generations/images/9/thumb', true, 'a portrait',
       '4 images: example_style 1 → 0.7; scheduled 1 → no fixed weight']);
check('both weights named where they differ; a hidden one hidden as the Generations tab hides it',
      [loraRows[1].querySelector('.mm-repair-text > span:last-child')?.textContent, loraRows[1].querySelector('img'),
       loraRows[1].querySelector('.mm-repair-hidden')?.textContent,
       loraRows[1].querySelector('.mm-repair-prompt')?.textContent],
      ['1 image: detail 1 → text encoder 1, UNet 0.4', null, 'X', 'Rated X: hidden, as the Generations tab hides it']);
check('a LoRA\'s name and a prompt drawn as text, never markup',
      [dialog().querySelectorAll('[data-mm-marker]').length, loraRows[2].querySelector('.mm-repair-prompt')?.textContent],
      [0, 'a <b data-mm-marker>bold</b> prompt']);
const loraAll = () => dialog().querySelector('[data-repair-all]');
untick(boxes()[1]);
check('one unticked: the count, Correct\'s number, Select all half',
      [dialog().querySelector('[data-repair-count]').textContent, correctButton().textContent, loraAll().indeterminate],
      ['2 of 3 ticked', 'Correct 2', true]);
untick(boxes()[0]);
untick(boxes()[2]);
check('none ticked: Correct greyed, saying why', [correctButton().disabled, correctButton().title], [true, 'Nothing ticked']);
loraAll().checked = true;
loraAll().dispatchEvent(new window.Event('change', { bubbles: true }));
check('Select all ticks every row', boxes().map((b) => b.checked), [true, true, true]);
// Ticked by hand where it did not, so what follows still runs.
boxes().filter((b) => !b.checked).forEach((b) => { b.checked = true; b.dispatchEvent(new window.Event('change', { bubbles: true })); });
untick(boxes()[1]);

// Held: while it works the window keeps itself and its controls still.
let release;
held = new Promise((resolve) => { release = resolve; });
correctButton().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the press', () => corrections.length === 1);
escape();
check('while it corrects: its line says so, every control off, and Esc does not close it',
      [loraStatus()?.textContent, [...(dialog()?.querySelectorAll('input, button') || [])].every((c) => c.disabled),
       dialog() !== null],
      ['Correcting 2...', true, true]);
// Closed by Esc, nothing after it can be read: the failure is said, and the suite ends.
if (!dialog()) done();
release({ success: false, error: 'database is locked' });
await waitFor('the failure', () => loraStatus()?.classList.contains('mm-question-error'));
check('the server\'s failure: said, nothing changed, and the controls back',
      [loraStatus().textContent, correctButton().disabled, boxes().map((b) => b.checked)],
      ['Could not correct them: database is locked. Nothing was changed.', false, [true, false, true]]);
held = Promise.resolve(new Error('Failed to fetch'));
correctButton().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the lost answer', () => corrections.length === 2 && loraStatus()?.textContent.startsWith('Could not hear'));
check('an answer lost on the way: it may have finished, so it says to look again',
      loraStatus().textContent,
      'Could not hear back from the server: Failed to fetch. It may have finished: close this and press Review again to see what is left.');
const askedBefore = asked.length;
correctButton().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('its answer', () => dialog()?.querySelector('[data-repair-close]'));
check('Correct sends only the ticked ones, each time', corrections, ['51,53', '51,53', '51,53']);
check('and says what happened, naming a skipped one by when it was made, and why',
      [...dialog().querySelectorAll('.mm-question-message')].map((p) => p.textContent),
      ['Corrected 1 generation.', 'The generation of 7 Nov 2026, 09:00 was skipped: it is already gone.']);
check('its line counts what is left', loraLine()?.querySelector('.mm-upkeep-line')?.textContent,
      'LoRA weights saved as 1: 1 generation');
await waitFor('the Generations tab redrawn', () => asked.slice(askedBefore).some((p) => p.startsWith('/model-manager/generations/')));
check('and the Generations tab drawn again', asked.slice(askedBefore).some((p) => p.startsWith('/model-manager/generations/')), true);
dialog().querySelector('[data-repair-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
press(loraLine().querySelector('button'));
await waitFor('its list again', () => dialog()?.querySelectorAll('[data-repair-id]').length === 3);
dialog().querySelector('[data-repair-cancel]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('opened from its line, then Cancel: closed, nothing more sent', [dialog(), corrections.length], [null, 3]);
press(loraLine().querySelector('button'));
await waitFor('its list for View all', () => dialog()?.querySelectorAll('[data-repair-id]').length === 3);
untick(boxes()[0]);
browsed.length = 0;
dialog().querySelector('[data-repair-view]').dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('its search', () => browsed.length);
check('View all, one unticked: the Generations tab searches every one listed',
      [dialog(), browsed.at(-1)], [null, 'generation:51,52,53']);
// The last one corrected: the line goes.
loraListed = LORA_ROWS.slice(1, 2);
correctAnswer = () => ({ success: true, corrected: [52], skipped: [] });
press(loraLine().querySelector('button'));
await waitFor('the last one', () => dialog()?.querySelectorAll('[data-repair-id]').length === 1);
correctButton().dispatchEvent(new window.Event('click', { bubbles: true }));
await waitFor('the last answer', () => dialog()?.querySelector('[data-repair-close]'));
check('none left: its line gone from the settings window', loraLine(), null);
dialog().querySelector('[data-repair-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
loraListed = [];
(await sharedModule('calls.mjs')).call('repairs.lora_weights');
await waitFor('the empty list', () => !dialog()?.textContent.includes('Looking for them'));
check('opened with none left: it says so', dialog().querySelector('.mm-question-message')?.textContent,
      'No generation holds LoRA weights saved as 1 any more.');
dialog().querySelector('[data-repair-close]').dispatchEvent(new window.Event('click', { bubbles: true }));
// Listed again, its line back: for the stop below to take away.
loraListed = LORA_ROWS;
(await sharedModule('calls.mjs')).call('repairs.lora_weights');
await waitFor('the list once more', () => dialog()?.querySelectorAll('[data-repair-id]').length === 3);
dialog().querySelector('[data-repair-cancel]').dispatchEvent(new window.Event('click', { bubbles: true }));
check('its line back while there are some', loraLine()?.querySelector('.mm-upkeep-line')?.textContent,
      'LoRA weights saved as 1: 3 generations');

// ----------------------------------------------- stopped with its tab
(await sharedModule('loading.mjs')).stopTab('generations');
check('the Generations tab stopped: the repairs stop too - their windows no longer offered, their lines gone',
      [offered(), line(), loraOffered(), loraLine()], [false, null, false, null]);

done();
