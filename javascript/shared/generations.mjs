/**
 * Your generations, as a model's gallery and the Generations tab both show
 * them: a thumbnail, rating one, deleting one or a generation, and selecting
 * some to delete (#89). The two keep different things - a card per
 * generation, tiles at three levels - and each draws its own; what they did
 * alike, each in a copy of its own, is here. Whether they are shown at all is
 * ui_options.mjs's.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { escapeHtml, dataAttributes } = await shared('core.mjs');
const { IMAGE_PLACEHOLDER_SVG, mediaFallback } = await shared('media.mjs');
const { RATING_LEVELS, nsfwBadge } = await shared('nsfw.mjs');

// ------------------------------------------------------ selecting to delete
// "Select", beside "Rate", where your generations are shown (the Generations
// tab, a model's Your generations): a tick on each batch and image, and one
// Delete for all of them - asked once. A batch's tick is the whole
// generation, as its own Delete: every image, those the NSFW filter hides
// too, which the question counts.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * The bar Select shows: how many are picked, Select all, Clear, Delete - and
 * Retry, where `actions` names one: the Queue tab's History. `actions` names
 * what each button does (shared/calls.mjs); `noun` what is counted, `all`
 * what Select all says.
 */
export function selectBarHtml(count, actions, { noun = 'image', all = 'Select all loaded' } = {}) {
    const none = count ? '' : 'disabled';
    return `<span class="mm-select-count">${plural(count, noun)} selected</span>
        <button type="button" class="mm-btn secondary mm-btn-small" data-action="${escapeHtml(actions.all)}">${escapeHtml(all)}</button>
        <button type="button" class="mm-btn secondary mm-btn-small" data-action="${escapeHtml(actions.clear)}"
                ${none}>Clear</button>
        ${actions.retry ? `<button type="button" class="mm-btn secondary mm-btn-small" data-action="${escapeHtml(actions.retry)}"
                ${none}>Retry...</button>` : ''}
        <button type="button" class="mm-btn danger mm-btn-small" data-action="${escapeHtml(actions.delete)}"
                ${none}>Delete...</button>`;
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
 * `action` is what a click does (shared/calls.mjs), with the level as
 * data-level beside `data`. Both tabs that show your generations draw it.
 */
export function ratingRowHtml(of, action, data = {}) {
    const level = of.mm_level ?? of.level;
    const mine = of.user_level;
    return `<div class="mm-rate" title="NSFW level: click to rate, click your rating again to clear it">
        ${RATING_LEVELS.map(([value, name]) => `<button type="button" class="mm-rate-chip${
            level === value ? ' mm-rate-current' : ''}${mine === value ? ' mm-rate-mine' : ''}"
            data-action="${escapeHtml(action)}" data-level="${value}"${dataAttributes(data)}>${name}</button>`).join('')}
    </div>`;
}

// ------------------------------------------------------------ one of them
/**
 * One of your images, as a thumbnail: a placeholder where its file is gone,
 * and its badge - as a Civitai image's card has it (nsfwBadge): from R up, or
 * "X · prompt" where its prompt raised it. It badged only the prompt's.
 * `viewable` marks it for the viewer - the Model Manager's cards open it from
 * the image itself.
 */
export function generationImageHtml(img, { viewable = false } = {}) {
    const url = new URL(img.url || '', window.location.origin).href;
    const level = nsfwBadge(img);
    const badge = level ? `<span class="mm-nsfw-badge">${escapeHtml(level)}</span>` : '';
    const image = img.exists
        ? `<img data-src="${escapeHtml(url)}" class="mm-lazy-media" src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="Generated image" loading="lazy"
                ${mediaFallback('', IMAGE_PLACEHOLDER_SVG)}${viewable ? `
                data-view-generation-image="${Number(img.id)}" title="Click to view"` : ''}>`
        : `<img src="${IMAGE_PLACEHOLDER_SVG}" alt="Image unavailable"
                title="Image unavailable: its file is no longer where it was saved">`;
    return `<div class="mm-generation-tile">${image}${badge}</div>`;
}

/**
 * Rate one of your images, or a generation or a group of them: `fields` are
 * what the server takes (image_id, or the generation and its scope; level;
 * the switches the answer is counted under). The server's answer, or null -
 * and why said through `say`.
 */
export async function requestRating(fields, say) {
    try {
        const body = new URLSearchParams();
        for (const [key, value] of Object.entries(fields)) {
            if (value !== undefined && value !== null) body.set(key, String(value));
        }
        const response = await fetch('/model-manager/generations/rate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        });
        const answer = await response.json();
        if (!answer.success) {
            say(`Could not rate: ${answer.error || 'no answer'}`);
            return null;
        }
        return answer;
    } catch (error) {
        say(`Could not rate: ${error.message}`);
        return null;
    }
}

/** Delete one of your images, with its file or not: the server's answer, or null, said through `say`. */
export function requestImageDelete(imageId, withFiles, say) {
    return requestDelete(`/model-manager/generations/images/${Number(imageId)}/delete`, withFiles, say);
}

/** Delete one generation - its record, and its images' files if asked. */
export function requestGenerationDelete(generationId, withFiles, say) {
    return requestDelete(`/model-manager/generations/${Number(generationId)}/delete`, withFiles, say);
}

async function requestDelete(endpoint, withFiles, say) {
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ delete_files: String(withFiles) }).toString(),
        });
        const data = await response.json();
        if (!data.success) {
            say(`Delete failed: ${data.error || 'unknown error'}`);
            return null;
        }
        return data;
    } catch (error) {
        say(`Delete failed: ${error.message}`);
        return null;
    }
}

/** What a tick picks: from the last one ticked to this, with Shift; this alone without. */
export function pickRange(last, index, shift) {
    return shift && last >= 0 ? [Math.min(last, index), Math.max(last, index)] : [index, index];
}
