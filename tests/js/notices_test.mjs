// The notices in the page's corner (#357): one column, newest at the bottom.
//
// Each notice was a box of its own pinned 16 px from the window's corner, so
// two at once sat on top of each other and only the newest could be read;
// each went after 12 s, with no way to close it or hold it while reading. The
// settings window's re-judging box shared the spot. Now one column holds
// them all: at most four shown, "+N more" above for the older ones, each with
// a ×, every clock held while the pointer is over the column or focus is on a
// ×; and the re-judging progress is a notice like any other, which stays
// while its pass runs and changes as it goes.
//
// Run against the code before #357's column, every check here fails but
// three, which keep what the old code already did: the console lines, a pass
// taking on the notice its last one left, and the notice gone with the last
// tab.
import { checker, mountTab, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
// A notice's 12 s, shortened: the checks are timed as parts of it.
const NOTICE_MS = 600;
// The pointer off the notices this long before they go on: shortened too.
const LEAVE_MS = 40;
window.mmTiming = { notice: NOTICE_MS, noticeLeave: LEAVE_MS, restampPoll: 20 };
// The browser's; the harness leaves it out, and a notice a script removes
// itself is counted out through it.
globalThis.MutationObserver = window.MutationObserver;
const { check, waitFor, done } = checker();

// The re-judging pass, as the server answers: one state per ask, the last kept.
let restampStates = [{ state: 'idle' }];
globalThis.fetch = async (url) => {
    if (String(url).includes('/model-manager/settings/nsfw-levels')) {
        const state = restampStates.length > 1 ? restampStates.shift() : restampStates[0];
        return { ok: true, status: 200, json: async () => state };
    }
    return { ok: true, status: 200, json: async () => ({}) };
};

// Their words go to the console as before; kept out of the suite's output.
const logged = [];
const { log, warn } = console;
console.log = (...args) => logged.push(args.join(' '));
console.warn = (...args) => logged.push(args.join(' '));

const { showNotice } = await sharedModule('notices.mjs');
const { restampNotice } = await sharedModule('settings.mjs');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const tick = () => sleep(0);
const column = () => document.querySelector('.mm-notices');
const notices = () => Array.from(document.querySelectorAll('.mm-notice:not(.mm-restamp)'));
const shown = () => notices().filter((n) => !n.hidden).map((n) => n.textContent);
const more = () => {
    const line = document.querySelector('.mm-notices-more');
    return line && !line.hidden ? line.textContent : null;
};
const closeOf = (element) => element?.querySelector('.mm-notice-close');
const press = (element) => element?.dispatchEvent(new window.Event('click', { bubbles: true }));
const pointer = (type) => column()?.dispatchEvent(new window.Event(type));
const clear = () => document.querySelectorAll('.mm-notice:not(.mm-restamp)').forEach((n) => n.remove());

const box = () => document.querySelector('.mm-restamp');
const boxText = () => box()?.querySelector('.mm-notice-text')?.textContent;
const boxShown = () => Boolean(box()) && !box().hidden;
// What the column holds above the button to the past notices, always its last
// once one has been shown (past_notices_test.mjs).
const held = () => Array.from(column()?.children || []).filter((c) => !c.classList.contains('mm-notices-past'));
const last = () => held().at(-1);

// --------------------------------- the re-judging box, before any notice
// The usual case: a settings save, no Send yet, so no column either.
restampNotice();
await tick();
restampStates = [{ state: 'running', judged: 1, total: 4 }];
restampNotice().watch();
await waitFor('the re-judging box before any notice', () => boxShown());
check('the re-judging box before any notice: in a column made for it, the last thing on the page',
      [box()?.parentNode === column(), document.body.lastElementChild === column()], [true, true]);
restampStates = [{ state: 'done', changed: 1, total: 4 }];
await waitFor('that pass to end', () => boxText()?.startsWith('Done'));
restampNotice().stop();

// ------------------------------------------------------- two at once
showNotice('Kept the image\'s sampler and steps.', { info: true });
showNotice('This WebUI has no VAE named example-vae.');
check('two notices at once stand in one column, the oldest first',
      [column()?.parentNode === document.body,
       Array.from(column()?.children || []).filter((c) => c.classList.contains('mm-notice'))
           .map((n) => [n.className, n.textContent])],
      [true, [['mm-notice mm-notice-info', 'Kept the image\'s sampler and steps.'],
              ['mm-notice', 'This WebUI has no VAE named example-vae.']]]);
check('the column is the last thing on the page, as each notice was', document.body.lastElementChild === column(), true);
check('each has a × that says nothing of its own, named Close for a screen reader',
      notices().map((n) => [closeOf(n)?.tagName, closeOf(n)?.textContent, closeOf(n)?.getAttribute('aria-label')]),
      [['BUTTON', '', 'Close'], ['BUTTON', '', 'Close']]);
check('the console lines are the words alone, as before',
      logged.slice(-2), ['[ModelManager] Kept the image\'s sampler and steps.',
                         '[ModelManager] This WebUI has no VAE named example-vae.']);
const later_ = document.createElement('div');
document.body.appendChild(later_);
showNotice('After the viewer opened.');
check('something added to the page after it - the image viewer - and a notice moves the column to the end again',
      document.body.lastElementChild === column(), true);
document.body.appendChild(later_);
pointer('pointerenter');
showNotice('Arrived under the pointer.');
const movedUnderPointer = document.body.lastElementChild === column();
pointer('pointerleave');
await sleep(LEAVE_MS * 2);
showNotice('Arrived after it left.');
check('but never while the pointer is on it - the browser then loses the pointer, and nothing would go; once it leaves, yes',
      [movedUnderPointer, document.body.lastElementChild === column()], [false, true]);
later_.remove();
notices().slice(-3).forEach((n) => n.remove());

// ------------------------------------------------------- × on the first
press(closeOf(notices()[0]));
check('× on the first of two: that one goes, the other stays as it was',
      notices().map((n) => [n.className, n.textContent]), [['mm-notice', 'This WebUI has no VAE named example-vae.']]);
clear();

// ------------------------------------------------------- held while read
showNotice('Held while read.');
await sleep(NOTICE_MS / 3);
pointer('pointerenter');
await sleep(NOTICE_MS);
const heldPastItsTime = shown();
pointer('pointerleave');
await sleep(NOTICE_MS / 3);
const justAfter = shown();
// It had two thirds of its time left: gone before a whole time has passed again.
await sleep(NOTICE_MS / 2);
check('the pointer over the column past a notice\'s time: still there; the pointer gone, it waits out '
      + 'only the time it had left, then goes', [heldPastItsTime, justAfter, notices().length],
      [['Held while read.'], ['Held while read.'], 0]);

// ---------------------------------------- held by the keyboard
showNotice('Held by the keyboard.');
await sleep(NOTICE_MS / 3);
closeOf(notices()[0])?.dispatchEvent(new window.Event('focusin', { bubbles: true }));
await sleep(NOTICE_MS);
const heldByFocus = shown();
const outOfColumn = new window.Event('focusout', { bubbles: true });
outOfColumn.relatedTarget = null;
closeOf(notices()[0])?.dispatchEvent(outOfColumn);
// Two thirds of its time were left: gone past that, before a whole time again.
await sleep(NOTICE_MS * 0.8);
check('focus on a × holds the column as the pointer does; focus gone, the notice goes',
      [heldByFocus, notices().length], [['Held by the keyboard.'], 0]);

// ---------------------------------------- × while the pointer stays
showNotice('Above.');
showNotice('Closed while held.');
showNotice('Below.');
pointer('pointerenter');
press(closeOf(notices()[1]));
const gaps = () => document.querySelectorAll('.mm-notices-gap').length;
check('× pressed while the pointer stays: the notice goes, its room kept empty',
      [shown(), gaps(), held().map((c) => c.className)],
      [['Above.', 'Below.'], 1, ['mm-notices-more', 'mm-notice', 'mm-notices-gap', 'mm-notice']]);
// Across the 8 px between two notices the pointer leaves the column, which
// takes the pointer only on what is in it, and comes back at once.
pointer('pointerleave');
await sleep(LEAVE_MS / 4);
pointer('pointerenter');
await sleep(LEAVE_MS * 2);
check('the pointer crossing from one notice to the next: the room still kept, the column still held',
      [gaps(), shown()], [1, ['Above.', 'Below.']]);
pointer('pointerleave');
const roomJustAfter = gaps();
await sleep(LEAVE_MS * 2);
check('the pointer gone, the room closes - a moment after, so a crossing does not count',
      [roomJustAfter, gaps(), held().map((c) => c.className)],
      [1, 0, ['mm-notices-more', 'mm-notice', 'mm-notice']]);
clear();

// A × pressed from the keyboard: focus on it, no pointer. The browser may
// send no focusout as the × goes (Firefox), so nothing here sends one.
showNotice('Above.');
showNotice('Closed from the keyboard.');
showNotice('Below.');
const keyed = closeOf(notices()[1]);
keyed?.focus();
keyed?.dispatchEvent(new window.Event('focusin', { bubbles: true }));
press(keyed);
const afterKeys = [shown(), gaps()];
await waitFor('the other two to go at their time', () => notices().length === 0, 30);
check('× pressed from the keyboard: no room kept - no pointer is there - and the column not left held',
      [afterKeys, notices().length], [[['Above.', 'Below.'], 0], 0]);

// ------------------------------------------------------- six at once
showNotice('one');
showNotice('two');
await sleep(NOTICE_MS / 2);
['three', 'four', 'five', 'six'].forEach((text) => showNotice(text));
check('six at once: the newest four shown, the two older counted above',
      [shown(), more(), notices().length], [['three', 'four', 'five', 'six'], '+2 more', 6]);
await waitFor('the hidden two to go at their own time', () => notices().length === 4, 20);
check('the hidden two still go at their time; the count goes with them',
      [shown(), more()], [['three', 'four', 'five', 'six'], null]);
showNotice('seven');
showNotice('eight');
check('two more: two hidden again', more(), '+2 more');
notices().filter((n) => !n.hidden).slice(0, 2).forEach((n) => n.remove());
await tick();
check('two taken off the page by a script: counted again from the page, no stale count',
      [shown(), more()], [['three', 'four', 'seven', 'eight'], null]);
clear();

// ------------------------------------------------ the re-judging box
// A notice like any other (#357): it stays while the pass runs, its words and
// bar changing, with no × until it ends; it counts in the four; its × then
// takes it away.
restampStates = [{ state: 'idle' }];
restampNotice();
await tick();
restampStates = [{ state: 'running', judged: 1, total: 4 }];
restampNotice().watch();
await waitFor('the re-judging notice', () => boxShown());
const firstPass = box();
['A Send notice.', 'two', 'three'].forEach((text) => showNotice(text));
check('a Send notice while the re-judging notice shows: both in the one column, four in all, none hidden',
      [box()?.parentNode === column(), shown(), more(), boxShown()],
      [true, ['A Send notice.', 'two', 'three'], null, true]);
showNotice('four');
check('it counts in the four like any notice: a fifth hides the oldest - here, it',
      [more(), box()?.hidden], ['+1 more', true]);
notices().at(-1)?.remove();
await tick();
check('while the pass runs: no ×, so it is shown to its end; its bar under its words',
      [closeOf(box())?.hidden, Boolean(box()?.querySelector('.mm-notice-bar'))], [true, true]);

restampStates = [{ state: 'done', changed: 1, total: 4 }];
await waitFor('the pass to end', () => boxText()?.startsWith('Done'));
check('its end in its own words, the edge saying it went well, in the same notice, now with its ×',
      [box() === firstPass, box()?.dataset.tone, closeOf(box())?.hidden], [true, 'good', false]);
restampStates = [{ state: 'running', judged: 1, total: 8 }];
restampNotice().watch();
await waitFor('a pass started while the last one\'s end still shows', () => boxText()?.startsWith('Judging'));
check('running again, its × goes again', closeOf(box())?.hidden, true);
restampStates = [{ state: 'done', changed: 1, total: 8 }];
await waitFor('that pass to end too', () => boxText()?.startsWith('Done') && box()?.textContent.includes(`${(8).toLocaleString()}`));
check('a pass started while the last end still shows takes that notice on, in its place',
      [box() === firstPass, document.querySelectorAll('.mm-restamp').length], [true, 1]);
press(closeOf(box()));
check('its × takes it away, as any notice\'s does', box(), null);

restampStates = [{ state: 'running', judged: 2, total: 8 }];
restampNotice().watch();
await waitFor('the next pass', () => boxShown());
check('the next pass is a new notice, at the bottom, with its own words',
      [box() !== firstPass, last() === box(), boxText()],
      [true, true, `Judging stored images again... ${(2).toLocaleString()} of ${(8).toLocaleString()}`]);
restampStates = [{ state: 'done', changed: 0, total: 8 }];
await waitFor('the next pass to end', () => boxText()?.startsWith('Done'));
restampNotice().stop();
check('the last tab stopped: the notice goes with it', box(), null);
clear();

// ------------------------------------- a notice that stays, then goes
const progress = showNotice('Working...', { stay: true, bar: null });
await sleep(NOTICE_MS * 1.2);
const stayed = [progress?.open, closeOf(progress?.element)?.hidden];
progress?.update({ text: 'Done.', bar: 1, tone: 'good' });
progress?.closeAfter(NOTICE_MS / 3);
pointer('pointerenter');
await sleep(NOTICE_MS / 2);
const heldEnd = progress?.open;
pointer('pointerleave');
await sleep(NOTICE_MS / 2);
check('a notice that stays has no time of its own, and no ×; given one at its end, it waits while the column is held, then goes',
      [stayed, heldEnd, progress?.open], [[true, true], true, false]);
check('its console line is written at its end, with the words it ended on', logged.at(-1), '[ModelManager] Done.');

const takenOn = showNotice('Ending...', { stay: true, bar: 1 });
takenOn?.closeAfter(NOTICE_MS / 3);
takenOn?.update({ text: 'Going again...', bar: 0.1 });
await sleep(NOTICE_MS / 2);
check('updated before its end came, a notice that stays takes that end back: still there, no × again',
      [takenOn?.open, closeOf(takenOn?.element)?.hidden], [true, true]);
takenOn?.close();

Object.assign(console, { log, warn });
done();
