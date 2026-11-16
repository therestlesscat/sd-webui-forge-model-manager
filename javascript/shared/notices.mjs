/**
 * Notices: the short messages in the page's corner that say what a Send did
 * or could not do. Send's own until #357 moved them here.
 */

/**
 * A notice in the corner, for twelve seconds. `info` is something to know
 * rather than something wrong: drawn and logged as such.
 */
export function showNotice(text, { info = false, html = null } = {}) {
    const notice = document.createElement('div');
    notice.className = info ? 'mm-notice mm-notice-info' : 'mm-notice';
    // Markup, where it links to a setting (#320); the console gets its words.
    if (html === null) notice.textContent = text;
    else notice.innerHTML = html;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 12000);
    (info ? console.log : console.warn)('[ModelManager]', notice.textContent);
}
