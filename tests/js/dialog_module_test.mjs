// The dialog module (#292, shared/dialog.mjs): one way to show a dialog.
//
// The container, openDialog, gives any dialog the same behaviour: the
// browser's own <dialog> opened as modal, the last opened on top; the page
// held while any is open; Esc and a click beside it closing the top one
// alone, the key going no further; focus in on opening and back on closing.
// The caller can turn Esc or the click beside it off, check before closing,
// and be told how it closed. The question, ask, lays out its own content from
// parts given as data, buttons by type; the progress popup is a question with
// no buttons. Before it, a question was the browser's confirm() or one of
// four hand-built backdrops, none holding the page or moving focus.
//
// The <dialog> here is the harness's stand-in (linkedom has none): a stack
// for the top layer, and Esc delivered as a browser does (escape()).
import { checker, escape, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
const { check, done } = checker();
const { ask, openDialog, showProgress, dialogShowing } = await sharedModule('dialog.mjs');

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = (element) => element?.dispatchEvent(new window.Event('click', { bubbles: true }));
const top = () => window.__topLayer.at(-1) ?? null;
const held = () => document.body.classList.contains('mm-modal-open');
const button = (dialog, value) => dialog?.querySelector(`[data-value="${value}"]`);
// The page's own listener for Esc, as the viewer and the tabs have.
let pageHeardEscape = 0;
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') pageHeardEscape += 1; });
const opener = document.createElement('button');
opener.textContent = 'Opener';
document.body.appendChild(opener);

// ------------------------------------------------------------ an answer
let asking = ask({
    title: 'Retry 2 tasks?',
    message: ['Copies are queued at the end of the queue.', 'A second paragraph.'],
    list: [{ text: '#16 a <b>bold</b> prompt', detail: 'Some Extension' }, { text: 'plain' }],
    tick: { label: 'Also the images' },
    choices: [{ label: "The first run's seed", value: 'first', note: '~3 req', checked: true },
              { label: 'A random seed', value: 'random' }],
    note: ({ ticked, choice }) => `ticked ${ticked}, ${choice}`,
    buttons: [{ label: 'Cancel', value: false }, { label: 'Retry', value: true, type: 'primary' },
              { label: 'Wipe', value: 'wipe', type: 'danger' }, { label: 'Odd', value: 'odd', type: 'shiny' },
              { label: 'Restart', value: 'restart', disabled: true, reason: 'Cannot restart here' }],
});
let question = top();
check('a question is a modal <dialog>, on top, on the page\'s body',
      [question?.tagName, question?.open, question?.parentNode === document.body], ['DIALOG', true, true]);
check('its parts in order: title, message, list, tick box, choices, note, buttons',
      Array.from(question.querySelector('.mm-question-box').children).map((e) => e.className || e.tagName),
      ['H3', 'mm-question-message', 'mm-question-message', 'mm-question-list', 'mm-question-tick',
       'mm-question-choices', 'mm-question-note-slot', 'mm-dialog-buttons']);
check('the title names the dialog', question.getAttribute('aria-labelledby'), question.querySelector('h3')?.id);
check('a list line as text, with its detail beside it',
      [question.querySelector('.mm-question-list span')?.textContent, question.querySelector('.mm-question-list b'),
       question.querySelector('.mm-question-detail')?.textContent], ['#16 a <b>bold</b> prompt', null, 'Some Extension']);
check('a choice\'s side note', question.querySelector('.mm-question-choices .mm-dialog-cost')?.textContent, '~3 req');
check('buttons drawn by type; a type it does not know drawn as secondary',
      Array.from(question.querySelectorAll('[data-answer]')).map((b) => b.className),
      ['mm-btn secondary', 'mm-btn primary', 'mm-btn danger', 'mm-btn secondary', 'mm-btn secondary']);
check('a disabled button says why', [button(question, 'restart')?.disabled, button(question, 'restart')?.title],
      [true, 'Cannot restart here']);
check('focus on the first button', document.activeElement, button(question, 'false'));
check('the page held while it is open', held(), true);
check('and a dialog is showing', dialogShowing(), true);
check('the note as the tick box and the choice stand', question.querySelector('.mm-question-note')?.textContent,
      'ticked false, first');
question.querySelector('[data-tick]').checked = true;
question.querySelectorAll('[data-choice]')[1].checked = true;
question.querySelector('[data-tick]').dispatchEvent(new window.Event('change', { bubbles: true }));
check('drawn again as they change', question.querySelector('.mm-question-note')?.textContent, 'ticked true, random');
click(button(question, 'restart'));
check('a disabled button answers nothing', question.open, true);
click(button(question, 'true'));
check('pressed: the answer, with the tick box and the choice', await asking, { value: true, ticked: true, choice: 'random' });
check('closed and gone from the page; the page let go; no dialog showing',
      [question.isConnected, held(), dialogShowing()], [false, false, false]);

// A box ticked with no change event - as code, or a suite, sets it: the
// answer reads the page, not only what change events said.
asking = ask({ title: 'Delete?', tick: { label: 'Also the files' }, choices: [{ label: 'A', value: 'a' }, { label: 'B', value: 'b' }],
               buttons: [{ label: 'Delete', value: true }] });
question = top();
question.querySelector('[data-tick]').checked = true;
question.querySelectorAll('[data-choice]')[1].checked = true;
click(button(question, 'true'));
check('ticked and picked with no change event: the answer says so', await asking, { value: true, ticked: true, choice: 'b' });

// Esc, and a click beside it: no answer.
asking = ask({ title: 'Delete?', buttons: [{ label: 'Cancel', value: false }, { label: 'Delete', value: true }] });
pageHeardEscape = 0;
escape();
check('Esc answers nothing', await asking, null);
check('and the key stops at the dialog: the page\'s own listener never hears it', pageHeardEscape, 0);
asking = ask({ title: 'Delete?', buttons: [{ label: 'Cancel', value: false }] });
click(top());
check('a click beside it answers nothing', await asking, null);
asking = ask({ title: 'Delete?', outside: false, buttons: [{ label: 'Cancel', value: false }] });
question = top();
click(question);
check('outside: false - a click beside it leaves it open', question.open, true);
click(button(question, 'false'));
await asking;

// Focus named, and back to the opener.
opener.focus();
asking = ask({ title: 'Sync?', focus: true, buttons: [{ label: 'Cancel', value: false }, { label: 'Sync', value: true }] });
question = top();
check('the caller names the button that takes focus', document.activeElement, button(question, 'true'));
escape();
await asking;
check('closed, focus goes back to what opened it', document.activeElement, opener);

// Told the answer as it closes, before the promise.
const order = [];
asking = ask({ title: 'Later?', buttons: [{ label: 'Later', value: 'later' }],
               answered: (answer) => order.push(`answered ${answer?.value}`) });
asking.then(() => order.push('resolved'));
click(button(top(), 'later'));
order.push('after the click');
await asking;
check('answered runs as it closes, before anything else; the promise after',
      order, ['answered later', 'after the click', 'resolved']);

// Redrawn while open: its parts changed, the button with focus keeps it.
asking = ask({ title: 'Restart or reload', message: 'The Queue is turned off.',
               buttons: [{ label: 'Reload', value: 'page' }, { label: 'Later', value: 'later' }] });
question = top();
button(question, 'later').focus();
asking.redraw({ message: ['The Queue is turned off.', 'The Model Manager tab is created by Reload UI.'],
                note: { text: 'The WebUI did not restart: no answer', error: true } });
check('redrawn while open: the new parts, the same dialog, still open',
      [question.querySelectorAll('.mm-question-message').length, question.querySelector('.mm-question-error')?.textContent,
       top() === question, question.open], [2, 'The WebUI did not restart: no answer', true, true]);
check('and the button that had focus keeps it', document.activeElement, button(question, 'later'));
asking.close();
check('closed by its caller: no answer', await asking, null);

// ------------------------------------------------------------ the container
// A window of its own, its content untouched, and a question over it.
const windowEl = document.createElement('dialog');
windowEl.innerHTML = '<div class="mm-dialog"><h3>Settings</h3><input id="w_search"><button id="w_close">×</button></div>';
let closedHow = null;
let allow = true;
const win = openDialog(windowEl, { focus: () => windowEl.querySelector('#w_search'),
                                   beforeClose: () => allow, onClose: (how) => { closedHow = how; } });
check('a window, its content untouched, opened modal and marked for the stylesheet',
      [windowEl.open, windowEl.classList.contains('mm-layer'), windowEl.querySelector('h3')?.textContent],
      [true, true, 'Settings']);
check('focus where the caller says', document.activeElement, windowEl.querySelector('#w_search'));
asking = ask({ title: 'Discard 1 unsaved change?', buttons: [{ label: 'Keep editing', value: false }] });
question = top();
check('a question over it is on top', [top() === question, windowEl.open], [true, true]);
pageHeardEscape = 0;
escape();
check('Esc closes the question alone, the window stays', [await asking, windowEl.open], [null, true]);
check('and focus goes back to the window', document.activeElement, windowEl.querySelector('#w_search'));
allow = false;
// Each press its own moment, as a person's are: the check before closing is
// awaited, and a press while it is still asked is not a second close.
escape();
await tick();
check('the check before closing says wait: the window stays', [windowEl.open, closedHow], [true, null]);
click(windowEl);
await tick();
check('a click beside it asks the same', [windowEl.open, closedHow], [true, null]);
await win.close('cancel');
check('its own × or Cancel - close(\'cancel\') - asks the same', [windowEl.open, closedHow], [true, null]);
allow = true;
escape();
await tick();
check('told it closed, and how', [windowEl.open, closedHow], [false, 'escape']);
check('Esc never reached the page', pageHeardEscape, 0);
check('the window stays on the page: it is the caller\'s', windowEl.isConnected, true);
check('the page let go once the last closed', held(), false);

// Focus named on a button that cannot take it yet - Sync images' Start,
// disabled while its folders load: the dialog itself, which no redraw of its
// content takes away - not a button in a list drawn again, nor the page.
const waiting = document.createElement('dialog');
waiting.innerHTML = '<input type="checkbox"><button id="w_cancel">Cancel</button><button id="w_start" disabled>Start</button>';
const waitingHandle = openDialog(waiting, { focus: () => waiting.querySelector('#w_start') });
check('a named button still disabled: focus on the dialog itself', document.activeElement, waiting);
await waitingHandle.close('code');

// Focus falling out of it to nowhere - the control that had it disabled as
// the window loads, or drawn again: back to the dialog itself, as a browser
// leaves focus on the page when a focused control is disabled.
const losing = document.createElement('dialog');
losing.innerHTML = '<button id="l_start">Start</button>';
const losingHandle = openDialog(losing);
const start = losing.querySelector('#l_start');
start.disabled = true;
document.body.focus();   // where a browser leaves it
start.dispatchEvent(new window.Event('focusout', { bubbles: true }));
await tick();
check('focus falling out to nowhere comes back to the dialog itself', document.activeElement, losing);
await losingHandle.close('code');

// A close the person did not ask for - a save, a stopped tab - is not asked about.
let askedAbout = 0;
const saved = openDialog(document.createElement('dialog'), { beforeClose: () => { askedAbout += 1; return false; } });
await saved.close('code');
check('close(\'code\') closes without the check', [saved.element.open, askedAbout], [false, 0]);

// A check that answers at once - nothing unsaved - closes it at once: a
// window opened again on the next line finds it closed.
const quick = openDialog(document.createElement('dialog'), { beforeClose: () => true });
quick.close('cancel');
check('a check that answers at once closes it before the next line', quick.element.open, false);

// A close by code while the check still asks - a save behind its question.
// Every question the check asks is answered at the end, so nothing waits for good.
const checksAsked = [];
const pending = openDialog(document.createElement('dialog'), { beforeClose: () => new Promise((r) => checksAsked.push(r)) });
const asked = pending.close('cancel');
// Not awaited: a close by code has nothing to wait for, and is done on return.
pending.close('code');
check('a close by code goes ahead while a check still asks', pending.element.open, false);
checksAsked.forEach((answer) => answer(true));
check('and that check, answered after, finds it closed: asked once', [await asked, checksAsked.length], [false, 1]);

// Two open: the page held until both close.
const first = openDialog(document.createElement('dialog'));
const second = openDialog(document.createElement('dialog'), { escape: false });
escape();
check('Esc off: Esc leaves it open', second.element.open, true);
await second.close();
check('one of two closed: the page still held', held(), true);
await first.close('done');
check('the last closed: let go', held(), false);

// The browser closing one without asking - Chrome may let a second Esc
// through: tidied up, or opened again where it must stay.
let toldNative = null;
const native = openDialog(document.createElement('dialog'), { onClose: (how) => { toldNative = how; } });
native.element.close();
check('closed by the browser: tidied up, told as Esc, the page let go', [toldNative, held()], ['escape', false]);
const stays = openDialog(document.createElement('dialog'), { escape: false });
stays.element.close();
check('one with Esc off is opened again', stays.element.open, true);
await stays.close();

// A question opened by Esc itself - the settings window's "Discard?": the
// press that opened it is spent, not its cancel too. Live on 7870 it opened
// and closed in the one press, read as Keep editing, and Esc did nothing.
const onEscapeAsk = (event) => {
    if (event.key !== 'Escape') return;
    document.removeEventListener('keydown', onEscapeAsk);
    asking = ask({ title: 'Discard 1 unsaved change?', buttons: [{ label: 'Keep editing', value: false }] });
};
document.addEventListener('keydown', onEscapeAsk);
opener.focus();
escape();
question = top();
check('a question opened by an Esc press stays open after that press', question?.open, true);
click(button(question, 'false'));
await asking;

// ------------------------------------------------------------ progress
const progress = showProgress('Syncing model data...');
const popup = top();
check('the progress popup: a turning circle and a line, no buttons',
      [Boolean(popup.querySelector('.mm-sync-spinner')), popup.querySelector('.mm-question-message')?.textContent,
       popup.querySelectorAll('button').length, popup.classList.contains('mm-progress')],
      [true, 'Syncing model data...', 0, true]);
escape();
click(popup);
check('Esc and a click beside it leave it open', popup.open, true);
progress.say('Restarting...');
check('it says what its caller says', popup.querySelector('.mm-question-message')?.textContent, 'Restarting...');
progress.close();
await tick();
check('and closes when told', [popup.open, popup.isConnected, held()], [false, false, false]);

done();
