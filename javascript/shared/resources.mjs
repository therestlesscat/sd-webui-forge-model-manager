/**
 * An image's resources - the LoRAs, embeddings and checkpoints its generation
 * data names - and the Resources dialog that lists them (#90): which Civitai
 * versions they are, merged from the two lists the data keeps, whether the
 * library has each, and a Download into it for one it does not. The Model
 * Manager's gallery, your generations and the Civitai Browser open the same
 * dialog, each naming the version its gallery is of (`exclude`), which it
 * leaves out - but a checkpoint's, kept as its first row (#377); and the
 * chips under a sent prompt (chips.mjs) use the same
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
const { familyName, fetchUiOptions } = await shared('ui_options.mjs');
const { afterRefreshes } = await shared('forge.mjs');

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

/** An image's legacy resource hashes, lower-cased and each once - those kept apart from their names too. */
export function imageResourceHashes(img) {
    const meta = img.meta || {};
    const legacy = meta.resources || [];
    return [...new Set(legacy.map((r) => String(r.hash || resourceHash(meta, r) || '').toLowerCase()).filter(Boolean))];
}

// What Forge loads through <lora:...>, by the file's own type or Civitai's.
const LORA_TYPES = new Set(['lora', 'locon', 'loha', 'lokr', 'dora', 'lycoris', 'lycoris full']);
const EMBEDDING_TYPES = new Set(['textualinversion', 'embedding', 'embed']);

/** A resource's kind as Forge loads it: 'lora' through <lora:...>, 'embedding' by its word, else null. */
export function resourceKind(type) {
    const value = String(type || '').toLowerCase();
    if (LORA_TYPES.has(value)) return 'lora';
    if (EMBEDDING_TYPES.has(value)) return 'embedding';
    return null;
}

/**
 * A resource's hash from the image's `hashes`, where its own entry has none:
 * Forge writes {"lora:Ghibli_v6": "58549cc3d3"} there and leaves the
 * resources list without them. Some write the kind in capitals - "LORA:",
 * "EMBED:", 5,561 and 35 keys in one library - so its case is ignored; the
 * name after it has to match as written. The chips and the Resources dialog
 * both read it (#377, R4): read beside the name alone, six of one image's
 * seven LoRAs were drawn again under "not found", each a row above.
 */
export function resourceHash(meta, resource) {
    const hashes = (meta && meta.hashes) || {};
    const kind = resourceKind(resource.type);
    const prefixes = kind === 'lora' ? ['lora', 'lyco'] : kind === 'embedding' ? ['embed'] : [];
    for (const [key, hash] of Object.entries(hashes)) {
        const at = key.indexOf(':');
        if (hash && at > 0 && key.slice(at + 1) === resource.name
            && prefixes.includes(key.slice(0, at).toLowerCase())) return hash;
    }
    return '';
}

/** How the prompt names a legacy resource: a LoRA's tag with its weight, an embedding's word. */
function promptTag(resource) {
    const name = String(resource.name || '');
    const kind = resourceKind(resource.type);
    if (!name || !kind) return '';
    if (kind === 'embedding') return name;
    const weight = resource.weight === undefined || resource.weight === null ? '' : `:${resource.weight}`;
    return `<lora:${name}${weight}>`;
}

// A row's kind as a person reads it: Civitai's types and the infotext's words, one spelling each.
const KIND_NAMES = { lora: 'LoRA', locon: 'LoCon', lycoris: 'LyCORIS', dora: 'DoRA', textualinversion: 'Embedding',
                     embed: 'Embedding', embedding: 'Embedding', checkpoint: 'Checkpoint', model: 'Checkpoint',
                     vae: 'VAE', controlnet: 'ControlNet', upscaler: 'Upscaler', hypernetwork: 'Hypernetwork' };
const rowKindName = (type) => KIND_NAMES[String(type || '').toLowerCase()] || String(type || 'Unknown');

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
    // Followed by its file (#374): the one its press was answered with.
    const state = job.file != null ? downloadState(job.file) : null;
    return state && { ...job, ...state };
}

// What the tabs and the chips are told, as page events: they import this
// module, so it cannot call them. New hash answers relabel each tab's
// Resources buttons; a download's progress redraws the chips, and one in the
// library has them look again.
function announceHashes() {
    window.dispatchEvent(new Event('mm-resource-hashes'));
}

function announceDownloads({ installed = false, landed = null } = {}) {
    window.dispatchEvent(new CustomEvent('mm-resource-downloads', { detail: { installed, landed } }));
}

/**
 * The version a download record fetched in place of `versionId` - the
 * model's newest, the image's being gone from Civitai - with its name: the
 * chips look its file up as the image's (#205). Null where the image's own
 * version came, or nothing was asked in this page.
 */
export function substituteOf(versionId) {
    const job = resourceDownloads[versionId];
    return job && job.substituted && !job.refused && job.target
        ? { versionId: job.target, versionName: job.versionName || '' } : null;
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
 * own, the version it shows. But not a checkpoint's (#377): it stays, first,
 * marked `own` - the Send line names it, and an image naming nothing else
 * said "Nothing here has a Civitai model behind it".
 *
 * `finished` says whether every hash has had its answer. Until then a hash
 * with no answer yet is still being looked up, and is left out rather than
 * listed as unknown.
 *
 * Returns { known, unknown, checkpointAside }: resources with a Civitai version
 * behind them, and the rest - a filename with no hash, a hash Civitai does not
 * know, or one that could not be checked. Those are shown as they are rather
 * than guessed at. `checkpointAside`: the image's checkpoint's hash has had no
 * answer yet.
 */
export function mergeImageResources(img, resolved, finished, exclude) {
    const meta = img.meta || {};
    const civitai = meta.civitaiResources || [];
    const legacy = meta.resources || [];

    const byVersion = new Map();
    // Whether a checkpoint's hash has no answer yet: the dialog draws no row for it as text
    // (withNamedCheckpoint) - the row said "named only by its name" for a checkpoint it knew.
    let checkpointAside = false;
    for (const resource of civitai) {
        const versionId = resource.modelVersionId;
        if (!versionId || (versionId === exclude && !isCheckpoint(resource.type))) continue;
        if (byVersion.has(versionId)) continue;
        byVersion.set(versionId, {
            versionId,
            modelId: resource.modelId || null,
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            versionName: resource.modelVersionName || '',
            own: versionId === exclude,
        });
    }

    const unknown = [];
    const seenUnknown = new Set();
    for (const resource of legacy) {
        const hash = String(resource.hash || resourceHash(meta, resource) || '').toLowerCase();
        const answered = hash && Object.prototype.hasOwnProperty.call(resolved, hash);
        const match = answered ? resolved[hash] : null;

        if (match && match.version_id) {
            if (match.version_id === exclude && !isCheckpoint(match.model_type || resource.type)) continue;
            if (byVersion.has(match.version_id)) {   // Civitai named it already: its row takes the prompt's tag
                const row = byVersion.get(match.version_id);
                if (!row.tag) row.tag = promptTag(resource);
                continue;
            }
            byVersion.set(match.version_id, {
                versionId: match.version_id,
                modelId: match.model_id || null,
                type: match.model_type || resource.type || 'Unknown',
                name: match.name || resource.name || 'Unknown',
                versionName: match.version_name || '',
                // The file it names, not only its version: a version can hold
                // an fp16 and an fp32 file, and only one made the image (#233).
                hash,
                tag: promptTag(resource),
                own: match.version_id === exclude,
            });
            continue;
        }

        // Asked about, but its answer has not come back yet.
        if (hash && !answered && !finished) {
            if (isCheckpoint(resource.type)) checkpointAside = true;
            continue;
        }

        // No hash, or Civitai has never heard of it, or the lookup failed.
        // Nothing more can be done with these, so they are shown rather than
        // dropped - deduplicated only where they are exactly the same thing.
        const key = hash || ((resource.type || '') + ':' + (resource.name || ''));
        if (seenUnknown.has(key)) continue;
        seenUnknown.add(key);
        unknown.push({
            type: resource.type || 'Unknown',
            name: resource.name || 'Unknown',
            hash: hash || null,
            tag: promptTag(resource),
            reason: !hash ? 'No hash recorded'
                : answered ? 'Not on Civitai'
                : 'Could not be checked',
        });
    }

    return { known: [...byVersion.values()], unknown, checkpointAside };
}

// Which resources panel is current. A slow one - many hashes, no API key -
// must not paint over one opened after it, and it now repaints each round.
let resourcesRequest = 0;

/**
 * What an image's Resources button says, or '' for no button.
 *
 * The count is the panel's own - mergeImageResources() over the hashes
 * answered so far - so the button and the list it opens agree: duplicates
 * counted once, the model this gallery belongs to not at all - unless it is
 * the image's checkpoint, which the list shows (#377). It used to add
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
 * Resources as an item of a tile's ⋯ menu (#362): labelled as the viewer's
 * button, opening the same dialog. Where the viewer draws no button, greyed,
 * saying why - a press that would do nothing.
 */
export function resourcesMenuItem(img, exclude, { leaving = null, send = null } = {}) {
    const label = resourceButtonLabel(img, exclude);
    // `send`: the Send line's, made when pressed (send.mjs resourcesSendLine, #377).
    if (label) return { label, run: () => showImageResources(img, exclude, { leaving, send: send?.() || null }) };
    const meta = img.meta || {};
    const named = (meta.civitaiResources || []).length || (meta.resources || []).length;
    return { label: 'Resources', disabled: true,
             title: named ? 'This image names no resource but this model' : 'This image\'s data names no resources' };
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

// The dialog's Send line (#377), handed by Send (send.mjs) to every dialog
// but the Civitai Browser's: { opened, why, reason, waits, check, run, pick,
// button, list, goesOn, ready }. `opened` says why the dialog is open - a
// send that `stop`ped for its checkpoint, one that asked to `choose` (the
// tab's box, Send as…), or the `resources` button. `run()` sends with the
// image's own checkpoint, `pick(name, model)` with one picked in the list, by
// Forge's name. `reason` says why the image's own waits - `missing`,
// `not_listed`... - and `why` in words, from `waits`; `check()` asks the
// server again, resolving to '' once it can be loaded; no `check`: nothing
// the dialog offers can help. `gaveUp`: the dialog stopped asking. `goesOn`:
// a send into img2img, which goes with the loaded checkpoint (#299).
// `choosing`: the box ticked; `chosen`: the name picked; `touched`: the box
// pressed, which nothing then changes. `usualSource`: what send/usual is
// asked with for a pick (#378); `usualAnswers`: its answer per name, kept
// while the dialog is open; `usual`: its tick, as the setting says at each
// pick (`usualOn`, read as the dialog opens); `usualPressed`: the tick
// pressed for this pick.
let resourcesSend = null;
// The dialog's resources, as last drawn: Send's line finds the checkpoint's row in them.
let resourcesRows = [];
// What it drew with no Civitai version, and whether a checkpoint's hash had no answer yet:
// the Resources button's box reads a checkpoint Civitai does not know from them.
let resourcesUnresolved = [];
let checkpointPending = false;
// Send's bar as last drawn, so a redraw that would change nothing writes nothing.
let drawnSendBar = '';
// Whether the library has said which of this dialog's resources it holds:
// the Resources button's box waits on it (startBox).
let installedAsked = false;

/**
 * The Resources dialog for an image - a Civitai image, or one of your own.
 * `note`, if given, is said at the top: a send stopped for a checkpoint the
 * library lacks opens it, to download it there (#134). `send` adds the Send
 * line at the bottom (#377): a box that shows your checkpoints to pick from,
 * and Send. `recheck` asks at once whether the image's own can be loaded,
 * as a download landing does. `leaving`, if given, is called as View leaves
 * for the Civitai Browser: the opener notes its place.
 *
 * @returns {Promise<boolean>} whether there was anything to show
 */
export async function showImageResources(img, exclude, { note = '', send = null, recheck = false,
                                                         leaving = null } = {}) {
    if (!img || !img.meta) return false;

    const civitai = img.meta.civitaiResources || [];
    const legacy = img.meta.resources || [];
    // A send opens it whatever the image lists: its Send line is the way on (#377).
    if (civitai.length === 0 && legacy.length === 0 && !send) return false;

    resourcesNote = note;
    installedAsked = false;
    resourcesSend = send ? startSendLine(send) : null;
    resourcesLeaving = leaving;
    const request = ++resourcesRequest;
    const stillWanted = () => request === resourcesRequest
        && !!document.querySelector('.mm-resources-modal');

    // Up straight away, with whatever needs no lookup, because an uncached
    // hash takes a moment and a dialog that opens late reads as a dead button.
    const hashes = imageResourceHashes(img);
    const first = withNamedCheckpoint(img, mergeImageResources(img, knownHashes, !hashes.length, exclude));
    renderResourcesModal(first, hashes.length);
    checkInstalledResources(first.known, first.unknown);
    askCivitaiModels(first.known);
    if (recheck) recheckSend();
    if (!hashes.length) {
        askPickList();
        return true;
    }

    const resolved = await resolveResourceHashes(hashes, (partial, remaining) => {
        Object.assign(knownHashes, partial);
        announceHashes();
        if (stillWanted()) {
            renderResourcesModal(withNamedCheckpoint(img, mergeImageResources(img, partial, false, exclude)), remaining);
        }
    });
    Object.assign(knownHashes, resolved);
    announceHashes();

    if (stillWanted()) {
        const merged = withNamedCheckpoint(img, mergeImageResources(img, resolved, true, exclude));
        renderResourcesModal(merged, 0);
        checkInstalledResources(merged.known, merged.unknown);
        askCivitaiModels(merged.known);
        askPickList();
    }
    return true;
}

/** A row's type, read as a checkpoint's: Civitai's "Checkpoint", the infotext's "model". */
const isCheckpoint = (type) => /^(checkpoint|model)$/i.test(String(type || ''));

/**
 * The dialog's rows, with one for a checkpoint the image names only as text
 * (`Model`, #377 case 1) where no row, found or not, is a checkpoint already:
 * it drew none, and the stop pointed at nothing. Drawn by the dialog alone -
 * not in mergeImageResources, which each tile's Resources button counts.
 */
function withNamedCheckpoint(img, resources) {
    const name = String(img?.meta?.Model || '').trim();
    // Not while its hash is still being looked up: the row said "named only by its name" for a
    // checkpoint it knew - in a checkpoint's own gallery, where that version was then left out.
    if (!name || resources.checkpointAside
        || [...resources.known, ...resources.unknown].some((r) => isCheckpoint(r.type))) return resources;
    return { known: resources.known,
             unknown: [...resources.unknown, { type: 'Checkpoint', name, reason: 'Named only by its name' }] };
}

/**
 * The Send line's state as a dialog opens: the box ticked when the dialog
 * was opened to send - a stop, the tab's box, Send as… - and, opened with the
 * Resources button, as the checkpoint's row and the setting say once known
 * (startBox).
 */
function startSendLine(send) {
    // Opened with the Resources button, `ready` stays unknown until the library has said (startBox).
    const line = { ...send, ready: send.opened === 'resources' ? undefined : send.ready ?? false,
                   choosing: send.opened !== 'resources',
                   chosen: null, touched: false, pickList: null, usualAnswers: new Map(),
                   usualOn: true, usual: true, usualPressed: false };
    // The settings asked afresh as the dialog opens: Forge's Settings page
    // does not refresh the page's copy (#377).
    fetchUiOptions().then((data) => {
        startSeveral(line, data);
        line.usualOn = data?.usual_settings !== false;
        // Picked before the answer came, the tick unpressed: it starts as the setting says.
        if (line.chosen && !line.usualPressed && line.usual !== line.usualOn && resourcesSend === line) {
            line.usual = line.usualOn;
            redrawUsual();
        }
        if (send.opened !== 'resources') return;
        line.settingOn = data?.choose_checkpoint === true;
        startBox(line);
    });
    return line;
}

/**
 * Whether the line ticks several checkpoints (#400): the setting Queue a
 * generation with several checkpoints on - nested under Choose the checkpoint
 * at every Send, it does nothing while that is off - the Queue on and built at this
 * start - its button is made only as the WebUI starts - and the send going
 * into txt2img. With the setting on and the Queue off, or turned on since,
 * the list keeps its round buttons and says what to do. Decided as the
 * dialog opens: a dialog open keeps what it started with.
 */
function startSeveral(line, data) {
    const wanted = data?.queue_several === true && data?.choose_checkpoint === true && line.tab === 'txt2img';
    const queue = data?.tabs?.queue;
    const queueOn = data?.queue_enabled !== false && queue?.on !== false;
    line.several = wanted && queueOn && queue?.built === true;
    line.severalWhy = !wanted || line.several ? ''
        : !queueOn ? 'Turn the Queue on to tick several checkpoints here and queue them.'
            : 'Restart the WebUI to tick several checkpoints here: the Queue was turned on since it started.';
    if (line.several) {
        line.ticked = line.chosen ? [line.chosen] : [];
        // The first tick is Send's, the rest a queued run's.
        line.loads = 'Send or a queued run';
        line.rowNote = (row) => runsNote(line, row);
    }
    if (resourcesSend === line && (line.several || line.severalWhy)) redrawSendBar();
}

/**
 * The Resources button's dialog's box: unticked while the image's checkpoint
 * row says Installed - the dialog's own answer, a database read, so opening
 * it runs no send plan - ticked when it does not, or with the setting on. A
 * box the person pressed stays as they left it.
 */
function startBox(line = resourcesSend) {
    if (!line || line !== resourcesSend || line.opened !== 'resources') return;
    const installed = checkpointInstalled();
    // Whether its unticked Send can go follows the row, a download landing too.
    if (installed !== null) line.ready = installed;
    if (line.touched || (installed === null && !line.settingOn)) {
        redrawSendBar();
        return;
    }
    const choosing = Boolean(line.settingOn) || installed === false;
    if (choosing !== line.choosing) {
        line.choosing = choosing;
        if (choosing) askPickList();
    }
    redrawSendBar();
}

/** Whether the image's checkpoint row reads Installed; null before the library has answered. */
function checkpointInstalled() {
    // A checkpoint's gallery sends its own file.
    if (resourcesSend?.galleryOwn) return true;
    const row = resourcesRows.find((r) => isCheckpoint(r.type));
    if (!row) {
        // Its hash not answered yet, it may still turn out a found row.
        if (!installedAsked || checkpointPending) return null;
        // One Civitai does not know - a merge of your own - is installed where the library holds its hash.
        const unknown = resourcesUnresolved.find((r) => isCheckpoint(r.type) && r.hash);
        return Boolean(unknown && installedResourceHashes.has(unknown.hash));
    }
    if (!installedAsked) return null;
    return resourceDownloadCell(row).includes('mm-res-state installed');
}

/**
 * The dialog (#377, R4, option F of its POC): a row in two lines, as the list of your
 * checkpoints - the name, which opens the model as View did, and the version; under them the
 * kind, the prompt's tag and the row's notes - its Download at the right. The image's
 * checkpoint first, then the rest in the image's order; what has no Civitai version greyed in
 * the same list. The Send line at the dialog's foot, outside what scrolls: 17 rows of one image
 * put it at the bottom edge of a 1080 px screen, the list below the fold.
 */
function renderResourcesModal(resources, pending = 0) {
    resourcesRows = resources.known;
    resourcesUnresolved = resources.unknown;
    checkpointPending = Boolean(resources.checkpointAside);
    const knownRow = (resource) => `
            <div class="mm-res-row">
                <div class="mm-res-name" data-res-name="${safeId(resource.versionId)}">${resourceNameHtml(resource)}</div>
                <div class="mm-res-actions" data-res-download="${safeId(resource.versionId)}">${resourceDownloadCell(resource)}</div>
                <div class="mm-res-open" data-res-open="${safeId(resource.versionId)}">${viewButton(resource)}</div>
            </div>`;
    const unknownRow = (resource) => `
            <div class="mm-res-row mm-res-unresolved">
                <div class="mm-res-name"><div class="mm-res-line"><span class="mm-res-title">${escapeHtml(resource.name)}</span></div>
                    <div class="mm-res-sub"><span class="mm-res-type">${escapeHtml(rowKindName(resource.type))}</span>${
                        resource.tag ? ` · <code class="mm-res-tag">${escapeHtml(resource.tag)}</code>` : ''}</div></div>
                <div class="mm-res-actions"><span class="mm-res-no-hash">${escapeHtml(resource.reason)}</span></div>
                <div class="mm-res-open"></div>
            </div>`;
    const checkpoints = [...resources.known.filter((r) => isCheckpoint(r.type)).map(knownRow),
                         ...resources.unknown.filter((r) => isCheckpoint(r.type)).map(unknownRow)];
    const others = [...resources.known.filter((r) => !isCheckpoint(r.type)).map(knownRow),
                    ...resources.unknown.filter((r) => !isCheckpoint(r.type)).map(unknownRow)];
    const head = (title, count) => `<div class="mm-res-head">${escapeHtml(title)}${
        count ? ` <span class="mm-res-count">${count}</span>` : ''}</div>`;
    const rows = checkpoints.length && others.length
        ? head('Checkpoint') + checkpoints.join('') + head('Other resources', others.length) + others.join('')
        : [...checkpoints, ...others].join('');

    // Still asking: say how many are left rather than claim there is nothing.
    const stillLooking = pending > 0
        ? `<div class="mm-res-loading">Looking up ${pending} more on Civitai...</div>`
        : '';

    const nothingKnown = pending === 0 && resources.known.length === 0
        ? '<div class="mm-res-loading">Nothing here has a Civitai model behind it.</div>'
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
                        + `<span data-res-note>${escapeHtml(resourcesNote)}</span></div>` : ''}
                    <div class="mm-resources-list">${rows}${stillLooking}${nothingKnown}</div>
                </div>
                ${drawnSendBar ? `<div class="mm-modal-footer mm-resources-foot">${drawnSendBar}</div>` : ''}
            </div>
        </dialog>
    `;

    openMetaModal(modalHtml);
}

// ------------------------------------------- the Send line, and the list
// The image's own checkpoint, or one of yours picked from a list (#377, R4:
// option A of its second POC) - a search, then Suggested, a tab per family
// and All. Every pick is sent one way, by Forge's name for it.

/** The picks that send the image as it was made. */
const AS_MADE = ['this gallery\'s', 'the image\'s own', 'same file'];

/**
 * The Send line: the list once ticked, and under it the box, what Send will
 * do, and Send - disabled, saying why, until there is something to send with -
 * at the dialog's foot, as a dialog's action is.
 */
function sendAgainButton() {
    if (!resourcesSend) return '';
    const line = resourcesSend;
    const box = `<label class="mm-res-choose"><input type="checkbox" data-action="resources.chooseTick"${
        line.choosing ? ' checked' : ''}> Choose the checkpoint to send with</label>`;
    const own = !line.choosing && (line.ready || line.goesOn);
    const enabled = line.choosing ? Boolean(line.chosen) : own;
    const status = sendLineStatus();
    const text = status.text ? `<span class="mm-res-send-status">${escapeHtml(status.text)}</span>` : '';
    const again = status.again ? '<button type="button" class="mm-btn secondary mm-btn-small" '
                                 + 'data-action="resources.checkAgain">Check again</button>' : '';
    return `<div class="mm-resources-send-wrap">
            ${line.choosing ? `<div class="mm-pick-area">${pickListHtml(line, 'dialog')}`
                              + `<div class="mm-usual" data-usual>${usualHtml()}</div>${pickNoteHtml(line)}</div>` : ''}
            <div class="mm-dialog-buttons mm-resources-send">${box}${text}${again}
                <button type="button" class="mm-btn primary" data-action="resources.sendAgain"${
                    enabled ? '' : ` disabled title="${escapeHtml((line.choosing ? status.text : line.why) || status.text || '')}"`}>${
                    escapeHtml(line.button || 'Send to txt2img')}</button>
            </div>
        </div>`;
}

/** What Send will do, said left of it; with `again`, Check again beside it. */
function sendLineStatus() {
    const line = resourcesSend;
    if (line.choosing) {
        const row = line.chosen && pickRows(line).find((r) => r.name === line.chosen);
        if (!row) return { text: line.ticked ? 'Tick a checkpoint to send with.' : 'Pick a checkpoint to send with.' };
        if (line.ticked?.length > 1) {
            return { text: `Sends with ${pickRowName(row)}, then Queue for ${line.ticked.length} checkpoints in txt2img `
                           + 'queues them all.' };
        }
        const asMade = (row.why || []).some((why) => AS_MADE.includes(why));
        const usual = line.usual && usualApplies(line.usualAnswers.get(line.chosen)) ? ' With its usual settings.' : '';
        return { text: `Sends with ${pickRowName(row)}. ${asMade ? 'The image comes out as made.'
                                                                  : 'It will not come out exactly as made.'}${usual}` };
    }
    if (line.goesOn && !line.ready) return { text: 'Sends with the checkpoint loaded now.' };
    if (line.opened === 'resources' && !line.check) {
        if (line.ready === undefined) return { text: '' };
        if (line.ready) return { text: 'Sends with the image\'s own checkpoint.' };
        // "Download it above" only where a Download is drawn: a checkpoint Civitai does not know has none.
        const offered = resourcesRows.some((r) => isCheckpoint(r.type)
                                                && resourceDownloadCell(r).includes('data-action="resources.download"'));
        return { text: offered ? 'The checkpoint is not in your library yet: download it above, or pick one of yours.'
                               : 'The checkpoint is not in your library: pick one of yours.' };
    }
    if (line.ready) return { text: '' };
    return sendStatus();
}

/**
 * What the stopped Send waits for, said beside it (#211): its tooltip alone
 * said it, and a checkpoint downloaded here read "Downloaded" on its row
 * while Send stayed grey. Its download, then Forge listing it - and once the
 * dialog has stopped asking, that it still waits, with Check again (`again`).
 */
function sendStatus() {
    const { reason, why, gaveUp } = resourcesSend;
    const checkpoint = resourcesRows.find((r) => isCheckpoint(r.type));
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

/** A checkpoint the short way, as its row's first line and Send's line name it: "Anime Mix v12", else its file. */
export function pickRowName(row) {
    return row.model ? [row.model, row.version].filter(Boolean).join(' ') : row.file;
}

// Why a row is suggested, as its second line says it (send.py's SUGGESTED_ORDER).
const WHY_TEXT = {
    'this gallery\'s': 'This gallery\'s', 'the image\'s own': 'The image\'s own', 'same file': 'Same file',
    'same version, other file': 'Same version, other file', 'same model': 'Same model, other version',
};

// ------------------------------------------- the list, wherever it is drawn
// The list draws from what it is handed - a holder, `{ pickList, chosen }`:
// the server's answer with the search and the family tab shown, and the name
// picked; or, for several picks (#400), `{ pickList, ticked }`, the names
// ticked, a tick box each - never from the open dialog itself. Its markup carries the name it
// was offered under (pickListHtml's data-pick-list), and its radios a group
// of that name, so its search, a tab and a pick act on that list alone. The
// Resources dialog's is one, `dialog`; several mode's Change window draws
// another (#400).

// Each list offered, by its name in the markup: what it is drawn from now, what a pick does there.
const pickLists = new Map();

/**
 * Offer a list by name: `holder()` answers what it is drawn from now -
 * null while there is none - `picked(name, input)` does a pick, and
 * `redrawn()`, if given, follows its rows drawn again. Answers how to take
 * it back.
 */
export function addPickList(name, { holder, picked, redrawn = null }) {
    const list = { holder, picked, redrawn };
    pickLists.set(name, list);
    return () => {
        if (pickLists.get(name) === list) pickLists.delete(name);
    };
}

/** The list an element is drawn in: its offer, what it is drawn from now, and its element. */
function listOf(element) {
    const root = element?.closest?.('[data-pick-list]');
    const list = root && pickLists.get(root.dataset.pickList);
    const state = list?.holder();
    return state ? { ...list, state, root } : null;
}

/** A list's rows again, in its element: its search box left as it is - its focus and caret too. */
function redrawListBody(root, holder) {
    const body = root?.querySelector('.mm-pick-body');
    if (body && holder?.pickList?.data) body.innerHTML = pickBodyHtml(holder, root.dataset.pickList);
}

/**
 * A list's answer with a row first for each ticked name it does not hold -
 * a checkpoint gone since, or one Forge has renamed since the list was made
 * (#400) - ticked, saying so, so it can be unticked: hidden, it stayed
 * ticked, and the press refused the whole task for it.
 */
export function withUnlisted(data, names) {
    const listed = new Set((data.checkpoints || []).map((c) => c.name));
    const unlisted = names.filter((name) => !listed.has(name))
        .map((name) => ({ name, file: name, family: null, read: true, supported: true, unlisted: true }));
    return { ...data, checkpoints: [...unlisted, ...(data.checkpoints || [])] };
}

/** The tab a list opens on: Suggested first; with none, the image's own family, All where that is not known. */
function firstPickTab(data) {
    const families = new Set((data?.checkpoints || []).map((c) => c.family).filter(Boolean));
    return data?.suggested?.length ? 'suggested' : families.has(data?.family) ? data.family : 'all';
}

/** Every checkpoint of the list's answer, each with why it is suggested, if it is. */
export function pickRows(holder) {
    const data = holder?.pickList?.data;
    if (!data) return [];
    const why = new Map((data.suggested || []).map((s) => [s.name, s.why || []]));
    return (data.checkpoints || []).map((c) => ({ ...c, why: why.get(c.name) || [] }));
}

/** Whether a row can be picked: a family this WebUI has no UI preset for cannot (#377, question 12). */
const pickable = (row) => row.supported || !row.read;

/** Whether a row matches the search: any part of what it says. */
function matches(row, words) {
    if (!words.length) return true;
    const text = [row.model, row.version, row.base_model, row.file, row.name, row.family,
                  row.family ? familyName(row.family) : '', ...(row.why || []).map((why) => WHY_TEXT[why] || why)]
        .join(' ').toLowerCase();
    return words.every((word) => text.includes(word));
}

/**
 * A list's markup, drawn from `holder`, in an element named for the list as
 * offered (addPickList): the search, a tab per family held, then the rows of
 * the tab shown. Drawn under a name nothing offers, its controls do nothing.
 */
export function pickListHtml(holder, name) {
    return `<div class="mm-pick" data-pick-list="${escapeHtml(name)}">${pickListInner(holder, name)}</div>`;
}

/** What the list's element holds. */
function pickListInner(holder, name) {
    const list = holder?.pickList;
    const search = (disabled) => `<input type="search" class="mm-pick-search" placeholder="Search your checkpoints"
                   aria-label="Search your checkpoints" value="${escapeHtml(list?.search || '')}"${disabled ? ' disabled' : ''}>`;
    if (!list || list.loading || list.error) {
        // Read or failed, the list takes the room it will take once read - a tab's height, the
        // rows' box - so the dialog does not change height when it comes (#377, R4).
        const text = list?.error || 'Reading your checkpoints…';
        return `${search(true)}<div class="mm-pick-body"><div class="mm-pick-tabs">`
            + '<button type="button" class="mm-pick-tab mm-pick-tab-held" disabled tabindex="-1" aria-hidden="true">'
            + `&nbsp;</button></div><div class="mm-pick-rows"><div class="mm-pick-wait">${escapeHtml(text)}</div></div></div>`;
    }
    return `${search(false)}<div class="mm-pick-body">${pickBodyHtml(holder, name)}</div>`;
}

/**
 * The tabs and the rows, redrawn as the search narrows them - the search box kept, focus and all.
 * Suggested is a tab of its own, first (#377, R4): the suggestions sat on top of every tab. A
 * family's tab holds every checkpoint of it, suggested or not, the image's base model first.
 */
function pickBodyHtml(holder, name) {
    const list = holder.pickList;
    const data = list.data;
    const rows = pickRows(holder);
    const words = String(list.search || '').toLowerCase().split(/\s+/).filter(Boolean);
    const shown = rows.filter((r) => matches(r, words));
    const families = [...new Set(rows.map((r) => r.family).filter(Boolean))];
    const suggested = (data.suggested || []).map((s) => shown.find((r) => r.name === s.name)).filter(Boolean);
    const hasSuggested = Boolean(data.suggested?.length);
    const tab = families.includes(list.tab) || list.tab === 'all' || (list.tab === 'suggested' && hasSuggested)
        ? list.tab : 'all';
    const count = (n) => ` <span class="mm-pick-count">${n}</span>`;
    const tabs = [...(hasSuggested ? [['suggested', 'Suggested', suggested.length, 'What suits this image']] : []),
                  ...families.map((f) => [f, familyName(f), shown.filter((r) => r.family === f).length,
                                          `Forge's UI preset: ${f}`]),
                  ['all', 'All', shown.length, 'Every checkpoint Forge lists']]
        .map(([id, label, n, tip]) => `<button type="button" class="mm-pick-tab${id === tab ? ' active' : ''}"`
            + ` data-action="resources.pickTab" data-family="${escapeHtml(id)}" title="${escapeHtml(tip)}">${
                escapeHtml(label)}${count(n)}</button>`)
        .join('');
    const section = (title, list2, family) => (list2.length
        ? (title ? `<div class="mm-pick-head">${escapeHtml(title)}${count(list2.length)}</div>` : '')
          + list2.map((r) => pickRowHtml(holder, name, r, family)).join('') : '');
    let body;
    if (tab === 'suggested') body = section('', suggested, true);
    else if (tab === 'all') body = section('', shown, true);
    else {
        const inTab = shown.filter((r) => r.family === tab);
        const base = data.same_base?.base_model;
        const sameBase = base ? inTab.filter((r) => r.base_model === base) : [];
        const rest = inTab.filter((r) => !sameBase.includes(r));
        body = sameBase.length
            ? section(`${base}, like the image`, sameBase, false) + section(`Other ${familyName(tab)}`, rest, false)
            : section('', rest, false);
    }
    return `<div class="mm-pick-tabs" role="tablist">${tabs}</div>
            <div class="mm-pick-rows">${body || '<div class="mm-pick-wait">No checkpoint matches.</div>'}</div>`;
}

/**
 * One row, in two lines: the model and its version, the base model at the right; then, smaller,
 * why it is suggested, loaded now, its family where the tab does not say it, and its file.
 */
function pickRowHtml(holder, name, row, family) {
    const can = pickable(row);
    const sub = [...row.why.filter((w) => w !== 'loaded now')
                     .map((w) => `<span class="mm-pick-why">${escapeHtml(WHY_TEXT[w] || w)}</span>`),
                 ...(holder.pickList.data.loaded === row.name
                     ? ['<span class="mm-pick-loaded">Loaded in Forge now</span>'] : []),
                 ...(family && row.family ? [escapeHtml(familyName(row.family))] : []),
                 // A name a list holds that Forge's list does not (#400): gone, or renamed.
                 ...(row.unlisted ? ['Forge does not list it'] : []),
                 // Not asked of Civitai until a sync reads it.
                 ...(!row.model && row.read && !row.unlisted ? ['Not on Civitai'] : []),
                 ...(!row.read ? ['Not read by a sync yet'] : []),
                 ...(!can ? [row.family ? escapeHtml(`No UI preset for ${familyName(row.family)} in this WebUI`)
                                        : 'Forge could not tell what model this is'] : []),
                 ...(row.model ? [`<span class="mm-pick-file">${escapeHtml(row.file)}</span>`] : [])]
        .join(' · ');
    // Several picks (#400): a tick box each, and what could not load it is a queued run, not Send;
    // the holder may say how each ticked one runs.
    const ticks = Array.isArray(holder.ticked);
    const runs = holder.rowNote?.(row) || '';
    const on = ticks ? holder.ticked.includes(row.name) : holder.chosen === row.name;
    const loads = holder.loads || (ticks ? 'a queued run' : 'Send');
    const title = can ? row.name
        : row.family ? `This WebUI has no UI preset for this checkpoint's family, so ${loads} could not load it.`
            : `Forge's model detector could not tell what model this checkpoint is, so ${loads} could not set Forge up for it.`;
    const input = ticks ? '<input type="checkbox"' : `<input type="radio" name="mm_pick_${escapeHtml(name)}"`;
    // A tick box ticked stays open to untick, whatever the row: a list holds it, and must be able to let it go.
    const off = !can && !(ticks && on);
    return `<label class="mm-pick-row${can ? '' : ' mm-pick-greyed'}${on ? ' picked' : ''}"`
        + ` title="${escapeHtml(title)}">`
        + `${input} value="${escapeHtml(row.name)}" data-action="resources.pickRow"${
            on ? ' checked' : ''}${off ? ' disabled' : ''}>`
        + `<span class="mm-pick-name">${escapeHtml(row.model || row.file)}${
            row.model && row.version ? ` <span class="mm-pick-ver">${escapeHtml(row.version)}</span>` : ''}</span>`
        + `<span class="mm-pick-base">${escapeHtml(row.base_model || '')}</span>`
        + `<span class="mm-pick-sub">${sub}</span>${runs ? `<span class="mm-pick-runs">${escapeHtml(runs)}</span>` : ''}</label>`;
}

/** The model the image's checkpoint is of, as the dialog has learnt it - its row's, or Civitai's answer. */
function imageModel() {
    const row = resourcesRows.find((r) => isCheckpoint(r.type));
    if (!row) return null;
    return row.modelId || civitaiModels.get(row.versionId)?.modelId || null;
}

/** What the list is asked with: the image's checkpoint as the dialog's lookup learnt it. */
function pickListParams(line) {
    const row = resourcesRows.find((r) => isCheckpoint(r.type));
    const civitai = row ? civitaiModels.get(row.versionId) : null;
    return { ...line.list, model_id: imageModel() || '', base_model: civitai?.baseModel || '',
             same_file: civitai?.sameFile?.version_id || '' };
}

/**
 * Ask for the list (`send/checkpoints`), once the dialog's missing-resources
 * lookup has answered: the suggestions are worked out from what it said of
 * the image's checkpoint - its model, its base model, the same file held -
 * which the server keeps only in memory. Asked again when a download lands.
 */
async function askPickList({ again = false } = {}) {
    const line = resourcesSend;
    if (!line?.choosing || !line.list || (line.pickList && !again)) return;
    const list = line.pickList || (line.pickList = { loading: true, search: '', tab: null });
    if (!list.data) redrawSendBar();
    await modelsAsked;
    if (resourcesSend !== line) return;
    const params = pickListParams(line);
    try {
        const data = await apiCall({ endpoint: '/model-manager/send/checkpoints', params });
        if (resourcesSend !== line) return;
        if (!data?.success) throw new Error(data?.error || 'the server did not answer');
        // Asked again - a download landed, Forge listed the checkpoint - a tick it no longer lists stays in sight.
        list.data = line.ticked?.length ? withUnlisted(data, line.ticked) : data;
        list.loading = false;
        list.error = '';
        if (list.tab === null) list.tab = firstPickTab(data);
        // The pick made first: the image comes out as made (#304's same file among them).
        if (!line.chosen && data.picked) {
            line.chosen = data.picked;
            if (line.ticked) line.ticked = [data.picked];
            askUsual(line, line.chosen);
        }
    } catch (error) {
        if (resourcesSend !== line) return;
        Object.assign(list, { loading: false, error: `Could not read your checkpoints: ${error.message || error}` });
    }
    redrawSendBar();
}

/** After the dialog's rows are drawn again: what its Send line says, and what a full redraw would draw. */
function dialogListRedrawn() {
    const status = document.querySelector('.mm-resources-modal .mm-res-send-status');
    if (status) status.textContent = sendLineStatus().text || '';
    // What a full redraw would draw now: one that would change nothing writes nothing.
    if (resourcesSend) drawnSendBar = sendAgainButton();
}

// ------------------------------------------- the pick's usual settings (#378)
// Beside the list's rows - under them on a narrow dialog - once a pick is made
// that the server says they apply to - not as made: until then a line saying
// what a pick will show. The pick's usual sampler, schedule type, steps and CFG scale,
// and a fifth where its UI preset takes one, beside the image's own; where
// they come from; and a tick that sends with them, ticked at each pick
// unless the setting says otherwise.

// The block as last drawn, so an answer that changes nothing writes nothing.
let drawnUsual = { block: null, html: '' };

// Each setting's name, as the block and Forge's controls name it.
const USUAL_NAMES = { sampler: 'Sampler', schedule_type: 'Schedule type', steps: 'Steps', cfg: 'CFG scale',
                      distilled_cfg: 'Distilled CFG Scale', shift: 'Shift' };

/** Whether an answer has anything the tick would send: a value 5 or more uses record that this WebUI lists. */
function usualApplies(answer) {
    return Boolean(answer?.applies && answer.source
                   && (answer.settings || []).some((r) => r.value !== null && r.value !== undefined && !r.thin && !r.missing));
}

/** A value as the block shows it; a dash for none. */
const shownValue = (value) => (value === null || value === undefined || value === '' ? '–' : String(value));

// The block's column before a pick, and for an as-made one; on a dialog too
// narrow for the column, the block under the rows, which keeps its height (style.css).
const USUAL_HINT = {
    none: 'Pick a checkpoint to see what it is usually run with.',
    asMade: 'Sends as made: the image\'s own settings go with it.',
};
const usualHint = (text) => `<div class="mm-usual-note mm-usual-hint">${escapeHtml(text)}</div>`;

/** The block's markup for the pick: asking, its answer, or a hint before a pick and for an as-made one. */
function usualHtml() {
    const line = resourcesSend;
    if (!line) return '';
    if (line.ticked?.length > 1) return severalUsualHtml(line);
    const row = line.chosen && pickRows(line).find((r) => r.name === line.chosen);
    if (!row) return usualHint(USUAL_HINT.none);
    const answer = line.usualAnswers.get(line.chosen);
    const name = escapeHtml(pickRowName(row));
    if (!answer || answer.loading) {
        // A pick the list says is as made draws no values while it asks: the server decides.
        return (row.why || []).some((why) => AS_MADE.includes(why)) ? usualHint(USUAL_HINT.asMade)
            : `<div class="mm-usual-note">Reading what ${name} is usually run with…</div>`;
    }
    if (answer.error) return `<div class="mm-usual-note">Could not read its usual settings: ${escapeHtml(answer.error)}.</div>`;
    if (!answer.applies) return usualHint(USUAL_HINT.asMade);
    if (!answer.source) {
        return '<div class="mm-usual-note">Not enough to go by: fewer than 5 of your generations or Civitai\'s stored '
               + 'images use it.</div>';
    }
    const cells = (answer.settings || []).map((r) => {
        const value = r.thin ? '<span class="mm-usual-thin">Not recorded enough</span>'
            : r.missing ? `${escapeHtml(shownValue(r.value))} <span class="mm-usual-thin">· not in this WebUI</span>`
                : escapeHtml(shownValue(r.value));
        const count = r.thin ? '' : `${Number(r.count)} of ${Number(r.of)}`;
        return `<span class="mm-usual-name">${escapeHtml(USUAL_NAMES[r.key] || r.key)}</span>`
            + `<span class="mm-usual-value" data-usual-key="${escapeHtml(r.key)}">${value}</span>`
            + `<span class="mm-usual-count">${count}</span>`
            + `<span class="mm-usual-own">${escapeHtml(shownValue(answer.image?.[r.key]))}</span>`;
    }).join('');
    const from = answer.source === 'yours' ? `From ${Number(answer.uses)} of your generations with it.`
        : `From ${Number(answer.uses)} Civitai images that name it.`;
    const hires = answer.image?.hires ? ' Hires fix keeps the image\'s settings.' : '';
    const tick = usualApplies(answer)
        ? `<label class="mm-usual-tick"><input type="checkbox" data-action="resources.usualTick"${
            line.usual ? ' checked' : ''}> Send with these instead of the image's</label>` : '';
    return `<div class="mm-usual-grid"><span class="mm-usual-head">${name} is usually run with</span>`
        + `<span class="mm-usual-head mm-usual-own">The image has</span>`
        // Beside the rows the name takes the whole row, and this heads the image's column under it.
        + `<span class="mm-usual-colhead mm-usual-own">The image has</span>${cells}</div>`
        + `<div class="mm-usual-from">${escapeHtml(from + hires)}</div>${tick}`;
}

/**
 * Two or more ticked (#400): what each runs with - its usual settings, as made,
 * or yours - one after another, and no tick: each takes its own when the task
 * is queued, and Hires fix follows each run's.
 */
function severalUsualHtml(line) {
    const rows = new Map(pickRows(line).map((row) => [row.name, row]));
    const each = line.ticked.map((name) => {
        const row = rows.get(name);
        const answer = line.usualAnswers.get(name);
        let what;
        if (row && (row.why || []).some((why) => AS_MADE.includes(why))) what = 'Runs as made, with the image\'s settings.';
        else if (!answer || answer.loading) what = 'Reading its usual settings…';
        else if (answer.error) what = 'Runs with your settings: its usual settings could not be read.';
        else if (!answer.applies) what = 'Runs as made, with the image\'s settings.';
        else if (!usualApplies(answer)) what = 'Runs with your settings: too few uses record its own.';
        else {
            what = (answer.settings || [])
                .filter((r) => r.value !== null && r.value !== undefined && !r.thin && !r.missing)
                .map((r) => `${USUAL_NAMES[r.key] || r.key} ${shownValue(r.value)}`).join(' · ');
        }
        return `<div class="mm-usual-each"><span class="mm-usual-each-name">${escapeHtml(row ? pickRowName(row) : name)}</span>`
            + `<span class="mm-usual-each-what">${escapeHtml(what)}</span></div>`;
    }).join('');
    return `<div class="mm-usual-head">What each runs with</div>${each}`
        + '<div class="mm-usual-from">A setting too few uses record, or one this WebUI lacks, stays as you set it. '
        + 'Hires fix follows each run\'s sampler, schedule type, CFG, and Distilled CFG or Shift.</div>';
}

/** The block again, in place: the list's rows, their scroll and the search box are left as they are. */
function redrawUsual() {
    const block = document.querySelector('.mm-resources-modal .mm-usual');
    // Only what differs: a rewrite would take focus from the tick (#292: Esc then reaches the page).
    // Compared with what was drawn, not the markup read back, which the browser rewrites.
    const html = usualHtml();
    if (block && (block !== drawnUsual.block || html !== drawnUsual.html)) {
        block.innerHTML = html;
        drawnUsual = { block, html };
    }
    const status = document.querySelector('.mm-resources-modal .mm-res-send-status');
    if (status) status.textContent = sendLineStatus().text || '';
    redrawSeveral();
    if (resourcesSend) drawnSendBar = sendAgainButton();
}

/**
 * Ask what a pick is usually run with (`send/usual`), once per name while
 * the dialog is open. Its answer is kept, and the block drawn again for the
 * pick picked now: one asked for an earlier pick draws that pick's, and none
 * once the dialog has closed.
 */
async function askUsual(line, name) {
    if (!line?.usualSource || !name || line.usualAnswers.has(name)) return;
    line.usualAnswers.set(name, { loading: true });
    const params = { ...line.usualSource, checkpoint: name, image_model: imageModel() || '' };
    let answer;
    try {
        const data = await apiCall({ endpoint: '/model-manager/send/usual', params });
        answer = data?.success ? data : { error: data?.error || 'the server did not answer' };
    } catch (error) {
        answer = { error: String(error?.message || error) };
    }
    line.usualAnswers.set(name, answer);
    redrawUsual();
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
            // Ready: Forge lists it now, and the list's answer names it the image's own (#377).
            if (!reason) askPickList({ again: true });
            redrawSendBar();
            if (!reason || wanted.gaveUp) return;
            await new Promise((resolve) => setTimeout(resolve, TIMING.sendRecheck));
        }
    } finally {
        wanted.checking = false;
    }
}

/** A pick in the dialog's list: what Send says, and Send itself, without redrawing the rows - their scroll stays. */
function pickInDialog(name, input) {
    if (resourcesSend.ticked) {
        tickInDialog(name, input);
        return;
    }
    resourcesSend.chosen = name;
    const button = document.querySelector('.mm-resources-modal [data-action="resources.sendAgain"]');
    if (button) {
        button.disabled = false;
        button.removeAttribute('title');
    }
    document.querySelectorAll('.mm-resources-modal .mm-pick-row').forEach((row) => {
        row.classList.toggle('picked', row.querySelector('input')?.value === name);
    });
    // A new pick: its usual settings asked, the tick as the setting says (#378).
    resourcesSend.usual = resourcesSend.usualOn;
    resourcesSend.usualPressed = false;
    askUsual(resourcesSend, name);
    redrawUsual();
}

/**
 * A tick in the dialog's list (#400): the first ticked is the one Send loads,
 * each ticked one's usual settings asked; the rows are not drawn again -
 * their scroll stays - only what each ticked one says, and the Send line.
 */
function tickInDialog(name, input) {
    const line = resourcesSend;
    const ticked = line.ticked.filter((n) => n !== name);
    if (input?.checked) ticked.push(name);
    line.ticked = ticked;
    const first = ticked[0] || null;
    // The usual tick is one pick's: it starts as the setting says again only for a new first.
    if (first !== line.chosen) {
        line.usual = line.usualOn;
        line.usualPressed = false;
    }
    line.chosen = first;
    input?.closest('.mm-pick-row')?.classList.toggle('picked', Boolean(input?.checked));
    ticked.forEach((n) => askUsual(line, n));
    const button = document.querySelector('.mm-resources-modal [data-action="resources.sendAgain"]');
    if (button) {
        button.disabled = !line.chosen;
        if (line.chosen) button.removeAttribute('title');
        else button.title = 'Tick a checkpoint to send with.';
    }
    redrawUsual();
}

/** Words as a sentence lists them: "a", "a and b", "a, b and c". */
function listNames(names) {
    return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0] || '';
}

/**
 * How a ticked checkpoint runs, said on its row once two or more are ticked
 * (#400): as made - the image's own, or the same file - with its usual
 * settings, or with yours where it has none; and, for a file no sync has
 * read, that its family is read when the task is queued.
 */
function runsNote(line, row) {
    if (!(line.ticked?.length > 1) || !line.ticked.includes(row.name)) return '';
    const unread = row.read ? '' : ' Its family is read when you queue.';
    if ((row.why || []).some((why) => AS_MADE.includes(why))) return `Runs as made, with the image's settings.${unread}`;
    const answer = line.usualAnswers.get(row.name);
    if (!answer || answer.loading) return `Reading its usual settings…${unread}`;
    if (answer.error) return `Runs with your settings: its usual settings could not be read.${unread}`;
    if (!answer.applies) return `Runs as made, with the image's settings.${unread}`;
    if (usualApplies(answer)) return `Runs with its usual settings.${unread}`;
    return `Runs with your settings: too few uses record its own.${unread}`;
}

/**
 * The line under the list: what to do where several cannot be ticked; else,
 * with ticks of more than one family, what stays as you set it for those of
 * another family than the first, which Send loads - usual settings record
 * none of it.
 */
function pickNote(line) {
    if (line.severalWhy) return line.severalWhy;
    if (!(line.ticked?.length > 1)) return '';
    const rows = new Map(pickRows(line).map((row) => [row.name, row]));
    const first = rows.get(line.ticked[0]);
    const others = line.ticked.slice(1).map((name) => rows.get(name))
        .filter((row) => row?.family && first?.family && row.family !== first.family);
    if (!others.length) return '';
    return `The size, the prompt and its LoRAs, ADetailer, ControlNet and Diffusion in Low Bits stay as you set them `
        + `for ${listNames(others.map(pickRowName))}, of another family than ${pickRowName(first)}.`;
}

/** The line under the list, where it says something: none, as before #400, where it does not. */
function pickNoteHtml(line) {
    const text = pickNote(line);
    return text ? `<div class="mm-pick-note" data-pick-note>${escapeHtml(text)}</div>` : '';
}

/** What each ticked row says, and the line under the list, drawn again in place: the rows keep their scroll. */
function redrawSeveral() {
    const line = resourcesSend;
    const modal = document.querySelector('.mm-resources-modal');
    if (!line || !modal) return;
    const rows = new Map(pickRows(line).map((row) => [row.name, row]));
    modal.querySelectorAll('[data-pick-list="dialog"] .mm-pick-row').forEach((element) => {
        const row = rows.get(element.querySelector('input')?.value);
        const text = row ? runsNote(line, row) : '';
        let note = element.querySelector('.mm-pick-runs');
        if (!text) {
            note?.remove();
            return;
        }
        if (!note) {
            note = document.createElement('span');
            note.className = 'mm-pick-runs';
            element.append(note);
        }
        if (note.textContent !== text) note.textContent = text;
    });
    const under = modal.querySelector('[data-pick-note]');
    const text = pickNote(line);
    if (!text) under?.remove();
    else if (under) {
        if (under.textContent !== text) under.textContent = text;
    } else {
        modal.querySelector('.mm-pick-area')?.insertAdjacentHTML('beforeend', pickNoteHtml(line));
    }
}

// The dialog's Send: closed, and the image sent - with the checkpoint picked,
// or, the box unticked, its own. It goes through every check, and never
// opens the dialog again: the tab's box is read by the tab's own Send alone.
function sendAgain() {
    const send = resourcesSend;
    if (!send) return undefined;
    if (send.choosing) {
        if (!send.chosen) return undefined;
        if (send.ticked?.length > 1) return sendSeveral(send);
        const row = pickRows(send).find((r) => r.name === send.chosen);
        const usual = send.usual && usualApplies(send.usualAnswers.get(send.chosen)) && row
            ? { name: pickRowName(row) } : null;
        closeMetaModal();
        resourcesSend = null;
        return send.pick(send.chosen, imageModel(), usual);
    }
    if (!send.ready && !send.goesOn) return undefined;
    closeMetaModal();
    resourcesSend = null;
    return send.run();
}

/**
 * Two or more ticked (#400): the image sent with the first, as made - each
 * run takes its own usual settings when the task is queued - then txt2img
 * enters several mode with them all, where they came from - the image, as
 * send/usual is asked - how each is named, and what the list was asked with,
 * for Change.
 */
async function sendSeveral(send) {
    const names = [...send.ticked];
    const rows = new Map(pickRows(send).map((row) => [row.name, row]));
    const labels = Object.fromEntries(names.filter((name) => rows.has(name))
        .map((name) => [name, pickRowName(rows.get(name))]));
    const model = imageModel();
    const source = { image: { ...send.usualSource, image_model: model || '' } };
    const listParams = pickListParams(send);
    closeMetaModal();
    resourcesSend = null;
    return send.pickSeveral(names, model, { source, labels, listParams });
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
                                                              : { modelId: safeId(answer.model_id), sameFile: answer.same_file || null,
                                                                  baseModel: answer.base_model || null,
                                                                  versionGone: Boolean(answer.version_gone),
                                                                  newest: answer.newest || null });
                }
            }
        } catch (error) {
            console.warn('[ModelManager] Could not ask Civitai about the resources\' models:', error);
        }
        for (const { version_id: id } of versions) {
            askingVersions.delete(id);
            const resource = resources.find((r) => r.versionId === id);
            redrawView(id, resource);
            if (civitaiModels.get(id)?.gone) redrawResourceDownload(id, resource);
            if (civitaiModels.get(id)?.versionGone) {
                const cell = document.querySelector(`.mm-resources-modal [data-res-name="${safeId(id)}"]`);
                if (cell && resource) cell.innerHTML = resourceNameHtml(resource);
                redrawResourceDownload(id, resource);
            }
        }
    })();
    modelsAsked = Promise.all([modelsAsked, asking]);
    return modelsAsked;
}

/**
 * What View does, as a row's name and as its View button (#377, R4): the model in the Civitai
 * Browser, or the website. Its model deleted from Civitai, neither - the red words go on the
 * row's second line.
 */
function viewAttributes(resource) {
    const id = resource.versionId;
    const title = available('civitaiBrowser') ? 'Show this model in the Civitai Browser tab' : 'Open this version on Civitai';
    return ` data-action="resources.view"`
        + `${dataAttributes({ versionId: safeId(id), modelId: resource.modelId ? safeId(resource.modelId) : null })}`
        + ` title="${escapeHtml(title)}"${viewing === id ? ' disabled' : ''}`;
}

function nameButton(resource) {
    if (civitaiModels.get(resource.versionId)?.gone) return `<span class="mm-res-title">${escapeHtml(resource.name)}</span>`;
    return `<button type="button" class="mm-res-view"${viewAttributes(resource)}>${escapeHtml(resource.name)}</button>`;
}

/**
 * View, in a column of its own at the row's right. It keeps its word while it looks a model up -
 * the second line says "Looking up..." - as "Looking up..." in it would widen the column.
 */
function viewButton(resource) {
    if (civitaiModels.get(resource.versionId)?.gone) return '';
    return `<button type="button" class="mm-btn secondary mm-btn-small"${viewAttributes(resource)}>View</button>`;
}

/** A row's name, notes and View again: View's state, its model deleted. */
function redrawView(versionId, resource) {
    const row = resourcesRows.find((r) => String(r.versionId) === String(versionId)) || resource;
    if (!row) return;
    const cell = document.querySelector(`.mm-resources-modal [data-res-name="${versionId}"]`);
    if (cell) cell.innerHTML = resourceNameHtml(row);
    const open = document.querySelector(`.mm-resources-modal [data-res-open="${versionId}"]`);
    if (open) open.innerHTML = viewButton(row);
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
    const notes = [`<span class="mm-res-type">${escapeHtml(rowKindName(resource.type))}</span>`,
                   ...(resource.own ? ['<span class="mm-res-own">This gallery\'s model</span>'] : []),
                   ...(resource.tag ? [`<code class="mm-res-tag">${escapeHtml(resource.tag)}</code>`] : []),
                   ...(viewing === resource.versionId ? ['<span class="mm-res-looking">Looking up...</span>'] : []),
                   ...(held ? [`<span class="mm-res-held">you have its ${escapeHtml(fileLabel(held, held.file_size) || held.name)} file</span>`] : []),
                   ...(civitaiModels.get(resource.versionId)?.versionGone
                       ? ['<span class="mm-res-gone">this version is deleted from Civitai</span>'] : []),
                   ...(civitaiModels.get(resource.versionId)?.gone
                       ? ['<span class="mm-res-state error" title="Civitai no longer has this model">Model deleted from Civitai</span>'] : [])];
    return `<div class="mm-res-line">${nameButton(resource)}${
        version ? ` <span class="mm-res-version">${escapeHtml(version)}</span>` : ''}</div>`
        + `<div class="mm-res-sub">${notes.join(' · ')}</div>`;
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
    // The version deleted, its model there: the newest instead, named before
    // the press, and only from its own button (#372). A model with no
    // version left has nothing to offer.
    const civitai = civitaiModels.get(id);
    if (civitai?.versionGone && (!job || job.status === 'unavailable')) {
        if (!civitai.newest) return '';
        const modelId = resource.modelId || civitai.modelId;
        return `<button type="button" class="mm-btn primary mm-btn-small" data-action="resources.download"`
            + `${dataAttributes({ versionId: safeId(id), modelId: modelId ? safeId(modelId) : null, newest: 1 })}`
            + ` title="Civitai deleted the image's version: this downloads the model's newest">`
            + `Download ${escapeHtml(civitai.newest.version_name || 'the newest')}, the newest</button>`;
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
    if (!downloads()) {
        return '<span class="mm-res-state">Not in the library - downloads run while the Model Manager or the '
            + 'Civitai Browser is on</span>';
    }
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
async function checkInstalledResources(resources, unresolved = []) {
    const ids = resources.map((r) => r.versionId).filter(Boolean);
    const line = resourcesSend;
    // A checkpoint Civitai does not know - a merge of your own - by its hash: the Send line's
    // box starts from whether the library holds it (checkpointInstalled).
    const hashes = [...resources, ...unresolved.filter((r) => isCheckpoint(r.type))].map((r) => r.hash).filter(Boolean);
    if (ids.length || hashes.length) {
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
    }
    // The Resources button's box starts from the checkpoint's row (#377).
    if (line === resourcesSend) installedAsked = true;
    for (const resource of resources) redrawResourceDownload(resource.versionId, resource);
    startBox();
    await labelImageFiles(resources);
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
    }
}

function redrawSendBar() {
    const box = document.querySelector('.mm-resources-modal .mm-resources-send-wrap');
    if (!box) return;
    // Redrawn as each row is - the downloads list's every look: only when it would differ.
    const bar = sendAgainButton();
    if (bar === drawnSendBar) return;
    drawnSendBar = bar;
    box.outerHTML = bar;
}

/**
 * Download a resource into the library: the version the image names. Its
 * model's newest if that is gone, only for a chip's press - a chip says so
 * before it (#205) - or the Resources dialog's own button for it (#372):
 * the dialog's Download is the exact version. `chip` is kept on the record:
 * a chip's own download renames its tag whatever the switch says.
 */
export async function downloadResource(versionId, modelId, hash = '', { chip = false, newest = false } = {}) {
    if (!downloads()) return;
    resourceDownloads[versionId] = { modelId, hash, asking: true, chip };
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
        if (fileId && onItsWay(fileId)) {
            // Coming already - started in the Civitai Browser, say: followed as
            // it is, not asked for again. It was refused, marked failed and never
            // followed, and stayed failed once it had landed (#119). A file the
            // server names itself, it answers with any download of it coming.
            Object.assign(resourceDownloads[versionId], { asking: false, target: versionId, file: fileId });
            followResourceDownloads();
            redrawResourceDownload(versionId, { versionId, modelId });
            announceDownloads();
            return;
        }
        // No file Civitai lists by the hash - the version deleted, say - is
        // downloaded as before: the version's primary, or, for a chip or the
        // newest's own button, the model's newest. One found is queued at
        // once, its name and size the row's (#223).
        data = await downloads().start(modelId, versionId, fileId,
                                       { newerIfGone: !fileId && (chip || newest), fileName: listed?.name,
                                         sizeKb: listed?.size_kb });
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
        Object.assign(job, { target: data.version_id, file: data.progress?.file_id ?? data.file_id ?? null,
                             versionName: data.version_name,
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
    const job = resourceDownloads[versionId];
    job.announced = true;
    installedResourceVersions.add(versionId);
    if (job.hash) installedResourceHashes.add(job.hash);
    // Which resource landed, whether a chip asked for it, and whether it is
    // the newest in its place: the chips rename by it (#205).
    announceDownloads({ installed: true,
                        landed: { versionId, chip: Boolean(job.chip), substituted: Boolean(job.substituted) } });
    recheckSend();
    startBox();
}

/**
 * Downloads landed and Forge's list refreshed (downloads.mjs): the list is
 * asked again, so a deleted version's newest, once here, shows as "same
 * model" (#372, #377) - only now, as Forge lists it only after its refresh.
 * Unticked, the answer it holds is dropped, and the box ticked asks afresh.
 */
async function listAfterDownloads() {
    const line = resourcesSend;
    if (!line?.pickList) return;
    await afterRefreshes();
    if (resourcesSend !== line) return;
    if (line.choosing) askPickList({ again: true });
    else line.pickList = null;
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
            const name = downloads().progress(job.file)?.file_name || `version ${id}`;
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
    scope.provide('resources.download', ({ versionId, modelId, hash, newest }) =>
        downloadResource(safeId(versionId), safeId(modelId), String(hash || '').toLowerCase(),
                         { newest: Boolean(newest) }));
    // The box: ticked, the list; unticked, the image's own. Pressed, it stays so.
    scope.provide('resources.chooseTick', (data, box) => {
        if (!resourcesSend) return;
        Object.assign(resourcesSend, { choosing: Boolean(box?.checked), touched: true });
        if (resourcesSend.choosing) askPickList();
        redrawSendBar();
    });
    // A family's tab, a pick and the search act on the list they are drawn in.
    scope.provide('resources.pickTab', ({ family }, button) => {
        const list = listOf(button);
        if (!list?.state.pickList?.data) return;
        list.state.pickList.tab = String(family || 'all');
        redrawListBody(list.root, list.state);
        list.redrawn?.();
    });
    scope.provide('resources.pickRow', (data, input) => {
        const list = listOf(input);
        if (list && input?.value) list.picked(input.value, input);
    });
    scope.onStop(addPickList('dialog', { holder: () => resourcesSend, picked: pickInDialog,
                                         redrawn: dialogListRedrawn }));

    scope.provide('resources.usualTick', (data, box) => {
        if (!resourcesSend) return;
        resourcesSend.usual = Boolean(box?.checked);
        resourcesSend.usualPressed = true;
        const status = document.querySelector('.mm-resources-modal .mm-res-send-status');
        if (status) status.textContent = sendLineStatus().text || '';
        drawnSendBar = sendAgainButton();
    });
    // The search narrows as it is typed: the rows redrawn, the box kept.
    if (typeof document !== 'undefined') {
        scope.listen(document, 'input', (event) => {
            if (!event.target?.matches?.('.mm-pick-search')) return;
            const list = listOf(event.target);
            if (!list?.state.pickList) return;
            list.state.pickList.search = event.target.value;
            redrawListBody(list.root, list.state);
            list.redrawn?.();
        });
    }
    whenDownloading((list) => {
        // Downloads landed, and Forge's list refreshed (downloads.mjs): the
        // checkpoint may be one of them.
        list.onBatchDone(() => {
            recheckSend();
            listAfterDownloads();
        });
        list.onChange(followResourceDownloads);
    });
}
