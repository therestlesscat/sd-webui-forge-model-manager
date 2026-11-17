// Past notices (#357): every notice kept as it appears, the last 50, in the
// browser tab's storage, and a window to read them again.
//
// A notice went after its 12 s for good: the console held the only copy, and
// one hidden behind "+N more" went unread. Now each is kept as it appears -
// the re-judging notice as it ends, its last words alone - and a button under
// the column, or "+N more", opens them: newest first, each with its time and
// its edge, a link to a setting drawn again as one. A page loaded again in
// the same browser tab reads them back.
//
// Run against the code before (commit 2 of #357), every check here fails but
// three: two keep what came before - no button before any notice, and the
// count of hidden notices - and focus on the Past notices button holding
// nothing has no button to try there; it failed on this commit's first build,
// whose window gave focus back to the button and held every notice.
import { ROOT, checker, escape, mountTab, press, sharedModule } from './harness.mjs';

const { window, document } = mountTab('model_manager/ui/tab_model_manager.py');
window.mmTiming = { notice: 600, noticeLeave: 40, restampPoll: 20 };
globalThis.MutationObserver = window.MutationObserver;
const { check, waitFor, done } = checker();

// The browser tab's storage: what a page loaded again finds.
const stored = new Map();
globalThis.sessionStorage = window.sessionStorage = {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => stored.set(key, String(value)),
    removeItem: (key) => stored.delete(key),
};

let restampStates = [{ state: 'idle' }];
globalThis.fetch = async (url) => {
    if (String(url).includes('/model-manager/settings/nsfw-levels')) {
        const state = restampStates.length > 1 ? restampStates.shift() : restampStates[0];
        return { ok: true, status: 200, json: async () => state };
    }
    return { ok: true, status: 200, json: async () => ({}) };
};

const { log, warn } = console;
console.log = () => {};
console.warn = () => {};

// Each notice raised at a time of its own, so its row's time can be read.
const realNow = Date.now;
let clock = new Date(2026, 10, 16, 14, 2, 31).getTime();
Date.now = () => clock;

const { showNotice } = await sharedModule('notices.mjs');
const { restampNotice, STARTS: SETTINGS_STARTS } = await sharedModule('settings.mjs');
const { STARTS: SEND_STARTS } = await sharedModule('send.mjs');
const { settingLink } = await sharedModule('core.mjs');
const { useServices, leaveServices } = await sharedModule('loading.mjs');
await useServices(['calls.mjs', 'notices.mjs'], 'suite');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pastButton = () => document.querySelector('.mm-notices .mm-notices-past');
const pastWindow = () => document.querySelector('dialog.mm-past-notices[open]');
const rows = () => Array.from(pastWindow()?.querySelectorAll('.mm-past-row') || [])
    .map((row) => [row.querySelector('.mm-past-time')?.textContent, row.dataset.kind,
                   row.querySelector('.mm-past-words')?.textContent]);
const click = (element) => element?.dispatchEvent(new window.Event('click', { bubbles: true }));
const closeWindow = () => click(pastWindow()?.querySelector('[data-past="close"]'));
const clearShown = () => document.querySelectorAll('.mm-notice').forEach((n) => n.remove());

// ------------------------------------------------------ kept as it appears
check('Send and the settings window start it, so the button is drawn as a page loads',
      [SEND_STARTS.includes('notices.mjs'), SETTINGS_STARTS.includes('notices.mjs')], [true, true]);
check('before any notice: no button to the past ones', pastButton(), null);
showNotice('Kept the image\'s sampler and steps.', { info: true });
clock += 2000;
showNotice('This WebUI has no VAE named example-vae.');
check('a notice raised: the button under the column says how many are kept',
      [pastButton()?.textContent, pastButton()?.parentNode?.lastElementChild === pastButton()],
      ['Past notices (2)', true]);
click(pastButton());
check('pressed, the window lists them newest first, each with its time and its kind',
      [pastWindow()?.querySelector('h3')?.textContent, rows()],
      ['Past notices', [['14:02:33', 'warning', 'This WebUI has no VAE named example-vae.'],
                        ['14:02:31', 'info', 'Kept the image\'s sampler and steps.']]]);
check('its line says how long they are kept',
      pastWindow()?.querySelector('.mm-question-message')?.textContent,
      'Kept in this browser tab until it closes. The last 50.');
const openBeforeClose = Boolean(pastWindow());
closeWindow();
check('Close closes it', [openBeforeClose, pastWindow()], [true, null]);

// ------------------------------- focus on its buttons holds nothing
// The window gives focus back to the button that opened it as it closes; held
// by that, every notice stayed until a click elsewhere.
clearShown();
const focusOn = (element) => {
    element?.focus();
    element?.dispatchEvent(new window.Event('focusin', { bubbles: true }));
};
const unheld = showNotice('Goes at its time.', { info: true });
focusOn(pastButton());
await sleep(1000);
check('focus on the Past notices button holds no notice: it goes at its time', unheld.open, false);
pastButton()?.blur();
pastButton()?.dispatchEvent(new window.Event('focusout', { bubbles: true }));

// ------------------------------------------- a notice while the window is open
click(pastButton());
const linkCount = rows().length;
showNotice('Came while it was open.', { info: true });
check('a notice raised while the window is open: its row is added at the top',
      [rows().length - linkCount, rows()[0]?.[2]], [1, 'Came while it was open.']);
closeWindow();

// --------------------------------------------- one end kept once
const said = stored.has('mm-past-notices') ? JSON.parse(stored.get('mm-past-notices')).length : 0;
const twice = showNotice('Working...', { stay: true, bar: null });
twice.update({ text: 'Done.', bar: 1, tone: 'good' });
twice.closeAfter(5000);
twice.update({ text: 'Done.', bar: 1, tone: 'good' });
twice.closeAfter(5000);
const afterTwice = JSON.parse(stored.get('mm-past-notices') || '[]');
check('an end said twice in the same words - two polls of one pass - is kept once',
      [afterTwice.length - said, afterTwice.at(-1)?.parts?.[0]?.text], [1, 'Done.']);
twice.update({ text: 'Done again, other words.', bar: 1, tone: 'good' });
twice.closeAfter(5000);
check('a later end in other words is kept as its own',
      JSON.parse(stored.get('mm-past-notices') || '[]').length - said, 2);
twice.close();

// ------------------------------------------- one gone from sight, still kept
clearShown();
for (let i = 1; i <= 5; i += 1) showNotice(`Notice ${i}.`, { info: true });
const moreLine = document.querySelector('.mm-notices-more');
check('"+N more" says how many wait hidden', [moreLine?.hidden, moreLine?.textContent], [false, '+1 more']);
click(moreLine);
check('and pressed, opens the same window, the hidden one in it',
      rows().map(([, , words]) => words).includes('Notice 1.'), true);
closeWindow();

// ------------------------------------------------------------ the last 50
clearShown();
for (let i = 1; i <= 50; i += 1) showNotice(`Batch ${i}.`, { info: true });
click(pastButton());
const fifty = rows().map(([, , words]) => words);
closeWindow();
check('51 and more: the last 50 kept, the oldest gone',
      [fifty.length, fifty[0], fifty.at(-1), pastButton()?.textContent],
      [50, 'Batch 50.', 'Batch 1.', 'Past notices (50)']);
clearShown();

// ------------------------------------------- the re-judging notice: its end
for (let i = 0; i < 50; i += 1) showNotice(`Filler ${i}.`, { info: true });
clearShown();
const countBefore = pastButton()?.textContent;
// Steps enough that some reach the notice as it changes: the first answers
// go to the check made as it starts.
restampStates = [{ state: 'running', judged: 0, total: 4 }, { state: 'running', judged: 1, total: 4 },
                 { state: 'running', judged: 2, total: 4 }, { state: 'running', judged: 3, total: 4 },
                 { state: 'done', changed: 1, total: 4 }];
restampNotice().watch();
await waitFor('the pass to end', () => document.querySelector('.mm-restamp .mm-notice-text')
    ?.textContent.startsWith('Done'));
click(pastButton());
const afterPass = rows().filter(([, , words]) => !words.startsWith('Filler'));
closeWindow();
check('a pass over stored images adds its last words alone, its edge saying it went well - not each step',
      [countBefore, afterPass.map(([, kind, words]) => [kind, words])],
      ['Past notices (50)', [['good', `Done: ${(1).toLocaleString()} of ${(4).toLocaleString()} images changed level.`]]]);
restampStates = [{ state: 'running', judged: 1, total: 4 }, { state: 'failed', error: 'the disk is full' }];
restampNotice().watch();
await waitFor('the failed pass to end', () => document.querySelector('.mm-restamp .mm-notice-text')
    ?.textContent.startsWith('Could not'));
click(pastButton());
check('and a failed one its failure, in red', rows()[0]?.slice(1),
      ['bad', 'Could not judge stored images again: the disk is full']);
closeWindow();
restampNotice().stop();

// ---------------------------------------------------------- Esc, and Clear
let reachedPage = 0;
const onPageKey = (event) => { if (event.key === 'Escape') reachedPage += 1; };
document.addEventListener('keydown', onPageKey);
click(pastButton());
const escaped = escape();
document.removeEventListener('keydown', onPageKey);
check('Esc closes the window, and goes no further: Forge takes it as Interrupt',
      [escaped?.classList.contains('mm-past-notices'), pastWindow(), reachedPage], [true, null, 0]);

showNotice('Still showing.', { info: true });
const keptBeforeClear = stored.size;
click(pastButton());
focusOn(pastWindow()?.querySelector('[data-past="clear"]'));
click(pastWindow()?.querySelector('[data-past="clear"]'));
check('Clear empties the list and takes the button away; a notice still showing stays',
      [rows(), pastWindow()?.querySelector('.mm-past-empty')?.textContent, pastButton(),
       Array.from(document.querySelectorAll('.mm-notice')).map((n) => n.textContent)],
      [[], 'No notices kept.', null, ['Still showing.']]);
check('and nothing is kept in the browser tab', [keptBeforeClear, stored.size], [1, 0]);
check('focus goes to Close, Clear being disabled now', document.activeElement?.dataset?.past, 'close');
closeWindow();
clearShown();

// ------------------------------------------------- a link to a setting kept
const CLIP_SKIP_MAX = 'model_manager_send_clip_skip_max';
clock = new Date(2026, 10, 16, 15, 0, 5).getTime();
showNotice(null, { info: true, html: `The image's Clip skip 3 is above your ${
    settingLink(CLIP_SKIP_MAX, 'Highest Clip skip')} of 2, so your Clip Skip applies.` });
check('kept as words and the setting it names, never as markup',
      JSON.parse(stored.get('mm-past-notices') || '[]').map((entry) => entry.parts),
      [[{ text: 'The image\'s Clip skip 3 is above your ' },
        { text: 'Highest Clip skip', setting: CLIP_SKIP_MAX },
        { text: ' of 2, so your Clip Skip applies.' }]]);

// --------------------------------- a row's link with focus, drawn anew
click(pastButton());
focusOn(pastWindow()?.querySelector('.mm-past-words [data-action="settings.open"]'));
const linkHadFocus = document.activeElement?.dataset?.action;
clock += 1000;
showNotice('Late.', { info: true });
check('a row\'s link with focus, the list drawn anew: focus goes to Close, not to the page',
      [linkHadFocus, document.activeElement?.dataset?.past], ['settings.open', 'close']);
clearShown();

// ------------------------------------------------- every tab switched off
const endAfterStop = showNotice('Still going.', { stay: true, bar: null });
const keptBeforeStop = stored.get('mm-past-notices');
leaveServices('suite');
check('the last tab stopped: the column, the button and the window go with it',
      [document.querySelector('.mm-notices'), pastButton(), pastWindow()], [null, null, null]);
const late = showNotice('A Send still under way says this.', { info: true });
check('a notice after that - a Send still under way - brings none of them back, and is not kept',
      [document.querySelector('.mm-notices'), late.open, stored.get('mm-past-notices') === keptBeforeStop],
      [null, false, true]);
endAfterStop.update({ text: 'Ended after the stop.', bar: 1, tone: 'good' });
endAfterStop.closeAfter(100);
check('nor a notice that stays, ended after it',
      [document.querySelector('.mm-notices'), stored.get('mm-past-notices') === keptBeforeStop], [null, true]);

// --------------------------------------------------- a page loaded again
// A new page in the same browser tab: the modules loaded afresh, the
// storage as the last page left it.
const fresh = (name) => import(`file:///${ROOT}/javascript/shared/${name}?page=2`);
const freshLoading = await fresh('loading.mjs');
const settingsOpened = [];
(await fresh('calls.mjs')).provide('settings.open', (data) => settingsOpened.push(data.focus));
await freshLoading.useServices(['calls.mjs', 'notices.mjs'], 'suite');
check('a page loaded again in the same browser tab: the list read back, its button drawn',
      pastButton()?.textContent, 'Past notices (2)');
click(pastButton());
check('its rows: the words whole, the time each was raised', rows(),
      [['15:00:06', 'info', 'Late.'],
       ['15:00:05', 'info', 'The image\'s Clip skip 3 is above your Highest Clip skip of 2, so your Clip Skip applies.']]);
const link = pastWindow()?.querySelector('.mm-past-words [data-action="settings.open"]');
if (link) press(link);
check('its link pressed opens the settings window at Highest Clip skip', settingsOpened, [CLIP_SKIP_MAX]);
closeWindow();

// What a stored list holds is read with care: a list someone else wrote, or
// an older one, is not drawn as it came.
freshLoading.leaveServices('suite');
stored.set('mm-past-notices', JSON.stringify([{ at: clock, kind: 'info', parts: [{ text: '<b>bold</b>' }] },
                                              { at: clock, kind: 'nonsense', parts: [{ text: 'a' }] },
                                              { at: clock, kind: 'info', parts: [] },
                                              { at: 1e300, kind: 'info', parts: [{ text: 'no time' }] },
                                              { at: clock, kind: 'info', parts: [{ text: 'x', setting: '' }] },
                                              'junk']));
const third = (name) => import(`file:///${ROOT}/javascript/shared/${name}?page=3`);
await (await third('loading.mjs')).useServices(['calls.mjs', 'notices.mjs'], 'suite');
click(pastButton());
check('a stored list read back drops what is not a notice - no words, no time, a link to no setting - and draws words as words',
      [pastButton()?.textContent, rows().map(([, , words]) => words),
       pastWindow()?.querySelector('.mm-past-words b')], ['Past notices (1)', ['<b>bold</b>'], null]);
closeWindow();

Date.now = realNow;
Object.assign(console, { log, warn });
done();
