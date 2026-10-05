/**
 * The Queue tab (#156-#158): the generation queue, managed.
 *
 * A status line - the queue's state, the task it is on and how far along,
 * how many tasks wait, are done, stopped or failed - with Start, Pause or
 * Resume, and Stop. Under it the Active list, in the order the tasks will
 * run, and History, newest first, each a page at a time. A row says what its
 * task asks for; a finished one shows the first images its run made, as the
 * Generations tab draws them.
 *
 * The status line is asked for only while the tab shows, and writes only
 * what changed. The lists are read again when the tab opens, after an
 * action, and when the status finds the counts or the running task
 * changed: a task started, ended or queued. Each list is drawn whole again;
 * drawing only the rows that changed is #172's.
 *
 * Start may answer with tasks whose scripts are gone: a dialog lists them,
 * to run anyway or not start at all (#151). The server is api/scheduler.py;
 * how far along a task is, Forge's own progress, asked by the task's job id.
 */

// The shared modules, asked for with the version the server gives them: see
// the top of civitai_browser.mjs for why, and why this is not a plain import.
window.mmSharedVersion ||= (async () => {
    let waiting = false;
    for (;;) {
        try {
            // Not there yet - 404, the extension's app_started not run - is
            // waited out. Any other answer is taken, one without a version as
            // this tab's own, for every tab: still one copy.
            const response = await fetch('/model-manager/asset-version', { cache: 'no-store' });
            if (response.status !== 404) {
                const body = response.ok ? await response.json().catch(() => null) : null;
                return /^\d+$/.test(String(body?.version ?? '')) ? `?v=${body.version}`
                    : new URL(import.meta.url).search;
            }
        } catch (e) { /* the server is not answering at all */ }
        if (!waiting) {
            waiting = true;
            console.log("[ModelManager] waiting for the Model Manager's API...");
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
})();
const sharedVersion = await window.mmSharedVersion;
const shared = (name) => import(new URL(`./shared/${name}${sharedVersion}`, import.meta.url).href);

// Asked for all at once, then taken one by one below: see generations.mjs.
const SHARED_MODULES = ['core.mjs', 'calls.mjs', 'tabs.mjs', 'notes.mjs', 'grid.mjs', 'media.mjs',
    'generations.mjs', 'update_notice.mjs', 'settings.mjs'];
SHARED_MODULES.forEach((name) => shared(name).catch(() => {}));

const { TIMING, onReady, apiCall, escapeHtml, setText } = await shared('core.mjs');
const { provide } = await shared('calls.mjs');
const { tabShowing } = await shared('tabs.mjs');
const { showNotes } = await shared('notes.mjs');
const { renderGridPagination } = await shared('grid.mjs');
const { setupLazyMedia } = await shared('media.mjs');
const { generationImageHtml } = await shared('generations.mjs');

// The notice of a newer version beside the header's: it draws itself.
await shared('update_notice.mjs');

// The settings window behind the gear in the header.
await shared('settings.mjs');

// What the status line calls each state of the queue (runner.Progress).
const STATES = {
    running: 'Running', pausing: 'Pausing…', paused: 'Paused', stopping: 'Stopping…', stopped: 'Stopped',
};
// What a row calls each status of a task (db/tasks_ops.py).
const STATUSES = {
    pending: 'Pending', running: 'Running', completed: 'Completed', stopped: 'Stopped', failed: 'Failed',
};
// The two lists, each with its element, its page, and its count.
const LISTS = {
    active: { element: 'queue_active', count: 'queue_active_count', empty: 'No task is waiting. '
              + 'Press Queue beside Generate, in txt2img or img2img, to add one.' },
    history: { element: 'queue_history', count: 'queue_history_count', empty: 'No task has run yet.' },
};

const pages = { active: 1, history: 1 };
let started = false;
let showing = false;
let polling = false;
// The counts and the running task the lists were last read under.
let lastSeen = null;

function byId(id) {
    return document.getElementById(id);
}

async function post(endpoint, form = null) {
    const response = await fetch(endpoint, form ? {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(form).toString(),
    } : { method: 'POST' });
    return response.json();
}

// ----------------------------------------------------------- the status line

/** How far along Forge is with a job: its own progress, or null. */
async function forgeProgress(job) {
    try {
        const response = await fetch('/internal/progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_task: job, id_live_preview: -1, live_preview: false }),
        });
        return await response.json();
    } catch (e) {
        return null;
    }
}

/** "3 pending · 9 completed · 1 failed": the statuses some task has. */
function countsText(counts = {}) {
    const parts = [`${counts.pending || 0} pending`];
    for (const status of ['completed', 'stopped', 'failed']) {
        if (counts[status]) parts.push(`${counts[status]} ${status}`);
    }
    return parts.join(' · ');
}

/** The task the queue is on, and how far along Forge says it is. */
function nowText(progress, forge) {
    if (!progress?.task_id) return '';
    let text = `Task #${progress.task_id}`;
    if (forge?.queued) text += ' · waiting for Forge';
    else if (forge?.active && typeof forge.progress === 'number') {
        text += ` · ${Math.round(forge.progress * 100)}%`;
        if (forge.eta) text += ` · ${Math.round(forge.eta)} s left`;
    }
    return text;
}

/** What the queue has to say: why it stopped, or inputs that ran at their defaults. */
function messageText(progress) {
    if (progress?.error) return `The queue stopped: ${progress.error}`;
    const notes = progress?.notes || [];
    return notes.length ? `Task #${progress.task_id}: ${notes.join('; ')}` : '';
}

function setShown(element, shown) {
    if (element && element.hidden === shown) element.hidden = !shown;
}

function setDisabled(element, disabled) {
    if (element && element.disabled !== disabled) element.disabled = disabled;
}

/** Draw the status line from the server's answer; only what changed is written. */
function drawStatus(answer, forge = null) {
    const progress = answer?.progress || null;
    const state = answer?.running ? (progress?.state || 'running') : 'stopped';
    const shown = byId('queue_state');
    setText(shown, STATES[state] || state);
    if (shown && shown.getAttribute('data-state') !== state) shown.setAttribute('data-state', state);
    setText(byId('queue_task'), answer?.running ? nowText(progress, forge) : '');
    setText(byId('queue_counts'), countsText(answer?.counts));
    const message = messageText(progress);
    setText(byId('queue_message'), message);
    setShown(byId('queue_message'), Boolean(message));
    const running = Boolean(answer?.running);
    setDisabled(byId('queue_start'), running || !answer?.counts?.pending);
    setShown(byId('queue_pause'), running && state === 'running');
    setShown(byId('queue_resume'), running && (state === 'paused' || state === 'pausing'));
    setDisabled(byId('queue_stop'), !running || state === 'stopping');
}

/** Draw the status line; true when the counts or the running task changed since last read. */
async function refreshStatus() {
    try {
        const answer = await apiCall({ endpoint: '/model-manager/queue/status' });
        if (!answer?.success) return false;
        const job = answer.running ? answer.progress?.job : null;
        drawStatus(answer, job ? await forgeProgress(job) : null);
        const seen = JSON.stringify([answer.counts, answer.running ? answer.progress?.task_id ?? null : null]);
        const changed = lastSeen !== null && seen !== lastSeen;
        lastSeen = seen;
        return changed;
    } catch (e) {
        console.warn('[ModelManager] Could not read the queue:', e);
        return false;
    }
}

// ----------------------------------------------------------------- the lists

function fileName(path) {
    return String(path || '').split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|gguf|pt|pth|bin)$/i, '');
}

/** When, as a row says it: "Oct 5, 14:05". */
function when(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso);
    return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** The size a task asks for, and hires fix's, as it was set. */
function sizeText(task) {
    let text = task.width && task.height ? `${task.width}×${task.height}` : '';
    if (task.scale_by) text = `×${task.scale_by} of the image`;
    const hires = task.hires;
    if (hires?.scale) text += ` → hires ×${hires.scale}`;
    else if (hires?.resize) {
        const [x, y] = hires.resize;
        text += ` → hires ${x || 'auto'}×${y || 'auto'}`;
    }
    return text;
}

/** One fact of a row, with its whole text on hover. */
function fact(text, title = '') {
    return text ? `<span class="queue-fact" title="${escapeHtml(title || text)}">${escapeHtml(text)}</span>` : '';
}

function taskRowHtml(task) {
    const status = STATUSES[task.status] || task.status;
    const modules = (task.modules || []).map(fileName).join(', ');
    const sampler = [task.sampler, task.scheduler].filter(Boolean).join(' · ');
    const batch = task.batch_size || task.n_iter ? `${task.batch_size || 1} × ${task.n_iter || 1}` : '';
    const shown = task.images || [];
    const rest = Math.max(0, (task.image_count || 0) - shown.length - (task.hidden_nsfw || 0));
    const images = shown.map((img) => generationImageHtml(img)).join('');
    return `
        <div class="queue-task" data-task="${Number(task.id)}" data-status="${escapeHtml(task.status)}">
            <div class="queue-task-text">
                <div class="queue-task-head">
                    <span class="queue-status" data-status="${escapeHtml(task.status)}">${escapeHtml(status)}</span>
                    <span class="queue-mode">${escapeHtml(task.mode)}</span>
                    <span class="queue-id">#${Number(task.id)}</span>
                    ${task.script ? `<span class="queue-script">${escapeHtml(task.script)}</span>` : ''}
                    ${task.retry_of ? `<span class="queue-copy">a copy of #${Number(task.retry_of)}</span>` : ''}
                    ${task.retried_as ? `<span class="queue-requeued">Requeued as #${Number(task.retried_as)}</span>` : ''}
                </div>
                <div class="queue-prompt" title="${escapeHtml(task.prompt)}">${escapeHtml(task.prompt) || '<em>No prompt</em>'}</div>
                <div class="queue-facts">
                    ${fact(fileName(task.checkpoint), task.checkpoint)}
                    ${fact(modules, (task.modules || []).join('\n'))}
                    ${fact(sizeText(task))}
                    ${fact(sampler)}
                    ${fact(task.steps ? `${task.steps} steps` : '')}
                    ${fact(batch ? `batch ${batch}` : '', 'Batch size × batch count')}
                    ${fact(task.created_at ? `queued ${when(task.created_at)}` : '')}
                    ${fact(task.finished_at ? `ended ${when(task.finished_at)}` : '')}
                </div>
                ${task.error ? `<div class="queue-error">${escapeHtml(task.error)}</div>` : ''}
            </div>
            ${shown.length || rest || task.hidden_nsfw ? `<div class="queue-images">${images}
                ${rest ? `<span class="queue-more">+${rest}</span>` : ''}
                ${task.hidden_nsfw ? `<span class="queue-more" title="Hidden by the Generations tab's NSFW setting">${Number(task.hidden_nsfw)} hidden</span>` : ''}
            </div>` : ''}
        </div>`;
}

/** A list's page strip, while it has more than one page. */
function pagesHtml(which, answer) {
    if (!answer || answer.pages <= 1) return '';
    return renderGridPagination({ current: answer.page, last: answer.pages, hasNext: answer.page < answer.pages,
                                  goTo: `queue.${which}Page`, prev: `queue.${which}Prev`, next: `queue.${which}Next` });
}

const lastAnswers = {};

async function refreshList(which) {
    const list = LISTS[which];
    const element = byId(list.element);
    if (!element) return;
    try {
        const answer = await apiCall({ endpoint: '/model-manager/queue/tasks',
                                       params: { which, page: pages[which] } });
        if (!answer?.success) throw new Error(answer?.error || 'no answer');
        // Past the end, after a delete: the last page there is.
        if (answer.page > answer.pages) {
            pages[which] = answer.pages;
            return refreshList(which);
        }
        lastAnswers[which] = answer;
        setText(byId(list.count), answer.total ? `(${answer.total})` : '');
        element.innerHTML = answer.tasks.length
            ? answer.tasks.map(taskRowHtml).join('') + pagesHtml(which, answer)
            : `<div class="queue-empty">${escapeHtml(list.empty)}</div>`;
        setupLazyMedia(element);
    } catch (e) {
        element.innerHTML = `<div class="queue-empty">Could not read the list: ${escapeHtml(e.message)}</div>`;
    }
}

function refreshLists() {
    return Promise.all([refreshList('active'), refreshList('history')]);
}

function refresh() {
    return Promise.all([refreshStatus(), refreshLists()]);
}

function goToPage(which, page) {
    const last = lastAnswers[which]?.pages || 1;
    pages[which] = Math.min(Math.max(1, Number(page) || 1), last);
    return refreshList(which);
}

// --------------------------------------------------------------- the controls

/**
 * A question with buttons, in the dialog every tab draws: resolves to the
 * value of the button pressed, or null - Esc, or a click beside it.
 */
function ask(title, bodyHtml, buttons) {
    return new Promise((resolve) => {
        let answer = null;
        const backdrop = document.createElement('div');
        backdrop.className = 'mm-dialog-backdrop';
        backdrop.innerHTML = `
            <div class="mm-dialog queue-dialog">
                <h3>${escapeHtml(title)}</h3>
                ${bodyHtml}
                <div class="mm-dialog-buttons">
                    ${buttons.map((b, i) => `<button type="button" class="mm-btn ${b.kind || 'secondary'}"
                        data-answer="${i}">${escapeHtml(b.label)}</button>`).join('')}
                </div>
            </div>`;
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
        backdrop.addEventListener('click', (event) => {
            const button = event.target.closest?.('[data-answer]');
            if (button) {
                answer = buttons[Number(button.getAttribute('data-answer'))].value;
                close();
            } else if (event.target === backdrop) {
                close();
            }
        });
        document.addEventListener('keydown', onEscape, true);
        document.body.appendChild(backdrop);
    });
}

/** The tasks Start found using scripts this WebUI no longer has, as a list. */
function missingHtml(missing) {
    return `<p>These tasks use extensions this WebUI does not have now.
        Run anyway, and they run without them.</p>
        <ul class="queue-missing">${missing.map((m) => `<li><b>#${Number(m.task)}</b>
            ${escapeHtml(String(m.prompt || '').slice(0, 80))}
            <span class="queue-missing-names">${escapeHtml((m.missing || []).join(', '))}</span></li>`).join('')}</ul>`;
}

async function start() {
    let answer = await post('/model-manager/queue/start');
    if (answer?.success && !answer.started && answer.missing?.length) {
        const go = await ask('Some tasks need missing extensions', missingHtml(answer.missing), [
            { label: 'Cancel', value: false },
            { label: 'Run anyway', value: true, kind: 'primary' },
        ]);
        if (!go) return;
        answer = await post('/model-manager/queue/start?force=true');
    }
    if (!answer?.success) console.warn('[ModelManager] Could not start the queue:', answer?.error);
    await refresh();
}

async function control(action) {
    const answer = await post(`/model-manager/queue/${action}`);
    if (!answer?.success) console.warn(`[ModelManager] Could not ${action} the queue:`, answer?.error);
    await refresh();
}

// -------------------------------------------------------------- the polling

/**
 * Each poll: the status line while the tab shows, and both lists as it
 * opens or the queue changes. Nothing is asked while it is hidden.
 */
async function poll() {
    if (polling) return;
    polling = true;
    try {
        const now = tabShowing('queue');
        const opened = now && !showing;
        showing = now;
        if (opened) await refresh();
        else if (now && await refreshStatus()) await refreshLists();
    } finally {
        polling = false;
    }
}

// ---------------------------------------------------------------- markup
provide('queue.start', () => start());
provide('queue.pause', () => control('pause'));
provide('queue.resume', () => control('resume'));
provide('queue.stop', () => control('stop'));
provide('queue.refresh', () => refresh());
provide('queue.activePage', ({ page }) => goToPage('active', page));
provide('queue.activePrev', () => goToPage('active', pages.active - 1));
provide('queue.activeNext', () => goToPage('active', pages.active + 1));
provide('queue.historyPage', ({ page }) => goToPage('history', page));
provide('queue.historyPrev', () => goToPage('history', pages.history - 1));
provide('queue.historyNext', () => goToPage('history', pages.history + 1));

/** The tab's markup, once Gradio has drawn it: see generations.mjs. */
function markupDrawn(tries = 240) {
    return new Promise((resolve) => {
        const look = (left) => {
            if (byId('queue_active') || left <= 0) resolve(!!byId('queue_active'));
            else setTimeout(() => look(left - 1), TIMING.drawRetry);
        };
        look(tries);
    });
}

onReady(async () => {
    if (started) return;
    started = true;
    if (!await markupDrawn()) {
        console.warn('[ModelManager] The Queue tab never appeared; not loading it');
        return;
    }
    showNotes('queue', 'queue_notes');
    await poll();
    setInterval(poll, TIMING.poll);
});
