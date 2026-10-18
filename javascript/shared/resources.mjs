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
const { TIMING, apiCall, escapeHtml, dataAttributes, formatBytes, safeId, safeUrl } = await shared('core.mjs');
const { ON_ITS_WAY, downloads, downloadState, onItsWay, whenDownloading } = await shared('downloads.mjs');
const { openMetaModal, closeMetaModal, closeViewer } = await shared('viewer.mjs');
const { available, open } = await shared('loading.mjs');

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
                // The file it names, not only its version: a version can hold
                // an fp16 and an fp32 file, and only one made the image (#233).
                hash,
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

// What the opener does before View takes the page to another tab: note its
// Previous Position (#250, #260). Replaced with each dialog.
let resourcesLeaving = null;

// A send stopped for its checkpoint (send.mjs), as the dialog's own Send:
// { why, reason, waits, check, run, ready }. `reason` says why it waits -
// `missing`, `not_listed`... - and `why` in words, from `waits`; `check()`
// asks the server again, resolving to '' once the checkpoint can be loaded,
// else the reason; `run()` sends. No `check`: nothing the dialog offers can
// help. `gaveUp`: the dialog stopped asking, the checkpoint still not ready.
let resourcesSend = null;
// The dialog's resources, as last drawn: Send's line finds the checkpoint's row in them.
let resourcesRows = [];
// Send's bar as last drawn, so a redraw that would change nothing writes nothing.
let drawnSendBar = '';

/**
 * The Resources dialog for an image - a Civitai image, or one of your own.
 * `note`, if given, is said at the top: a send stopped for a checkpoint the
 * library lacks opens it, to download it there (#134) - or, with another
 * file of its version held, to send with that (`send.useInstalled`). `send` adds a Send
 * at the bottom, disabled until the checkpoint can be loaded - asked again
 * once downloads land, or at once with `recheck`. `leaving`, if given, is
 * called as View leaves for the Civitai Browser: the opener notes its place.
 *
 * @returns {Promise<boolean>} whether there was anything to show
 */
export async function showImageResources(img, exclude, { note = '', send = null, recheck = false,
                                                         leaving = null } = {}) {
    if (!img || !img.meta) return false;

    const civitai = img.meta.civitaiResources || [];
    const legacy = img.meta.resources || [];
    if (civitai.length === 0 && legacy.length === 0) return false;

    resourcesNote = note;
    resourcesSend = send ? { ...send, ready: false } : null;
    resourcesLeaving = leaving;
    const request = ++resourcesRequest;
    const stillWanted = () => request === resourcesRequest
        && !!document.querySelector('.mm-resources-modal');

    // Up straight away, with whatever needs no lookup, because an uncached
    // hash takes a moment and a dialog that opens late reads as a dead button.
    const hashes = imageResourceHashes(img);
    const first = mergeImageResources(img, knownHashes, !hashes.length, exclude);
    renderResourcesModal(first, hashes.length);
    checkInstalledResources(first.known);
    askCivitaiModels(first.known);
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
        askCivitaiModels(merged.known);
    }
    return true;
}

function renderResourcesModal(resources, pending = 0) {
    resourcesRows = resources.known;
    const rows = resources.known.map(resource => `
            <tr>
                <td class="mm-res-type">${escapeHtml(resource.type)}</td>
                <td class="mm-res-name" data-res-name="${safeId(resource.versionId)}">${resourceNameHtml(resource)}</td>
                <td class="mm-res-actions">
                    <span data-res-view="${safeId(resource.versionId)}">${viewCell(resource)}</span>
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

    drawnSendBar = sendAgainButton();
    const modalHtml = `
        <dialog class="mm-window" id="mm_meta_modal">
            <div class="mm-modal mm-resources-modal">
                <div class="mm-modal-header">
                    <h3>Resources</h3>
                    <button class="mm-modal-close">&times;</button>
                </div>
                <div class="mm-modal-body">
                    ${resourcesNote ? `<div class="mm-banner"><span class="mm-banner-icon">!</span>`
                        + `<span data-res-note>${escapeHtml(noteText())}</span></div>` : ''}
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
                    ${drawnSendBar}
                </div>
            </div>
        </dialog>
    `;

    openMetaModal(modalHtml);
}

/**
 * The dialog's Send, for a send it stopped: disabled, saying why, until ready
 * - or until the person picks what the library has instead: a tick for
 * another file of the checkpoint's version (#233) or one other version of its
 * model, a dropdown for several versions (#278). One Send, whichever it sends with.
 */
function sendAgainButton() {
    if (!resourcesSend) return '';
    const { ready, why, alternative, alternatives, useChecked, chosen } = resourcesSend;
    const canUse = !ready && resourcesSend.useInstalled;
    const offered = canUse && alternative;
    const listed = canUse && !alternative && alternatives?.length > 1;
    const enabled = ready || (offered && useChecked) || (listed && chosen);
    const caution = 'the image may not come out exactly the same';
    const tick = !offered ? ''
        : `<label class="mm-res-use-installed"><input type="checkbox" data-action="resources.useInstalledTick"${
            useChecked ? ' checked' : ''}> `
          + (alternative.kind === 'version'
              ? `Use ${escapeHtml(alternative.label)}, the version I have, instead: ${caution}</label>`
              : `Use the ${escapeHtml(alternative.label)} file I have instead: ${caution}</label>`);
    const pick = !listed ? ''
        : '<label class="mm-res-use-installed mm-res-pick">Send with: <select class="mm-dialog-select" '
          + `data-action="resources.chooseVersion" title="The image may not come out exactly the same.">`
          + `<option value=""${chosen ? '' : ' selected'}>The image's own checkpoint - download it above</option>`
          + alternatives.map((v) => `<option value="${safeId(v.version_id)}"${
              Number(v.version_id) === chosen ? ' selected' : ''}>${escapeHtml(versionLabel(v))}</option>`).join('')
          + '</select></label>';
    const status = enabled ? null : sendStatus();
    const line = status?.text
        ? `<span class="mm-res-send-status">${escapeHtml(status.text)}</span>`
          + (status.again ? '<button type="button" class="mm-btn secondary mm-btn-small" '
                            + 'data-action="resources.checkAgain">Check again</button>' : '')
        : '';
    return `<div class="mm-dialog-buttons mm-resources-send">${tick}${pick}${line}
                <button type="button" class="mm-btn primary" data-action="resources.sendAgain"${
                    enabled ? '' : ` disabled title="${escapeHtml(why || '')}"`}>Send to txt2img</button>
            </div>`;
}

/**
 * What the stopped Send waits for, said beside it (#211): its tooltip alone
 * said it, and a checkpoint downloaded here read "Downloaded" on its row
 * while Send stayed grey. Its download, then Forge listing it - and once the
 * dialog has stopped asking, that it still waits, with Check again (`again`).
 */
function sendStatus() {
    const { reason, why, gaveUp } = resourcesSend;
    const checkpoint = resourcesRows.find((r) => /checkpoint/i.test(r.type || ''));
    const job = checkpoint && resourceDownload(checkpoint.versionId);
    if (job && ON_ITS_WAY.has(job.status)) return { text: 'Waiting for the checkpoint\'s download to finish…' };
    // Landed, and the check it set off not answered yet: Forge is next. The
    // reason was still the last answer's, and on 7880 the line said "not in
    // your library" for 120 ms beside a row saying Downloaded.
    const landing = job?.status === 'complete' && reason === 'missing' && resourcesSend.checking;
    if (reason === 'not_listed' || landing) {
        return gaveUp ? { text: why, again: true } : { text: 'Waiting for Forge to list the checkpoint…' };
    }
    if (reason === 'missing') {
        const offered = checkpoint && resourceDownloadCell(checkpoint).includes('data-action="resources.download"');
        if (offered) return { text: `${why.replace(/\.$/, '')}: download it above.` };
        return { text: why, again: gaveUp };
    }
    return { text: why || '' };
}

/**
 * Ask the server again whether the stopped send's checkpoint can be loaded,
 * and redraw the dialog's Send: at once, then every TIMING.sendRecheck for
 * TIMING.sendRecheckMax - Forge lists a download only once its refresh is
 * done. Stops when the dialog closes or is opened for another image; stopped
 * by the time with the checkpoint not ready, it has given up (`gaveUp`) until
 * asked again - Check again, or a download landing.
 */
async function recheckSend() {
    const wanted = resourcesSend;
    if (!wanted?.check || wanted.ready || wanted.checking) return;
    wanted.checking = true;
    if (wanted.gaveUp) {
        wanted.gaveUp = false;
        redrawSendBar();
    }
    const until = Date.now() + TIMING.sendRecheckMax;
    try {
        while (resourcesSend === wanted && document.querySelector('.mm-resources-modal')) {
            let reason = wanted.reason;
            try {
                reason = await wanted.check();
            } catch (error) {
                console.warn('[ModelManager] Could not ask again about the checkpoint:', error);
            }
            if (resourcesSend !== wanted) return;
            const why = reason ? wanted.waits?.[reason] || wanted.waits?.missing || wanted.why : '';
            Object.assign(wanted, { reason, why, ready: !reason, gaveUp: Boolean(reason) && Date.now() >= until });
            redrawSendBar();
            if (!reason || wanted.gaveUp) return;
            await new Promise((resolve) => setTimeout(resolve, TIMING.sendRecheck));
        }
    } finally {
        wanted.checking = false;
    }
}
// The dialog's other way out of a stopped send: closed, and sent with what
// the library has - a `file` of the image's version, though not the image's
// own (#233), or another `version` of its model (#278).
function useInstalled(versionId, kind) {
    const send = resourcesSend;
    if (!send?.useInstalled) return undefined;
    closeMetaModal();
    resourcesSend = null;
    return send.useInstalled(versionId, kind);
}

// The dialog's Send: closed, and the image sent again, through every check -
// with what the library has, when that is what is ticked or picked.
function sendAgain() {
    const send = resourcesSend;
    if (!send?.ready && send?.alternative && send.useChecked) {
        return useInstalled(send.alternative.versionId, send.alternative.kind || 'file');
    }
    if (!send?.ready && !send?.alternative && send?.chosen) return useInstalled(send.chosen, 'version');
    if (!send?.ready) return undefined;
    closeMetaModal();
    resourcesSend = null;
    return send.run();
}

// ------------------------------------------- View, in the Civitai Browser
// View showed the version on civitai.com, out of the WebUI. It shows the
// model in the Civitai Browser (#260), by its model id - asked of the server
// where the image's list leaves it out - and says a model Civitai answers
// 404 for is deleted. The website stays the way out where the Civitai
// Browser cannot help.

// What the server says of each version's model, once asked: version id ->
// { modelId }, or { gone: true }. A version it could not answer for is
// absent, and asked about again by the next dialog.
const civitaiModels = new Map();
// The versions being asked about, and all the asking under way: View waits on it.
const askingVersions = new Set();
let modelsAsked = Promise.resolve();
// The version whose View waits on that answer.
let viewing = null;

/**
 * Ask the server what Civitai says of these rows' models - the route the
 * chips ask (resources.missing_files): each version's model id, or gone,
 * only on a 404 for the model alone. One request a dialog; answers kept.
 */
function askCivitaiModels(resources) {
    const versions = resources.filter((r) => r.versionId && !civitaiModels.has(r.versionId)
                                             && !askingVersions.has(r.versionId))
        .map((r) => ({ version_id: r.versionId, model_id: r.modelId || null }));
    if (!versions.length) return modelsAsked;
    for (const { version_id: id } of versions) askingVersions.add(id);
    const asking = (async () => {
        try {
            const response = await fetch('/model-manager/missing-resources', {
                method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ versions: JSON.stringify(versions), hashes: '' }) });
            const data = await response.json();
            if (data && data.success) {
                for (const [id, answer] of Object.entries(data.versions || {})) {
                    civitaiModels.set(Number(id), answer.gone ? { gone: true }
                                                              : { modelId: safeId(answer.model_id) });
                }
            }
        } catch (error) {
            console.warn('[ModelManager] Could not ask Civitai about the resources\' models:', error);
        }
        for (const { version_id: id } of versions) {
            askingVersions.delete(id);
            redrawView(id, resources.find((r) => r.versionId === id));
            if (civitaiModels.get(id)?.gone) redrawResourceDownload(id, resources.find((r) => r.versionId === id));
        }
    })();
    modelsAsked = Promise.all([modelsAsked, asking]);
    return modelsAsked;
}

/** A row's View - or, its model deleted from Civitai, the red words in its place. */
function viewCell(resource) {
    const id = resource.versionId;
    if (civitaiModels.get(id)?.gone) {
        return '<span class="mm-res-state error" title="Civitai no longer has this model">Model deleted from Civitai</span>';
    }
    const title = available('civitaiBrowser') ? 'Show this model in the Civitai Browser tab' : 'Open this version on Civitai';
    const looking = viewing === id;
    return `<button type="button" class="mm-btn secondary mm-btn-small" data-action="resources.view"`
        + `${dataAttributes({ versionId: safeId(id), modelId: resource.modelId ? safeId(resource.modelId) : null })}`
        + ` title="${escapeHtml(title)}"${looking ? ' disabled' : ''}>${looking ? 'Looking up...' : 'View'}</button>`;
}

function redrawView(versionId, resource) {
    const cell = document.querySelector(`.mm-resources-modal [data-res-view="${versionId}"]`);
    if (cell) cell.innerHTML = viewCell(resource || { versionId, modelId: cell.querySelector('[data-model-id]')
        ?.dataset.modelId || null });
}

/**
 * View: the model in the Civitai Browser, at the image's version - the
 * dialog closed, and the viewer under it, the opener's place noted first.
 * With the Civitai Browser off, or no model id to be had, the website.
 */
async function viewResource(versionId, modelId) {
    const website = () => {
        const url = safeUrl(`https://civitai.com/model-versions/${versionId}`);
        if (url) window.open(url, '_blank', 'noopener');
    };
    if (!available('civitaiBrowser')) return website();
    let model = modelId || civitaiModels.get(versionId)?.modelId || null;
    if (!model && askingVersions.has(versionId)) {
        viewing = versionId;
        redrawView(versionId, { versionId, modelId: null });
        await modelsAsked;
        viewing = null;
        redrawView(versionId, { versionId, modelId: null });
        model = civitaiModels.get(versionId)?.modelId || null;
    }
    if (civitaiModels.get(versionId)?.gone) return undefined;
    if (!model) return website();
    const leaving = resourcesLeaving;
    closeMetaModal();
    closeViewer();
    leaving?.();
    return open('civitaiBrowser', 'showModel', `model:${model} version:${versionId}`);
}

// ------------------------------------------- downloading from the dialog
// The dialog's Download used to be a link to Civitai's download URL: the
// right version, but saved wherever the browser saves things, and unknown to
// the library. It now downloads as the Civitai Browser does - into the folder
// for its type, and into the library - the version the image names, or the
// model's newest if that version is gone from Civitai.

// Version ids of the dialog's resources that are in the library.
const installedResourceVersions = new Set();
// The hashes of the files the library holds, of the dialog's resources named by one;
// of those it holds another file of the version of, provably, that file (#233);
// and the image's own file by its hash, as Civitai lists it.
const installedResourceHashes = new Set();
const otherFileHashes = new Map();
const imageFiles = new Map();

/** A file as a person tells it apart from its version's others: "fp32 full, 5.5 GB". */
function fileLabel(file, bytes) {
    const kind = [file?.fp, file?.size].filter(Boolean).join(' ');
    return [kind, bytes ? formatBytes(bytes) : ''].filter(Boolean).join(', ');
}

/** A row's name: the model, its version - and the image's file, with the one the library has instead. */
function resourceNameHtml(resource) {
    const held = resource.hash && !installedResourceHashes.has(resource.hash) && otherFileHashes.get(resource.hash);
    const made = held && imageFiles.get(resource.hash);
    const madeLabel = made ? fileLabel(made, made.size_kb ? made.size_kb * 1024 : 0) : '';
    const version = [resource.versionName, madeLabel].filter(Boolean).join(' · ');
    return `${escapeHtml(resource.name)}${version ? ` <span class="mm-res-version">${escapeHtml(version)}</span>` : ''}`
        + (held ? `<div class="mm-res-held">you have its ${escapeHtml(fileLabel(held, held.file_size) || held.name)} file</div>` : '');
}

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
    const hash = resource.hash || resourceDownloads[id]?.hash || '';
    // Named by a hash, it is not installed while the library provably holds
    // another file of its version - fp16 for the image's fp32 - which would
    // not make the image again. Where that cannot be told, the version is.
    const other = Boolean(hash) && otherFileHashes.has(hash) && !installedResourceHashes.has(hash);
    // Its Download is the image's own file (downloadResource), the row's name says which.
    const held = !other && ((hash && installedResourceHashes.has(hash)) || installedResourceVersions.has(id));
    if (!job && held) {
        return '<span class="mm-res-state installed">Installed</span>';
    }
    // Deleted from Civitai: nothing to download, and the row says so (#260).
    if (!job && civitaiModels.get(id)?.gone) return '';
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
        + `${dataAttributes({ versionId: safeId(id), modelId: modelId ? safeId(modelId) : null, hash: hash || null })}`
        + `${other ? ' title="Download the file this image was made with"' : ''}>Download</button>`;
}

/** Redraw one row's download cell, if the dialog is showing it - and Send's line, which says what the checkpoint's row does. */
function redrawResourceDownload(versionId, resource) {
    const cell = document.querySelector(`.mm-resources-modal [data-res-download="${versionId}"]`);
    if (cell) cell.innerHTML = resourceDownloadCell(resource || { versionId, modelId: null });
    redrawSendBar();
}

/** Mark which of the dialog's versions the library holds, and redraw them. */
async function checkInstalledResources(resources) {
    const ids = resources.map((r) => r.versionId).filter(Boolean);
    if (!ids.length) return;
    const hashes = resources.map((r) => r.hash).filter(Boolean);
    try {
        const data = await apiCall({ endpoint: '/model-manager/image-resources',
                                     params: { version_ids: ids.join(','), hashes: hashes.join(',') } });
        for (const id of Object.keys((data && data.versions) || {})) installedResourceVersions.add(Number(id));
        for (const hash of Object.keys((data && data.hashes) || {})) installedResourceHashes.add(hash.toLowerCase());
        for (const [hash, held] of Object.entries((data && data.other_files) || {})) {
            otherFileHashes.set(hash.toLowerCase(), held);
        }
    } catch (error) {
        console.warn('[ModelManager] Could not check which resources are installed:', error);
    }
    for (const resource of resources) redrawResourceDownload(resource.versionId, resource);
    offerInstalledFile(resources);
    offerOtherVersions(resources).catch((error) =>
        console.warn('[ModelManager] Could not ask which other versions the library holds:', error));
    await labelImageFiles(resources);
}

/**
 * A send stopped for its checkpoint, the library holding another file of its
 * version (#233): the dialog's Send can go with that one, once the person
 * ticks that they want it - the image may not come out exactly the same.
 * The closer match: it takes the place of any other versions offered (#278).
 */
function offerInstalledFile(resources) {
    if (!resourcesSend?.useInstalled) return;
    const resource = resources.find((r) => r.hash && /checkpoint/i.test(r.type || '')
                                           && otherFileHashes.has(r.hash) && !installedResourceHashes.has(r.hash));
    if (!resource) return;
    const held = otherFileHashes.get(resource.hash);
    resourcesSend.alternative = { versionId: resource.versionId, resource, kind: 'file',
                                  label: fileLabel(held, held.file_size) || held.name };
    resourcesSend.alternatives = null;
    redrawSendBar();
    redrawNote();
}

/** A held version as the tick and the dropdown name it: "V17 (SD 1.5)". */
function versionLabel(version) {
    const name = version.version_name || version.file_name || `version ${version.version_id}`;
    return version.base_model ? `${name} (${version.base_model})` : name;
}

/**
 * A send stopped for a checkpoint the library lacks, and no other file of its
 * version held: the versions of its model the library holds, to send with
 * instead (#278) - a tick for one, a dropdown for several. Asked once a
 * dialog, by the model id the image's data or Civitai's answer gives.
 */
async function offerOtherVersions(resources) {
    const send = resourcesSend;
    if (!send?.useInstalled || send.reason !== 'missing' || send.alternative || send.versionsAsked) return;
    const resource = resources.find((r) => r.versionId && /checkpoint/i.test(r.type || '')
                                           && !installedResourceVersions.has(r.versionId)
                                           && !(r.hash && installedResourceHashes.has(r.hash)));
    if (!resource) return;
    let modelId = resource.modelId || civitaiModels.get(resource.versionId)?.modelId;
    if (!modelId && askingVersions.has(resource.versionId)) {
        await modelsAsked;
        modelId = civitaiModels.get(resource.versionId)?.modelId;
    }
    if (!modelId || resourcesSend !== send || send.versionsAsked) return;
    send.versionsAsked = true;
    const answer = await apiCall({ endpoint: '/model-manager/other-versions',
                                   params: { version_id: resource.versionId, model_id: modelId } });
    const versions = (answer?.success && answer.versions) || [];
    // The file of its own version, found meanwhile, is the closer match.
    if (resourcesSend !== send || send.alternative || !versions.length) return;
    send.versionsOf = resource;
    if (versions.length === 1) {
        send.alternative = { versionId: versions[0].version_id, resource, kind: 'version',
                             label: versionLabel(versions[0]) };
    } else {
        Object.assign(send, { alternatives: versions, chosen: null });
    }
    redrawSendBar();
    redrawNote();
}

/** What Civitai says each image file named by a hash is, where the library holds another file of it. */
async function labelImageFiles(resources) {
    for (const resource of resources) {
        if (!resource.hash || !otherFileHashes.has(resource.hash) || imageFiles.has(resource.hash)) continue;
        try {
            const found = await apiCall({ endpoint: '/model-manager/civitai/file-by-hash', params: { hash: resource.hash } });
            if (found?.file?.file_id) imageFiles.set(resource.hash, found.file);
        } catch (error) {
            console.warn('[ModelManager] Could not ask Civitai which file this image used:', error);
        }
        const cell = document.querySelector(`.mm-resources-modal [data-res-name="${safeId(resource.versionId)}"]`);
        if (cell) cell.innerHTML = resourceNameHtml(resource);
        redrawNote();
    }
}

/**
 * The dialog's note: a stopped send's, naming the image's file where another
 * of its version is held - or its version, where other versions are (#278).
 */
function noteText() {
    const alternative = resourcesSend?.alternative;
    const versionsOf = resourcesSend?.versionsOf;
    if (versionsOf && (alternative?.kind === 'version' || (!alternative && resourcesSend.alternatives?.length))) {
        const which = [versionsOf.name, versionsOf.versionName].filter(Boolean).join(' ');
        return `The checkpoint this image was made with, ${which}, is not in your library. `
               + 'Download it here, or send with the version of it you have.';
    }
    const made = alternative && imageFiles.get(alternative.resource.hash);
    if (!made) return resourcesNote;
    const which = [alternative.resource.name, alternative.resource.versionName].filter(Boolean).join(' ');
    return `The checkpoint this image was made with, the ${fileLabel(made, made.size_kb ? made.size_kb * 1024 : 0)} `
           + `file of ${which}, is not in your library. Download it here, or send with the file of it you have.`;
}

function redrawNote() {
    const note = document.querySelector('.mm-resources-modal [data-res-note]');
    if (note && note.textContent !== noteText()) note.textContent = noteText();
}

function redrawSendBar() {
    const box = document.querySelector('.mm-resources-modal .mm-resources-send');
    if (!box) return;
    // Redrawn as each row is - the downloads list's every look: only when it would differ.
    const bar = sendAgainButton();
    if (bar === drawnSendBar) return;
    drawnSendBar = bar;
    box.outerHTML = bar;
}

/** Download a resource into the library: the version the image names, or its model's newest if it is gone. */
export async function downloadResource(versionId, modelId, hash = '') {
    if (!downloads()) return;
    if (onItsWay(versionId)) {
        // Coming already - started in the Civitai Browser, say: followed as
        // it is, not asked for again. It was refused, marked failed and never
        // followed, and stayed failed once it had landed (#119).
        resourceDownloads[versionId] = { modelId, hash, target: versionId };
        followResourceDownloads();
        redrawResourceDownload(versionId, { versionId, modelId });
        announceDownloads();
        return;
    }
    resourceDownloads[versionId] = { modelId, hash, asking: true };
    redrawResourceDownload(versionId, { versionId, modelId, hash });
    announceDownloads();
    // As every other download is: the downloads list asks for it and follows
    // it, and this follows the list (followResourceDownloads). Named by a
    // hash, the file Civitai lists with that hash is asked for, not the
    // version's primary: another file of the version did not make the image.
    let data;
    try {
        let fileId;
        let listed;
        if (hash) {
            const found = await apiCall({ endpoint: '/model-manager/civitai/file-by-hash', params: { hash } })
                .catch(() => null);
            fileId = found?.file?.file_id || undefined;
            listed = found?.file;
        }
        // No file Civitai lists by the hash - the version deleted, say - is
        // downloaded as before: the version's primary, or the model's newest.
        // One found is queued at once, its name and size the row's (#223).
        data = await downloads().start(modelId, versionId, fileId,
                                       { newerIfGone: !fileId, fileName: listed?.name, sizeKb: listed?.size_kb });
    } catch (error) {
        data = { success: false, error: String(error.message || error) };
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
    if (resourceDownloads[versionId].hash) installedResourceHashes.add(resourceDownloads[versionId].hash);
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
    scope.provide('resources.checkAgain', () => recheckSend());
    scope.provide('resources.view', ({ versionId, modelId }) => viewResource(safeId(versionId), safeId(modelId)));
    scope.provide('resources.download', ({ versionId, modelId, hash }) =>
        downloadResource(safeId(versionId), safeId(modelId), String(hash || '').toLowerCase()));
    scope.provide('resources.chooseVersion', (data, select) => {
        if (!resourcesSend) return;
        resourcesSend.chosen = Number(select?.value) || null;
        redrawSendBar();
    });
    scope.provide('resources.useInstalledTick', (data, box) => {
        if (!resourcesSend) return;
        resourcesSend.useChecked = Boolean(box?.checked);
        redrawSendBar();
    });
    whenDownloading((list) => {
        // Downloads landed, and Forge's list refreshed (downloads.mjs): the
        // checkpoint may be one of them.
        list.onBatchDone(() => recheckSend());
        list.onChange(followResourceDownloads);
    });
}
