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
 * cardPreview.<setting key>. An inline handler in markup reaches only
 * globals, so what markup calls stays on window - the tab's own.
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
