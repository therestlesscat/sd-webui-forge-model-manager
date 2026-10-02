/**
 * Your generations, as a model's gallery and the Generations tab both show
 * them: selecting some to delete, and rating one. Whether they are shown at
 * all is ui_options.mjs's.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { RATING_LEVELS } = await shared('nsfw.mjs');

// ------------------------------------------------------ selecting to delete
// "Select", beside "Rate", where your generations are shown (the Generations
// tab, a model's Your generations): a tick on each batch and image, and one
// Delete for all of them - asked once. A batch's tick is the whole
// generation, as its own Delete: every image, those the NSFW filter hides
// too, which the question counts.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * The bar Select shows: how many images, Select all loaded, Clear, Delete.
 * `calls` names the window functions each button runs.
 */
export function selectBarHtml(images, calls) {
    return `<span class="mm-select-count">${plural(images, 'image')} selected</span>
        <button type="button" class="mm-btn secondary mm-btn-small" onclick="${calls.all}">Select all loaded</button>
        <button type="button" class="mm-btn secondary mm-btn-small" onclick="${calls.clear}"
                ${images ? '' : 'disabled'}>Clear</button>
        <button type="button" class="mm-btn danger mm-btn-small" onclick="${calls.delete}"
                ${images ? '' : 'disabled'}>Delete...</button>`;
}

/** What the one Delete asks: "Delete 37 images of 12 generations? (3 of them hidden by the NSFW filter)". */
export function bulkDeleteQuestion(images, generations, hidden = 0) {
    return `Delete ${plural(images, 'image')} of ${plural(generations, 'generation')}?`
        + (hidden ? ` (${hidden} of them hidden by the NSFW filter)` : '');
}

/**
 * Delete these generations whole and these images, in one request; the
 * server's answer ({success, images, deleted_files, failed}), or
 * {success: false, error}.
 */
export async function deleteManyGenerations({ generationIds = [], imageIds = [], withFiles = false }) {
    try {
        const response = await fetch('/model-manager/generations/delete-many', {
            method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ generation_ids: generationIds.join(','), image_ids: imageIds.join(','),
                                        delete_files: String(Boolean(withFiles)) }) });
        return await response.json();
    } catch (error) {
        return { success: false, error: error.message };
    }
}

/** What a finished Delete says. */
export function bulkDeleteReport(data, withFiles) {
    const failed = (data.failed || []).length;
    return `Deleted ${plural(data.images || 0, 'image')}`
        + (withFiles ? ` and ${plural(data.deleted_files || 0, 'file')}` : '; the image files are still on disk')
        + (failed ? `; ${failed} file${failed === 1 ? '' : 's'} could not be deleted` : '');
}

/**
 * A row of the levels one can rate an image of one's own, the one it has
 * marked: outlined when it is its prompt's, filled when it is a person's
 * rating. `of` is an image - its mm_level and user_level - or something
 * holding several, with the level and user_level they share, if they do.
 * `call` is the click, % standing for the level. Both tabs that show your
 * generations draw it.
 */
export function ratingRowHtml(of, call) {
    const level = of.mm_level ?? of.level;
    const mine = of.user_level;
    return `<div class="mm-rate" title="NSFW level: click to rate, click your rating again to clear it">
        ${RATING_LEVELS.map(([value, name]) => `<button type="button" class="mm-rate-chip${
            level === value ? ' mm-rate-current' : ''}${mine === value ? ' mm-rate-mine' : ''}"
            onclick="event.stopPropagation(); ${call.replace('%', value)}">${name}</button>`).join('')}
    </div>`;
}
