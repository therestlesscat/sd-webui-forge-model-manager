// A repair in the page (#241): the loading module asks which repairs the
// library needs once the tabs have started, imports a repair's script only
// when the server names it, and stops it with its tab. Generations recorded
// twice: its line in the settings window's place for repairs, the note's
// Review, and its window - every early copy ticked to begin with, Remove
// sending only the ticked ones, Cancel nothing. The server's side:
// generations_review_test.py; a library that needs none: repairs_none_test.mjs.
import { bootPage, checker, mountTab, press, sharedModule, tabsAnswer, withGalleryPages } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_generations.py');
const { check, waitFor, done } = checker();

const ROWS = [
    { id: 41, kept: 42, created_at: '2026-10-22T12:24:09', mode: 'txt2img', batch_count: 2, images: 2,
      kept_images: 4, same_press: 1, prompt: 'a lighthouse', image_id: 7, hidden_level: null },
    { id: 31, kept: 33, created_at: '2026-10-22T12:20:00', mode: 'txt2img', batch_count: 3, images: 2,
      kept_images: 6, same_press: 2, prompt: null, image_id: null, hidden_level: 'X' },
];
let listed = ROWS;
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
        return reply({ success: true, repairs: { recorded_twice: { count: 2, tab: 'generations' } } });
    }
    if (path === '/model-manager/repairs/recorded-twice') return reply({ success: true, early: listed });
    if (path === '/model-manager/repairs/recorded-twice/remove') {
        const ids = new URLSearchParams(init.body).get('ids');
        posted.push(ids);
        return reply({ success: true, removed: ids.split(',').map(Number), skipped: [] });
    }
    if (path === '/model-manager/generations/browse') browsed.push(new URL(href).searchParams.get('search'));
    if (path === '/model-manager/notes') {
        return reply({ success: true, notes: [{ id: 'recorded-twice-0-70-5', version: '0.70.5', kind: 'action',
            tabs: ['generations'], title: 'Some generations were recorded twice', text: 't',
            action: { id: 'repair', label: 'Review', repair: 'recorded_twice' } }] });
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

// ----------------------------------------------- stopped with its tab
(await sharedModule('loading.mjs')).stopTab('generations');
check('the Generations tab stopped: the repair stops too - its window no longer offered, its line gone',
      [offered(), line()], [false, null]);

done();
