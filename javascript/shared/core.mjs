/**
 * What every part of the page uses: how long it waits (TIMING), asking the
 * server, text put in the page safely - escaped, or a description cleaned -
 * copying and opening from a click, and numbers, sizes and dates as a person
 * reads them.
 */

/**
 * How long the page waits, and how often it asks the server how something is
 * going - in one place, so a test can shorten them all before the page loads,
 * with window.mmTiming. In the WebUI they are these.
 */
export const TIMING = Object.freeze({
    poll: 1000,           // downloads and sync progress
    scanPoll: 500,        // Scan Disk progress
    presetSettle: 600,    // no server call after a preset switch this long: done in the page alone
    presetQuiet: 400,     // quiet this long after the last call: Forge has nothing more to send
    presetMax: 15000,     // a server this slow is not waited on further
    estimate: 120,        // the sync dialog's cost, asked once its controls stop changing
    modulesCheck: 300,    // between asks whether Forge took a VAE / Text Encoder change
    modulesCheckMax: 3000, // and how long it is given to
    tabShown: 2000,       // a tab asked to show, at most: Gradio shows it in a moment
    sendRecheck: 1000,    // between asks whether a stopped send's checkpoint can be loaded now
    sendRecheckMax: 10000, // and for how long: Forge lists a download once its refresh is done
    pasteSettle: 100,     // after Forge's paste, before what it does not set: scheduler, modules, hires
    frame: 60,            // a frame of Gradio's: a dropdown opened, an option pressed
    presetFrame: 100,     // between looks at Forge's UI preset while it switches
    scrollSettle: 500,    // a smooth scroll to a gallery's top, at most
    drawRetry: 250,       // between looks for markup Gradio has not drawn yet
    previewWait: 300,     // the settings' card preview, drawn once a field stops changing
    restampPoll: 250,     // a restamp of stored image levels' progress
    ...(typeof window !== 'undefined' && window.mmTiming) || {},
});

export function onReady(callback) {
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(callback, 100);
    } else {
        document.addEventListener('DOMContentLoaded', callback);
    }
}

export async function apiCall({ endpoint, params = {} }) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.append(key, value);
        }
    });
    const response = await fetch(url);
    return response.json();
}

/**
 * Read a stream of newline-delimited JSON, handing each event to `handle` as
 * it comes: the Civitai Browser's filtered search and draw, and every
 * gallery's page (apiCallTelling). What `handle` throws ends it.
 */
export async function readEvents(response, handle) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();          // keep any partial line

        for (const line of lines) {
            if (!line.trim()) continue;
            let evt;
            try {
                evt = JSON.parse(line);
            } catch (e) {
                console.warn('[ModelManager] Bad stream line:', line);
                continue;
            }
            handle(evt);
        }
    }
}

/**
 * apiCall, for an endpoint that says what it waits on before it answers
 * (streams_status, api/common.py): each {text, wait} to `onStatus` as it
 * comes - a turn at Civitai's rate, a retry in Civitai's words - and the
 * answer at the end. `form` sends a POST's fields. A reply that is no
 * stream is read as apiCall reads one.
 */
export async function apiCallTelling({ endpoint, params = {}, form = null, onStatus = () => {} }) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.append(key, value);
        }
    });
    const response = await fetch(url, form
        ? { method: 'POST', body: new URLSearchParams(form).toString(),
            headers: { Accept: 'application/x-ndjson', 'Content-Type': 'application/x-www-form-urlencoded' } }
        : { headers: { Accept: 'application/x-ndjson' } });
    if (!String(response.headers?.get?.('content-type') || '').includes('ndjson')) return response.json();
    let answer;
    await readEvents(response, (event) => {
        if (event.type === 'status') onStatus(event);
        else if (event.type === 'result') answer = event.result;
    });
    if (answer === undefined) throw new Error('the answer stopped before it was complete');
    return answer;
}

/**
 * Make text safe to place in HTML - as content, or inside a quoted attribute.
 *
 * This used to serialize a text node, which escapes & < > and, per the HTML
 * spec, nothing else. Almost every caller puts the result inside a quoted
 * attribute, and a Civitai prompt containing `"` then closed the attribute and
 * added one of its own: `onmouseover`, say. Prompts, tags, trigger words and
 * file names are all written by whoever uploaded them, so quotes are escaped
 * too.
 *
 * Not enough for a script context. An attribute is decoded before its handler
 * runs, so `&#39;` inside an onclick is a quote again by the time JavaScript
 * sees it. Data never goes inside an inline handler: see data-copy and
 * data-open-url below.
 */
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/**
 * Put text in an element, or a title on it, only if it differs. An
 * onAfterUiUpdate callback runs 250 ms after any change to the page, so one
 * that writes the same text again changes the page, and schedules itself
 * again - forever, four times a second, and every extension's callbacks with
 * it (quiet_updates_test.mjs).
 */
// What holds the page still - something open over it - by name. Each of them
// took the class off as it closed, whatever was still open: Show All closed
// over the viewer let the page under it scroll (#122). One set for the page:
// the shared modules are one copy a page.
const holding = new Set();

/**
 * Hold the page still while `who` is open over it, or let it go: the page
 * scrolls again only once nothing holds it. `who`: 'viewer', 'dialog' (the
 * metadata and Resources window), 'settings'.
 */
export function holdPage(who, held) {
    if (held) holding.add(who);
    else holding.delete(who);
    document.body.classList.toggle('mm-modal-open', holding.size > 0);
}

export function setText(element, text) {
    if (element && element.textContent !== text) element.textContent = text;
}

export function setTitle(element, title) {
    if (element && element.title !== title) element.title = title;
}

export function escapeHtml(text) {
    // Nothing is empty; a 0 is "0" - the settings window shows a number
    // field's 0 through this. The one escape for every module (#93).
    if (text === null || text === undefined) return '';
    return String(text).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/**
 * ` data-<key>="<value>"` for each entry, escaped: what an element's
 * data-action reads (shared/calls.mjs). A key is written as dataset reads it
 * back - versionId is data-version-id - and a value left out is not written.
 */
export function dataAttributes(data = {}) {
    return Object.entries(data)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => ` data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${escapeHtml(value ?? '')}"`)
        .join('');
}

/**
 * An id from Civitai, as a number, or null if it is not one.
 *
 * Ids go into URLs and handler calls unquoted, so a string arriving where a
 * number was expected would be code. Civitai sends numbers today; this is so
 * that stays true of what reaches the page, whatever it sends tomorrow.
 */
export function safeId(value) {
    const n = Number(value);
    return Number.isSafeInteger(n) && n > 0 ? n : null;
}

/**
 * The http(s) URL in `value`, or null.
 *
 * Relative URLs are read against Civitai, since that is where the text they
 * come from was written.
 */
export function safeUrl(value, protocols = ['http:', 'https:']) {
    if (!value) return null;
    try {
        const url = new URL(String(value), 'https://civitai.com');
        return protocols.includes(url.protocol) ? url.href : null;
    } catch (e) {
        return null;
    }
}

/**
 * A model description, reduced to formatting.
 *
 * Descriptions are HTML by design, so they cannot be escaped - but they were
 * inserted raw, and the scan also reads them from .civitai.info files other
 * tools write. Anything not on the list goes: tags are unwrapped to their text,
 * and script-bearing ones are dropped with their contents. Only a link's href,
 * an image's src and a title survive as attributes, and only as http(s).
 *
 * Parsed with DOMParser, which is inert. Setting innerHTML on a detached
 * element is not: an <img onerror> fires there too.
 */
const DESCRIPTION_TAGS = new Set([
    'A', 'ABBR', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'DIV', 'EM', 'H1', 'H2',
    'H3', 'H4', 'H5', 'H6', 'HR', 'I', 'IMG', 'LI', 'OL', 'P', 'PRE', 'S', 'SMALL',
    'SPAN', 'STRIKE', 'STRONG', 'SUB', 'SUP', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD',
    'TR', 'U', 'UL',
]);
const DESCRIPTION_DROPPED = new Set([
    'SCRIPT', 'STYLE', 'IFRAME', 'FRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE',
    'FORM', 'INPUT', 'BUTTON', 'TEXTAREA', 'SELECT', 'SVG', 'MATH', 'NOSCRIPT',
    'TEMPLATE', 'AUDIO', 'VIDEO', 'SOURCE',
]);

function cleanDescriptionNode(node) {
    for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === 3) continue;               // text
        if (child.nodeType !== 1) { child.remove(); continue; }   // comments and the rest

        const tag = child.tagName.toUpperCase();
        if (DESCRIPTION_DROPPED.has(tag)) { child.remove(); continue; }

        cleanDescriptionNode(child);

        if (!DESCRIPTION_TAGS.has(tag)) {
            child.replaceWith(...Array.from(child.childNodes));
            continue;
        }

        for (const attr of Array.from(child.attributes)) {
            const name = attr.name.toLowerCase();
            const kept = name === 'title'
                || (tag === 'A' && name === 'href')
                || (tag === 'IMG' && (name === 'src' || name === 'alt'));
            if (!kept) child.removeAttribute(attr.name);
        }

        if (tag === 'A') {
            const href = safeUrl(child.getAttribute('href'), ['http:', 'https:', 'mailto:']);
            if (href) child.setAttribute('href', href);
            else child.removeAttribute('href');
            child.setAttribute('target', '_blank');
            child.setAttribute('rel', 'noopener noreferrer');
        } else if (tag === 'IMG') {
            const src = safeUrl(child.getAttribute('src'));
            if (src) child.setAttribute('src', src);
            else child.remove();
        }
    }
}

export function sanitizeHtml(html) {
    if (!html) return '';
    // A whole document rather than the bare fragment: browsers put a fragment
    // into <body> either way, but not every DOM implementation does.
    const doc = new DOMParser().parseFromString(
        '<!doctype html><html><body>' + String(html) + '</body></html>', 'text/html');
    cleanDescriptionNode(doc.body);
    return doc.body.innerHTML;
}

/**
 * Copying and opening, without putting data inside an onclick.
 *
 * Buttons that used to carry the text in their handler -
 * `writeText(\`${prompt}\`)` ran any ${...} in a prompt - now carry it in a
 * data attribute, which is never executed, and this one listener acts on it.
 * Installed once, on the document, so it covers markup rendered later.
 */
if (typeof document !== 'undefined'
        && typeof document.addEventListener === 'function'
        && !globalThis.__mmDelegatedClicks) {
    globalThis.__mmDelegatedClicks = true;
    document.addEventListener('click', (event) => {
        const target = event.target && event.target.closest
            ? event.target.closest('[data-copy], [data-open-url]')
            : null;
        if (!target) return;

        if (target.hasAttribute('data-open-url')) {
            const url = safeUrl(target.getAttribute('data-open-url'));
            if (url) window.open(url, '_blank', 'noopener');
            return;
        }

        const text = target.getAttribute('data-copy') || '';
        if (navigator.clipboard) navigator.clipboard.writeText(text);

        if (target.tagName === 'BUTTON') {
            const label = target.textContent;
            target.textContent = 'Copied!';
            setTimeout(() => { target.textContent = label; }, 1500);
        } else {
            target.classList.add('mm-copied');
            setTimeout(() => target.classList.remove('mm-copied'), 600);
        }
    });
}

export function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

/** Bytes as a version's files read: "1.99 GB". */
export function formatBytes(bytes) {
    if (!bytes) return 'Unknown';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return bytes + ' B';
}

/** A date as a version's details read it: "Mar 1, 2025". */
export function formatDay(dateStr) {
    if (!dateStr) return 'Unknown';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    } catch {
        return dateStr;
    }
}
