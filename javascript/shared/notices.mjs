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
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING } = await shared('core.mjs');

// Notices shown at once; older ones wait out their time hidden, counted above.
const SHOWN = 4;

let column = null;
let more = null;
let observer = null;
// Over the column with the pointer, or on a × with the keyboard: no notice goes.
let hovered = false;
let focused = false;
let leaving = null;
const timers = new Set();

const paused = () => hovered || focused;

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
        more = document.createElement('div');
        more.className = 'mm-notices-more';
        more.hidden = true;
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
        column.addEventListener('focusin', () => setPaused(() => { focused = true; }));
        column.addEventListener('focusout', (event) => {
            if (event.relatedTarget && column.contains(event.relatedTarget)) return;
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
        setPaused(() => { focused = Boolean(column?.contains(document.activeElement)); });
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

    setWords(text, html);
    setBar(bar);
    setTone(tone);
    close.hidden = stay;
    notice.appendChild(close);
    theColumn().appendChild(notice);
    count();
    if (!stay) {
        timer = later(remove, TIMING.notice);
        log();
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
            if (stay) log();
        },
        close: () => remove(),
    };
}
