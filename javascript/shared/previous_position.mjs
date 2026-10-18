/**
 * Previous Position (#250): where a tab's page was when one of its actions
 * took the page to another tab - a Send, a link to the Model Manager or the
 * Civitai Browser - and a button to go back there.
 *
 * The whole WebUI is one page with one scroll. Another tab is shorter, and to
 * come back the person scrolls up to the tab bar, which is not sticky: back in
 * the tab, the page is at its top. The place is noted by the action itself,
 * before it switches - noted on every scroll, the way up to the tab bar would
 * be noted too, and the place kept would be the top. A plain click on the tab
 * bar notes nothing: the person is at the top by then.
 *
 * Every tab keeps its place in the browser's storage, so it survives a
 * reload - the Generations and Civitai Images tabs since #264, in the page's
 * memory before. In those two the place is the tile left, not a height (#264):
 * the Generations tab lists the newest first, so each batch generated after a
 * Send pushes every tile down, and after a reload a grid starts again from its
 * first part. The tile is named by what it shows - the image, its batch, the
 * groups opened to reach it - and found in whatever grid the tab shows: the
 * image itself, or the batch or group that holds it. They still forget it as
 * their grid starts again, but not as the tab starts after a reload.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { viewerPageScroll } = await shared('viewer.mjs');

/** A place kept in the browser's storage, under `key`_position and `key`_target. */
function storageStore(key) {
    const name = (what) => `${key}_${what}`;
    return {
        get: (what) => localStorage.getItem(name(what)),
        set: (what, value) => localStorage.setItem(name(what), value),
        remove: (what) => localStorage.removeItem(name(what)),
    };
}

/** A place kept in the page's memory: gone with a reload. */
function memoryStore() {
    const kept = new Map();
    return {
        get: (what) => (kept.has(what) ? kept.get(what) : null),
        set: (what, value) => kept.set(what, value),
        remove: (what) => kept.delete(what),
    };
}

/**
 * One tab's Previous Position.
 *
 * @param {object} options
 * @param {string} options.id - the button's id.
 * @param {string} options.action - the tab's action that calls `restore`.
 * @param {string} options.row - a selector for where the button goes.
 * @param {string} [options.before] - the id of what it goes before, in that row; else the row's end.
 * @param {string} [options.storageKey] - kept in the browser's storage under this key; else in memory.
 * @param {string} [options.label] - the tab's name in the console's lines.
 * @param {string} [options.text] - what the button says; [options.tip] its tooltip.
 * @param {object} [options.grid] - a tab of tiles' grid, where the place is a tile, found by `seek`:
 *   `count()` tiles loaded, `ids(index)` what a tile is, `parts()` loaded and `more()` to come,
 *   `load()` the next part, `show(index)` the tile brought into view, `status(text)`, and
 *   `view()`, which changes when the grid starts again.
 */
export function previousPosition({ id, action, row, before = '', storageKey = '', label = 'ModelManager',
                                   text = '↓ Previous Position',
                                   tip = 'Scroll to previous position. Right-click to clear.', grid = null }) {
    const store = storageKey ? storageStore(storageKey) : memoryStore();
    let seeking = null;     // the search under way, while there is one
    let stopping = false;   // asked to stop: it ends as its part comes

    function update() {
        const pos = store.get('position');
        let btn = document.getElementById(id);
        if ((pos && parseInt(pos, 10) > 0) || store.get('target')) {
            if (!btn) {
                const buttonsRow = document.querySelector(row);
                if (buttonsRow) {
                    btn = document.createElement('button');
                    btn.id = id;
                    btn.type = 'button';
                    btn.className = 'mm-btn secondary mm-scroll-restore-btn';
                    btn.textContent = text;
                    btn.title = tip;
                    btn.dataset.action = action;
                    btn.oncontextmenu = (e) => {
                        e.preventDefault();
                        clear();
                    };
                    buttonsRow.insertBefore(btn, (before && document.getElementById(before)) || null);
                }
            }
            if (btn) btn.style.display = 'inline-flex';
        } else if (btn) {
            btn.style.display = 'none';
        }
    }

    /**
     * Remember where the page is, before an action takes it to another tab:
     * where it was when the viewer opened, if it is open, as the page is held
     * still while it is. And `target`, a selector for the image or card sent,
     * which the button brings back into view - from the viewer, the image
     * shown last, not the one it opened on. In a tab of tiles, `target` is
     * the tile's ids instead, the innermost first, for `seek`.
     */
    function remember(target) {
        const pos = viewerPageScroll() ?? (window.scrollY || document.documentElement.scrollTop || 0);
        store.set('position', String(pos));
        if (Array.isArray(target) && target.length) store.set('target', JSON.stringify(target));
        else if (typeof target === 'string' && target) store.set('target', target);
        else store.remove('target');
        update();
        console.log(`[${label}] Saved scroll position:`, pos, target || '');
    }

    function restore() {
        const target = store.get('target');
        const ids = grid ? tileIds(target) : null;
        if (ids) {
            if (!seeking) return seek(ids);
            // Pressed while it looks: the button is Stop. Pressed again before
            // the part on its way has come: a new search, once that one ends.
            if (stopping) return seeking.then(() => seek(ids));
            stop();
            return undefined;
        }
        let sent = null;
        try {
            sent = target ? document.querySelector(target) : null;
        } catch (e) { /* not a selector: the position instead */ }
        if (sent) {
            sent.scrollIntoView({ block: 'center', behavior: 'smooth' });
            console.log(`[${label}] Restored to the image sent`);
            return;
        }
        const pos = store.get('position');
        if (pos) {
            window.scrollTo({ top: parseInt(pos, 10), behavior: 'smooth' });
            console.log(`[${label}] Restored scroll position:`, pos);
        }
    }

    /** Forget the place - asked, or as the grid it was noted in goes. */
    function clear() {
        if (store.get('position') === null && store.get('target') === null) return;
        store.remove('position');
        store.remove('target');
        update();
        console.log(`[${label}] Cleared scroll position`);
    }

    /** The ids a tab of tiles noted, or null for a selector or a height. */
    function tileIds(target) {
        try {
            const ids = JSON.parse(target || '');
            return Array.isArray(ids) && ids.length ? ids.map(String) : null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Bring the tile left into view, loading the grid's parts until it is
     * there: up to SEEK_PARTS, then on only if the person says so - a part is
     * a request, and a large library has hundreds. A level shows one kind of
     * tile - groups, batches or images - so the first tile any id names is
     * the one: the image where images are shown, else its batch or group. Not
     * found, the page stays where it is, saying so: a height would land on
     * other images. A new grid meanwhile - a reload, Back - ends the search.
     */
    function seek(ids) {
        seeking = looking(ids).finally(() => {
            seeking = null;
            stopping = false;
        });
        return seeking;
    }

    async function looking(ids) {
        const wanted = new Set(ids);
        const view = grid.view();
        let checked = 0;
        let asked = false;
        let busy = false;
        try {
            for (;;) {
                const count = grid.count();
                for (; checked < count; checked += 1) {
                    if (!grid.ids(checked).some((tileId) => wanted.has(tileId))) continue;
                    grid.status('');
                    grid.show(checked);
                    console.log(`[${label}] Restored to the tile left:`, ids[0]);
                    return;
                }
                if (!grid.more()) {
                    grid.status(NOT_FOUND);
                    return;
                }
                if (grid.parts() >= SEEK_PARTS && !asked) {
                    asked = true;
                    if (!window.confirm(keepLooking(count))) {
                        grid.status('');
                        return;
                    }
                }
                grid.status(`Looking for the image you left: ${count.toLocaleString()} tiles loaded...`);
                if (!busy) busy = showBusy(true);
                const parts = grid.parts();
                await grid.load();
                // A part that did not come - an error, which the status says - is not asked for again.
                if (stopping) {
                    // Said again: the part's own load cleared the status as it came.
                    grid.status(STOPPED);
                    return;
                }
                if (grid.view() !== view || grid.parts() === parts) return;
            }
        } finally {
            if (busy) showBusy(false);
        }
    }

    /** Stop the search, as the button is pressed while it looks: at once on the page, the part on its way let come. */
    function stop() {
        stopping = true;
        showBusy(false);
        grid.status(STOPPED);
        console.log(`[${label}] Stopped looking for the tile left`);
    }

    /**
     * The button while it loads parts: a turning circle, Looking..., and a
     * stop square - pressed, it stops. A tile found in the parts loaded needs
     * none: it comes at once.
     */
    function showBusy(on) {
        const btn = document.getElementById(id);
        if (!btn) return on;
        // Held at its width, so what follows in the row stays put.
        const width = btn.getBoundingClientRect?.().width || 0;
        btn.style.width = on && width ? `${width}px` : '';
        btn.setAttribute('aria-busy', String(on));
        btn.title = on ? BUSY.tip : tip;
        if (!on) {
            btn.textContent = text;
            return on;
        }
        const icon = (name) => {
            const span = document.createElement('span');
            span.className = name;
            span.setAttribute('aria-hidden', 'true');
            return span;
        };
        btn.replaceChildren(icon('mm-btn-spinner'), document.createTextNode(BUSY.text), icon('mm-btn-stop'));
        return on;
    }

    return { remember, update, restore, clear };
}

/** How many parts Previous Position loads looking for its tile before it asks to go on (#264). */
export const SEEK_PARTS = 20;

/** What the button says while it loads parts looking for the image: shorter than Back to image, with room for its two icons. */
const BUSY = { text: 'Looking...', tip: 'Looking for the image you left. Press to stop.' };

const STOPPED = 'Stopped looking for the image you left.';

/** The button in a tab of tiles, where it finds the image left rather than a height (#264). */
export const TILE_BUTTON = {
    text: '↓ Back to image',
    tip: 'Bring the image you left back into view, loading more of the grid if needed. Right-click to clear.',
};

const NOT_FOUND = 'The image you left is not in this view: none of its tiles is it, or holds it.';

function keepLooking(count) {
    return `The image you left is not in the ${count.toLocaleString()} tiles loaded here. `
        + 'Keep loading until it is found? Each further part of the grid is a request to the server.';
}
