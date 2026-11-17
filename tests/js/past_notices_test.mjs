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
// What ui-options says, Keep past notices among it (#357): until the checks
// of that setting, nothing, which keeps notices as the default does.
let uiAnswer = {};
let uiUnreached = false;
let uiHeld = null;
globalThis.fetch = async (url) => {
    if (String(url).includes('/model-manager/ui-options')) {
        if (uiHeld) await uiHeld;
        if (uiUnreached) throw new Error('Failed to fetch');
        return { ok: true, status: 200, json: async () => uiAnswer };
    }
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

// ------------------------------------------------ Keep past notices (#357)
// The setting, off: nothing kept, the list emptied, no button, "+N more" a
// count. Followed at a page's load, at each save - from the settings window
// or the Past notices window's own box - and at an Apply on the Settings page.
const KEEP = 'model_manager_keep_past_notices';
const saidSaved = (value, changed = [KEEP]) => window.dispatchEvent(new window.CustomEvent('mm-settings-saved', {
    detail: { changed, settings: { [KEEP]: { value }, model_manager_page_size: { value: 20 } } } }));
const pageNumber = { n: 3 };
let show = null;
const newPage = async () => {
    pageNumber.n += 1;
    const load = (name) => import(`file:///${ROOT}/javascript/shared/${name}?page=${pageNumber.n}`);
    const loading = await load('loading.mjs');
    const calls = await load('calls.mjs');
    // This page's own copy: the first page's is stopped.
    show = (await load('notices.mjs')).showNotice;
    await loading.useServices(['calls.mjs', 'notices.mjs'], 'suite');
    await sleep(20);
    return { loading, calls };
};
const moreButton = () => document.querySelector('.mm-notices-more');
const keptList = () => JSON.parse(stored.get('mm-past-notices') || '[]').map((entry) => entry.parts[0].text);
const kept = (text) => [{ at: clock, kind: 'info', parts: [{ text }] }];

// A page loaded while it is off, nothing kept: the column, made at its
// first notice, makes "+N more" a count from the start.
(await third('loading.mjs')).leaveServices('suite');
clearShown();
stored.delete('mm-past-notices');
uiAnswer = { keep_past_notices: false };
let current = await newPage();
check('nothing kept, nothing drawn at load', document.querySelector('.mm-notices'), null);
for (let i = 1; i <= 5; i += 1) show(`First ${i}.`, { info: true });
check('a page loaded with it off: its column, made later, has "+N more" a count alone',
      [moreButton()?.textContent, moreButton()?.disabled, stored.has('mm-past-notices')], ['+1 more', true, false]);
current.loading.leaveServices('suite');
clearShown();

// A page loaded while it is off, a list still kept from before.
stored.set('mm-past-notices', JSON.stringify(kept('From before.')));
current = await newPage();
check('a page loaded with it off: the list kept from before is emptied, and no button drawn',
      [stored.has('mm-past-notices'), pastButton()], [false, null]);
for (let i = 1; i <= 5; i += 1) show(`Off ${i}.`, { info: true });
check('off: a notice is kept nowhere, no button comes, and "+N more" only counts',
      [stored.has('mm-past-notices'), pastButton(), moreButton()?.textContent, moreButton()?.disabled],
      [false, null, '+1 more', true]);
click(moreButton());
check('pressed anyway, "+N more" opens nothing', pastWindow(), null);

// Turned on from the settings window.
saidSaved(true);
show('On again.', { info: true });
check('saved on: the next notice is kept, its button back, "+N more" a button again',
      [keptList(), pastButton()?.textContent, moreButton()?.disabled], [['On again.'], 'Past notices (1)', false]);
click(moreButton());
check('and "+N more" opens the window', Boolean(pastWindow()), true);
saidSaved(true, ['model_manager_page_size']);
check('another setting saved, this one on still: the window and the list as they were',
      [rows().map(([, , words]) => words), keptList()], [['On again.'], ['On again.']]);
const box = () => pastWindow()?.querySelector('[data-past="keep"]');
check('the window\'s box shows it on', box()?.checked, true);

// Turned off from the settings window, opened over this one by a link.
saidSaved(false);
check('saved off, the window open: list, storage and button gone, the box unticked, Clear disabled',
      [rows(), stored.has('mm-past-notices'), pastButton(), box()?.checked,
       pastWindow()?.querySelector('[data-past="clear"]')?.disabled, moreButton()?.disabled],
      [[], false, null, false, true, true]);
const offLine = pastWindow()?.querySelector('.mm-past-empty');
check('the window says it keeps none, and how to keep them again: a link to the setting',
      [offLine?.textContent, offLine?.querySelector('[data-action="settings.open"]')?.dataset?.focus],
      ['Not keeping notices. Tick Keep past notices to keep them again.', KEEP]);
closeWindow();

// A browser tab loaded before another turned it off: its save of "off" is
// one the server already holds, and says nothing changed.
saidSaved(true);
show('Kept in the older tab.', { info: true });
saidSaved(false, []);
check('saved off with nothing changed on the server: the list emptied all the same',
      [stored.has('mm-past-notices'), pastButton()], [false, null]);

// A notice that stays, turned off while it runs.
saidSaved(true);
const running = show('Judging...', { stay: true, bar: null });
saidSaved(false);
running.update({ text: 'Judged.', bar: 1, tone: 'good' });
running.closeAfter(100);
check('a notice that stays, turned off while it runs: not kept at its end', stored.has('mm-past-notices'), false);
saidSaved(true);
running.update({ text: 'Judged.', bar: 1, tone: 'good' });
running.closeAfter(100);
check('turned on again, the same end said again: kept then', keptList(), ['Judged.']);
running.close();
clearShown();

// The Settings page's Apply: ui-options asked afresh, not the page's first answer.
current.loading.leaveServices('suite');
uiAnswer = { keep_past_notices: true };
current = await newPage();
show('Kept before the Apply.', { info: true });
uiAnswer = { keep_past_notices: false };
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied', { detail: { changed: [KEEP] } }));
await waitFor('the Apply followed', () => !stored.has('mm-past-notices'));
check('turned off on the Settings page: followed at its Apply', [stored.has('mm-past-notices'), pastButton()],
      [false, null]);

// An Apply's answer coming after a newer save: older, so not taken.
let releaseApply = null;
uiHeld = new Promise((resolve) => { releaseApply = resolve; });
uiAnswer = { keep_past_notices: false };
window.dispatchEvent(new window.CustomEvent('mm-settings-page-applied', { detail: { changed: [KEEP] } }));
saidSaved(true);
releaseApply();
await sleep(20);
uiHeld = null;
show('Kept after a late Apply answer.', { info: true });
check('an Apply\'s answer coming after a newer save is older: the save holds',
      keptList().includes('Kept after a late Apply answer.'), true);
saidSaved(false);

// The window's own box, through the settings module's save.
saidSaved(true);
show('Kept for the box.', { info: true });
const asked = [];
let answerSave = null;
current.calls.provide('settings.save', (values) => {
    asked.push(values);
    return new Promise((resolve) => { answerSave = resolve; });
});
click(pastButton());
const untick = () => {
    const tick = box();
    if (!tick) return;
    tick.checked = !tick.checked;
    tick.dispatchEvent(new window.Event('change', { bubbles: true }));
};
focusOn(box());
untick();
const second = new window.Event('click', { bubbles: true, cancelable: true });
box()?.dispatchEvent(second);
answerSave?.({ success: false, errors: { [KEEP]: 'is not a Model Manager setting' } });
await sleep(10);
check('unticked: saved through the settings module, a second press while it runs held back',
      [asked, second.defaultPrevented], [[{ [KEEP]: false }], true]);
check('refused: the box back, the reason said, the list untouched',
      [box()?.checked, pastWindow()?.querySelector('.mm-past-status')?.hidden,
       pastWindow()?.querySelector('.mm-past-status')?.textContent, keptList()],
      [true, false, 'Not saved: is not a Model Manager setting', ['Kept for the box.']]);
current.calls.provide('settings.save', async () => { throw new Error('Failed to fetch'); });
untick();
await sleep(10);
check('a server not reached: the box back, and why',
      [box()?.checked, pastWindow()?.querySelector('.mm-past-status')?.textContent],
      [true, 'Not saved: Failed to fetch']);
current.calls.provide('settings.save', async (values) => ({ success: true, changed: [],
    settings: { [KEEP]: { value: values[KEEP] } } }));
untick();
await sleep(10);
check('saved: the window follows the answer - list, storage and button gone, the box unticked, its focus kept',
      [rows(), stored.has('mm-past-notices'), pastButton(), box()?.checked,
       pastWindow()?.querySelector('.mm-past-status')?.hidden, document.activeElement === box()],
      [[], false, null, false, true, true]);
untick();
await sleep(10);
check('ticked again there: on, the window open still', [box()?.checked, Boolean(pastWindow())], [true, true]);

// Another setting saved, this one unchanged: the window is not drawn again,
// and a row's link keeps its focus.
show(null, { info: true, html: `Kept with a ${settingLink(CLIP_SKIP_MAX, 'link')}.` });
const rowLink = () => pastWindow()?.querySelector('.mm-past-words [data-action="settings.open"]');
focusOn(rowLink());
saidSaved(true, ['model_manager_page_size']);
check('another setting saved, this one unchanged: a row\'s link keeps its focus',
      [Boolean(rowLink()), document.activeElement === rowLink()], [true, true]);

// The reasons a save gives none of.
const statusLine = () => pastWindow()?.querySelector('.mm-past-status');
current.calls.provide('settings.save', async () => ({ success: false }));
untick();
await sleep(10);
check('refused without a reason: the box back, and said so',
      [box()?.checked, statusLine()?.textContent], [true, 'Not saved: the server did not say why']);
current.calls.provide('settings.save', () => undefined);
untick();
await sleep(10);
check('the settings not there to save it: said so', statusLine()?.textContent, 'Not saved: the settings have not loaded yet');
saidSaved(false);
check('the setting changed elsewhere after: the failed save\'s line goes, the box follows',
      [statusLine()?.hidden, box()?.checked], [true, false]);
saidSaved(true);

// One save at a time, whatever window is open: closed and opened again
// while a save runs, the new window's box waits too.
show('Kept for the reopened window.', { info: true });
let answerHeld = null;
current.calls.provide('settings.save', () => new Promise((resolve) => { answerHeld = resolve; }));
untick();
closeWindow();
click(pastButton());
const pressAgain = new window.Event('click', { bubbles: true, cancelable: true });
box()?.dispatchEvent(pressAgain);
check('closed and opened again during a save: the new box shows the setting, and its press waits',
      [box()?.checked, pressAgain.defaultPrevented], [true, true]);
answerHeld?.({ success: true, changed: [], settings: { [KEEP]: { value: true } } });
await sleep(10);

// The window closed before a save's failure came: a notice says it.
let failHeld = null;
current.calls.provide('settings.save', () => new Promise((resolve) => { failHeld = resolve; }));
untick();
closeWindow();
failHeld?.({ success: false, error: 'the disk is full' });
await sleep(10);
check('the window closed before the save failed: a notice says so, and the setting stays on',
      [Array.from(document.querySelectorAll('.mm-notice')).map((n) => n.textContent).at(-1), pastButton() !== null],
      ['Keep past notices was not saved: the disk is full.', true]);
clearShown();

// No answer from ui-options: notices kept, as the default.
current.loading.leaveServices('suite');
uiUnreached = true;
current = await newPage();
show('Kept without an answer.', { info: true });
check('ui-options not answering: notices kept, as by default', keptList().includes('Kept without an answer.'), true);
current.loading.leaveServices('suite');
uiUnreached = false;

// The page's first answer coming after a save: older, so not taken.
let release = null;
uiHeld = new Promise((resolve) => { release = resolve; });
uiAnswer = { keep_past_notices: false };
current = await newPage();
saidSaved(true);
release();
await sleep(20);
uiHeld = null;
show('Kept after the save.', { info: true });
check('the page\'s first answer, come after a save, is older: the save holds',
      keptList().includes('Kept after the save.'), true);
current.loading.leaveServices('suite');
clearShown();

Date.now = realNow;
Object.assign(console, { log, warn });
done();
