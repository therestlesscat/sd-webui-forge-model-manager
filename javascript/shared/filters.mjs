/**
 * What both tabs' filter bars share: base models in order, the file size
 * boxes, and a saved search.
 */

/**
 * Base model names in the order a filter lists them: alphabetical, with
 * 'Other' - a catch-all - at the bottom rather than in the middle.
 */
export function sortBaseModels(values) {
    const named = values.filter(v => v !== 'Other');
    named.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    return values.includes('Other') ? named.concat('Other') : named;
}

/**
 * A file size box's value in GB, or '' when it is empty or not a positive
 * number - which apiCall and the stream both leave out of the request. Both
 * tabs' File Size filters.
 */
export function sizeBound(id) {
    const value = parseFloat(document.getElementById(id)?.value);
    return Number.isFinite(value) && value > 0 ? value : '';
}

// ------------------------------------------------------ saved searches
// A tab's Save Search: one set of filters, kept in the database (the same in
// every browser, and in both WebUIs when they share it).

/** A tab's saved filters, or null: none saved, or the server not answering. */
export async function savedSearch(tab) {
    try {
        const data = await (await fetch(`/model-manager/saved-search?tab=${encodeURIComponent(tab)}`,
                                        { cache: 'no-store' })).json();
        return data && data.success ? data.filters : null;
    } catch (e) {
        return null;
    }
}

/** Save a tab's filters, or forget them with null. Whether the server kept it. */
export async function saveSearch(tab, filters) {
    try {
        const data = await (await fetch('/model-manager/saved-search', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tab, filters }) })).json();
        return Boolean(data && data.success);
    } catch (e) {
        return false;
    }
}
