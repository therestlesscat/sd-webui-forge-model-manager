/**
 * What one part of the page offers the rest, by name (#94).
 *
 * The tabs and the shared modules used to reach each other through window
 * globals - one tab defining window.mmShowModel, another calling it - and
 * nothing said who offered what, or what a caller got when that tab had not
 * loaded: five callers checked, each its own way, and five did nothing
 * without a word. What a file offers it now provides here, and others call it
 * by name; tests/tools/check_js_references.mjs fails on a file that reads
 * another's window global, and on a call to a name nothing provides.
 *
 * A name is "<area>.<what>": modelManager.showModel, settings.open,
 * cardPreview.<setting key>.
 *
 * Markup asks by name too (#95): a button, a link or a field says what it does
 * in data-action, and carries what that needs in data-* of its own. It used to
 * hold JavaScript - onclick="window.mmSelectModel(3)" - reaching a window
 * global by a name in a string, in the tabs' markup and in their Python alike,
 * that no check followed: a rename broke a button only when it was pressed.
 */

// One map for the page, even if the shared modules ever load twice: without
// the server's version each tab imports its own copy of them (see the top of
// model_manager.mjs), and one tab's offers have to reach the others.
const offered = (globalThis.__mmOffered ||= new Map());

/** Offer `fn` under `name`; offered again, the later one answers. */
export function provide(name, fn) {
    offered.set(name, fn);
}

/** Whether `name` has been offered - its tab has loaded. */
export function ready(name) {
    return offered.has(name);
}

/**
 * Call what was offered under `name`. Nothing offered - its tab has not
 * loaded - is said in the console, and answers undefined.
 */
export function call(name, ...args) {
    const fn = offered.get(name);
    if (!fn) {
        console.warn(`[ModelManager] ${name} is not ready: its tab has not loaded`);
        return undefined;
    }
    return fn(...args);
}

/**
 * One listener for the page calls what markup names - a field on its change,
 * anything else on a click - with the element's other data-* as an object
 * (strings, as markup holds them), the element, and the event: settings.open
 * is { tab } from the gear and from code alike. The innermost action is the
 * one: a card's pin is a button inside the card's own action, and its click
 * pins without opening the card, as event.stopPropagation() in the pin's
 * handler did. Nothing is stopped: the rest of the page sees every click. A
 * stop in the metadata window kept Copy JSON's click from the listener that
 * copies, and the button did nothing (0.44.18 to 0.44.20). An action runs as
 * the click reaches the document, after anything around its element has
 * heard it - where an inline handler ran first: the viewer, closing on Send,
 * waits for the click to be done (shared/viewer.mjs).
 */
function act(event) {
    const element = event.target?.closest?.('[data-action]');
    if (!element) return;
    const field = element.matches('input, select, textarea');
    if (field !== (event.type === 'change')) return;
    if (element.tagName === 'A') event.preventDefault();
    const { action, ...data } = element.dataset;
    call(action, data, element, event);
}

/**
 * The page's one listener, started by the first tab that starts this module
 * (#182). Once for the page, as the map: a second copy of this module would
 * call every action twice.
 */
export function start() {
    if (typeof document === 'undefined' || typeof document.addEventListener !== 'function'
            || globalThis.__mmActing) return;
    globalThis.__mmActing = true;
    document.addEventListener('click', act);
    document.addEventListener('change', act);
}
