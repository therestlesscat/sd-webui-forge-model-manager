/**
 * Every dialog the extension shows, in two layers (#292).
 *
 * The container, openDialog: any dialog - its content its own - behaves the
 * same. It is the browser's own <dialog>, opened as modal, so it shows above
 * everything, the last opened on top, and nothing behind it can be clicked or
 * tabbed into. The page is held while any is open. Esc and a click beside it
 * close the top one alone, and the key goes no further: the viewer and the
 * tabs behind never see it. Focus goes in on opening and back on closing. The
 * caller can turn Esc or the click beside it off, run a check before any
 * close, name where focus goes, and be told how it closed.
 *
 * The question, ask: a short dialog that lays out its own content from parts
 * handed to it as data, never markup - a title, a message, a list, one tick
 * box, choices, a note, buttons - always in that order and drawn the same
 * way. No templates: the caller picks the parts and the buttons in its own
 * order; a button is a label, the value it answers with and a type (primary,
 * secondary, danger). By convention Cancel comes first, so the default focus,
 * the first button, is the safe one. The progress popup, showProgress, is a
 * question with no buttons that only its caller closes.
 *
 * Before #292 a question was the browser's confirm() - which held every
 * script on the page while open - or one of four hand-built backdrops, each
 * with its own Esc and click handling, none holding the page or moving focus.
 *
 * It does nothing as it is imported, and listens only on its own dialogs.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, holdPage } = await shared('core.mjs');

const opened = [];    // the container's dialogs open, the last on top
// The closes a dialog's check before closing is asked about: the person's.
const ASKED = ['escape', 'outside', 'cancel'];
let made = 0;         // for each question's title id

/**
 * Whether a question or a dialog is showing over the page - one open, not one
 * waiting in the markup: the Model Manager keeps its sync window there, closed,
 * and all three tabs are one page, so asking only whether one exists found
 * them always, and the viewer's keys never worked. A ⋯ menu counts too.
 */
export function dialogShowing() {
    if (opened.length) return true;
    return Array.from(document.querySelectorAll('.gen-menu'))
        .some((element) => element.isConnected && !element.hidden && element.style.display !== 'none');
}

/**
 * Open `element`, a <dialog>, as modal: the container's behaviour, its
 * content untouched. One not on the page is added to its body.
 *
 * @param {HTMLDialogElement} element
 * @param {object} [options]
 * @param {boolean} [options.escape] - Esc closes it (true).
 * @param {boolean} [options.outside] - a click beside it closes it (true).
 * @param {Function} [options.beforeClose] - asked before Esc, a click beside it
 *   or the caller's close('cancel') - its own × or Cancel - closes it, with how;
 *   false, or a promise of false, keeps it open. Any other close - a save, a
 *   stopped tab: close('code') - is not asked.
 * @param {Element|Function} [options.focus] - what takes focus on opening; else the first button.
 * @param {Element|null} [options.returnFocus] - where focus goes on closing; else what had it on opening.
 * @param {Function} [options.onClose] - told it closed, and how: 'escape', 'outside', or the caller's word.
 * @returns {{ element: HTMLDialogElement, close: Function }} close(how), true once closed.
 */
export function openDialog(element, { escape = true, outside = true, beforeClose = null, focus = null,
                                      returnFocus, onClose = null } = {}) {
    const opener = document.activeElement;
    // Opened by an Esc press - the settings window asks "Discard?" on Esc -
    // that press is spent: the browser would take it as this dialog's cancel
    // too, and close it as it showed.
    const pressed = globalThis.window?.event;
    if (pressed?.type === 'keydown' && pressed.key === 'Escape') pressed.preventDefault();
    // The stylesheet's for every dialog it opens: the backdrop, the browser's own box cleared.
    element.classList.add('mm-layer');
    if (!element.isConnected) document.body.appendChild(element);
    let asking = false;
    let closed = false;

    const handle = { element, close: (how = 'code') => close(how) };

    // Esc reaches the dialog as its cancel: taken here, so the check before
    // closing runs and the dialog closes as every other way does.
    const onCancel = (event) => {
        event.preventDefault();
        if (escape) close('escape');
    };
    // The key itself stops at the dialog: the viewer and the tabs listen for
    // Esc on the page, and closed what lay behind it as well.
    const onKey = (event) => {
        if (event.key === 'Escape') event.stopPropagation();
    };
    // The dialog's own box fills it; a click landing on the dialog itself is
    // on the backdrop beside the box.
    const onClick = (event) => {
        if (outside && event.target === element) close('outside');
    };
    // Focus that falls out of it to nowhere - the control that had it
    // disabled, as Sync images' Start is while its folders load, or drawn
    // again - comes back to the dialog itself: on the page, Tab walked on and
    // Esc reached the WebUI's own handler, which interrupts a generation.
    const onFocusOut = (event) => {
        if (event.relatedTarget) return;
        setTimeout(() => {
            if (closed || element.contains(document.activeElement)) return;
            focusSelf();
        }, 0);
    };
    const focusSelf = () => {
        if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1');
        element.focus?.();
    };
    // The browser closed it without asking - Chrome may not let a cancel be
    // held back twice in a row: tidy up, or open again one that must stay.
    const onNativeClose = () => {
        if (closed) return;
        if (!escape) {
            element.showModal();
            return;
        }
        finish('escape');
    };

    // Closed at once when the check answers at once - nothing unsaved - so a
    // window opened again straight after finds it closed; awaited only when
    // the check asks a question. A close by code - a save, a stopped tab -
    // does not wait for a check still asking: that answer then finds it closed.
    function close(how) {
        if (closed || (asking && ASKED.includes(how))) return Promise.resolve(false);
        const go = beforeClose && ASKED.includes(how) ? beforeClose(how) : true;
        if (typeof go?.then !== 'function') return Promise.resolve(go === false ? false : (finish(how), true));
        asking = true;
        return go.then((answer) => answer, () => false).then((answer) => {
            asking = false;
            if (answer === false || closed) return false;
            finish(how);
            return true;
        });
    }

    function finish(how) {
        closed = true;
        element.removeEventListener('cancel', onCancel);
        element.removeEventListener('keydown', onKey);
        element.removeEventListener('click', onClick);
        element.removeEventListener('close', onNativeClose);
        element.removeEventListener('focusout', onFocusOut);
        if (element.open) element.close();
        const at = opened.indexOf(handle);
        if (at >= 0) opened.splice(at, 1);
        holdPage('dialogs', opened.length > 0);
        const back = returnFocus === undefined ? opener : returnFocus;
        if (back?.isConnected) back.focus?.({ preventScroll: true });
        onClose?.(how);
    }

    element.addEventListener('cancel', onCancel);
    element.addEventListener('keydown', onKey);
    element.addEventListener('click', onClick);
    element.addEventListener('close', onNativeClose);
    element.addEventListener('focusout', onFocusOut);
    element.showModal();
    opened.push(handle);
    holdPage('dialogs', true);
    // The caller's choice, unless it cannot take focus yet - Sync images'
    // Start, disabled while its folders load: then the dialog itself, which
    // no redraw of its content takes away. A button in the folder list did:
    // the list was drawn again, and focus fell to the page behind.
    const named = typeof focus === 'function' ? focus() : focus;
    if (named?.disabled) {
        focusSelf();
    } else {
        (named || element.querySelector('button:not([disabled])'))?.focus?.();
    }
    return handle;
}

/**
 * Ask a question: its parts drawn in this order, as given -
 *
 *   title     one line
 *   message   a paragraph, or several
 *   list      lines, each { text, detail } - the detail quieter, beside it
 *   tick      one box: { label, checked }
 *   choices   options, one picked: [{ label, value, note, checked }]
 *   note      a line under the rest - a string, { text, error }, or a function
 *             of { ticked, choice } giving either, drawn again as they change
 *   buttons   [{ label, value, type, disabled, reason }] - type primary,
 *             secondary or danger; a disabled one says why in its tooltip
 *
 * and `focus`, the value of the button that takes focus (else the first);
 * `outside: false` keeps a click beside it from closing it; `className`
 * names it, for the stylesheet and the suites; `answered`, told the answer
 * as the question closes, before anything else runs - the promise resolves a
 * moment later, and a caller that may be asked again meanwhile needs it then.
 *
 * @returns {Promise<{ value, ticked, choice }|null>} null for Esc or a click
 *   beside it. The promise also has redraw(parts), which changes the parts of
 *   a question still open, and close().
 */
export function ask(parts) {
    let spec = { ...parts };
    const element = document.createElement('dialog');
    const id = `mm_question_${made += 1}`;
    element.className = ['mm-question', spec.className].filter(Boolean).join(' ');
    element.setAttribute('aria-labelledby', id);
    const state = {
        ticked: Boolean(spec.tick?.checked),
        choice: (spec.choices || []).find((c) => c.checked)?.value ?? spec.choices?.[0]?.value ?? null,
    };
    let answer = null;
    let handle = null;

    const noteHtml = () => {
        const said = typeof spec.note === 'function' ? spec.note({ ...state }) : spec.note;
        const note = typeof said === 'string' ? { text: said } : said;
        if (!note?.text) return '';
        return `<p class="mm-question-note${note.error ? ' mm-question-error' : ''}">${escapeHtml(note.text)}</p>`;
    };

    function draw() {
        const message = [].concat(spec.message ?? []).filter(Boolean);
        const buttons = spec.buttons || [];
        element.innerHTML = `<div class="mm-dialog mm-question-box">
            ${spec.busy ? '<div class="mm-sync-spinner"></div>' : ''}
            ${spec.title ? `<h3 id="${id}">${escapeHtml(spec.title)}</h3>` : ''}
            ${message.map((p) => `<p class="mm-question-message">${escapeHtml(p)}</p>`).join('')}
            ${spec.list?.length ? `<ul class="mm-question-list">${spec.list.map((item) => `<li>
                <span>${escapeHtml(item.text)}</span>${item.detail
                    ? ` <span class="mm-question-detail">${escapeHtml(item.detail)}</span>` : ''}</li>`).join('')}</ul>` : ''}
            ${spec.tick ? `<label class="mm-question-tick"><input type="checkbox" data-tick${
                state.ticked ? ' checked' : ''}> <span>${escapeHtml(spec.tick.label)}</span></label>` : ''}
            ${spec.choices?.length ? `<div class="mm-question-choices">${spec.choices.map((c, i) => `
                <label class="mm-dialog-option"><input type="radio" name="${id}_choice" data-choice="${i}"
                    value="${escapeHtml(String(c.value))}"${
                    c.value === state.choice ? ' checked' : ''}>
                    <span>${escapeHtml(c.label)}</span>${c.note
                        ? `<span class="mm-dialog-cost">${escapeHtml(c.note)}</span>` : ''}</label>`).join('')}</div>` : ''}
            <div class="mm-question-note-slot">${noteHtml()}</div>
            ${buttons.length ? `<div class="mm-dialog-buttons">${buttons.map((b, i) => `<button type="button"
                class="mm-btn ${b.type === 'primary' || b.type === 'danger' ? b.type : 'secondary'}" data-answer="${i}"
                data-value="${escapeHtml(String(b.value))}"${b.disabled ? ' disabled' : ''}${
                    b.reason ? ` title="${escapeHtml(b.reason)}"` : ''}>${escapeHtml(b.label)}</button>`).join('')}</div>` : ''}
        </div>`;
    }

    // The button named by `focus`, else the first that can be pressed.
    const focused = () => {
        const buttons = spec.buttons || [];
        const at = buttons.findIndex((b) => b.value === spec.focus && !b.disabled);
        return at >= 0 ? element.querySelector(`[data-answer="${at}"]`) : null;
    };

    // The tick box and the choice as the page has them: what the answer and
    // the note go by, whether a click or code set them.
    const read = () => {
        const tick = element.querySelector('[data-tick]');
        if (tick) state.ticked = Boolean(tick.checked);
        const picked = Array.from(element.querySelectorAll('[data-choice]')).find((radio) => radio.checked);
        if (picked) state.choice = spec.choices[Number(picked.getAttribute('data-choice'))]?.value ?? null;
    };

    element.addEventListener('change', () => {
        read();
        if (typeof spec.note === 'function') {
            element.querySelector('.mm-question-note-slot').innerHTML = noteHtml();
        }
    });
    element.addEventListener('click', (event) => {
        const button = event.target.closest?.('[data-answer]');
        if (!button || button.disabled) return;
        read();
        answer = { value: spec.buttons[Number(button.getAttribute('data-answer'))].value, ...state };
        handle?.close('answer');
    });

    draw();
    const promise = new Promise((resolve) => {
        handle = openDialog(element, {
            escape: spec.escape !== false,
            outside: spec.outside !== false,
            focus: focused,
            onClose: () => {
                element.remove();
                spec.answered?.(answer);
                resolve(answer);
            },
        });
    });
    promise.redraw = (next) => {
        // The button that had focus keeps it, by its value, if it is still there.
        const had = element.contains(document.activeElement)
            ? document.activeElement.getAttribute?.('data-value') : null;
        spec = { ...spec, ...next };
        draw();
        const again = had === null ? null
            : Array.from(element.querySelectorAll('[data-value]')).find((b) => b.getAttribute('data-value') === had);
        (again || focused() || element.querySelector('button:not([disabled])'))?.focus?.();
    };
    promise.close = () => handle?.close('code');
    return promise;
}

/**
 * The progress popup: a message and a turning circle, which Esc and a click
 * beside it leave open. say(text) changes the message; close() closes it.
 */
export function showProgress(text) {
    const question = ask({ message: text, busy: true, buttons: [], escape: false, outside: false,
                           className: 'mm-progress' });
    return {
        say: (next) => question.redraw({ message: next }),
        close: () => question.close(),
    };
}
