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

/** Say on a tab's Save Search button what happened, for a moment. */
export function flashSaveSearch(buttonId, text) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.textContent = text;
    setTimeout(() => { btn.textContent = 'Save Search'; }, 1500);
}

/**
 * Trained or merged is a question only checkpoints answer: a tab's
 * checkpoint-type filter (`<prefix>_checkpoint_type`) is usable only while its
 * Type (`<prefix>_type`) is Checkpoint.
 *
 * Disabled rather than hidden, so the filter bar keeps its shape and the
 * control explains itself when it cannot be used.
 */
export function syncCheckpointType(prefix) {
    const typeSelect = document.getElementById(`${prefix}_type`);
    const checkpointType = document.getElementById(`${prefix}_checkpoint_type`);
    if (!typeSelect || !checkpointType) return;

    const applies = typeSelect.value === 'Checkpoint';
    checkpointType.disabled = !applies;
    checkpointType.title = applies
        ? 'Show only trained checkpoints, or only merges'
        : 'Only applies when Type is Checkpoint';
    checkpointType.closest('.filter-group')?.classList.toggle('filter-disabled', !applies);
}
