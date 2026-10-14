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
 * The Model Manager had this alone, its place in the browser's storage, so it
 * survives a reload. The Generations and Civitai Images tabs keep theirs in
 * the page's memory: a reload starts their grid from its first part, and an
 * old place would land on other images.
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
 */
export function previousPosition({ id, action, row, before = '', storageKey = '', label = 'ModelManager' }) {
    const store = storageKey ? storageStore(storageKey) : memoryStore();

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
                    btn.textContent = '↓ Previous Position';
                    btn.title = 'Scroll to previous position. Right-click to clear.';
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
     * shown last, not the one it opened on.
     */
    function remember(target) {
        const pos = viewerPageScroll() ?? (window.scrollY || document.documentElement.scrollTop || 0);
        store.set('position', String(pos));
        if (target) store.set('target', target);
        else store.remove('target');
        update();
        console.log(`[${label}] Saved scroll position:`, pos, target || '');
    }

    function restore() {
        const target = store.get('target');
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

    return { remember, update, restore, clear };
}
