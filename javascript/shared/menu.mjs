/**
 * The ⋯ menu a tile opens (#298): what more can be done with it - its models
 * in another tab - under the button that opened it. The Generations and the
 * Civitai Images tabs both open it; each says what its menu offers, and this
 * module draws, places and closes it.
 *
 * It is measured once drawn and placed inside the window: below the button,
 * else above; growing left from the button's right edge, else right from its
 * left; moved in along an edge where neither side has room; and capped to the
 * window, with a scroll of its own, where it is bigger. Until #298 it was
 * placed by its right edge alone, and ran past the window's left edge and
 * below its bottom.
 *
 * One is open at a time, for the page. A click outside it, Esc, a scroll of
 * the page or a resize of the window closes it: its place is worked out for
 * the moment it opens, and the menu is fixed to the window, not to its tile.
 * A click on its own ⋯ closes it too, through the tab's action
 * (closeMenuOf): the click-away listener leaves that one alone, or it closed
 * the menu and the action opened it again.
 * Its listeners go through the scope of the tab that opened it.
 *
 * It does nothing as it is imported.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml } = await shared('core.mjs');
const { available, unavailableReason } = await shared('loading.mjs');

// Kept from the window's edges; and between the menu and its button.
const MARGIN = 8;
const GAP = 4;

let menu = null;   // the one open: { element, button, scope, away, key, moved }

/**
 * Where a menu of `size` goes beside a button whose box is `button`, in a
 * window `view` wide and tall - all in the window's pixels. Below the button,
 * else above, else moved in from the bottom; its right edge on the button's,
 * growing left, else its left edge on the button's, growing right, else moved
 * in from the right. Bigger than the window less its margins, it is capped
 * there: `maxHeight` and `maxWidth` say so, null when it fits.
 *
 * @returns {{top: number, left: number, maxHeight: ?number, maxWidth: ?number}}
 */
export function placeMenu(size, button, view) {
    const room = { width: Math.max(0, view.width - 2 * MARGIN), height: Math.max(0, view.height - 2 * MARGIN) };
    const width = Math.min(size.width, room.width);
    const height = Math.min(size.height, room.height);

    let top = button.bottom + GAP;
    if (top + height > view.height - MARGIN) {
        const above = button.top - GAP - height;
        top = above >= MARGIN ? above : Math.max(MARGIN, view.height - MARGIN - height);
    }

    let left = button.right - width;
    if (left < MARGIN) {
        left = button.left + width <= view.width - MARGIN ? button.left
            : Math.max(MARGIN, view.width - MARGIN - width);
    }

    // A button partly out of the window - its tile cut by an edge - still
    // leaves the menu inside it.
    top = Math.min(Math.max(top, MARGIN), Math.max(MARGIN, view.height - MARGIN - height));
    left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, view.width - MARGIN - width));

    return { top: Math.round(top), left: Math.round(left),
             maxHeight: size.height > room.height ? Math.round(room.height) : null,
             maxWidth: size.width > room.width ? Math.round(room.width) : null };
}

/** An item that opens another tab: greyed, saying why, while that tab is not available (#184). */
export function tabItem(name, item) {
    return available(name) ? item : { label: item.label, disabled: true, title: unavailableReason(name) };
}

/**
 * The menu, beside `button`: each item a `{ label, run }`, or `{ label,
 * disabled: true, title }` for one greyed with its reason in `title`. Any
 * other menu closes first; with no items, none opens.
 *
 * @param scope   the opening tab's scope: the menu's listeners go through it
 */
export function openMenu(scope, button, items) {
    closeMenu();
    if (!items.length) return;
    const element = document.createElement('div');
    element.className = 'gen-menu';
    element.setAttribute('role', 'menu');
    element.innerHTML = items.map((item, i) => `<button type="button" role="menuitem" data-item="${i}"`
        + `${item.disabled ? ' disabled' : ''}${item.title ? ` title="${escapeHtml(item.title)}"` : ''}>`
        + `${escapeHtml(item.label)}</button>`).join('');
    element.addEventListener('click', (event) => {
        const chosen = event.target.closest?.('[data-item]');
        if (!chosen || chosen.disabled) return;
        closeMenu();
        items[Number(chosen.getAttribute('data-item'))].run();
    });

    // Drawn out of sight at the window's corner, so its own size is what is
    // measured, then placed - all before the browser draws a frame.
    element.style.visibility = 'hidden';
    element.style.top = '0px';
    element.style.left = '0px';
    document.body.appendChild(element);
    const view = { width: window.innerWidth || 0, height: window.innerHeight || 0 };
    const box = button.getBoundingClientRect?.() || { top: 0, bottom: 0, left: 0, right: 0 };
    const measure = () => {
        const rect = element.getBoundingClientRect?.() || {};
        return { width: rect.width || 0, height: rect.height || 0 };
    };
    let place = placeMenu(measure(), box, view);
    if (place.maxWidth !== null) {
        // Narrowed to the window, its items wrap: its height is measured again.
        element.style.width = `${place.maxWidth}px`;
        place = placeMenu(measure(), box, view);
    }
    if (place.maxHeight !== null) element.style.maxHeight = `${place.maxHeight}px`;
    element.style.top = `${place.top}px`;
    element.style.left = `${place.left}px`;
    element.style.visibility = '';

    const away = (event) => {
        if (!element.contains(event.target) && !button.contains?.(event.target)) closeMenu();
    };
    // Caught on the way down, before the tabs' own keys hear it - and the
    // WebUI's, which interrupts a running generation on Esc.
    const key = (event) => {
        if (event.key !== 'Escape') return;
        closeMenu();
        event.preventDefault?.();
        event.stopImmediatePropagation?.();
    };
    // The page's own scroll and the window's size: a scroll inside the menu
    // is the menu's, and never reaches the window.
    const moved = () => closeMenu();
    menu = { element, button, scope, away, key, moved };
    scope.listen(document, 'keydown', key, true);
    scope.listen(window, 'scroll', moved);
    scope.listen(window, 'resize', moved);
    // A moment later, so the click that opened it does not close it - and only
    // while it is still open: an item clicked at once had closed it, and its
    // listener stayed, closing the next menu at a click inside it (#184).
    scope.later(() => {
        if (menu?.away === away) scope.listen(document, 'click', away, true);
    }, 0);
}

/** The menu closed if it was opened from `button` - a second press of its ⋯: says whether it was. */
export function closeMenuOf(button) {
    return Boolean(menu && button && menu.button === button) && closeMenu();
}

/**
 * The menu closed, if one is open - with `scope`, only one that scope opened:
 * a tab switched off closes its own, never the other tab's. Says whether one was.
 */
export function closeMenu(scope = null) {
    if (!menu || (scope && menu.scope !== scope)) return false;
    const open = menu;
    menu = null;
    open.element.remove();
    open.scope.unlisten(document, 'click', open.away, true);
    open.scope.unlisten(document, 'keydown', open.key, true);
    open.scope.unlisten(window, 'scroll', open.moved);
    open.scope.unlisten(window, 'resize', open.moved);
    return true;
}
