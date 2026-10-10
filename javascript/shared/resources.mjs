/**
 * An image's resources - the LoRAs, embeddings and checkpoints its generation
 * data names - and the Resources dialog that lists them (#90): which Civitai
 * versions they are, merged from the two lists the data keeps, whether the
 * library has each, and a Download into it for one it does not. The Model
 * Manager's gallery, your generations and the Civitai Browser open the same
 * dialog, each naming the version its gallery is of (`exclude`), which it
 * leaves out; and the chips under a sent prompt (chips.mjs) use the same
 * lookups and downloads.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, apiCall, escapeHtml, dataAttributes, safeId } = await shared('core.mjs');
const { downloads, downloadState, onItsWay, whenDownloading } = await shared('downloads.mjs');
const { openMetaModal, closeMetaModal } = await shared('viewer.mjs');

// ------------------------------------------- an image's resources, looked up
// Which Civitai versions an image's resource hashes are, and the downloads of
// them under way - the chips' and the Model Manager's Resources dialog's.

/**
 * Turn resource hashes into Civitai versions, a round at a time.
 *
 * The server asks Civitai about a bounded number per request and hands the
 * rest back as `deferred`, so a big image is resolved over several requests
 * instead of one that runs for minutes. onRound is called after each round
 * that leaves work outstanding, so the panel can show what is known so far.
 *
 * Returns every answer the server gave: hash -> { version_id, ... }, where a
 * null version_id means Civitai does not know that hash. A hash missing from
 * the result was never answered - its lookup failed.
 */
export async function resolveResourceHashes(hashes, onRound) {
    const resolved = {};
    let pending = hashes;

    while (pending.length) {
        let data;
        try {
            const response = await fetch('/model-manager/resolve-hashes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'hashes=' + encodeURIComponent(pending.join(',')),
            });
            data = await response.json();
        } catch (e) {
            console.warn('[ModelManager] Could not resolve resource hashes:', e);
            break;
        }
        if (!data.success) break;

        Object.assign(resolved, data.resolved || {});
        const deferred = data.deferred || [];
        // A round that gets nowhere would loop for ever; stop instead.
        if (deferred.length >= pending.length) break;
        pending = deferred;
        if (pending.length && onRound) onRound(resolved, pending.length);
    }

    return resolved;
}

// Every hash answer this page has seen: hash -> { version_id, ... }, as
// resolveResourceHashes() returns them. The answers are the server's too -
// it keeps them - so this only saves asking again within a page load.
export const knownHashes = {};

/** An image's legacy resource hashes, lower-cased and each once. */
export function imageResourceHashes(img) {
    const legacy = (img.meta || {}).resources || [];
    return [...new Set(legacy.map(r => (r.hash || '').toLowerCase()).filter(Boolean))];
}

// Version id (as the image names it) -> what the downloads list cannot say
// of its download: { modelId, asking, target, versionName, substituted,
// refused, held, announced, warned }. `target` is the version downloaded - another,
// when the image's is gone - `refused` the server's no ({ status, error })
// before the list had it, `held` its answer that the library has a
// substitute already. How it is going is the list's (resourceDownload).
export const resourceDownloads = {};

/**
 * Where a resource's download stands, for its chip and its row in the
 * dialog: the record's own word where the list has none, else the list's,
 * as a Download button reads it (downloadState) - with the record's
 * versionName and substituted. Null when nothing was asked, or the list has
 * forgotten the download: a Download again, as the button.
 */
export function resourceDownload(versionId) {
    const job = resourceDownloads[versionId];
    if (!job) return null;
    if (job.refused) return { ...job, ...job.refused };
    if (job.asking) return { ...job, status: 'starting', percent: 0 };
    if (job.held) return { ...job, status: 'complete', percent: 100 };
    const state = downloadState(job.target || versionId);
    return state && { ...job, ...state };
}

// What the tabs and the chips are told, as page events: they import this
// module, so it cannot call them. New hash answers relabel each tab's
// Resources buttons; a download's progress redraws the chips, and one in the
// library has them look again.
function announceHashes() {
    window.dispatchEvent(new Event('mm-resource-hashes'));
}

function announceDownloads({ installed = false } = {}) {
    window.dispatchEvent(new CustomEvent('mm-resource-downloads', { detail: { installed } }));
}

/**
 * Gather an image's resources into one list, without guessing.
 *
 * The generation data names them twice. Civitai's own list carries
 * modelVersionId; the legacy infotext list carries an AutoV2 hash and the
 * filename whoever generated the image had on disk. The two share no key, so
 * the hashes are resolved into version ids and the lists merged on that -
 * never on name similarity, which does not survive contact with real data:
 * "stablydiffuseds_26" is "StablyDiffused's Aesthetic Mix".
 *
 * Anything naming the version whose gallery this is (`exclude`) gets dropped.
 * An image is an example *of* that model, so listing it says nothing - and it
 * is a quarter of all the rows in this library. The Civitai Browser names its
 * own, the version it shows.
 *
 * `finished` says whether every hash has had its answer. Until then a hash
 * with no answer yet is still being looked up, and is left out rather than
 * listed as unknown.
 *
 * Returns { known, unknown }: resources with a Civitai version behind them,
 * and the rest - a filename with no hash, a hash Civitai does not know, or one
 * that could not be checked. Those are shown as they are rather than guessed at.
 */
export function mergeImageResources(img, resolved, finished, exclude) {
    const meta = img.meta || {};
    const civitai = meta.civitaiResources || [];
    const legacy = meta.resources || [];

    const byVersion = new Map();
    for (const resource of civitai) {
        const versionId = resource.modelVersionId;
        if (!versionId || versionId === exclude) continue;
        if (byVersion.has(versionId)) continue;
        byVersion.set(versionId, {
            versionId,
            modelId: resource.modelId || null,
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            versionName: resource.modelVersionName || '',
        });
    }

    const unknown = [];
    const seenUnknown = new Set();
    for (const resource of legacy) {
        const hash = (resource.hash || '').toLowerCase();
        const answered = hash && Object.prototype.hasOwnProperty.call(resolved, hash);
        const match = answered ? resolved[hash] : null;

        if (match && match.version_id) {
            if (match.version_id === exclude) continue;
            if (byVersion.has(match.version_id)) continue;   // Civitai named it already
            byVersion.set(match.version_id, {
                versionId: match.version_id,
                modelId: match.model_id || null,
                type: match.model_type || resource.type || 'Unknown',
                name: match.name || resource.name || 'Unknown',
                versionName: match.version_name || '',
            });
            continue;
        }

        // Asked about, but its answer has not come back yet.
        if (hash && !answered && !finished) continue;

        // No hash, or Civitai has never heard of it, or the lookup failed.
        // Nothing more can be done with these, so they are shown rather than
        // dropped - deduplicated only where they are exactly the same thing.
        const key = hash || ((resource.type || '') + ':' + (resource.name || ''));
        if (seenUnknown.has(key)) continue;
        seenUnknown.add(key);
        unknown.push({
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            reason: !hash ? 'no hash recorded'
                : answered ? 'not on Civitai'
                : 'could not be checked',
        });
    }

    return { known: [...byVersion.values()], unknown };
}

// Which resources panel is current. A slow one - many hashes, no API key -
// must not paint over one opened after it, and it now repaints each round.
let resourcesRequest = 0;

/**
 * What an image's Resources button says, or '' for no button.
 *
 * The count is the panel's own - mergeImageResources() over the hashes
 * answered so far - so the button and the list it opens agree: duplicates
 * counted once, the model this gallery belongs to not at all. It used to add
 * the two lists up raw, and said 5 over a panel of 2, or appeared over an
 * empty one.
 *
 * A hash nobody has looked up yet may turn out to be another resource, a
 * duplicate, or this model, so while any is outstanding the count is a
 * floor: "Resources (2+)", or just "Resources" with none known yet. Opening
 * the panel looks them up, and the button becomes exact.
 */
export function resourceButtonLabel(img, exclude) {
    const meta = img.meta || {};
    if (!(meta.civitaiResources || []).length && !(meta.resources || []).length) return '';

    const pending = imageResourceHashes(img)
        .some(hash => !Object.prototype.hasOwnProperty.call(knownHashes, hash));
    const { known, unknown } = mergeImageResources(img, knownHashes, false, exclude);
    const count = known.length + unknown.length;

    if (pending) return count ? `Resources (${count}+)` : 'Resources';
    return count ? `Resources (${count})` : '';
}

/**
 * Learn what the server already knows about these images' hashes, in one
 * request, and tell the tabs, which relabel their buttons with it. Nothing is
 * asked of Civitai: that happens only when a panel is opened.
 */
export async function learnResourceHashes(images) {
    const unknown = [...new Set(images.flatMap(imageResourceHashes))]
        .filter(hash => !Object.prototype.hasOwnProperty.call(knownHashes, hash));
    if (!unknown.length) return;
    try {
        const response = await fetch('/model-manager/resolve-hashes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'hashes=' + encodeURIComponent(unknown.join(',')) + '&local_only=true',
        });
        const data = await response.json();
        if (!data.success) return;
        Object.assign(knownHashes, data.resolved || {});
        announceHashes();
    } catch (e) {
        console.warn('[ModelManager] Could not read known resource hashes:', e);
    }
}

// What the open dialog says above its list, if anything: why a send opened it.
let resourcesNote = '';

// A send stopped for its checkpoint (send.mjs), as the dialog's own Send:
// { why, check, run, ready }. `why` says why it waits; `check()` asks the
// server again, resolving to '' once the checkpoint can be loaded, else a
// new why; `run()` sends. No `check`: nothing the dialog offers can help.
let resourcesSend = null;

/**
 * The Resources dialog for an image - a Civitai image, or one of your own.
 * `note`, if given, is said at the top: a send stopped for a checkpoint the
 * library lacks opens it, to download it there (#134). `send` adds a Send
 * at the bottom, disabled until the checkpoint can be loaded - asked again
 * once downloads land, or at once with `recheck`.
 *
 * @returns {Promise<boolean>} whether there was anything to show
 */
export async function showImageResources(img, exclude, { note = '', send = null, recheck = false } = {}) {
    if (!img || !img.meta) return false;

    const civitai = img.meta.civitaiResources || [];
    const legacy = img.meta.resources || [];
    if (civitai.length === 0 && legacy.length === 0) return false;

    resourcesNote = note;
    resourcesSend = send ? { ...send, ready: false } : null;
    const request = ++resourcesRequest;
    const stillWanted = () => request === resourcesRequest
        && !!document.querySelector('.mm-resources-modal');

    // Up straight away, with whatever needs no lookup, because an uncached
    // hash takes a moment and a dialog that opens late reads as a dead button.
    const hashes = imageResourceHashes(img);
    const first = mergeImageResources(img, knownHashes, !hashes.length, exclude);
    renderResourcesModal(first, hashes.length);
    checkInstalledResources(first.known);
    if (recheck) recheckSend();
    if (!hashes.length) return true;

    const resolved = await resolveResourceHashes(hashes, (partial, remaining) => {
        Object.assign(knownHashes, partial);
        announceHashes();
        if (stillWanted()) renderResourcesModal(mergeImageResources(img, partial, false, exclude), remaining);
    });
    Object.assign(knownHashes, resolved);
    announceHashes();

    if (stillWanted()) {
        const merged = mergeImageResources(img, resolved, true, exclude);
        renderResourcesModal(merged, 0);
        checkInstalledResources(merged.known);
    }
    return true;
}

function renderResourcesModal(resources, pending = 0) {
    const rows = resources.known.map(resource => `
            <tr>
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name">${escapeHtml(resource.name)}${resource.versionName
                    ? ` <span class="mm-res-version">${escapeHtml(resource.versionName)}</span>` : ''}</td>
                <td class="mm-res-actions">
                    <button type="button" class="mm-btn secondary mm-btn-small" data-open-url="https://civitai.com/model-versions/${safeId(resource.versionId)}">View</button>
                    <span data-res-download="${safeId(resource.versionId)}">${resourceDownloadCell(resource)}</span>
                </td>
            </tr>
        `).join('');

    // Still asking: say how many are left rather than claim there is nothing.
    const stillLooking = pending > 0
        ? `<tr><td colspan="3" class="mm-res-loading">Looking up ${pending} more on Civitai...</td></tr>`
        : '';

    const nothingKnown = pending === 0 && resources.known.length === 0
        ? '<tr><td colspan="3" class="mm-res-loading">Nothing here has a Civitai model behind it.</td></tr>'
        : '';

    const unknownRows = resources.unknown.length
        ? '<tr><td colspan="3" class="mm-res-group">Named in the generation data, but not found on Civitai</td></tr>'
          + resources.unknown.map(resource => `
            <tr class="mm-res-unresolved">
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name">${escapeHtml(resource.name)}</td>
                <td class="mm-res-actions"><span class="mm-res-no-hash">${escapeHtml(resource.reason)}</span></td>
            </tr>
        `).join('')
        : '';

    const modalHtml = `
        <div class="mm-modal-overlay" id="mm_meta_modal">
            <div class="mm-modal mm-resources-modal">
                <div class="mm-modal-header">
                    <h3>Resources</h3>
                    <button class="mm-modal-close">&times;</button>
                </div>
                <div class="mm-modal-body">
                    ${resourcesNote ? `<div class="mm-banner"><span class="mm-banner-icon">!</span>`
                        + `<span>${escapeHtml(resourcesNote)}</span></div>` : ''}
                    <table class="mm-resources-table">
                        <thead>
                            <tr>
                                <th>Type</th>
                                <th>Name</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows}${stillLooking}${nothingKnown}${unknownRows}
                        </tbody>
                    </table>
                    ${sendAgainButton()}
                </div>
            </div>
        </div>
    `;

    openMetaModal(modalHtml);
}

/** The dialog's Send, for a send it stopped: disabled, saying why, until ready. */
function sendAgainButton() {
    if (!resourcesSend) return '';
    const { ready, why } = resourcesSend;
    return `<div class="mm-dialog-buttons mm-resources-send">
                <button type="button" class="mm-btn primary" data-action="resources.sendAgain"${
                    ready ? '' : ` disabled title="${escapeHtml(why || '')}"`}>Send to txt2img</button>
            </div>`;
}

/**
 * Ask the server again whether the stopped send's checkpoint can be loaded,
 * and redraw the dialog's Send: at once, then every TIMING.sendRecheck for
 * TIMING.sendRecheckMax - Forge lists a download only once its refresh is
 * done. Stops when the dialog closes or is opened for another image.
 */
async function recheckSend() {
    const wanted = resourcesSend;
    if (!wanted?.check || wanted.ready || wanted.checking) return;
    wanted.checking = true;
    const until = Date.now() + TIMING.sendRecheckMax;
    try {
        while (resourcesSend === wanted && document.querySelector('.mm-resources-modal')) {
            let why = wanted.why;
            try {
                why = await wanted.check();
            } catch (error) {
                console.warn('[ModelManager] Could not ask again about the checkpoint:', error);
            }
            if (resourcesSend !== wanted) return;
            Object.assign(wanted, { why, ready: !why });
            const box = document.querySelector('.mm-resources-modal .mm-resources-send');
            if (box) box.outerHTML = sendAgainButton();
            if (!why || Date.now() >= until) return;
            await new Promise((resolve) => setTimeout(resolve, TIMING.sendRecheck));
        }
    } finally {
        wanted.checking = false;
    }
}
// The dialog's Send: closed, and the image sent again, through every check.
function sendAgain() {
    const send = resourcesSend;
    if (!send?.ready) return undefined;
    closeMetaModal();
    resourcesSend = null;
    return send.run();
}

// ------------------------------------------- downloading from the dialog
// The dialog's Download used to be a link to Civitai's download URL: the
// right version, but saved wherever the browser saves things, and unknown to
// the library. It now downloads as the Civitai Browser does - into the folder
// for its type, and into the library - the version the image names, or the
// model's newest if that version is gone from Civitai.

// Version ids of the dialog's resources that are in the library.
const installedResourceVersions = new Set();

// What a row says while its download is on its way: the words a Download
// button says (downloads.mjs), with the percent where there is room.
function onItsWayText({ status, percent }) {
    if (status === 'starting') return 'Starting...';
    if (status === 'pending') return 'Queued';
    if (status === 'paused') return `Paused, ${percent}%`;
    if (status === 'finishing') return 'Adding to library...';
    return percent ? `${percent}%` : 'Downloading...';
}

function resourceDownloadCell(resource) {
    const id = resource.versionId;
    const job = resourceDownload(id);
    if (!job && installedResourceVersions.has(id)) {
        return '<span class="mm-res-state installed">Installed</span>';
    }
    if (job && job.status === 'complete') {
        const which = job.substituted ? ` ${escapeHtml(job.versionName || '')} (the image's is gone)` : '';
        return `<span class="mm-res-state installed">Downloaded${which}</span>`;
    }
    if (job && job.status === 'unavailable') {
        return `<span class="mm-res-state error" title="${escapeHtml(job.error || '')}">Not on Civitai</span>`;
    }
    const failed = job && (job.status === 'error' || job.status === 'cancelled');
    if (job && !failed) return `<span class="mm-res-state">${onItsWayText(job)}</span>`;
    // Downloads run with the Model Manager or the Civitai Browser (#182).
    if (!downloads()) return '<span class="mm-res-state">Not in the library</span>';
    const retry = failed
        ? `<span class="mm-res-state error" title="${escapeHtml(job.error || job.status)}">Failed</span> ` : '';
    const modelId = resource.modelId || resourceDownloads[id]?.modelId;
    return `${retry}<button type="button" class="mm-btn primary mm-btn-small" data-action="resources.download"`
        + `${dataAttributes({ versionId: safeId(id), modelId: modelId ? safeId(modelId) : null })}>Download</button>`;
}

/** Redraw one row's download cell, if the dialog is showing it. */
function redrawResourceDownload(versionId, resource) {
    const cell = document.querySelector(`.mm-resources-modal [data-res-download="${versionId}"]`);
    if (cell) cell.innerHTML = resourceDownloadCell(resource || { versionId, modelId: null });
}

/** Mark which of the dialog's versions the library holds, and redraw them. */
async function checkInstalledResources(resources) {
    const ids = resources.map((r) => r.versionId).filter(Boolean);
    if (!ids.length) return;
    try {
        const data = await apiCall({ endpoint: '/model-manager/image-resources',
                                     params: { version_ids: ids.join(',') } });
        for (const id of Object.keys((data && data.versions) || {})) installedResourceVersions.add(Number(id));
    } catch (error) {
        console.warn('[ModelManager] Could not check which resources are installed:', error);
    }
    for (const resource of resources) redrawResourceDownload(resource.versionId, resource);
}

/** Download a resource into the library: the version the image names, or its model's newest if it is gone. */
export async function downloadResource(versionId, modelId) {
    if (!downloads()) return;
    if (onItsWay(versionId)) {
        // Coming already - started in the Civitai Browser, say: followed as
        // it is, not asked for again. It was refused, marked failed and never
        // followed, and stayed failed once it had landed (#119).
        resourceDownloads[versionId] = { modelId, target: versionId };
        followResourceDownloads();
        redrawResourceDownload(versionId, { versionId, modelId });
        announceDownloads();
        return;
    }
    resourceDownloads[versionId] = { modelId, asking: true };
    redrawResourceDownload(versionId, { versionId, modelId });
    announceDownloads();
    // As every other download is: the downloads list asks for it and follows
    // it, and this follows the list (followResourceDownloads).
    let data;
    try {
        data = await downloads().start(modelId, versionId, undefined, { newerIfGone: true });
    } catch (error) {
        data = { success: false, error: String(error) };
    }
    const status = data && data.status;
    const job = resourceDownloads[versionId];
    job.asking = false;
    if (!data || !data.success) {
        // Not found is for good - the version and its model are gone - and
        // is said as such, with nothing to retry; anything else can be.
        job.refused = { status: status === 404 ? 'unavailable' : 'error',
                        error: (data && data.error) || 'Download failed' };
        console.warn(`[ModelManager] Download of version ${versionId} refused: ${job.refused.error}`);
    } else {
        Object.assign(job, { target: data.version_id, versionName: data.version_name,
                             substituted: !!data.substituted });
        // A substitute the library has already: nothing is downloaded.
        if (data.already_installed) {
            job.held = true;
            finishResourceDownload(versionId);
        }
    }
    redrawResourceDownload(versionId, { versionId, modelId });
    announceDownloads();
}

// In the library: the chips look it up, and a stopped send asks again.
function finishResourceDownload(versionId) {
    resourceDownloads[versionId].announced = true;
    installedResourceVersions.add(versionId);
    announceDownloads({ installed: true });
    recheckSend();
}

/**
 * Follow the dialog's downloads in the downloads list, which polls every
 * download at once: each row and chip is redrawn from it, and one that has
 * reached the library is announced, once.
 */
function followResourceDownloads() {
    const followed = Object.entries(resourceDownloads).filter(([, job]) => job.target && !job.refused);
    if (!followed.length) return;
    for (const [id, job] of followed) {
        const state = resourceDownload(id);
        if (state && state.status === 'complete' && !job.announced) finishResourceDownload(Number(id));
        else if (state && (state.status === 'error' || state.status === 'cancelled') && !job.warned) {
            job.warned = true;
            const name = downloads().progress(job.target)?.file_name || `version ${id}`;
            console.warn(`[ModelManager] Download of ${name} failed: ${state.error || state.status}`);
        }
        redrawResourceDownload(Number(id));
    }
    announceDownloads();
}
/**
 * Started by what opens the dialog - Send, an image's card, the Civitai
 * Browser (#182): its Send and Download offered by name, and the downloads
 * list followed once a tab that downloads has started it. It used to start
 * the list itself, as it was imported.
 */
export function start(scope) {
    scope.provide('resources.sendAgain', () => sendAgain());
    scope.provide('resources.download', ({ versionId, modelId }) => downloadResource(safeId(versionId), safeId(modelId)));
    whenDownloading((list) => {
        // Downloads landed, and Forge's list refreshed (downloads.mjs): the
        // checkpoint may be one of them.
        list.onBatchDone(() => recheckSend());
        list.onChange(followResourceDownloads);
    });
}
