// Notes to the user at the top of a tab (showNotes in shared/notes.mjs; the
// server's side: notes_test.py), as a pile: one note in full, what needs
// doing on top, the edges of the rest under it; its arrows step through
// them, a click on the edges spreads them into rows. Each note is coloured
// by its kind, with its button, if it has one, and Dismiss, which brings the
// next one up and which the server keeps for every browser. The Model
// Manager's "Sync once" note opens the sync dialog with "Read every file's
// header again" ticked.
import { readFileSync } from 'node:fs';
import { ROOT, checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, waitFor, done } = checker();

// As the server sends them: newest first.
const NOTES = [
    { id: 'database', version: '0.41.0', kind: 'warning', audience: 'update', tabs: ['model_manager'],
      title: 'This update changed the database', text: 'Update the other copy too.' },
    { id: 'pinned-tabs', version: '0.40.13', kind: 'feature', audience: 'everyone', tabs: ['model_manager'],
      title: 'Pin the models you come back to', text: 'Pinned ones get a tab.' },
    { id: 'reread-headers', version: '0.40.11', kind: 'action', audience: 'update', tabs: ['model_manager'],
      title: 'Sync once', text: 'Tick <b>Read every file\'s header again</b>.',
      action: { id: 'reread_headers', label: 'Open Sync' } },
    { id: 'generations-tab', version: '0.40.0', kind: 'feature', audience: 'everyone', important: true,
      tabs: ['model_manager'], title: 'Every image you generate, in one place', text: 'Read this.' },
];
const asked = [];
const dismissed = [];
globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const reply = (body) => ({ ok: true, json: async () => body });
    if (href.includes('/model-manager/notes/dismiss')) {
        dismissed.push(new URLSearchParams(String(init.body)).get('id'));
        return reply({ success: true });
    }
    if (href.includes('/model-manager/notes')) {
        asked.push(new URL(href, 'http://webui').searchParams.get('tab'));
        return reply({ success: true, notes: NOTES });
    }
    return reply({ success: true });
};

await import(`file:///${ROOT}/javascript/model_manager.mjs`);
// The other tabs import the shared module too - under the same version, so
// the same copy (#53): one click dismisses a note once.
await sharedModule('notes.mjs');
document.dispatchEvent(new window.Event('DOMContentLoaded'));

const panel = () => document.getElementById('mm_notes');
const notes = () => Array.from(panel()?.querySelectorAll('[data-note]') || []);
const top = () => notes()[0];
const click = (element) => element?.dispatchEvent(new window.Event('click', { bubbles: true }));
const count = () => panel().querySelector('.mm-note-count')?.textContent;
const steps = () => Array.from(panel().querySelectorAll('[data-note-step]')).map((b) => b.disabled);
const edges = () => panel().querySelectorAll('.mm-note-edge').length;
await waitFor('the notes', () => notes().length > 0, 6000);

check('the tab asks for its own notes', asked, ['model_manager']);
check('a pile: one note in full, the important one on top - headed so, whatever its kind or age',
      [notes().map((n) => n.dataset.note), top().querySelector('strong')?.textContent, count(), edges()],
      [['generations-tab'], '[Important] Every image you generate, in one place', '1 of 4', 2]);
click(panel().querySelector('[data-note-step="1"]'));
check('then what needs doing, then warnings, then features', count(), '2 of 4');
check('coloured by its kind, with its mark, its title and version',
      [top().className, top().querySelector('.mm-banner-icon')?.textContent,
       top().querySelector('strong')?.textContent, top().querySelector('.mm-note-version')?.textContent],
      ['mm-banner mm-note mm-note-action', '!', 'Sync once', '0.40.11']);
check('its text as text, never markup', [top().querySelector('.mm-banner-note b'),
      top().querySelector('.mm-banner-note')?.textContent], [null, 'Tick <b>Read every file\'s header again</b>.']);
check('the arrows\' room as a pile of 4 needs: one digit a side',
      panel().querySelector('.mm-note-steps')?.getAttribute('style'), '--mm-note-digits: 1');
check('its button, Dismiss, and the arrows',
      [Array.from(top().querySelectorAll('.mm-btn')).map((b) => b.textContent.trim()), steps()],
      [['Open Sync', 'Dismiss'], [false, false]]);

click(top().querySelector('[data-note-action]'));
check('which opens the sync dialog with "Read every file\'s header again" ticked, and the move not',
      [document.getElementById('mm_sync_dialog')?.style.display, document.getElementById('mm_sync_reread')?.checked,
       document.getElementById('mm_sync_move')?.checked],
      ['flex', true, false]);
click(document.getElementById('mm_sync_dialog_cancel'));

click(panel().querySelector('[data-note-step="1"]'));
check('› steps to the next note', [top().dataset.note, top().className, count()],
      ['database', 'mm-banner mm-note mm-note-warning', '3 of 4']);
click(panel().querySelector('[data-note-step="1"]'));
check('to the last, whose next arrow is off', [top().dataset.note, count(), steps()],
      ['pinned-tabs', '4 of 4', [false, true]]);
click(panel().querySelector('[data-note-step="-1"]'));
click(panel().querySelector('[data-note-step="-1"]'));
click(panel().querySelector('[data-note-step="-1"]'));
check('and ‹ back to the first, whose back arrow is off', [top().dataset.note, count(), steps()],
      ['generations-tab', '1 of 4', [true, false]]);
click(panel().querySelector('[data-note-step="1"]'));

click(panel().querySelector('.mm-note-edge'));
check('a click on the edges spreads the pile into rows, with a way back',
      [notes().map((n) => n.dataset.note), edges(), !!panel().querySelector('[data-note-step]'),
       panel().querySelector('.mm-note-gather')?.textContent.trim()],
      [['generations-tab', 'reread-headers', 'database', 'pinned-tabs'], 0, false, 'Pile them up']);
check('each row keeping the arrows\' room, empty, so its Dismiss is where the pile\'s was',
      notes().map((n) => Array.from(n.querySelector('.mm-note-buttons').children).slice(-2).map((c) => c.className)),
      Array(4).fill(['mm-btn secondary mm-btn-small mm-note-dismiss', 'mm-note-steps mm-note-steps-none']));
click(panel().querySelector('.mm-note-gather'));
check('which piles them up again, where it was', [notes().length, count()], [1, '2 of 4']);

click(top().querySelector('[data-note-dismiss]'));
await waitFor('the dismissal', () => dismissed.length > 0);
await new Promise((resolve) => setTimeout(resolve, 50));
check('Dismiss takes the top note away, brings the next up, and tells the server - once',
      [top()?.dataset.note, count(), edges(), dismissed], ['database', '2 of 3', 2, ['reread-headers']]);

click(top().querySelector('[data-note-dismiss]'));
await new Promise((resolve) => setTimeout(resolve, 50));
click(panel().querySelector('[data-note-step="-1"]'));
click(top().querySelector('[data-note-dismiss]'));
await new Promise((resolve) => setTimeout(resolve, 50));
// The arrows stay, off, so Dismiss does not jump right by their width as
// the last-but-one note goes.
check('the last note left is still a pile, "1 of 1": its arrows there and off, no edges',
      [notes().map((n) => n.dataset.note), count(), steps(), edges()],
      [['pinned-tabs'], '1 of 1', [true, true], 0]);
{
    // No layout here: the widths that hold Dismiss still are the stylesheet's.
    const css = readFileSync(`${ROOT}/style.css`, 'utf8');
    const rule = (selector) => css.match(new RegExp(`(^|\\n)${selector.replace(/[.]/g, '\\.')} \\{([^}]*)\\}`))?.[2] || '';
    check('the arrows as wide as the count\'s digits, and Dismiss, each a set width - digits all one width',
          [/(^|[^-])width: calc\([^;]*var\(--mm-note-digits, 1\)/.test(rule('.mm-note-steps')),
           /(^|[^-])width: \d+px/.test(rule('.mm-note-step')),
           /(^|[^-])width: \d+px/.test(rule('.mm-note-dismiss')), /tabular-nums/.test(rule('.mm-note-count'))],
          [true, true, true, true]);
}

// Gradio redraws a tab's markup wholesale, emptying the panel: the notes are
// drawn again - without the ones dismissed.
panel().innerHTML = '';
const { showNotes } = await import(`file:///${ROOT}/javascript/shared/notes.mjs`);
showNotes('model_manager', 'mm_notes');
check('drawn again after a redraw, the dismissed ones not among them', notes().map((n) => n.dataset.note),
      ['pinned-tabs']);

done();
