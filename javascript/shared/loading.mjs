/**
 * The loading module (#183): which of the extension's tabs run, and the one
 * place that starts and stops them.
 *
 * The WebUI loads one script of ours, javascript/loader.mjs, which asks the
 * server for the shared version and calls boot() here. boot() asks
 * ui-options once which tabs are on, and which this start built (tabs.py),
 * and loads only those: a tab switched off is never imported, and none of
 * its code runs. The WebUI used to load every tab's script, whatever the
 * switches said - Generations off, its script still offered its actions and
 * added its listeners. A tab's script, in javascript/tabs/ - a folder the
 * WebUI does not list - does nothing as it is imported. It exports start(scope),
 * and whatever it adds outside its own markup goes through the scope: a
 * listener on the document or the window, a timer, an after-update hook, an
 * observer, an action offered. Listeners on its own elements hide with it.
 *
 * Switched off mid-session, a tab stops at once: its scope takes all of that
 * back, its button hides, and the page leaves it if it showed. So does each
 * shared service it used that no running tab uses any more (#186). Switched
 * on again, a tab built at this start and not started yet starts at once;
 * one that ran here comes back with a page reload, or a restart of the
 * WebUI, which the popup offers - only a new page is sure to hold nothing a
 * stop missed; one not built, with Reload UI. Once for the page: the tabs
 * share this copy.
 */

// The other shared modules, under the version this one was asked for under -
// the copy the tabs loaded. A plain import would be another URL, and another
// copy of it, with state of its own.
const shared = (name) => import(new URL(`./${name}${new URL(import.meta.url).search}`, import.meta.url).href);
const { TIMING, escapeHtml, onReady, once } = await shared('core.mjs');
const { call, provide, withdraw } = await shared('calls.mjs');
const { panelButton, showTab, shownPanel, tabButton, tabShowing } = await shared('tabs.mjs');
const { uiOptions } = await shared('ui_options.mjs');

/**
 * Each tab, by the name tabs.mjs knows it by, in the order the WebUI shows
 * them: its script in javascript/tabs/; its name in ui-options (tabs.py); its
 * switch (#185); the element that says Gradio has drawn
 * its markup; where the page goes when it hides while showing; what else
 * hides with it; and the event that tells the other tabs.
 */
export const TABS = {
    queue: { file: 'queue.mjs', server: 'queue', setting: 'model_manager_queue_enabled', markup: 'queue_active',
             root: 'queue_app', elsewhere: 'txt2img', also: ['txt2img_queue', 'img2img_queue'],
             event: 'mm-queue-enabled' },
    generations: { file: 'generations.mjs', server: 'generations', setting: 'model_manager_record_generations',
                   markup: 'gen_grid', root: 'generations_app', elsewhere: 'modelManager', also: [],
                   event: 'mm-generations-enabled' },
    modelManager: { file: 'model_manager.mjs', server: 'model_manager', setting: 'model_manager_model_manager_enabled',
                    markup: 'mm_load_btn', root: 'model_manager_app', elsewhere: 'txt2img', also: [], event: null },
    civitaiBrowser: { file: 'civitai_browser.mjs', server: 'civitai_browser',
                      setting: 'model_manager_civitai_browser_enabled', markup: 'cb_search_btn',
                      root: 'civitai_browser_app', elsewhere: 'txt2img', also: [], event: null },
};

// What a disabled link says each tab is (tabs.py's NAMES).
const LABELS = { queue: 'The Queue', generations: 'Your generations', modelManager: 'The Model Manager tab',
                 civitaiBrowser: 'The Civitai Browser tab' };

// Each tab: whether it is on and built, as the server last said - undefined
// until it has - its running scope and script, whether its start() has been
// called, and whether it ran and stopped.
const state = Object.fromEntries(Object.keys(TABS).map((name) => [name, { on: undefined, built: undefined,
                                                                         scope: null, module: null,
                                                                         started: false, stopped: false }]));

/** Whether your generations are shown: false only once the server said so. */
export function generationsEnabled() {
    return state.generations.on !== false;
}

/** Whether the queue is on: false only once the server said so. */
export function queueEnabled() {
    return state.queue.on !== false;
}

// ------------------------------------------------------- between tabs
// A tab reaches another only through here (#184): whether it is available,
// and open it at one of its entries - what its script offers the others. It
// called the other's actions by name, after checking ready() its own way,
// and drew its link whether that tab was there or not.

/** Whether a tab is there for the others: on, and started in this page. */
export function available(name) {
    const now = state[name];
    return Boolean(now && now.on !== false && now.started && now.scope?.live);
}

/** Why a tab is not available, as a link to it says. */
export function unavailableReason(name) {
    const now = state[name];
    const label = LABELS[name] || name;
    if (now?.on === false) return `${label} is turned off in the settings`;
    // Settings -> Reload UI builds it, as the popup says: this said a restart (#208).
    if (now?.built === false) return `${label} was turned on after the WebUI started. Settings -> Reload UI adds it.`;
    if (now?.stopped) return `${label} was turned off in this page: it comes back with a reload`;
    return `${label} has not started yet`;
}

/**
 * The attributes of a link to another tab: its own title while that tab is
 * available; else disabled, saying why - as every control that would do
 * nothing. `disabled`: disabled for a reason of its own as well. The page's
 * one rule keeps it so as tabs come and go (applyLinks).
 */
export function linkTo(name, title, { disabled = false } = {}) {
    const on = available(name);
    return ` data-needs-tab="${escapeHtml(name)}" data-title-available="${escapeHtml(title)}"`
        + `${disabled ? ' data-disabled-own' : ''} title="${escapeHtml(on ? title : unavailableReason(name))}"`
        + `${on && !disabled ? '' : ' disabled'}`;
}

/**
 * Show a tab and open it at one of its entries, with these arguments.
 * Answers false, doing nothing, when it is not available.
 */
export async function open(name, entry, ...args) {
    if (!available(name)) return false;
    const fn = state[name].module?.entries?.[entry];
    if (typeof fn !== 'function') throw new Error(`The ${name} tab offers no ${entry}`);
    await showTab(name);
    await fn(...args);
    return true;
}

/** Every link to another tab, as that tab is now - writing only what differs: this runs after every update. */
function applyLinks() {
    if (typeof document === 'undefined') return;
    for (const link of document.querySelectorAll('[data-needs-tab]')) {
        const name = link.dataset.needsTab;
        const on = available(name);
        const disabled = !on || 'disabledOwn' in link.dataset;
        if (link.disabled !== disabled) link.disabled = disabled;
        const title = on ? (link.dataset.titleAvailable ?? '') : unavailableReason(name);
        if (link.title !== title) link.title = title;
    }
}

/** A tab came or went: its links, and the others told. */
function changed(name) {
    applyLinks();
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('mm-tabs-changed', { detail: { tab: name } }));
}

// ------------------------------------------------------------- the scope

/**
 * What a tab adds outside its own markup, taken back when it stops. Each
 * call does what its plain form does, and keeps how to undo it.
 */
export function createScope(name) {
    const undo = new Set();
    const keep = (step) => { undo.add(step); return step; };
    const listening = [];
    // A listener is one per target, type, function and capture, as the browser counts them.
    const captures = (options) => Boolean(typeof options === 'object' ? options?.capture : options);
    const scope = {
        name,
        live: true,
        /** target.addEventListener, removed on stop. */
        listen: (target, type, listener, options) => {
            target.addEventListener(type, listener, options);
            const step = keep(() => target.removeEventListener(type, listener, options));
            listening.push({ target, type, listener, capture: captures(options), step });
        },
        /** target.removeEventListener: what the tab takes back itself, no longer to take back on stop. */
        unlisten: (target, type, listener, options) => {
            target.removeEventListener(type, listener, options);
            const at = listening.findIndex((l) => l.target === target && l.type === type && l.listener === listener
                                                  && l.capture === captures(options));
            if (at >= 0) undo.delete(listening.splice(at, 1)[0].step);
        },
        /** setInterval - its arguments in that order - cleared on stop. */
        every: (work, ms) => {
            const id = setInterval(() => scope.live && work(), ms);
            keep(() => clearInterval(id));
            return id;
        },
        /** setTimeout, cleared on stop: what a stopped tab waited for never comes. */
        later: (work, ms) => {
            const step = () => clearTimeout(id);
            const id = setTimeout(() => {
                undo.delete(step);
                if (scope.live) work();
            }, ms);
            keep(step);
            return id;
        },
        /** A promise that settles after `ms` - never, once the tab has stopped. */
        sleep: (ms) => {
            return new Promise((resolve) => scope.later(resolve, ms));
        },
        /** onAfterUiUpdate: the WebUI keeps every callback, so a stopped tab's does nothing. Named as its work. */
        afterUpdate: (work) => {
            if (typeof onAfterUiUpdate !== 'function') return;
            const hook = () => { if (scope.live) work(); };
            Object.defineProperty(hook, 'name', { value: work.name });
            onAfterUiUpdate(hook);
        },
        /** An observer, disconnected on stop. */
        observe: (observer) => {
            keep(() => observer.disconnect());
            return observer;
        },
        /** An action offered (shared/calls.mjs), withdrawn on stop. */
        provide: (action, fn) => {
            provide(action, fn);
            keep(() => withdraw(action, fn));
        },
        /** Anything else to take back: a registration a shared module answered how to undo. */
        onStop: (step) => {
            if (typeof step === 'function') keep(step);
        },
        /**
         * Whether Gradio has drawn the element - after the scripts have run,
         * and later on a slow machine - looked for until it is, for a minute at most.
         */
        markup: (id, tries = 240) => {
            const app = () => (typeof gradioApp === 'function' ? gradioApp() : document);
            return new Promise((resolve) => {
                const look = (left) => {
                    const drawn = Boolean(app().querySelector(`#${id}`));
                    if (drawn || left <= 0 || !scope.live) resolve(drawn && scope.live);
                    else scope.later(() => look(left - 1), TIMING.drawRetry);
                };
                look(tries);
            });
        },
        /** Take back everything, last first. */
        stop: () => {
            if (!scope.live) return;
            scope.live = false;
            for (const step of [...undo].reverse()) {
                try {
                    step();
                } catch (error) {
                    console.error(`[ModelManager] Stopping the ${name} tab:`, error);
                }
            }
            undo.clear();
        },
    };
    return scope;
}

/**
 * What a tab's script does once started, declared at its top level where it
 * belongs - a listener beside its handler, an action beside what it does -
 * and done by its start(scope), through the scope. Declaring does nothing:
 * a tab's script does nothing as it is imported.
 */
export function tabWork() {
    const steps = [];
    return {
        listen: (target, type, listener, options) => {
            steps.push((scope) => scope.listen(target, type, listener, options));
        },
        provide: (action, fn) => steps.push((scope) => scope.provide(action, fn)),
        afterUpdate: (work) => steps.push((scope) => scope.afterUpdate(work)),
        run: (work) => steps.push(work),
        start: (scope) => steps.forEach((step) => step(scope)),
    };
}

// ---------------------------------------------------- the shared services
// What the tabs share - the page's actions, the notes, the settings window,
// the downloads list, the sync, Send - each started once for the page, by the
// first tab whose STARTS reach it, with a scope of its own (#186). Its users
// are the running tabs that reach it; when the last one stops, so does it.
// They used to start once and run on: with the Model Manager off, the page
// still asked for the sync's progress each time it came back into view. A
// service stopped does not start again in this page.

const services = new Map();     // file -> { scope, users, ready, stopped }

/** These services and what each starts in turn (its STARTS), each after what it starts. */
async function reach(files, seen = new Set(), order = []) {
    for (const file of files) {
        if (seen.has(file)) continue;
        seen.add(file);
        await reach((await shared(file)).STARTS || [], seen, order);
        order.push(file);
    }
    return order;
}

/**
 * Start these services for `user` - a tab, or a suite - and what they start
 * in turn: each once for the page, its users counted. Answers false,
 * starting nothing, when one of them has stopped in this page.
 */
export async function useServices(files, user) {
    const all = await reach(files);
    if (all.some((file) => services.get(file)?.stopped)) return false;
    for (const file of all) {
        let service = services.get(file);
        if (!service) {
            const scope = createScope(file);
            service = { scope, users: new Set(), stopped: false,
                        ready: shared(file).then((module) => module.start?.(scope))
                            .catch((error) => console.error(`[ModelManager] Starting ${file}:`, error)) };
            services.set(file, service);
        }
        service.users.add(user);
        await service.ready;
    }
    return true;
}

/** `user` uses no service any more: each it leaves without users stops, the last started first. */
export function leaveServices(user) {
    for (const service of [...services.values()].reverse()) {
        if (!service.users.delete(user) || service.users.size) continue;
        service.scope.stop();
        service.stopped = true;
    }
}

// ------------------------------------------------------- starting, stopping

/**
 * Load a tab's script and start it, once its markup is there: the shared
 * services it uses first (#182, #186). Resolves once its start() has been
 * called - not when it is done, as a tab's start goes on with its first
 * requests - with its scope; null, starting nothing, when a service it needs
 * has stopped in this page: only a reload brings that back.
 */
export async function startTab(name) {
    const tab = TABS[name];
    const now = state[name];
    if (now.scope || now.stopped) return now.scope;
    const scope = createScope(name);
    now.scope = scope;
    const module = await import(new URL(`../tabs/${tab.file}${new URL(import.meta.url).search}`, import.meta.url).href);
    if (!await useServices(module.STARTS, name)) {
        now.scope = null;
        scope.stop();
        now.stopped = true;
        changed(name);
        return null;
    }
    if (!await scope.markup(tab.markup)) {
        if (scope.live) console.warn(`[ModelManager] The ${name} tab never appeared; not loading it`);
        return scope;
    }
    now.module = module;
    now.started = true;
    Promise.resolve().then(() => module.start(scope))
        .catch((error) => console.error(`[ModelManager] Starting the ${name} tab:`, error));
    changed(name);
    return scope;
}

/**
 * Stop a tab: its scope takes back all it added, and each service only it
 * still used stops. It starts again only in a new page.
 */
export function stopTab(name) {
    const now = state[name];
    if (!now.scope) return;
    now.scope.stop();
    now.scope = null;
    now.started = false;
    now.stopped = true;
    leaveServices(name);
    changed(name);
}

/** Show or hide an element - writing only what differs: this runs after every update. */
function showElement(element, shown) {
    const display = shown ? '' : 'none';
    if (element && element.style.display !== display) element.style.display = display;
}

/**
 * Where the page goes when a tab hides while showing: its own fallback,
 * unless that one is not there - off, not built, or stopped; one still
 * starting is, as at the page's load.
 */
function fallbackFor(name) {
    const elsewhere = TABS[name].elsewhere;
    const there = state[elsewhere];
    return there && (there.on === false || there.built === false || there.stopped) ? 'txt2img' : elsewhere;
}

/**
 * A tab's button, shown while it is on and has not stopped, and what else
 * shows with it - the Queue buttons beside Generate, which the server wires,
 * while the queue is on. Off while showing: the page goes elsewhere, rather
 * than stay on a tab whose button is gone.
 */
function apply(name) {
    const tab = TABS[name];
    const now = state[name];
    const on = now.on !== false;
    showElement(tabButton(name), on && !now.stopped);
    const app = typeof gradioApp === 'function' ? gradioApp() : document;
    tab.also.forEach((id) => showElement(app.querySelector(`#${id}`), on && !newerDatabase));
    if ((!on || now.stopped) && tabShowing(name)) showTab(fallbackFor(name));
}

function applyAll() {
    Object.keys(TABS).forEach(apply);
    drawDatabaseNotices();
    applyLinks();
    if (returnTo) goBack();
}

/** A new answer for one tab: start or stop it, hide or show it, and tell the other tabs. */
function setOn(name, on) {
    const now = state[name];
    const changed = now.on !== undefined && now.on !== on;
    now.on = on;
    if (changed && !on) {
        // One that ran here may have left something a stop missed: a new
        // page, or a restarted WebUI, is the clean slate.
        const ran = Boolean(now.scope) || now.stopped;
        stopTab(name);
        waitForReload(name, ran ? 'off' : null);
    }
    if (changed && on) {
        if (now.built && !now.stopped) {
            waitForReload(name, null);
            startTab(name).then((scope) => { if (!scope) waitForReload(name, 'page'); });
        } else {
            waitForReload(name, now.built ? 'page' : 'ui');
        }
    }
    apply(name);
    const event = TABS[name].event;
    if (changed && event) window.dispatchEvent(new CustomEvent(event, { detail: { enabled: on } }));
}

// --------------------------------------------- a restart, or a reload
// A tab switch this page cannot fully take (#185, #186). A tab that ran here
// may have left something its stop missed - a new page is sure to hold
// nothing of it - and one turned on again comes back only in a new page; one
// this start did not build is created by Settings -> Reload UI. One popup
// says so for every switch saved, and offers Restart WebUI - the server and
// the page afresh, the cleanest slate, where the WebUI comes back after it -
// the lighter way, or Later. Either way the page comes back to the tab that
// showed. A tab turned on that starts at once asks nothing.

const waiting = new Map();          // tab -> 'off', 'page' or 'ui'; DATABASE -> 'restart'
// A new database file, saved: the server opens it only as it starts (#136).
const DATABASE = 'database';
const DATABASE_SETTING = 'model_manager_database_path';
let restartable = false;            // whether the WebUI comes back after a restart (ui-options)
const NOT_RESTARTABLE = 'This WebUI was not started by webui.bat or webui.sh: a restart would leave it shut down';
const RETURN_KEY = 'mm-return-to';  // the tab that showed, for the page a reload brings
let returnTo = null;

function waitForReload(name, how) {
    if (how) waiting.set(name, how);
    else waiting.delete(name);
    drawReloadPopup();
}

function reloadPopup() {
    return typeof document === 'undefined' ? null : document.querySelector('.mm-reload-dialog');
}

function drawReloadPopup(error = null) {
    if (typeof document === 'undefined') return;
    if (!waiting.size) {
        closeReloadPopup();
        return;
    }
    let popup = reloadPopup();
    if (!popup) {
        popup = document.createElement('div');
        popup.className = 'mm-dialog-backdrop mm-reload-dialog';
        popup.addEventListener('click', onReloadClick);
        document.body.appendChild(popup);
        document.addEventListener('keydown', onReloadKey, true);
    }
    const ui = [...waiting.values()].includes('ui');
    // A reload is offered only for what one brings: a new database needs the server started afresh.
    const reloads = [...waiting.values()].some((how) => how !== 'restart');
    const LINES = { off: 'is turned off.', page: 'comes back with a page reload.',
                    ui: 'is created by Settings -> Reload UI.',
                    restart: 'is opened when the WebUI starts: restart it to use the new file.' };
    const who = (name) => (name === DATABASE ? 'The database file you saved' : LABELS[name]);
    const lines = [...waiting].map(([name, how]) => `${who(name)} ${LINES[how]}`);
    const notes = [restartable ? 'Restart WebUI starts the server and the page afresh: the cleanest slate. '
                                 // Every download not over comes back paused, queued ones too: none
                                 // resumes by itself (download_service.restore, #187).
                                 + 'A running generation and sync end. Downloads come back paused: '
                                 + 'resume them after.'
                               : `${NOT_RESTARTABLE}.`,
                   ...(reloads ? ['Reloading loses unsaved input, like a typed prompt.'] : [])];
    popup.innerHTML = `
        <div class="mm-dialog" role="dialog" aria-modal="true" aria-labelledby="mm_reload_title">
            <h3 id="mm_reload_title">Restart or reload</h3>
            <div class="mm-reload-list">${lines.map((line) => `<p>${escapeHtml(line)}</p>`).join('\n')}</div>
            <div class="mm-reload-notes">${notes.map((note) => `<p>${escapeHtml(note)}</p>`).join('\n')}</div>
            ${error ? `<p class="mm-reload-error">${escapeHtml(error)}</p>` : ''}
            <div class="mm-dialog-buttons">
                <button type="button" class="mm-btn ${restartable ? 'primary' : 'secondary'}" data-reload="restart"${
                    restartable ? '' : ` disabled title="${escapeHtml(NOT_RESTARTABLE)}"`}>Restart WebUI</button>
                ${reloads ? `<button type="button" class="mm-btn ${restartable ? 'secondary' : 'primary'}" data-reload="${
                    ui ? 'ui' : 'page'}">${ui ? 'Reload UI' : 'Reload the page'}</button>` : ''}
                <button type="button" class="mm-btn secondary" data-reload="later">Later</button>
            </div>
        </div>`;
}

function closeReloadPopup() {
    waiting.clear();
    reloadPopup()?.remove();
    if (typeof document !== 'undefined') document.removeEventListener('keydown', onReloadKey, true);
}

/** The tab showing, for the page a reload brings to show again. */
function rememberTab() {
    try {
        sessionStorage.setItem(RETURN_KEY, shownPanel() || '');
    } catch {
        // Without the storage, the new page starts on its first tab.
    }
}

/** After a reload asked for here: the tab that showed, once Gradio has drawn its button - unless it is hidden now. */
function goBack() {
    const button = panelButton(returnTo);
    if (!button) return;
    returnTo = null;
    if (button.style.display !== 'none') button.click();
}

function onReloadClick(event) {
    const button = event.target.closest?.('[data-reload]');
    if (!button && event.target !== event.currentTarget) return;
    if (button?.disabled) return;
    const how = button?.dataset.reload || 'later';
    if (how === 'restart') {
        restartWebui(button);
        return;
    }
    closeReloadPopup();
    if (how === 'later') return;
    rememberTab();
    if (how === 'page') window.location.reload();
    if (how === 'ui') {
        const app = typeof gradioApp === 'function' ? gradioApp() : document;
        const reloadUi = app.querySelector('#settings_restart_gradio');
        if (reloadUi) reloadUi.click();
        else window.location.reload();
    }
}

/**
 * Restart WebUI: the server answers, then ends its process for its start
 * script to start afresh; the page waits for it as the WebUI's own restart
 * does (restart_reload, its ui.js), and loads again.
 */
async function restartWebui(button) {
    button.disabled = true;
    button.textContent = 'Restarting...';
    let answer;
    try {
        answer = await (await fetch('/model-manager/restart', { method: 'POST' })).json();
    } catch (error) {
        answer = { success: false, error: String(error) };
    }
    if (!answer?.success) {
        drawReloadPopup(`The WebUI did not restart: ${answer?.error || 'no answer'}`);
        return;
    }
    rememberTab();
    closeReloadPopup();
    if (typeof restart_reload === 'function') {
        restart_reload();
        return;
    }
    const ask = () => fetch('./internal/ping').then((r) => (r.ok ? window.location.reload() : again()), again);
    const again = () => setTimeout(ask, 500);
    setTimeout(ask, 2000);
}

function onReloadKey(event) {
    if (event.key !== 'Escape' || !reloadPopup()) return;
    event.stopPropagation();
    closeReloadPopup();
}

/** Each switch, as `value(setting)` says it: one it says nothing of stays as it is. */
function takeSwitches(value) {
    for (const [name, tab] of Object.entries(TABS)) {
        const on = value(tab.setting);
        if (typeof on === 'boolean') setOn(name, on);
    }
}

// ------------------------------------------- a database newer than this copy

// The server's word that the database is at a schema newer than this copy
// knows (#136): {schema, known, path}, or null. Then no tab starts - each
// would ask the database, which this copy refuses - and each tab that is on
// and built is covered by a notice saying why, and what to do.
let newerDatabase = null;

function databaseNotice() {
    const { schema, known, path } = newerDatabase;
    return `<div class="newer-database">
        <h3>This copy of the Model Manager is older than its database.</h3>
        <p>The database is at schema v${escapeHtml(String(schema))}. This copy knows up to
           v${escapeHtml(String(known))}. Another WebUI sharing it has been updated.</p>
        <p>To use it here, update this copy: Extensions, Check for updates, then Apply and restart UI.</p>
        <p>Or give this WebUI a database of its own: Settings, Model Manager, Database file.</p>
        <p class="newer-database-path">Database: ${escapeHtml(path)}</p>
        <div class="newer-database-actions">
            <button type="button" class="mm-btn primary" data-action="database.openExtensions">Open Extensions</button>
            <button type="button" class="mm-btn secondary" data-action="database.openSettings">Database settings</button>
        </div>
    </div>`;
}

/**
 * The notice over each tab that would have started: drawn once its markup is
 * there, and again when Gradio draws the tab anew - only where it is missing,
 * as this runs after every update.
 */
function drawDatabaseNotices() {
    if (!newerDatabase) return;
    const app = typeof gradioApp === 'function' ? gradioApp() : document;
    for (const [name, tab] of Object.entries(TABS)) {
        const root = app.querySelector(`#${tab.root}`);
        if (!root || !state[name].on || !state[name].built || root.querySelector(':scope > .newer-database')) continue;
        root.classList.add('database-blocked');
        root.insertAdjacentHTML('afterbegin', databaseNotice());
    }
}

/**
 * The notice's buttons: the WebUI's Extensions tab, and our settings window -
 * started alone - at the file's path. The page's one listener for them is
 * calls.mjs's, which a tab would have started.
 */
async function offerDatabaseActions() {
    await useServices(['calls.mjs'], 'database');
    provide('database.openExtensions', () => showTab('extensions'));
    provide('database.openSettings', async () => {
        if (await useServices(['settings.mjs'], 'database')) {
            call('settings.open', { section: 'storage', focus: 'model_manager_database_path' });
        }
    });
}

/**
 * Start the page: the tabs that are on and built, once the page is ready -
 * every one when the server cannot say, as before - then follow their
 * switches, saved in the settings window (its answer says each value) or on
 * the WebUI's Settings page. There the WebUI hands every setting, as the
 * server now has it, to onOptionsChanged - the only way back with every tab
 * off, when the settings window cannot open. The settings window's module
 * watched that page's Apply, and only a tab running starts it.
 */
export const boot = once(() => {
    try {
        returnTo = sessionStorage.getItem(RETURN_KEY) || null;
        sessionStorage.removeItem(RETURN_KEY);
    } catch {
        returnTo = null;
    }
    onReady(async () => {
        const data = await uiOptions();
        restartable = data?.restartable === true;
        newerDatabase = data?.database_newer || null;
        if (newerDatabase) await offerDatabaseActions();
        for (const [name, tab] of Object.entries(TABS)) {
            const said = data?.tabs?.[tab.server];
            state[name].on = said ? said.on !== false : true;
            state[name].built = said ? said.built !== false : true;
            apply(name);
            if (state[name].on && state[name].built && !newerDatabase) startTab(name);
        }
        drawDatabaseNotices();
        window.addEventListener('mm-settings-saved', (event) => {
            takeSwitches((setting) => event.detail?.settings?.[setting]?.value);
            if ((event.detail?.changed || []).includes(DATABASE_SETTING)) waitForReload(DATABASE, 'restart');
        });
        if (typeof onOptionsChanged === 'function') {
            onOptionsChanged(() => takeSwitches((setting) => (typeof opts === 'object' ? opts?.[setting] : undefined)));
        }
        if (typeof onAfterUiUpdate === 'function') onAfterUiUpdate(applyAll);
    });
});
