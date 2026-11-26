/**
 * Feedback in every tab's header (#443): a menu of two items, each opening its
 * page in a new browser tab - GitHub's new issue, or the feedback form, which
 * needs no account. Where each leads is the button's own data (ui/header.py),
 * so the repository's address has one source.
 *
 * Its menu is the ⋯ menu's (menu.mjs): a second press of Feedback closes it.
 * It is opened through this service's scope, which closes it when the last tab
 * stops: a tab's own stop closes only the menus it opened.
 *
 * It does nothing as it is imported.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { safeUrl } = await shared('core.mjs');
const { openMenu, closeMenu, closeMenuOf } = await shared('menu.mjs');

// The items' icons: drawn by the menu as they are, so never anything but these.
const ISSUE_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">'
    + '<circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="1.5" fill="currentColor"></circle></svg>';
const FORM_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"'
    + ' stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>'
    + '<line x1="8" y1="9" x2="16" y2="9"></line><line x1="8" y1="13" x2="13" y2="13"></line></svg>';

/** The two items, each opening its address in a new tab, as data-open-url does (core.mjs). */
export function feedbackItems(data) {
    const opener = (address) => () => {
        const url = safeUrl(address);
        if (url) window.open(url, '_blank', 'noopener');
    };
    return [
        { label: 'Create a GitHub issue', icon: ISSUE_ICON, external: true,
          detail: 'Report a bug or ask for a feature, in public. Needs a GitHub account.',
          run: opener(data.issues) },
        { label: 'Send anonymous feedback', icon: FORM_ICON, external: true,
          detail: 'A short form, no account needed. Leave an email only if you want a reply.',
          run: opener(data.form) },
    ];
}

/** Offers the header's Feedback while any tab runs, and closes its menu with the last. */
export function start(scope) {
    scope.provide('feedback.open', (data, button) => {
        if (closeMenuOf(button)) return;      // its own button again: closed
        openMenu(scope, button, feedbackItems(data));
    });
    scope.onStop(() => closeMenu(scope));
}
