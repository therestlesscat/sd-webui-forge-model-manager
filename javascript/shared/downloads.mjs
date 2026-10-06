/**
 * A version to download, and the downloads on their way - the same in both
 * tabs.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, apiCall, escapeHtml, dataAttributes, safeId, formatBytes, formatDay } = await shared('core.mjs');
const { provide } = await shared('calls.mjs');
const { apiKeyIsMissing } = await shared('ui_options.mjs');

// ------------------------------------------------------ a version to download
// Both tabs show a version that is not in the library the same way: what it
// is, what it costs, which of its files a download produces. The Civitai
// Browser shows every version of a search result; the Model Manager shows the
// versions of a local model that were never downloaded.

/**
 * Describe a version's paywall, or '' when it is free.
 *
 * `paid_access` is attached by the backend: Civitai leaves `availability`
 * as "Public" for paid versions, so the field is the only marker.
 */
export function paidAccessLabel(version) {
    const paid = version?.paid_access;
    if (!paid) return '';
    if (paid.permanent) return 'Paid';
    return paid.ends_at ? `Early Access until ${formatDay(paid.ends_at)}` : 'Early Access';
}

export function isPaid(version) {
    return !!version?.paid_access;
}

/**
 * Index of the file a download of this version will produce.
 *
 * Mirrors download_service.pick_file_index: files[0] is often the full
 * fp32 weights, roughly twice the size of the pruned file Civitai marks
 * primary, so the primary one is the default rather than the first.
 */
export function primaryFileIndex(version) {
    const files = version?.files || [];
    const primary = files.findIndex(f => f.primary);
    return primary === -1 ? 0 : primary;
}

/**
 * How a file reads in the picker: "pruned fp16 - 1.99 GB".
 *
 * metadata carries format/size/fp for model files; anything without it
 * (a VAE, a config, training data) falls back to its name and type.
 */
export function describeFile(file) {
    const meta = file?.metadata || {};
    const parts = [meta.size, meta.fp].filter(Boolean);

    if (!parts.length) {
        const type = file?.type && file.type !== 'Model' ? file.type : '';
        parts.push(type || file?.name || 'File');
    } else if (file?.type && file.type !== 'Model') {
        parts.push(file.type);
    }

    const size = file?.sizeKB ? formatBytes(file.sizeKB * 1024) : '';
    return size ? `${parts.join(' ')} - ${size}` : parts.join(' ');
}

// What a Download button says while its version is on its way, and is
// disabled for: one click, one download.
const DOWNLOAD_BUTTON_BUSY = {
    starting: 'Starting...', pending: 'Queued', downloading: 'Downloading...',
    finishing: 'Adding to library...', complete: 'Downloaded', paused: 'Paused',
};

// A version asked for and not yet over is not asked for again: the server
// answers the download it has (#119). A finished one can be - its file may
// have been deleted since - though its Download button, saying Downloaded,
// takes no click until the list forgets it.
const ON_ITS_WAY = new Set(['starting', 'pending', 'downloading', 'finishing', 'paused']);

/** Whether a version's download is on its way: asked for, queued, coming, being added, or paused. */
export function onItsWay(versionId) {
    return ON_ITS_WAY.has(downloads()?.status(versionId));
}

/** A Download button's label and whether it is disabled, from its version's download. */
function downloadButtonState(versionId) {
    const busy = DOWNLOAD_BUTTON_BUSY[downloads()?.status(versionId)];
    return { disabled: !!busy, label: busy || 'Download' };
}

/**
 * The Download button and, when there is a choice, the file picker.
 *
 * `controls` is the tab's, named once there: the `prefix` of its ids - the
 * button is `<prefix>_download_btn` - and what its markup does
 * (shared/calls.mjs): `download`, reading data-model-id, data-version-id and
 * data-file-id, and `selectFile`, the picker's value its file's index.
 * A paid version answers the download URL
 * with 401/403 until it is bought on Civitai, so it is offered only when
 * Civitai says the API key's account bought it (`paid_access.owned`, see
 * civitai/ownership.py); otherwise its label, saying why. While
 * the version is downloading - from the click until it is in the library - the
 * button says so and takes no clicks: a second click started it again.
 */
export function renderDownloadControls({ controls, modelId, version, fileIndex, owned }) {
    const { prefix, download, selectFile } = controls;
    const files = version?.files || [];
    const file = files[fileIndex];
    const paidLabel = paidAccessLabel(version);

    let button = '';
    if (owned) {
        button = `<button class="mm-btn secondary" disabled>Already Owned</button>`;
    } else if (paidLabel && version?.paid_access?.owned !== true) {
        const why = version?.paid_access?.owned === false
            ? 'Civitai says your account has not bought it. Just bought it? Its API takes some minutes to know: '
              + 'open this version again shortly'
            : apiKeyIsMissing()
                ? 'Set a Civitai API key in the settings: a version you have bought then downloads here'
                : 'Civitai could not say whether your account has bought it';
        // Its page is the panel's View on Civitai, beside this.
        button = `<button class="mm-btn secondary" disabled title="${escapeHtml(why)}">${escapeHtml(paidLabel)}</button>`;
    } else if (file) {
        const state = downloadButtonState(version?.id);
        const bought = paidLabel ? ' title="Paid on Civitai - your account has bought it"' : '';
        button = `<button class="mm-btn primary" id="${prefix}_download_btn"${bought} `
            + `data-download-version="${safeId(version?.id)}" ${state.disabled ? 'disabled' : ''} `
            + `data-action="${escapeHtml(download)}"`
            + `${dataAttributes({ modelId: safeId(modelId), versionId: safeId(version?.id), fileId: safeId(file?.id) })}>`
            + `${state.label}</button>`;
    }

    // Only worth a control when there is something to choose between.
    const picker = files.length > 1
        ? `<select class="${prefix}-file-select" data-action="${escapeHtml(selectFile)}"
                   title="Which file to download">
             ${files.map((f, i) => `<option value="${i}" ${i === fileIndex ? 'selected' : ''}
                    title="${escapeHtml(f.name || '')}">${escapeHtml(describeFile(f))}`
                    + `${f.primary ? ' (default)' : ''}</option>`).join('')}
           </select>`
        : '';

    return `${button}\n${picker}`;
}

/**
 * Point the File and File Size rows and the Download button at another file.
 *
 * In place rather than re-rendering the panel, which would scroll the reader
 * back to the top. The rows are `<prefix>_file_name` and `<prefix>_file_size`;
 * `controls` as for renderDownloadControls.
 */
export function showChosenFile(controls, modelId, version, file) {
    const { prefix } = controls;
    const nameCell = document.getElementById(`${prefix}_file_name`);
    if (nameCell) nameCell.textContent = file.name || 'Unknown';

    const sizeCell = document.getElementById(`${prefix}_file_size`);
    if (sizeCell) {
        sizeCell.textContent = file.sizeKB ? formatBytes(file.sizeKB * 1024) : 'Unknown';
    }

    // The button's action reads these (renderDownloadControls).
    const button = document.getElementById(`${prefix}_download_btn`);
    if (button) {
        const ids = { 'data-model-id': modelId, 'data-version-id': version?.id, 'data-file-id': file.id };
        for (const [name, id] of Object.entries(ids)) button.setAttribute(name, String(safeId(id) ?? ''));
    }
}

// ---------------------------------------------------------------- downloads
// A download takes minutes, and neither tab should make anyone stay in it to
// see how it is going. So there is one list, polled once, and each tab draws
// it in a panel of its own: a download started in either shows in both.
// The tabs share this module's one copy (#53), so the list is its own.

/**
 * Tell the WebUI about newly downloaded files.
 *
 * Downloading writes the file but the WebUI has already listed its model
 * directories, so a new checkpoint does not appear in the native dropdown
 * until something re-scans. Click the refresh control next to that
 * dropdown - the same one a user would press. Forge and Forge Neo both
 * expose it as #forge_refresh_checkpoint, and both hand back only new
 * choices, so the current selection is left alone.
 */
export function refreshWebUiModelList() {
    const root = (typeof gradioApp === 'function') ? gradioApp() : document;
    const refreshButton = root.querySelector('#forge_refresh_checkpoint');

    if (refreshButton) {
        refreshButton.click();
        console.log('[ModelManager] Refreshed the WebUI model list');
    } else {
        console.warn('[ModelManager] Could not find the checkpoint refresh button; '
            + 'the new model may need a manual refresh');
    }
}

/** Bytes a second as a person reads them: "12.4 MB", "800 KB" - one decimal, none when it is 0. */
function formatSpeed(bytes) {
    const [unit, size] = [['GB', 1073741824], ['MB', 1048576], ['KB', 1024]].find(([, s]) => bytes >= s)
        || ['B', 1];
    return `${(bytes / size).toFixed(1).replace(/\.0$/, '')} ${unit}`;
}

/**
 * How fast a download is going, and how long it has left, as the server
 * measured them (DownloadProgress.rate): "12.4 MB/s · about 5 min left", or
 * "stalled" - never "0 B/s" - and nothing while there is nothing to say yet.
 */
export function downloadRateText(dl) {
    if (dl.status !== 'downloading') return '';
    if (dl.stalled) return 'stalled';
    if (!dl.speed_bps) return '';
    const parts = [`${formatSpeed(dl.speed_bps)}/s`];
    const left = dl.eta_seconds;
    if (typeof left === 'number') {
        const minutes = Math.ceil(left / 60);        // rounded up: "about 1 min" is never late
        if (left < 60) parts.push('less than a minute left');
        else if (minutes < 60) parts.push(`about ${minutes} min left`);
        else parts.push(`about ${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ''} left`);
    }
    return parts.join(' · ');
}

const DOWNLOAD_STATUS_TEXT = {
    downloading: 'Downloading', pending: 'Queued', finishing: 'Adding to library',
    complete: 'Complete', error: 'Error', cancelled: 'Cancelled', paused: 'Paused',
};

/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th, 21st. */
function ordinal(n) {
    const tens = n % 100;
    const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return `${n}${suffix}`;
}

/** A small button in a download's row: downloads.control, as the panel's Pause all. */
function downloadControl(action, versionId, label, title, { disabled = false, kind = 'secondary' } = {}) {
    return `<button class="mm-btn mm-btn-small ${kind}" title="${escapeHtml(title)}" ${disabled ? 'disabled' : ''}
                    data-action="downloads.control" data-control="${escapeHtml(action)}"`
        + `${dataAttributes({ versionId: safeId(versionId) })}>${label}</button>`;
}

/** One download, as a panel shows it. Classes are the tab's own: `<prefix>-download-*`. */
function renderDownloadItem(dl, prefix) {
    const status = dl.status || 'pending';
    const percent = dl.percent?.toFixed(1) || 0;
    const downloaded = formatBytes(dl.downloaded_bytes || 0);
    const total = formatBytes(dl.total_bytes || 0);
    // finishing: on disk, being added to the library. Not complete until
    // it is, so that Complete and "Show in MM" arrive together.
    const showProgress = status === 'downloading' || status === 'pending' || status === 'finishing'
        || status === 'paused';
    const showCancel = status === 'downloading' || status === 'pending' || status === 'paused';
    const id = dl.version_id;
    // Running: Pause. Waiting: Start now, and up or down the queue. Paused: Resume.
    const controls = status === 'downloading'
        ? downloadControl('pause', id, 'Pause', 'Pause: keeps what has arrived, and lets the next in the queue start')
        : status === 'pending'
            ? downloadControl('start_now', id, 'Start now', 'Start it now, beside those running')
              + downloadControl('up', id, '↑', 'Move up the queue', { disabled: dl.queue_position === 1 })
              + downloadControl('down', id, '↓', 'Move down the queue', { disabled: !!dl.last_in_queue })
            : status === 'paused'
                ? downloadControl('resume', id, 'Resume', 'Carry on from where it stopped', { kind: 'primary' })
                : '';
    const showDismiss = status === 'complete' || status === 'error' || status === 'cancelled';
    const p = prefix;

    return `
        <div class="${p}-download-item ${status}">
            <div class="${p}-download-item-header">
                <div class="${p}-download-name" title="${escapeHtml(dl.file_name || 'Unknown')}">${escapeHtml(dl.file_name || 'Unknown')}</div>
                <span class="${p}-download-status-badge ${status}">${DOWNLOAD_STATUS_TEXT[status] || status}</span>
            </div>
            ${showProgress ? `
                <div class="${p}-download-progress">
                    <div class="${p}-download-bar" style="width: ${status === 'pending' || status === 'finishing' ? 100 : percent}%"></div>
                </div>
            ` : ''}
            <div class="${p}-download-info">
                <span class="${p}-download-percent">
                    ${status === 'downloading' ? `${percent}% - ${downloaded} / ${total}` : ''}
                    ${downloadRateText(dl) ? ` · ${escapeHtml(downloadRateText(dl))}` : ''}
                    ${status === 'downloading' && dl.started_over ? ' · started over: the server would not resume' : ''}
                    ${status === 'pending' ? (dl.queue_position ? `Waiting - ${ordinal(dl.queue_position)} in the queue` : 'Waiting...') : ''}
                    ${status === 'paused' ? `Paused - ${downloaded} / ${total}` : ''}
                    ${status === 'finishing' ? `Adding to library... ${total}` : ''}
                    ${status === 'complete' ? `${total}` : ''}
                    ${status === 'complete' && dl.filed ? ` · ${escapeHtml(dl.filed)}` : ''}
                    ${status === 'error' ? escapeHtml(dl.error || 'Download failed') : ''}
                    ${status === 'error' && dl.page_url
                        ? ` <a class="mm-download-page-link" href="${escapeHtml(dl.page_url)}" target="_blank" rel="noopener">Open on Civitai</a>`
                        : ''}
                    ${status === 'cancelled' ? 'Download cancelled' : ''}
                </span>
                <div class="${p}-download-actions">
                    ${controls}
                    ${showCancel ? `
                        <button class="mm-btn mm-btn-small danger" data-action="downloads.cancel"${dataAttributes({ versionId: safeId(dl.version_id) })}>Cancel</button>
                    ` : ''}
                    ${showDismiss ? `
                        <button class="mm-btn mm-btn-small secondary" data-action="downloads.dismiss"${dataAttributes({ versionId: safeId(dl.version_id) })}>Dismiss</button>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

function createDownloads() {
    const items = {};          // version id -> the server's progress
    // The list's order, as the server keeps it: the order downloads were
    // added in, which ↑/↓ change - never their state, so no row moves when
    // one is paused or resumed. (An object's number keys come out sorted.)
    let sequence = [];
    const panels = new Set();  // tab prefixes with a panel on the page
    const completed = [];      // callbacks, each given a download once it is in the library
    const batchDone = [];      // callbacks, once nothing is left running
    const changed = [];        // callbacks, after each look at the list - the Resources dialog's
    // Dismissed here, and asked of the server to forget. A poll already on its
    // way can still carry one; it is not taken back unless it starts again.
    const dismissed = new Set();
    let poll = null;
    let landed = false;        // a download reached the library in this batch
    const finished = (dl) => ['complete', 'error', 'cancelled'].includes(dl.status);

    const running = (dl) => dl.status === 'downloading' || dl.status === 'pending'
        || dl.status === 'finishing' || (dl.status === 'complete' && !dl.synced);
    const starting = new Set();  // clicked, and the server has not answered yet

    /** Every Download button on the page, as its version's download stands. */
    function renderButtons() {
        for (const button of document.querySelectorAll('[data-download-version]')) {
            const state = downloadButtonState(Number(button.getAttribute('data-download-version')));
            button.disabled = state.disabled;
            button.textContent = state.label;
        }
    }

    function render() {
        const listed = sequence.filter((id) => items[id]);
        const downloads = [...listed, ...Object.keys(items).map(Number).filter((id) => !listed.includes(id))]
            .map((id) => items[id]);
        const lastPlace = Math.max(0, ...downloads.map((d) => d.queue_position || 0));
        downloads.forEach((d) => { d.last_in_queue = d.status === 'pending' && d.queue_position === lastPlace; });

        const active = downloads.filter(d => d.status === 'downloading' || d.status === 'finishing').length;
        const queued = downloads.filter(d => d.status === 'pending').length;
        const paused = downloads.filter(d => d.status === 'paused').length;
        const done = downloads.filter(finished).length;
        const summary = [active && `${active} downloading`, queued && `${queued} pending`,
                         paused && `${paused} paused`, done && `${done} finished`].filter(Boolean).join(', ')
            || `${downloads.length} total`;

        renderButtons();
        for (const prefix of panels) {
            const panel = document.getElementById(`${prefix}_downloads`);
            const list = document.getElementById(`${prefix}_download_list`);
            const summaryEl = document.getElementById(`${prefix}_downloads_summary`);
            const dismissAll = document.getElementById(`${prefix}_downloads_dismiss_all`);
            const pauseAll = document.getElementById(`${prefix}_downloads_pause_all`);
            const resumeAll = document.getElementById(`${prefix}_downloads_resume_all`);
            if (panel) panel.style.display = downloads.length ? 'block' : 'none';
            if (dismissAll) dismissAll.style.display = done ? '' : 'none';
            if (pauseAll) pauseAll.style.display = active + queued ? '' : 'none';
            if (resumeAll) resumeAll.style.display = paused ? '' : 'none';
            if (!list) continue;
            if (summaryEl) summaryEl.textContent = summary;
            list.innerHTML = downloads.map(dl => renderDownloadItem(dl, prefix)).join('');
        }
    }

    async function tick() {
        try {
            const result = await apiCall({ endpoint: '/model-manager/civitai/download/progress' });
            if (!result.success || !result.downloads) return;
            // The list is the server's: one it no longer has is gone here too.
            const listed = new Set(result.downloads.map((dl) => dl.version_id));
            for (const id of Object.keys(items)) {
                if (!listed.has(items[id].version_id)) delete items[id];
            }
            sequence = result.downloads.map((dl) => dl.version_id);
            for (const dl of result.downloads) {
                if (dismissed.has(dl.version_id)) {
                    if (finished(dl)) continue;
                    dismissed.delete(dl.version_id);         // started again
                }
                const prev = items[dl.version_id];
                // The file lands well before its database row does; until
                // `synced` the model is not in the library yet.
                const arrived = dl.status === 'complete' && dl.synced && !(prev && prev.synced);
                items[dl.version_id] = dl;
                if (arrived) {
                    landed = true;
                    for (const callback of completed) {
                        try { callback(dl); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
            render();
            told();

            if (!Object.values(items).some(running)) {
                clearInterval(poll);
                poll = null;
                // Once per batch - re-scanning walks every model directory,
                // so there is no point doing it per file.
                if (landed) {
                    landed = false;
                    refreshWebUiModelList();
                    for (const callback of batchDone) {
                        try { callback(); } catch (e) { console.error('[ModelManager] Download callback:', e); }
                    }
                }
            }
        } catch (e) {
            console.error('[ModelManager] Download poll error:', e);
        }
    }

    function told() {
        for (const callback of changed) {
            try { callback(); } catch (e) { console.error('[ModelManager] Download callback:', e); }
        }
    }

    const store = {
        /** Draw the list in this tab's panel: `<prefix>_downloads` and the ids inside it. */
        addPanel: (prefix) => { panels.add(prefix); render(); },
        onComplete: (callback) => { completed.push(callback); },
        onBatchDone: (callback) => { batchDone.push(callback); },
        /** Called after each look at the list, and when one is added to it. */
        onChange: (callback) => { changed.push(callback); },
        /** A version's download as the server last said, or undefined. */
        progress: (versionId) => items[versionId],

        /** Follow a download the server has accepted. */
        track: (progress) => {
            if (!progress || progress.version_id == null) return;
            dismissed.delete(progress.version_id);
            items[progress.version_id] = progress;
            if (!sequence.includes(progress.version_id)) sequence.push(progress.version_id);
            render();
            told();
            if (!poll) poll = setInterval(tick, TIMING.poll);
        },

        /**
         * Ask for a version, and follow it. Returns the server's answer, with
         * its HTTP status. `newerIfGone`: the model's newest version if this
         * one is gone from Civitai - what the Resources dialog asks for.
         */
        start: async function start(modelId, versionId, fileId, { newerIfGone = false } = {}) {
            if (onItsWay(versionId)) return { success: false, error: 'Already downloading' };
            starting.add(Number(versionId));
            renderButtons();
            try {
                const form = new FormData();
                if (modelId) form.append('model_id', modelId);
                form.append('version_id', versionId);
                // Omitted when unknown, which leaves the backend on the primary.
                if (fileId !== undefined && fileId !== null) form.append('file_id', fileId);
                if (newerIfGone) form.append('newer_if_gone', 'true');
                const response = await fetch('/model-manager/civitai/download', { method: 'POST', body: form });
                const result = await response.json();
                starting.delete(Number(versionId));
                if (result.success && result.progress) store.track(result.progress);
                return { ...result, status: response.status };
            } finally {
                starting.delete(Number(versionId));
                renderButtons();
            }
        },

        /** Where a version's download stands: 'starting', the server's status, or undefined. */
        status: (versionId) => (starting.has(Number(versionId)) ? 'starting'
            : items[versionId]?.status),

        /**
         * Steer the downloads (pause, resume, start_now, up, down, pause_all,
         * resume_all): the server's answer is the list afresh, and one that
         * starts something running polls again.
         */
        control: async function control(action, versionId = 0) {
            try {
                const form = new FormData();
                form.append('action', action);
                form.append('version_id', versionId);
                const response = await fetch('/model-manager/civitai/download/control', { method: 'POST', body: form });
                const result = await response.json();
                if (result.success && result.downloads) {
                    sequence = result.downloads.map((d) => d.version_id);
                    for (const dl of result.downloads) {
                        if (!dismissed.has(dl.version_id) || !finished(dl)) items[dl.version_id] = dl;
                    }
                    render();
                    if (!poll && Object.values(items).some(running)) poll = setInterval(tick, TIMING.poll);
                }
                return result;
            } catch (e) {
                console.error('[ModelManager] Download control error:', e);
                return { success: false, error: String(e) };
            }
        },

        cancel: async function cancel(versionId) {
            try {
                const form = new FormData();
                form.append('version_id', versionId);
                await fetch('/model-manager/civitai/download/cancel', { method: 'POST', body: form });
                // A waiting or paused one is cancelled at once, and nothing
                // may be polling to show it: the list is asked for now.
                await tick();
            } catch (e) {
                console.error('[ModelManager] Cancel error:', e);
            }
        },

        /** Take a finished download off the list, here and on the server. */
        dismiss: (versionId) => store.forget([versionId], versionId),

        /** Take every finished download off the list. */
        dismissFinished: () => store.forget(
            Object.values(items).filter(finished).map((dl) => dl.version_id), 0),

        // The server forgets them too: it kept every download until the WebUI
        // restarted, and the next poll brought back what was dismissed here.
        forget: async function forget(versionIds, asked) {
            for (const id of versionIds) {
                dismissed.add(id);
                delete items[id];
            }
            render();
            try {
                const form = new FormData();
                form.append('version_id', asked);
                await fetch('/model-manager/civitai/download/dismiss', { method: 'POST', body: form });
            } catch (e) {
                console.error('[ModelManager] Dismiss error:', e);
            }
        },

        get: (versionId) => items[versionId],
    };

    // The list as the server has it, once, when the page loads: after a
    // restart its paused downloads are there to resume - and in a page opened
    // while downloads run, they are followed. It used to be asked for only
    // once a download was started in this page, so neither was ever shown.
    if (typeof fetch === 'function') {
        tick().then(() => {
            if (!poll && Object.values(items).some(running)) poll = setInterval(tick, TIMING.poll);
        });
    }

    // The tabs' panels are drawn by Gradio after this runs, and redrawn
    // empty whenever it re-renders them: with downloads to show and a panel
    // empty, they are drawn again. A paused download is not running, so no
    // poll comes to draw it - after a restart the panel stayed hidden. Once a
    // panel holds its rows nothing is written, so this cannot set off the
    // next update itself (quiet_updates_test.mjs).
    if (typeof onAfterUiUpdate === 'function') {
        onAfterUiUpdate(() => {
            if (!Object.keys(items).length) return;
            const empty = [...panels].some((prefix) => {
                const list = document.getElementById(`${prefix}_download_list`);
                return list && !list.children.length;
            });
            if (empty) render();
        });
    }

    // What the panels' buttons do - a row's, and Pause all, Resume all and
    // Dismiss all in the tabs' markup; a version 0 is all of them.
    provide('downloads.control', ({ control, versionId }) => store.control(control, safeId(versionId) ?? 0));
    provide('downloads.cancel', ({ versionId }) => store.cancel(safeId(versionId)));
    provide('downloads.dismiss', ({ versionId }) => store.dismiss(safeId(versionId)));
    provide('downloads.dismissFinished', () => store.dismissFinished());
    return store;
}

let downloadsPanel = null;
const waiting = [];         // what follows the list once it runs

/**
 * The downloads list, started by the tabs that download - the Model Manager
 * and the Civitai Browser (#182). Send's Resources dialog and chips download
 * through it, and only while it runs. It used to start with the first module
 * to ask, and the Queue alone, through Send, asked for the list.
 */
export function start() {
    if (downloadsPanel) return;
    downloadsPanel = createDownloads();
    waiting.splice(0).forEach((follow) => follow(downloadsPanel));
}

/** The downloads both tabs show (see above): null until a tab that downloads has started it. */
export function downloads() {
    return downloadsPanel;
}

/** `follow(list)` once the downloads list runs - now, if it does. */
export function whenDownloading(follow) {
    if (downloadsPanel) follow(downloadsPanel);
    else waiting.push(follow);
}
