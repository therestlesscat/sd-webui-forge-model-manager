/**
 * The long jobs: Sync with Civitai and Scan Disk (#92) - the Model Manager's
 * buttons and the dialogs behind them, starting a job, following it, cancelling
 * it, and finding one still running when the page loads, or is looked at again.
 * One of each kind at a time, as the server runs them (model_manager/jobs.py).
 * They lived in the Model Manager's script; a note's button opens their
 * dialogs (showSyncDialog, showScanDialog).
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, apiCall, escapeHtml, setText } = await shared('core.mjs');

// What the Model Manager connects the jobs to (connectJobs): its status line;
// its grid and the base models listed for it, loaded again once a job has
// changed the library; and its filters and how many models they match, for a
// sync of "these results".
let setStatus = () => {};
let loadModels = () => {};
let loadBaseModelOptions = () => {};
let getFilters = () => ({});
let gridTotal = () => 0;

/** Connect the jobs to the Model Manager's status line and grid: it calls this once. */
export function connectJobs(tab) {
    ({ setStatus, loadModels, loadBaseModelOptions, getFilters, gridTotal } = tab);
}

// Sync state
let isSyncing = false;
let syncPollInterval = null;

// Scan state
let isScanning = false;
let scanPollInterval = null;

// ==================== SYNC FUNCTIONS ====================

// Start sync with Civitai
/**
 * Identify files by hashing them, and ask Civitai what they are.
 *
 * `targets` picks which of the files on disk to read: all of them, only the
 * ones that already resolve to a Civitai model, or only the ones that do not.
 */
async function startSync(targets = 'all', keepImageCount = false) {
    if (isSyncing) return;

    isSyncing = true;
    updateSyncUI(true);
    setStatus(`Starting force sync (${targets})...`);

    try {
        const bodyData = `force=true&targets=${encodeURIComponent(targets)}&keep_image_count=${keepImageCount}`;
        console.log('[ModelManager] Sending sync request with body:', bodyData);

        const response = await fetch('/model-manager/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: bodyData
        });

        const data = await response.json();

        if (data.success) {
            // Start polling for progress
            syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
        } else {
            setStatus('Sync failed: ' + (data.error || 'Unknown error'), true);
            isSyncing = false;
            updateSyncUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Sync error:', error);
        setStatus('Sync error: ' + error.message, true);
        isSyncing = false;
        updateSyncUI(false);
    }
}

// Poll sync progress
async function pollSyncProgress() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/sync/progress' });

        if (data.success && data.progress) {
            const p = data.progress;

            // Update progress bar
            const percent = p.total > 0 ? (p.processed / p.total * 100) : 0;
            const fillEl = document.getElementById('mm_sync_fill');
            const textEl = document.getElementById('mm_sync_text');

            if (fillEl) fillEl.style.width = percent + '%';
            if (textEl) {
                textEl.textContent = `Syncing: ${p.processed}/${p.total} - ${p.current_model || 'Preparing...'}`;
            }

            // Update status
            setStatus(`Sync: ${p.synced} synced, ${p.not_found} not found, ${p.skipped} skipped, ${p.errors} errors`);

            // Check if complete
            if (p.is_complete) {
                clearInterval(syncPollInterval);
                syncPollInterval = null;
                isSyncing = false;
                updateSyncUI(false);

                // Show final status
                const errorInfo = p.errors > 0 ? ` (${p.error_messages.slice(-3).join('; ')})` : '';
                setStatus(`Sync complete: ${p.synced} synced, ${p.not_found} not found, ${p.skipped} skipped, ${p.errors} errors${errorInfo}`);
                loadBaseModelOptions();

                // Reload models to show updated data
                if (p.synced > 0) {
                    setTimeout(loadModels, 500);
                }
            }
        }
    } catch (error) {
        console.error('[ModelManager] Progress poll error:', error);
    }
}

// Cancel sync
async function cancelSync() {
    try {
        await fetch('/model-manager/sync/cancel', { method: 'POST' });
        setStatus('Canceling sync...');
    } catch (error) {
        console.error('[ModelManager] Cancel error:', error);
    }
}

/**
 * Refresh Civitai data for models that were already identified.
 *
 * "Sync with Civitai" hashes every file to work out what it is. Once that
 * has happened the answer is stored, so this only re-reads the metadata,
 * a hundred models per request. Images are optional because they are the
 * slow half - they cannot be batched.
 */
// The sync dialog asks two questions - which models, and how much of each -
// and answers a third before either is committed to: what it will cost. The
// estimate comes from the server, counted by the same code that does the
// batching, so the figure cannot drift from what actually happens.

let syncEstimateTimer = null;
let syncResultPaths = null;     // resolved lazily, for the "these results" scope
let syncDepthBeforeRehash = null;   // restored when the scope leaves "force"
let syncImagesWereOn = false;       // to tell "just switched on" from "still on"
let syncUnidentified = null;        // {unidentified, never_asked, asked_not_found, identified}

/**
 * The hashing option's own cost, in files rather than requests.
 *
 * The asterisk is the point: this comes from the database, which holds what
 * the last scan found. A file added since is not counted, and the sync walks
 * the model folders itself - so the number is a floor.
 */
function describeForceSync(counts, mode) {
    if (!counts) return 'Scans your model folders and reads each file in full.';

    const files = mode === 'identified' ? counts.identified
        : mode === 'unidentified' ? counts.unidentified
        : counts.total;
    const head = `${files.toLocaleString()} files* to read in full`;

    if (mode === 'identified') {
        return `${head} - the ones that already resolve to a Civitai model,`
            + ' read again in case anything about them has changed.';
    }
    if (mode === 'unidentified') {
        const parts = [];
        if (counts.never_asked) {
            parts.push(`${counts.never_asked.toLocaleString()} never asked about`);
        }
        if (counts.asked_not_found) {
            parts.push(`${counts.asked_not_found.toLocaleString()} asked before and not on Civitai`);
        }
        return `${head}${parts.length ? ` - ${parts.join(', ')}` : ''}.`;
    }
    return `${head} - every model you have, identified or not.`;
}

/** The counts beside each force-sync mode. */
function updateForceModeLabels() {
    const select = document.getElementById('mm_sync_force_mode');
    if (!select) return;
    const counts = syncUnidentified;
    const LABELS = [['all', 'All', 'total'],
                    ['identified', 'All identified', 'identified'],
                    ['unidentified', 'All unidentified', 'unidentified']];
    Array.from(select.options).forEach((option) => {
        const row = LABELS.find((l) => l[0] === option.value);
        if (!row) return;
        option.textContent = counts
            ? `${row[1]} (${counts[row[2]].toLocaleString()}*)`
            : row[1];
    });
}

function syncDialogChoice() {
    const scope = document.querySelector('input[name="mm_sync_scope"]:checked')?.value || 'all';
    return {
        scope,
        staleDays: scope === 'stale'
            ? parseInt(document.getElementById('mm_sync_stale_days')?.value || '0', 10)
            : 0,
        downloadedDays: scope === 'downloaded'
            ? parseInt(document.getElementById('mm_sync_downloaded_days')?.value || '0', 10)
            : 0,
        images: document.getElementById('mm_sync_images')?.checked || false,
        prompts: document.getElementById('mm_sync_prompts')?.checked || false,
        // As many images as each model has, unless the first page is chosen (#103).
        keepImageCount: document.querySelector('input[name="mm_sync_images_count"]:checked')?.value !== 'first',
        // A force sync reads files rather than asking about ids, so it is a
        // scope of its own rather than a depth.
        forceMode: scope === 'force'
            ? (document.getElementById('mm_sync_force_mode')?.value || 'all')
            : null,
    };
}

/** The file paths the filter bar currently selects, fetched once per opening. */
async function resolveResultPaths() {
    if (syncResultPaths) return syncResultPaths;
    const filters = getFilters();
    filters.paths_only = true;
    const data = await apiCall({ endpoint: '/model-manager/models', params: filters });
    syncResultPaths = (data && data.success) ? (data.paths || []) : [];
    return syncResultPaths;
}

/**
 * Ask the server what the current choice would cost, and show it.
 *
 * Debounced, because every control in the dialog calls it.
 */
function refreshSyncEstimate() {
    clearTimeout(syncEstimateTimer);
    syncEstimateTimer = setTimeout(async () => {
        const choice = syncDialogChoice();
        const estimateEl = document.getElementById('mm_sync_estimate');
        const startBtn = document.getElementById('mm_sync_dialog_start');

        if (choice.scope === 'force') {
            // Costed in files, not requests: this one is bound by reading
            // bytes off the disk. The count comes from the database, so
            // opening the dialog stays instant - the sync walks the model
            // folders itself and may find more, which the asterisk says.
            if (estimateEl) {
                estimateEl.textContent = describeForceSync(syncUnidentified, choice.forceMode)
                    + ' Also scans your model folders for files that are not in'
                    + ' the database yet, so the real number may be higher.';
            }
            if (startBtn) startBtn.disabled = false;
            // Its images, fetched either way, are costed in requests.
            try {
                const data = await apiCall({ endpoint: '/model-manager/sync/estimate',
                                             params: { force_mode: choice.forceMode || 'all' } });
                if (data && data.success) showImageOptions(data.force_images, choice.keepImageCount);
            } catch (error) {
                console.error('[ModelManager] Sync estimate failed:', error);
            }
            return;
        }

        try {
            const params = {
                include_images: choice.images,
                include_prompts: choice.images && choice.prompts,
                keep_image_count: choice.keepImageCount,
                stale_days: choice.staleDays,
                downloaded_days: choice.downloadedDays,
            };
            if (choice.scope === 'results') {
                params.paths = (await resolveResultPaths()).join(',');
            }
            const data = await apiCall({ endpoint: '/model-manager/sync/estimate', params });
            if (!data || !data.success) return;

            const { estimate, windows } = data;
            const { requests } = estimate;

            // Requests, not minutes: how long they take depends on the rate
            // limit, the round trip and any retries - none of which this knows,
            // and two of which differ from one machine to the next.
            //
            // The prompt count is an estimate - a gallery's size is only known
            // once it is fetched, so the server works from the ones already
            // cached - and says so with a ~, as does a total that includes it.
            // The rest are exact counts of the requests the sync will make.
            const cost = (id, count, approximate = false) => {
                const el = document.getElementById(id);
                if (el) {
                    el.textContent = count
                        ? `${approximate ? '~' : ''}${count.toLocaleString()} req`
                        : '-';
                }
            };
            // The checkpoint trained/merged check is part of fetching metadata
            // (two requests per hundred checkpoints). The total always counted
            // it; no line did, so the lines came to less than the total.
            cost('mm_cost_metadata', requests.metadata + (requests.checkpoints || 0));
            cost('mm_cost_images', requests.images);
            cost('mm_cost_prompts', requests.prompts, true);
            showImageOptions(choice.images ? estimate.image_options : null, choice.keepImageCount);
            const totalApproximate = requests.prompts > 0;

            syncUnidentified = data.unidentified || null;
            updateForceModeLabels();

            fillWindows('mm_sync_stale_days', windows);
            fillWindows('mm_sync_downloaded_days', data.download_windows);

            const allEl = document.getElementById('mm_scope_all');
            if (allEl && typeof estimate.all_versions === 'number') {
                allEl.textContent = `(${estimate.all_versions})`;
            }
            const resultsEl = document.getElementById('mm_scope_results');
            if (resultsEl && syncResultPaths) {
                resultsEl.textContent = `(${syncResultPaths.length})`;
            }

            if (estimateEl) {
                estimateEl.textContent = estimate.versions
                    ? `${estimate.versions.toLocaleString()} models`
                      + ` - ${totalApproximate ? '~' : ''}${requests.total.toLocaleString()}`
                      + ' requests to Civitai'
                    : 'Nothing selected - this would do nothing.';
            }
            if (startBtn) startBtn.disabled = !estimate.versions;
        } catch (error) {
            console.error('[ModelManager] Sync estimate failed:', error);
        }
    }, TIMING.estimate);
}

/**
 * The Images choice (#103): what each way of refetching costs, and the
 * notice above the buttons. `options` is the server's (image_options, or
 * force_images for a force sync); null hides them, images not being asked for.
 */
function showImageOptions(options, keep) {
    const group = document.getElementById('mm_sync_images_count');
    const notice = document.getElementById('mm_sync_images_notice');
    if (group) group.hidden = !options;
    if (notice) notice.hidden = !options;
    if (!options) return;
    const req = (option) => `${(option?.requests || 0).toLocaleString()} req`;
    setText(document.getElementById('mm_cost_images_kept'), req(options.kept));
    setText(document.getElementById('mm_cost_images_first'), req(options.first));
    setText(document.getElementById('mm_sync_images_first_label'), `First ${options.page} images per model`);
    setText(notice, imageCountNotice(options, keep));
}

/**
 * What refetching images will do (#103), in words: with the first page, how
 * many stored images go - and that they can still be seen, Load More
 * fetching them again - and, either way, that what comes back may not be
 * what is there now. `one` words it for a single model: its Sync button.
 */
export function imageCountNotice(options, keep, { one = false } = {}) {
    const said = [];
    const { images = 0, models = 0 } = options?.deletes || {};
    if (!keep && images) {
        said.push(one
            ? `This deletes ${images.toLocaleString()} of this model's stored images, past the first ${options.page} of each version.`
            : `This deletes ${images.toLocaleString()} stored images from your library: `
              + `${models.toLocaleString()} ${models === 1 ? 'model holds' : 'models hold'} more than ${options.page}.`);
        said.push('You can still see them as usual - Load More fetches them from Civitai again; only the stored copies go.');
    }
    said.push("The images synced won't necessarily be the ones you have now: Civitai's order changes as new images arrive.");
    return said.join(' ');
}

/**
 * The question a model's Sync asks first (#103): as many images as each of
 * its versions has - chosen to start with - or the first page of each;
 * each costed in requests, the images' and their prompts', with the notice
 * of what the choice does. Resolves to { keep }, or null for Cancel.
 * `options` is the estimate's image_options over the model's files.
 */
export function askImageCount(options) {
    return new Promise((resolve) => {
        let answer = null;
        const cost = (option) => `~${((option?.requests || 0) + (option?.prompts || 0)).toLocaleString()} req`;
        const backdrop = document.createElement('div');
        backdrop.className = 'mm-dialog-backdrop';
        backdrop.innerHTML = `
            <div class="mm-dialog mm-dialog-narrow mm-image-count-dialog" role="dialog" aria-modal="true">
                <h3>Sync this model</h3>
                <div class="mm-dialog-section">
                    <label class="mm-dialog-option">
                        <input type="radio" name="mm_sync_model_count" value="kept" checked>
                        <span>As many images as it has now</span>
                        <span class="mm-dialog-cost">${escapeHtml(cost(options.kept))}</span>
                    </label>
                    <label class="mm-dialog-option">
                        <input type="radio" name="mm_sync_model_count" value="first">
                        <span>First ${escapeHtml(String(options.page))} images of each version</span>
                        <span class="mm-dialog-cost">${escapeHtml(cost(options.first))}</span>
                    </label>
                </div>
                <div class="mm-dialog-notice"></div>
                <div class="mm-dialog-actions">
                    <button type="button" class="mm-btn secondary" data-close>Cancel</button>
                    <button type="button" class="mm-btn primary" data-confirm>Sync</button>
                </div>
            </div>`;
        const keep = () => backdrop.querySelector('input[name="mm_sync_model_count"]:checked')?.value !== 'first';
        const say = () => setText(backdrop.querySelector('.mm-dialog-notice'), imageCountNotice(options, keep(), { one: true }));
        const close = () => {
            if (!backdrop.isConnected) return;
            backdrop.remove();
            document.removeEventListener('keydown', onEscape, true);
            resolve(answer);
        };
        const onEscape = (event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            close();
        };
        backdrop.addEventListener('change', say);
        backdrop.addEventListener('click', (event) => {
            if (event.target.closest?.('[data-confirm]')) {
                answer = { keep: keep() };
                close();
            } else if (event.target === backdrop || event.target.closest?.('[data-close]')) {
                close();
            }
        });
        document.addEventListener('keydown', onEscape, true);
        say();
        document.body.appendChild(backdrop);
    });
}

/** A window dropdown, each option carrying how many models it would take. */
function fillWindows(selectId, windows) {
    const select = document.getElementById(selectId);
    if (!select || !windows || !windows.length) return;

    const chosen = select.value;
    select.textContent = '';
    windows.forEach((w) => {
        const option = document.createElement('option');
        option.value = String(w.days);
        option.textContent = `${w.label} (${w.versions})`;
        select.appendChild(option);
    });
    select.value = chosen || String(windows[2] ? windows[2].days : 7);
}

/**
 * "These search results" only means something once a search has run.
 *
 * Before that the grid is empty, so the option would either sync nothing or
 * quietly sync everything depending on how the empty filter set was read. It
 * is disabled instead, and carries its count once there is one - without
 * waiting to be picked, since the count is half of what makes it choosable.
 */
async function syncDialogResultsScope() {
    const radio = document.querySelector('input[name="mm_sync_scope"][value="results"]');
    if (!radio) return;
    const row = radio.closest('.mm-dialog-option');
    const label = document.getElementById('mm_scope_results');

    const searched = gridTotal() > 0;
    radio.disabled = !searched;
    if (row) row.classList.toggle('mm-dialog-muted', !searched);

    if (!searched) {
        if (radio.checked) {
            const all = document.querySelector('input[name="mm_sync_scope"][value="all"]');
            if (all) all.checked = true;
        }
        if (label) label.textContent = '';
        return;
    }

    if (label) label.textContent = '...';
    const paths = await resolveResultPaths();
    if (label) label.textContent = `(${paths.length})`;
}

/** Prompts only mean anything once the images they belong to are refetched. */
function syncDialogDependencies() {
    const images = document.getElementById('mm_sync_images');
    const prompts = document.getElementById('mm_sync_prompts');
    const promptsRow = document.getElementById('mm_sync_prompts_row');
    const imagesRow = images && images.closest('.mm-dialog-option');
    const scope = document.querySelector('input[name="mm_sync_scope"]:checked');
    const hashing = !!(scope && scope.value === 'force');

    // Identifying a file fetches its metadata, its gallery and the prompts
    // behind it - sync_model() does all three - so the depth is not a choice
    // while it is on. Whatever was chosen before comes back afterwards.
    if (hashing && images && prompts) {
        if (!syncDepthBeforeRehash) {
            syncDepthBeforeRehash = { images: images.checked, prompts: prompts.checked };
        }
        images.checked = true;
        prompts.checked = true;
    } else if (!hashing && syncDepthBeforeRehash && images && prompts) {
        images.checked = syncDepthBeforeRehash.images;
        prompts.checked = syncDepthBeforeRehash.prompts;
        syncDepthBeforeRehash = null;
    }

    // A disabled box must not sit there ticked: that reads as "this will
    // happen", when the whole point of disabling it is that it cannot. So
    // prompts follow images on the way down, and are offered again - ticked,
    // since that is the useful default - when images come back.
    if (!hashing && images && prompts) {
        if (!images.checked) {
            prompts.checked = false;
        } else if (!syncImagesWereOn) {
            prompts.checked = true;
        }
    }
    if (images) syncImagesWereOn = images.checked;

    if (images) images.disabled = hashing;
    if (prompts) prompts.disabled = hashing || !images.checked;
    if (imagesRow) imagesRow.classList.toggle('mm-dialog-muted', hashing);
    if (promptsRow) promptsRow.classList.toggle('mm-dialog-muted', hashing || !images.checked);

    updateForceModeLabels();
}

function openSyncDialog() {
    if (isSyncing) return;
    syncResultPaths = null;
    const dialog = document.getElementById('mm_sync_dialog');
    if (!dialog) return;
    dialog.style.display = 'flex';
    syncDialogDependencies();
    syncDialogResultsScope();
    refreshSyncEstimate();
}

/**
 * The Sync dialog, from elsewhere - a note: with Force sync and its mode
 * chosen if asked ("unidentified": the files Civitai has not identified
 * yet). Opened, never started.
 */
export function showSyncDialog({ force = null } = {}) {
    openSyncDialog();
    if (!force) return;
    const scope = document.querySelector('input[name="mm_sync_scope"][value="force"]');
    const mode = document.getElementById('mm_sync_force_mode');
    if (mode) mode.value = force;
    if (scope) {
        scope.checked = true;
        scope.dispatchEvent(new Event('change', { bubbles: true }));
    }
    mode?.dispatchEvent(new Event('change', { bubbles: true }));
}

function closeSyncDialog() {
    const dialog = document.getElementById('mm_sync_dialog');
    if (dialog) dialog.style.display = 'none';
}

async function startSyncFromDialog() {
    const choice = syncDialogChoice();
    closeSyncDialog();

    if (choice.scope === 'force') {
        startSync(choice.forceMode || 'all', choice.keepImageCount);
        return;
    }

    const paths = choice.scope === 'results' ? await resolveResultPaths() : null;
    startMetadataSync({
        includeImages: choice.images,
        includePrompts: choice.images && choice.prompts,
        keepImageCount: choice.keepImageCount,
        staleDays: choice.staleDays,
        downloadedDays: choice.downloadedDays,
        paths,
    });
}

async function startMetadataSync({ includeImages = false, includePrompts = true, keepImageCount = false,
                                   staleDays = 0, downloadedDays = 0,
                                   paths = null } = {}) {
    if (isSyncing) return;

    isSyncing = true;
    updateSyncUI(true);
    setStatus(includeImages
        ? 'Refreshing Civitai metadata and images...'
        : 'Refreshing Civitai metadata...');

    try {
        const body = new URLSearchParams({
            include_images: String(includeImages),
            include_prompts: String(includePrompts),
            keep_image_count: String(keepImageCount),
            stale_days: String(staleDays),
            downloaded_days: String(downloadedDays),
        });
        if (paths && paths.length) body.set('paths', paths.join(','));

        const response = await fetch('/model-manager/sync/metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString()
        });
        const data = await response.json();

        if (data.success) {
            // pollSyncProgress() is a single sample that clears this
            // interval once the run reports complete - without the
            // interval the bar freezes and isSyncing is never released.
            syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
        } else {
            setStatus(`Metadata sync failed: ${data.error}`, true);
            isSyncing = false;
            updateSyncUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Metadata sync error:', error);
        setStatus(`Metadata sync failed: ${error.message}`, true);
        isSyncing = false;
        updateSyncUI(false);
    }
}

// Update UI based on sync state
function updateSyncUI(syncing) {
    const syncBtn = document.getElementById('mm_sync_btn');
    const cancelBtn = document.getElementById('mm_sync_cancel_btn');
    const progressDiv = document.getElementById('mm_sync_progress');
    const loadBtn = document.getElementById('mm_load_btn');
    const refreshBtn = document.getElementById('mm_refresh_btn');

    if (syncBtn) syncBtn.disabled = syncing || isScanning;
    if (loadBtn) loadBtn.disabled = syncing || isScanning;
    if (refreshBtn) refreshBtn.disabled = syncing || isScanning;
    if (cancelBtn) cancelBtn.style.display = syncing ? 'inline-block' : 'none';
    if (progressDiv) progressDiv.style.display = syncing ? 'block' : 'none';

    // Reset progress bar when starting
    if (syncing) {
        const fillEl = document.getElementById('mm_sync_fill');
        const textEl = document.getElementById('mm_sync_text');
        if (fillEl) fillEl.style.width = '0%';
        if (textEl) textEl.textContent = 'Preparing...';
    }
}

// ==================== SCAN/REFRESH FUNCTIONS ====================

// Start database refresh scan
/**
 * Say what Scan Disk will do before it does it.
 *
 * It adds and removes rows to match what is on disk, which is not something to
 * discover after the fact - and unlike the sync dialog there is nothing to
 * choose here, so it is a confirmation rather than a form.
 */
function openScanDialog() {
    if (isScanning || isSyncing) return;
    const dialog = document.getElementById('mm_scan_dialog');
    if (!dialog) {
        startScan();     // no dialog in the page: do the thing rather than nothing
        return;
    }
    // Every scan starts as the usual one: reading every header, or moving
    // files, is asked for each time.
    const reread = document.getElementById('mm_scan_reread');
    if (reread) reread.checked = false;
    const move = document.getElementById('mm_scan_move');
    if (move) move.checked = false;
    dialog.style.display = 'flex';
    showMisplaced();
}

/**
 * Which files Scan Disk would move into their type's folder, before anyone
 * ticks the box: the count, why each would move, and the ones that will stay
 * because their name is taken there. Its box is never ticked for anyone - a
 * note's button ticks "Re-evaluate file headers", and must not move files.
 */
async function showMisplaced() {
    const move = document.getElementById('mm_scan_move');
    const note = document.getElementById('mm_scan_move_note');
    const details = document.getElementById('mm_scan_misplaced');
    const list = document.getElementById('mm_scan_misplaced_list');
    if (!move || !note) return;
    move.disabled = true;
    if (details) details.hidden = true;
    let files = [];
    try {
        const data = await apiCall({ endpoint: '/model-manager/scan/misplaced' });
        files = data.success ? data.files || [] : null;
    } catch (e) {
        files = null;
    }
    if (files === null) {
        setText(note, 'Could not tell which files are in another type\'s folder.');
        return;
    }
    if (!files.length) {
        setText(note, 'No file is in a folder for another type.');
        return;
    }
    const staying = files.filter((f) => f.clash).length;
    setText(note, `${files.length} file${files.length === 1 ? ' is' : 's are'} in a folder for another type - `
        + 'a VAE in Stable-diffusion, say, where Forge offers it as a checkpoint. Ticked, each is moved '
        + 'with its .civitai.info and preview into its type\'s folder; its place in the library, its pin '
        + 'and its generations go with it.'
        + (staying ? ` ${staying} will stay where ${staying === 1 ? 'it is' : 'they are'}: `
            + 'a file of that name is already in the folder.' : ''));
    const clashText = { same: 'the same file is already there', different: 'a different file of that name is already there',
                        exists: 'a file of that name is already there' };
    if (list) {
        list.innerHTML = files.map((f) => `<li>${escapeHtml(f.path)} → ${escapeHtml(f.to)}
            <span class="mm-scan-misplaced-why">(${escapeHtml(f.file_type)}${f.identified_by ? ': ' + escapeHtml(f.identified_by) : ''})${
            f.clash ? ' - stays: ' + clashText[f.clash] : ''}</span></li>`).join('');
    }
    if (details) details.hidden = false;
    move.disabled = false;
}

/** Scan Disk's dialog, from elsewhere - a note: "Re-evaluate file headers" ticked if asked. */
export function showScanDialog({ rereadHeaders = false } = {}) {
    openScanDialog();
    const reread = document.getElementById('mm_scan_reread');
    if (reread) reread.checked = rereadHeaders;
}

function closeScanDialog() {
    const dialog = document.getElementById('mm_scan_dialog');
    if (dialog) dialog.style.display = 'none';
}

/**
 * @param {{rereadHeaders?: boolean, moveMisplaced?: boolean}} options -
 *     rereadHeaders: read what every file is from its header again, not only
 *     new or changed files. moveMisplaced: move files in another type's
 *     folder into their own.
 */
async function startScan({ rereadHeaders = false, moveMisplaced = false } = {}) {
    if (isScanning || isSyncing) return;

    isScanning = true;
    updateScanUI(true);
    setStatus('Starting database refresh...');

    try {
        const response = await fetch('/model-manager/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reread_headers: rereadHeaders, move_misplaced: moveMisplaced }),
        });

        const data = await response.json();

        if (data.success) {
            // Start polling for progress
            scanPollInterval = setInterval(pollScanProgress, TIMING.scanPoll);
        } else {
            setStatus('Scan failed: ' + (data.error || 'Unknown error'), true);
            isScanning = false;
            updateScanUI(false);
        }
    } catch (error) {
        console.error('[ModelManager] Scan error:', error);
        setStatus('Scan error: ' + error.message, true);
        isScanning = false;
        updateScanUI(false);
    }
}

// Poll scan progress
async function pollScanProgress() {
    try {
        const data = await apiCall({ endpoint: '/model-manager/scan/progress' });

        if (data.success && data.progress) {
            const p = data.progress;

            // Update progress bar
            const percent = p.total > 0 ? (p.processed / p.total * 100) : 0;
            const fillEl = document.getElementById('mm_scan_fill');
            const textEl = document.getElementById('mm_scan_text');

            if (fillEl) fillEl.style.width = percent + '%';
            if (textEl) {
                textEl.textContent = `Scanning: ${p.processed}/${p.total} - ${p.current_file || 'Preparing...'}`;
            }

            // Update status
            setStatus(`Scan: ${p.processed}/${p.total} models processed`);

            // Check if complete
            if (p.is_complete) {
                clearInterval(scanPollInterval);
                scanPollInterval = null;
                isScanning = false;
                updateScanUI(false);

                // Show final status
                const errorInfo = p.error_count > 0 ? ` (${p.error_count} errors)` : '';
                const moveInfo = (p.moved ? `, ${p.moved} moved into their type's folder` : '')
                    + (p.not_moved ? `, ${p.not_moved} left where ${p.not_moved === 1 ? 'it was' : 'they were'} (a file of that name is already there)` : '');
                setStatus(`Scan complete: ${p.processed} models indexed${moveInfo}${errorInfo}`);
                loadBaseModelOptions();

                // Reload models to show updated data
                setTimeout(loadModels, 500);
            }
        }
    } catch (error) {
        console.error('[ModelManager] Scan progress poll error:', error);
    }
}

// Cancel scan
async function cancelScan() {
    try {
        await fetch('/model-manager/scan/cancel', { method: 'POST' });
        setStatus('Canceling scan...');
    } catch (error) {
        console.error('[ModelManager] Scan cancel error:', error);
    }
}

// Update UI based on scan state
function updateScanUI(scanning) {
    const refreshBtn = document.getElementById('mm_refresh_btn');
    const scanCancelBtn = document.getElementById('mm_scan_cancel_btn');
    const scanProgressDiv = document.getElementById('mm_scan_progress');
    const loadBtn = document.getElementById('mm_load_btn');
    const syncBtn = document.getElementById('mm_sync_btn');

    if (refreshBtn) refreshBtn.disabled = scanning || isSyncing;
    if (loadBtn) loadBtn.disabled = scanning || isSyncing;
    if (syncBtn) syncBtn.disabled = scanning || isSyncing;
    if (scanCancelBtn) scanCancelBtn.style.display = scanning ? 'inline-block' : 'none';
    if (scanProgressDiv) scanProgressDiv.style.display = scanning ? 'block' : 'none';

    // Reset progress bar when starting
    if (scanning) {
        const fillEl = document.getElementById('mm_scan_fill');
        const textEl = document.getElementById('mm_scan_text');
        if (fillEl) fillEl.style.width = '0%';
        if (textEl) textEl.textContent = 'Preparing...';
    }
}

// Check for ongoing scan/sync processes and resume polling
export async function checkOngoingProcesses() {
    console.log('[ModelManager] Checking for ongoing processes...');

    // Check for ongoing scan
    try {
        const scanData = await apiCall({ endpoint: '/model-manager/scan/progress' });
        if (scanData.success && scanData.progress && !scanData.progress.is_complete) {
            console.log('[ModelManager] Found ongoing scan, resuming...');
            isScanning = true;
            updateScanUI(true);
            setStatus(`Scan in progress: ${scanData.progress.processed}/${scanData.progress.total}`);

            // Resume polling
            if (!scanPollInterval) {
                scanPollInterval = setInterval(pollScanProgress, TIMING.scanPoll);
            }
        }
    } catch (error) {
        console.log('[ModelManager] No ongoing scan');
    }

    // Check for ongoing sync
    try {
        const syncData = await apiCall({ endpoint: '/model-manager/sync/progress' });
        if (syncData.success && syncData.progress && !syncData.progress.is_complete) {
            console.log('[ModelManager] Found ongoing sync, resuming...');
            isSyncing = true;
            updateSyncUI(true);
            setStatus(`Sync in progress: ${syncData.progress.processed}/${syncData.progress.total}`);

            // Resume polling
            if (!syncPollInterval) {
                syncPollInterval = setInterval(pollSyncProgress, TIMING.poll);
            }
        }
    } catch (error) {
        console.log('[ModelManager] No ongoing sync');
    }
}

if (typeof document !== 'undefined') {
    // Also check when tab becomes visible
    document.addEventListener?.('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            // Only check if we're not already tracking a process
            if (!isScanning && !isSyncing) {
                checkOngoingProcesses();
            }
        }
    });
}

/**
 * Wire the jobs' buttons and dialogs: Sync and its Cancel, Scan Disk and its
 * Cancel, and both dialogs - the Model Manager's markup, which its
 * bindElements() calls this for once it is there.
 */
export function bindJobControls() {
    const syncBtn = document.getElementById('mm_sync_btn');
    const cancelBtn = document.getElementById('mm_sync_cancel_btn');
    const refreshBtn = document.getElementById('mm_refresh_btn');
    const scanCancelBtn = document.getElementById('mm_scan_cancel_btn');

    // Bind sync button
    if (syncBtn) {
        const newSyncBtn = syncBtn.cloneNode(true);
        syncBtn.parentNode.replaceChild(newSyncBtn, syncBtn);

        newSyncBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openSyncDialog();
        });
    }

    // The dialog behind that button. Every control re-costs the choice, so
    // the figure at the bottom always describes what Start would do.
    const syncDialog = document.getElementById('mm_sync_dialog');
    if (syncDialog) {
        syncDialog.addEventListener('change', (e) => {
            if (e.target.id === 'mm_sync_images' || e.target.name === 'mm_sync_scope'
                    || e.target.id === 'mm_sync_force_mode') {
                syncDialogDependencies();
            }
            // Touching a window picks the scope it belongs to, so the two
            // do not have to be set in the right order.
            const SCOPE_OF = {
                mm_sync_stale_days: 'stale',
                mm_sync_downloaded_days: 'downloaded',
                mm_sync_force_mode: 'force',
            };
            const scope = SCOPE_OF[e.target.id];
            if (scope) {
                const radio = syncDialog.querySelector(
                    `input[name="mm_sync_scope"][value="${scope}"]`);
                if (radio) radio.checked = true;
            }
            refreshSyncEstimate();
        });
        syncDialog.addEventListener('click', (e) => {
            if (e.target === syncDialog) closeSyncDialog();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && syncDialog.style.display !== 'none') closeSyncDialog();
        });
        const dialogCancel = document.getElementById('mm_sync_dialog_cancel');
        if (dialogCancel) dialogCancel.addEventListener('click', closeSyncDialog);
        const dialogStart = document.getElementById('mm_sync_dialog_start');
        if (dialogStart) dialogStart.addEventListener('click', startSyncFromDialog);
    }

    // Bind sync cancel button
    if (cancelBtn) {
        const newCancelBtn = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

        newCancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            cancelSync();
        });
    }

    // Bind refresh/scan button
    if (refreshBtn) {
        const newRefreshBtn = refreshBtn.cloneNode(true);
        refreshBtn.parentNode.replaceChild(newRefreshBtn, refreshBtn);

        newRefreshBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openScanDialog();
        });
    }

    // The confirmation behind it: same dismissal rules as the sync dialog.
    const scanDialog = document.getElementById('mm_scan_dialog');
    if (scanDialog) {
        scanDialog.addEventListener('click', (e) => {
            if (e.target === scanDialog) closeScanDialog();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && scanDialog.style.display !== 'none') closeScanDialog();
        });
        const scanCancel = document.getElementById('mm_scan_dialog_cancel');
        if (scanCancel) scanCancel.addEventListener('click', closeScanDialog);
        const scanStart = document.getElementById('mm_scan_dialog_start');
        if (scanStart) {
            scanStart.addEventListener('click', () => {
                const rereadHeaders = !!document.getElementById('mm_scan_reread')?.checked;
                const moveMisplaced = !!document.getElementById('mm_scan_move')?.checked;
                closeScanDialog();
                startScan({ rereadHeaders, moveMisplaced });
            });
        }
    }

    // Bind scan cancel button
    if (scanCancelBtn) {
        const newScanCancelBtn = scanCancelBtn.cloneNode(true);
        scanCancelBtn.parentNode.replaceChild(newScanCancelBtn, scanCancelBtn);

        newScanCancelBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            cancelScan();
        });
    }
}
