/**
 * Notices: the short messages in the page's corner that say what a Send did
 * or could not do. Send's own until #357 moved them here.
 *
 * They stand in one column in the corner, newest at the bottom (#357). Each
 * was a box of its own pinned to the same spot, so two at once sat on top of
 * each other and only the newest could be read. At most four show, with a
 * count of the older ones above them; each has a × of its own, and while the
 * pointer is over the column none goes. A notice can also stay until told,
 * with its words, a bar and its edge changed as it goes: the settings
 * window's progress while stored images are judged again is one.
 *
 * Each is kept in a list as it appears (Past notices): the last 50, in the
 * browser tab's storage, so a reload keeps them. A button under the column
 * opens them, as "+N more" does. Unless the setting says not to: then none
 * is kept, and turning it off empties the list.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, escapeHtml, settingLink } = await shared('core.mjs');
const { openDialog } = await shared('dialog.mjs');
const { call } = await shared('calls.mjs');
// ui-options needs no start of its own: its first ask is shared by the page.
const { uiOptions, fetchUiOptions, KEEP_PAST_NOTICES_SETTING: KEEP } = await shared('ui_options.mjs');

// Notices shown at once; older ones wait out their time hidden, counted above.
const SHOWN = 4;

let column = null;
let more = null;
let observer = null;
// Over the column with the pointer, or on a × with the keyboard: no notice goes.
let hovered = false;
let focused = false;
let leaving = null;
// The last tab using this has stopped: what a Send still under way says goes
// to the console alone, and the column does not come back for it.
let stopped = false;
const timers = new Set();

// Past notices: oldest first, as they were raised. Read from the browser
// tab's storage when first needed - a page loaded again in the same tab finds
// the last page's - and written back at each change.
const KEPT = 50;
const STORE = 'mm-past-notices';
const KINDS = ['info', 'warning', 'good', 'bad'];
let past = null;
let pastButton = null;
let pastWindow = null;
// Keep past notices (#357): as its default until the page learns it. Each
// save or Apply on the Settings page that says it counts one; an answer asked
// for before the last of them - the load's, an Apply's - is older, and is
// not taken.
let keeping = true;
let heard = 0;
// The window's box saving it: one save at a time, whatever window is open.
let saving = false;

const paused = () => hovered || focused;
// Only a ×'s focus holds the column. The buttons to Past notices take focus
// too, back from the window when it closes; held by them, every notice stayed
// until a click elsewhere.
const isClose = (element) => Boolean(element?.classList?.contains('mm-notice-close'));

/**
 * Run `work` after `ms`, a clock that stops while the column is paused and
 * goes on with the time it had left. Returns what `cancel` takes.
 */
function later(work, ms) {
    const timer = { work, left: ms, started: 0, id: null };
    timers.add(timer);
    if (!paused()) run(timer);
    return timer;
}

function run(timer) {
    timer.started = Date.now();
    timer.id = setTimeout(() => {
        timers.delete(timer);
        timer.work();
    }, Math.max(0, timer.left));
}

function cancel(timer) {
    if (!timer) return;
    clearTimeout(timer.id);
    timers.delete(timer);
}

function pause() {
    for (const timer of timers) {
        if (timer.id === null) continue;
        clearTimeout(timer.id);
        timer.id = null;
        timer.left -= Date.now() - timer.started;
    }
}

function resume() {
    for (const timer of timers) {
        if (timer.id === null) run(timer);
    }
    // A notice closed while paused kept its room, so the next × did not
    // slide under the pointer; the room closes now.
    column?.querySelectorAll('.mm-notices-gap').forEach((gap) => gap.remove());
}

function setPaused(change) {
    const was = paused();
    change();
    if (was && !paused()) resume();
    else if (!was && paused()) pause();
}

/** The column, made at the first notice; the last thing on the page, as each notice was. */
function theColumn() {
    if (!column) {
        column = document.createElement('div');
        column.className = 'mm-notices';
        more = document.createElement('button');
        more.type = 'button';
        more.className = 'mm-notices-more';
        more.hidden = true;
        // With nothing kept there is nothing to open: a count alone.
        more.disabled = !keeping;
        more.addEventListener('click', () => {
            if (keeping) openPast();
        });
        column.appendChild(more);
        // Only what is in the column takes the pointer (style.css): the space
        // beside a narrower notice is Forge's page. So the 8 px between two
        // notices is outside too, and crossing it must not let them go.
        column.addEventListener('pointerenter', () => {
            clearTimeout(leaving);
            setPaused(() => { hovered = true; });
        });
        column.addEventListener('pointerleave', () => {
            clearTimeout(leaving);
            leaving = setTimeout(() => setPaused(() => { hovered = false; }), TIMING.noticeLeave);
        });
        column.addEventListener('focusin', (event) => setPaused(() => { focused = isClose(event.target); }));
        column.addEventListener('focusout', (event) => {
            if (isClose(event.relatedTarget) && column.contains(event.relatedTarget)) return;
            setPaused(() => { focused = false; });
        });
        // A notice taken off the page by anything - a test, another script -
        // is counted out too, not only those this module removes.
        if (typeof MutationObserver === 'function') {
            observer = new MutationObserver(count);
            observer.observe(column, { childList: true });
        }
    }
    // Moved only when something has been added after it - and never under
    // the pointer: Chromium then loses it, sends no pointerleave when the
    // pointer goes, and every notice was held for good. Nothing covers a
    // column the pointer is on.
    if (!hovered && document.body.lastElementChild !== column) document.body.appendChild(column);
    return column;
}

/** The newest four shown, the rest hidden and counted: read from the page each time. */
function count() {
    if (!column) return;
    const notices = Array.from(column.children).filter((child) => child.classList.contains('mm-notice'));
    const hidden = Math.max(0, notices.length - SHOWN);
    // Only what differs is written: a write the observer sees would count
    // again, and again.
    notices.forEach((notice, index) => {
        if (notice.hidden !== index < hidden) notice.hidden = index < hidden;
    });
    const words = hidden ? `+${hidden} more` : '';
    if (more.textContent !== words) more.textContent = words;
    if (more.hidden !== !hidden) more.hidden = !hidden;
}

// ------------------------------------------------------------ past notices

function storage() {
    try {
        return globalThis.sessionStorage ?? null;
    } catch {
        // A browser that refuses storage keeps the list for this page alone.
        return null;
    }
}

const isPart = (part) => typeof part?.text === 'string'
    && (part.setting === undefined || (typeof part.setting === 'string' && part.setting !== ''));
const isEntry = (entry) => typeof entry?.at === 'number' && Number.isFinite(new Date(entry.at).getTime())
    && KINDS.includes(entry.kind) && Array.isArray(entry.parts) && entry.parts.length > 0
    && entry.parts.every(isPart);

function pastList() {
    if (past) return past;
    past = [];
    try {
        const kept = JSON.parse(storage()?.getItem(STORE) || '[]');
        if (Array.isArray(kept)) past = kept.filter(isEntry).slice(-KEPT);
    } catch {
        // Nothing readable kept: an empty list.
    }
    return past;
}

function keepPast() {
    try {
        if (past.length) storage()?.setItem(STORE, JSON.stringify(past));
        else storage()?.removeItem(STORE);
    } catch {
        // Full or refused: the list still holds for this page.
    }
}

/**
 * A notice's words as parts: its text, and each link to a setting as its
 * words and the setting it names - never markup, which the list would have
 * to clean, and cleaning removes a button, words and all.
 */
function partsOf(element, skip) {
    const parts = [];
    const add = (text) => {
        if (!text) return;
        const lastPart = parts.at(-1);
        if (lastPart && lastPart.setting === undefined) lastPart.text += text;
        else parts.push({ text });
    };
    const walk = (node) => {
        node.childNodes.forEach((child) => {
            if (child === skip) return;
            if (child.nodeType !== 1) {
                add(child.textContent);
            } else if (child.dataset?.action === 'settings.open' && child.dataset.focus) {
                parts.push({ text: child.textContent, setting: child.dataset.focus });
            } else {
                walk(child);
            }
        });
    };
    walk(element);
    return parts;
}

/** Kept, unless stopped or the setting is off: whether it was. */
function remember(kind, parts) {
    if (stopped || !keeping) return false;
    const list = pastList();
    list.push({ at: Date.now(), kind, parts });
    if (list.length > KEPT) list.splice(0, list.length - KEPT);
    keepPast();
    drawPastButton();
    pastWindow?.draw();
    return true;
}

/** Under the column, while the list holds a notice. */
function drawPastButton() {
    const n = pastList().length;
    if (!n) {
        pastButton?.remove();
        pastButton = null;
        return;
    }
    const home = theColumn();
    if (!pastButton) {
        pastButton = document.createElement('button');
        pastButton.type = 'button';
        pastButton.className = 'mm-notices-past';
        pastButton.addEventListener('click', openPast);
    }
    const words = `Past notices (${n})`;
    if (pastButton.textContent !== words) pastButton.textContent = words;
    if (home.lastElementChild !== pastButton) home.appendChild(pastButton);
}

const two = (n) => String(n).padStart(2, '0');
const timeOf = (at) => {
    const date = new Date(at);
    return `${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
};

const wordsHtml = (parts) => parts.map((part) => (part.setting === undefined
    ? escapeHtml(part.text) : settingLink(part.setting, part.text))).join('');

/**
 * Keep past notices as the page last learnt it. Off, the list goes - from
 * the browser tab's storage too - with its button, and "+N more" only counts;
 * a window open says so, and its box can turn it on again.
 */
function follow(on) {
    // Unchanged, nothing is drawn again: a focus in the window stays.
    if (stopped || on === keeping) return;
    keeping = on;
    if (!keeping) {
        past = [];
        keepPast();
    }
    drawPastButton();
    if (more && more.disabled !== !keeping) more.disabled = !keeping;
    pastWindow?.follow();
}

// Off only when said so: no answer, or one without it, is the default.
const keptBy = (data) => data?.keep_past_notices !== false;

/**
 * The window: every notice kept, newest first, with its time and its edge.
 * A link to a setting is drawn again as one, and opens the settings window
 * there through the page's own listener. Its box is the setting itself,
 * saved as it is pressed.
 */
function openPast() {
    if (pastWindow) return;
    const element = document.createElement('dialog');
    element.className = 'mm-question mm-past-notices';
    element.setAttribute('aria-labelledby', 'mm_past_notices_title');
    element.innerHTML = `<div class="mm-dialog mm-question-box">
        <h3 id="mm_past_notices_title">Past notices</h3>
        <p class="mm-question-message">Kept in this browser tab until it closes. The last ${KEPT}.</p>
        <ul class="mm-past-list"></ul>
        <div class="mm-dialog-buttons">
            <label class="mm-question-tick mm-past-keep"><input type="checkbox" data-past="keep">
                <span>Keep past notices</span></label>
            <button type="button" class="mm-btn secondary" data-past="clear">Clear</button>
            <button type="button" class="mm-btn secondary" data-past="close">Close</button>
        </div>
        <p class="mm-question-note mm-question-error mm-past-status" hidden></p>
    </div>`;
    const list = element.querySelector('.mm-past-list');
    const box = element.querySelector('[data-past="keep"]');
    const status = element.querySelector('.mm-past-status');
    const clear = element.querySelector('[data-past="clear"]');
    const closer = element.querySelector('[data-past="close"]');
    // A save under way: the box is not disabled, which would drop its focus
    // to the page, where Esc reaches Forge's Interrupt; presses wait instead.
    box.checked = keeping;
    const drawBox = () => {
        if (!saving && box.checked !== keeping) box.checked = keeping;
    };
    const draw = () => {
        // A row's link with focus is drawn anew: focus goes to Close, not to
        // the page, where Esc would reach Forge's Interrupt.
        const hadFocus = list.contains(document.activeElement);
        const rows = pastList().slice().reverse();
        // Off, this window cannot be opened again: the way back is said here,
        // and its link finds the setting whichever settings the window shows.
        const empty = keeping ? 'No notices kept.'
            : `Not keeping notices. Tick ${settingLink(KEEP, 'Keep past notices')} to keep them again.`;
        list.innerHTML = rows.length ? rows.map((entry) => `<li class="mm-past-row" data-kind="${entry.kind}">
            <span class="mm-past-time">${timeOf(entry.at)}</span>
            <span class="mm-past-words">${wordsHtml(entry.parts)}</span></li>`).join('')
            : `<li class="mm-past-empty">${empty}</li>`;
        clear.disabled = !rows.length;
        if (hadFocus) closer.focus();
    };
    element.addEventListener('click', (event) => {
        const button = event.target.closest?.('[data-past]');
        if (button === box) {
            if (saving) event.preventDefault();
            return;
        }
        if (!button || button.disabled) return;
        if (button.dataset.past === 'clear') {
            // The list only: notices still showing stay.
            past = [];
            keepPast();
            drawPastButton();
            draw();
            // Clear, now disabled, lets go of focus.
            closer.focus();
        } else {
            handle.close('cancel');
        }
    });
    box.addEventListener('change', async () => {
        const want = box.checked;
        if (saving) {
            box.checked = !want;
            return;
        }
        saving = true;
        status.hidden = true;
        const asking = pastWindow;
        let answer;
        try {
            answer = await call('settings.save', { [KEEP]: want });
        } catch (e) {
            answer = { success: false, error: e.message };
        }
        saving = false;
        if (answer?.success) {
            // Taken from the answer, as from the saved event: a tab that
            // missed another's change saves what the server already holds.
            const value = answer.settings?.[KEEP]?.value;
            heard += 1;
            follow(typeof value === 'boolean' ? value : want);
            drawBox();
        } else {
            drawBox();
            // Nothing answered: the settings module, which saves, is not there.
            const why = answer === undefined ? 'the settings have not loaded yet'
                : answer?.errors?.[KEEP] || answer?.error || 'the server did not say why';
            if (pastWindow === asking) {
                status.textContent = `Not saved: ${why}`;
                status.hidden = false;
            } else {
                // The window closed before the answer: said where it is seen.
                showNotice(`Keep past notices was not saved: ${why}.`);
            }
        }
    });
    drawBox();
    draw();
    const handle = openDialog(element, {
        focus: closer,
        onClose: () => {
            element.remove();
            pastWindow = null;
        },
    });
    pastWindow = {
        draw,
        follow: () => {
            // A failed save's line goes once the setting has changed anyway.
            status.hidden = true;
            drawBox();
            draw();
        },
        close: () => handle.close('code'),
    };
}

/**
 * Started with Send and the settings window (their STARTS): the list kept by
 * this browser tab drawn as its button at once, and Keep past notices
 * followed - at load, at each save, and at an Apply on the Settings page
 * that names it. Stopped with the last tab that uses them: the column, the
 * button and the window go, and every notice's clock with them.
 */
export function start(scope) {
    drawPastButton();
    uiOptions().then((data) => {
        if (!heard) follow(keptBy(data));
    }).catch(() => {});
    // Every save says it, changed or not: saving what the server already
    // holds still tells this page what that is.
    scope.listen(window, 'mm-settings-saved', (event) => {
        const value = event.detail?.settings?.[KEEP]?.value;
        if (typeof value !== 'boolean') return;
        heard += 1;
        follow(value);
    });
    // The Settings page says only which changed: asked afresh, not from the
    // page's first answer.
    scope.listen(window, 'mm-settings-page-applied', (event) => {
        if (!(event.detail?.changed || []).includes(KEEP)) return;
        heard += 1;
        const asked = heard;
        fetchUiOptions().then((data) => {
            if (data && heard === asked) follow(keptBy(data));
        });
    });
    scope.onStop(() => {
        stopped = true;
        pastWindow?.close();
        timers.forEach((timer) => clearTimeout(timer.id));
        timers.clear();
        clearTimeout(leaving);
        observer?.disconnect();
        column?.remove();
        column = null;
        more = null;
        observer = null;
        pastButton = null;
        hovered = false;
        focused = false;
    });
}

/** The ×: no text of its own, so a notice's words and its console line are as they were. */
function closeButton(close) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'mm-notice-close';
    button.setAttribute('aria-label', 'Close');
    button.addEventListener('click', () => {
        // The focus on this × goes with it. Chromium says so with a focusout
        // in the middle of the removal; Firefox says nothing, and the column
        // stayed paused for good. Let go of it first, then ask the page.
        if (document.activeElement === button) button.blur();
        close();
        setPaused(() => {
            focused = isClose(document.activeElement) && Boolean(column?.contains(document.activeElement));
        });
    });
    return button;
}

/**
 * A notice in the corner, for twelve seconds (TIMING.notice) and any time the
 * column was paused. `info` is something to know rather than something wrong:
 * drawn and logged as such.
 *
 * A notice of something still going on - a pass over stored images - says
 * `stay`: it has no time of its own until `closeAfter` gives it one, and is
 * logged then, with the words it ends on. Until then it has no ×: what is
 * going on is shown to its end. `bar` draws a bar under its words:
 * the share done, from 0 to 1, or null while that is not known yet. `tone`
 * colours its edge for how it ended, 'good' or 'bad'.
 *
 * Returns the notice: `update` changes its words, bar and tone in place (and,
 * for one that stays, takes back a close not yet come); `closeAfter(ms)`;
 * `close()`; `open`, false once it is gone - closed, timed out, or taken off
 * the page by anything else.
 */
export function showNotice(text, { info = false, html = null, stay = false, bar, tone = '', className = '' } = {}) {
    const notice = document.createElement('div');
    notice.className = (info ? 'mm-notice mm-notice-info' : 'mm-notice') + (className ? ` ${className}` : '');
    // With a bar, the words have a line of their own above it.
    let words = notice;
    let fill = null;
    if (bar !== undefined) {
        words = document.createElement('div');
        words.className = 'mm-notice-text';
        const track = document.createElement('div');
        track.className = 'mm-notice-bar';
        fill = document.createElement('div');
        fill.className = 'mm-notice-fill';
        track.appendChild(fill);
        notice.append(words, track);
    }
    let timer = null;
    const close = closeButton(() => remove({ keepRoom: true }));

    function setWords(newText, newHtml) {
        // The × stays where it is; the words around it are replaced.
        Array.from(words.childNodes).forEach((node) => { if (node !== close) node.remove(); });
        const fresh = document.createElement('div');
        // Markup, where it links to a setting (#320); the console gets its words.
        if (newHtml === null || newHtml === undefined) fresh.textContent = newText;
        else fresh.innerHTML = newHtml;
        const before = close.parentNode === words ? close : null;
        Array.from(fresh.childNodes).forEach((node) => words.insertBefore(node, before));
    }

    function setBar(share) {
        if (!fill) return;
        // No share yet: what is to be done is still being counted.
        notice.classList.toggle('mm-notice-unknown', share === null);
        fill.style.width = share === null ? '' : `${Math.round(share * 100)}%`;
    }

    function setTone(value) {
        if (value) notice.dataset.tone = value;
        else delete notice.dataset.tone;
    }

    function remove({ keepRoom = false } = {}) {
        cancel(timer);
        timer = null;
        // The room is kept for the pointer alone: a × pressed from the
        // keyboard has nothing under it to slide.
        if (keepRoom && hovered && notice.parentNode === column && !notice.hidden) {
            const gap = document.createElement('div');
            gap.className = 'mm-notices-gap';
            // Its width too: the room is what keeps the pointer in the
            // column, which takes the pointer only on what it holds.
            gap.style.width = `${notice.offsetWidth}px`;
            gap.style.height = `${notice.offsetHeight}px`;
            notice.replaceWith(gap);
        } else {
            notice.remove();
        }
        count();
    }

    const log = () => ((stay ? notice.dataset.tone !== 'bad' : info) ? console.log : console.warn)(
        '[ModelManager]', notice.textContent);
    // Kept as it appears; one that stays, as it ends - its last words, not
    // each step of its bar, and once: an end said again in the same words is
    // the same end (two polls of one pass each end it).
    let keptAs = null;
    const keep = () => {
        const kind = KINDS.includes(notice.dataset.tone) ? notice.dataset.tone : (info ? 'info' : 'warning');
        const parts = partsOf(words, close);
        const as = JSON.stringify([kind, parts]);
        if (as === keptAs) return;
        // Not kept - the setting off - it may be kept at a later end in the
        // same words, once on.
        if (remember(kind, parts)) keptAs = as;
    };

    setWords(text, html);
    setBar(bar);
    setTone(tone);
    close.hidden = stay;
    notice.appendChild(close);
    if (stopped) {
        // Said, but not shown: the page's tabs are off.
        log();
        return { element: notice, get open() { return false; }, update() {}, closeAfter() {}, close() {} };
    }
    // Above the button to the past ones, the column's last.
    const home = theColumn();
    home.insertBefore(notice, pastButton?.parentNode === home ? pastButton : null);
    count();
    if (!stay) {
        timer = later(remove, TIMING.notice);
        log();
        keep();
    }

    return {
        element: notice,
        get open() { return notice.isConnected; },
        update({ text: newText, html: newHtml, bar: share, tone: newTone } = {}) {
            if (newText !== undefined || newHtml !== undefined) setWords(newText, newHtml);
            if (share !== undefined) setBar(share);
            if (newTone !== undefined) setTone(newTone);
            if (stay) {
                cancel(timer);
                timer = null;
                close.hidden = true;
            }
        },
        closeAfter(ms) {
            cancel(timer);
            timer = later(remove, ms);
            close.hidden = false;
            if (stay) {
                log();
                keep();
            }
        },
        close: () => remove(),
    };
}
